"""Supplemental-source lifecycle with isolated transport, never real acquisition."""
from datetime import datetime
import json

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from test_automatic_delivery import scene, simulated_delivery_transport
from test_delivery_official_facts import frozen_material, approved, BROWSER_CLAIM
from app.models import (Project, SinglePromptCitationManifest, SinglePromptExecutionProposalResult,
    SupplementalSourceAcquisition, TargetBrandCapabilityTruth)
from app.api.release_catalog import _record_project_configuration
from app.modules.single_prompt_v2.supplemental_sources import (
    queue_source, execute_source, source_view, frozen_sources, recover_interrupted_sources,
)
from app.modules.single_prompt_v2.automatic_delivery import create_task, authorize_task, execute_task, task_view
from app.modules.single_prompt_v2.delivery_text import text_digest

URL = 'https://example.com/supplemental-manual'
TEXT = BROWSER_CLAIM + '\n' + '这是一份隔离工程输入。请在已创建项目中核对功能入口、输入格式和当前限制。' * 8


def fetched(url=URL, status='SUCCESS'):
    when = datetime(2026, 10, 10, 10, 0)
    receipt = frozen_material()['official_source_materials'][0]['acquisition_receipt']
    receipt.update(requested_url=url, final_url=url, acquired_at=when.isoformat(), content_hash=text_digest(TEXT))
    receipt['documents'][0]['url'] = url
    return {'url': url, 'title': '隔离补充官网资料', 'clean_text': TEXT, 'fetch_status': status,
        'fetch_time': when, 'acquisition_receipt': receipt, 'failure_reason': ''}


def queue(db, key='supplemental-request'):
    return queue_source(db, project_id=1, url=URL, idempotency_key=key, fetch_authorized=True)[0]


def test_supplemental_source_is_frozen_scoped_idempotent_and_not_a_citation(scene):
    db, _, args, tmp = scene
    before = [(r.manifest_id, r.payload_hash, r.payload_json) for r in db.query(SinglePromptCitationManifest)]
    row = queue(db)
    assert queue(db).source_id == row.source_id
    with pytest.raises(HTTPException):
        frozen_sources(db, project_id=1, source_ids=[row.source_id])
    calls = []
    def transport(urls):
        calls.append(urls)
        return [fetched()]
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    execute_source(row.source_id, session_factory=factory, fetcher=transport)
    execute_source(row.source_id, session_factory=factory, fetcher=transport)
    db.refresh(row)
    assert calls == [[URL]] and row.status == 'READY'
    assert source_view(row)['original_citation_count'] == 0
    fixed = frozen_sources(db, project_id=1, source_ids=[row.source_id])
    assert fixed[0]['text'] == TEXT and fixed[0]['source_role'] == 'SUPPLEMENTAL_PUBLIC_SOURCE'
    with pytest.raises(HTTPException):
        frozen_sources(db, project_id=2, source_ids=[row.source_id])
    task, _ = create_task(db, **{**args, 'idempotency_key': 'with-supplement'}, supplemental_source_ids=[row.source_id])
    assert json.loads(task.input_json)['supplemental_sources'] == fixed
    assert before == [(r.manifest_id, r.payload_hash, r.payload_json) for r in db.query(SinglePromptCitationManifest)]
    row.snapshot_json = '{}'
    with pytest.raises(IntegrityError, match='SUPPLEMENTAL_SOURCE_IMMUTABLE'):
        db.commit()
    db.rollback()
    from scripts.release_backup import backup, verify
    saved = backup(db.get_bind().url.database, tmp / 'source-backup')
    assert saved['supplemental_source_bindings'] == 1
    assert verify(tmp / 'source-backup')['supplemental_source_bindings'] == 1


@pytest.mark.parametrize('mode', ['missing_receipt', 'wrong_url', 'failed', 'partial'])
def test_supplemental_invalid_and_partial_acquisition_never_become_full_source(scene, mode):
    db, _, _, _ = scene
    row = queue(db)
    value = fetched()
    if mode == 'missing_receipt': value['acquisition_receipt'] = {}
    if mode == 'wrong_url': value['url'] = 'https://example.com/wrong'
    if mode == 'failed': value['fetch_status'] = 'FETCH_FAILED'
    if mode == 'partial': value['fetch_status'] = 'PARTIAL'
    execute_source(row.source_id, session_factory=sessionmaker(bind=db.get_bind()), fetcher=lambda urls: [value])
    db.refresh(row)
    assert row.status == ('PARTIAL' if mode == 'partial' else 'FAILED')
    if mode == 'partial':
        assert frozen_sources(db, project_id=1, source_ids=[row.source_id])[0]['coverage_scope'] == 'PARTIAL'
    else:
        assert row.snapshot_hash == '' and row.failure_detail


def test_supplemental_authority_private_urls_and_interruption_are_not_retried(scene):
    db, _, _, _ = scene
    for url, allowed in [(URL, False), ('http://127.0.0.1', True), ('file:///etc/passwd', True)]:
        with pytest.raises(HTTPException):
            queue_source(db, project_id=1, url=url, idempotency_key='not-allowed', fetch_authorized=allowed)
    assert db.query(SupplementalSourceAcquisition).count() == 0
    row = queue(db)
    row.status = 'RUNNING'
    db.commit()
    assert recover_interrupted_sources(db) == 1
    execute_source(row.source_id, session_factory=sessionmaker(bind=db.get_bind()),
        fetcher=lambda urls: pytest.fail('Interrupted request cannot retry itself'))
    db.refresh(row)
    assert row.status == 'INTERRUPTED'


def test_existing_worker_routes_supplemental_and_contract_change_stops_before_fetch(scene, monkeypatch):
    from scripts import release_worker
    from app.modules.single_prompt_v2 import supplemental_sources as module
    db, original, _, _ = scene
    original.status = 'CANCELLED'
    db.commit()
    row = queue(db)
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(release_worker, 'ReleaseSessionLocal', factory)
    calls = []
    def transport(urls):
        calls.extend(urls)
        return [fetched()]
    monkeypatch.setattr(release_worker, 'execute_source', lambda identity, session_factory:
        execute_source(identity, session_factory=session_factory, fetcher=transport))
    assert release_worker.run_once() == f'supplemental_source:{row.source_id}'
    assert calls == [URL]
    other = queue(db, 'new-explicit-request')
    identity = module.request_identity
    monkeypatch.setattr(module, 'request_identity', lambda *a: {**identity(*a), 'attempts_per_url_ceiling': 3})
    execute_source(other.source_id, session_factory=factory, fetcher=transport)
    db.refresh(other)
    assert other.status == 'FAILED' and '授权契约不匹配' in other.failure_detail
    assert calls == [URL]


def test_extra_official_source_reaches_draft_without_entering_citation_scope(scene, monkeypatch):
    db, _, args, _ = scene
    db.get(Project, 1).website_url = 'https://example.com'
    _record_project_configuration(db, db.get(Project, 1))
    db.commit()
    row = queue(db)
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    execute_source(row.source_id, session_factory=factory, fetcher=lambda urls: [fetched()])
    db.refresh(row)
    manifests = [(r.manifest_id, r.payload_hash) for r in db.query(SinglePromptCitationManifest)]
    task, _ = create_task(db, **{**args, 'idempotency_key': 'draft-with-extra'}, supplemental_source_ids=[row.source_id])
    authorize_task(db, task, expected_revision=task.revision, input_hash=task.input_hash,
        max_requests=6, max_tokens=600000, max_cost_cny=6,
        conservative_cny_per_million_tokens=10, pricing_source='isolated-not-provider-price',
        pricing_checked_at=datetime.utcnow().date().isoformat(), authorized_by='isolated-test')
    def claims(payload):
        return {'claims': [{'normalized_claim': BROWSER_CLAIM, 'subject_text': 'Target', 'predicate': '支持',
            'object_text': '批量生成短链（仅限已创建项目）', 'claim_type': 'CAPABILITY',
            'polarity': 'POSITIVE', 'source_span': BROWSER_CLAIM}]}
    def draft(payload):
        fact = next(e for e in payload['public_evidence'] if e.get('attribution_prefix'))
        return {'sections': [{'heading': '核对项目适用条件', 'blocks': [
            {'kind': 'TARGET_STATEMENT', 'text': fact['text'], 'evidence_ids': [fact['evidence_id']]}]}]}
    calls = simulated_delivery_transport(monkeypatch, source_response=claims,
        fact_response=lambda p: {'checks': [approved(c['claim_id']) for c in p['claims']]}, draft_response=draft)
    execute_task(task.task_id, session_factory=factory)
    db.refresh(task)
    assert task.status.startswith('COMPLETED'), (task.blocker_code, task.blocker_detail)
    assert len(calls) == 6
    citation = next(c for c in calls if 'frozen_candidate_pairs' in c)
    assert URL not in json.dumps(citation) and TEXT not in json.dumps(citation, ensure_ascii=False)
    delivery = task_view(task)['objects']['deliveries'][0]
    output = json.loads(db.query(SinglePromptExecutionProposalResult).filter_by(result_version=delivery['result_version']).one().output_json)
    assert output['delivery_input']['supplemental_sources'][0]['snapshot_id'] == row.source_id
    assert BROWSER_CLAIM in output['publication_draft']['body_markdown']
    assert manifests == [(r.manifest_id, r.payload_hash) for r in db.query(SinglePromptCitationManifest)]
    assert db.query(TargetBrandCapabilityTruth).count() == 0


def test_supplemental_formal_api_lists_without_fetch_and_rejects_forged_snapshot(scene):
    from release_test_client import TestClient
    from app.core.release_database import get_release_db
    from app.release_main import create_release_app
    db, _, _, _ = scene
    app = create_release_app(validate_on_startup=False)
    app.dependency_overrides[get_release_db] = lambda: db
    client = TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 55000))
    uri = '/api/v2/projects/1/supplemental-sources'
    payload = {'url': URL, 'idempotency_key': 'explicit-api-request', 'fetch_authorized': True}
    assert client.post(uri, json={**payload, 'snapshot_hash': 'a'*64}).status_code == 422
    saved = client.post(uri, json=payload)
    assert saved.status_code == 201 and saved.json()['status'] == 'QUEUED'
    assert client.post(uri, json=payload).status_code == 200
    for _ in range(2):
        assert client.get(uri).json() == [saved.json()]
    assert db.query(SupplementalSourceAcquisition).count() == 1
