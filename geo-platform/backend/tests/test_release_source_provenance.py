"""Acquisition records are bounded evidence, never implicit official Truth."""
import copy
import json
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app.models import SinglePromptPreparedSourceSnapshot, SinglePromptSourceDisposition
from app.modules.optimization.passage_service import _acquisition_receipt
from app.modules.single_prompt_v2 import source_preparation as sources
from test_release_first_slice import _session, _configure_artifacts, _seed_frozen_analysis, _create_preparation


TEXT = '目标工具在专业套餐中支持批量导出。导出前须选择日期范围，结果不包含已删除记录。' * 4
WHEN = datetime(2026, 10, 9, 12)
URL = 'https://example.com/docs'


def receipt():
    result = {'url': URL, 'final_url': 'https://other.example/final', 'fetch_time': WHEN,
              'fetch_method': 'HTTP兜底抓取', 'network_policy': 'PUBLIC_DNS_PINNED_TLS_VERIFIED_V1',
              'fetch_status': 'SUCCESS', 'clean_text': TEXT}
    document = {'url': result['final_url'], 'status': 200, 'tls_verified': True,
                'public_address_pinned': True, 'response_body_hash': 'f' * 64,
                'content_type': 'text/html', 'last_modified': ''}
    return _acquisition_receipt(result, [document])


def validate(value, method='AUTO_FETCH'):
    sources._validate_acquisition_receipt(value, text_hash=sources._text_hash(TEXT), source_url=URL,
                                          acquired_at=WHEN, method=method)


def test_final_host_is_preserved_not_promoted_to_official():
    value = receipt()
    validate(value)
    assert value['requested_url'] != value['final_url']
    assert value['scope'] == 'TRANSPORT_AND_EXTRACTED_CONTENT_ONLY'
    assert not any(key in value for key in ['truth_status', 'eligibility_by_use', 'official_source'])


@pytest.mark.parametrize('field,value', [
    ('content_hash', 'a' * 64), ('requested_url', 'https://wrong.example'),
    ('final_url', 'https://unknown.example'), ('acquired_at', '2026-10-10T12:00:00'),
    ('network_policy', 'UNVERIFIED'), ('extra_field', True),
    ('documents', []),
])
def test_receipt_rejects_wrong_binding(field, value):
    altered = receipt()
    altered[field] = value
    with pytest.raises(ValueError, match='RECEIPT_INVALID'):
        validate(altered)


@pytest.mark.parametrize('value', [[], None, False, 'invalid'])
def test_malformed_receipt_not_silently_unknown(value):
    with pytest.raises(ValueError, match='RECEIPT_INVALID'):
        validate(value)


def test_manual_paste_cannot_claim_verified_transport():
    with pytest.raises(ValueError, match='RECEIPT_INVALID'):
        validate(receipt(), method='MANUAL_HTML_SOURCE')
    validate({}, method='MANUAL')


def test_acquisition_requires_success_and_exact_final_document():
    result = {'fetch_status': 'PARTIAL'}
    assert _acquisition_receipt(result, receipt()['documents']) == {}
    result.update(fetch_status='SUCCESS', final_url='https://unknown.example')
    assert _acquisition_receipt(result, receipt()['documents']) == {}


def test_auto_fetch_freezes_receipt_and_detects_tampering(tmp_path, monkeypatch):
    _configure_artifacts(monkeypatch, tmp_path)
    db, engine = _session(tmp_path)
    try:
        analysis = _seed_frozen_analysis(db, reference_urls=[URL])
        preparation, _ = _create_preparation(db, analysis)
        sources.queue_auto_fetch(db, preparation_id=preparation.preparation_id, project_id=1, prompt_id=44)
        summary = sources.execute_auto_fetch(preparation.preparation_id,
            session_factory=sessionmaker(bind=engine, expire_on_commit=False), fetcher=lambda urls: [{
                'canonical_url': receipt()['final_url'], 'fetch_status': 'SUCCESS', 'title': '产品使用说明',
                'clean_text': TEXT, 'fetch_time': WHEN, 'acquisition_receipt': receipt(),
            }])
        assert summary == {'requested': 1, 'ready': 1, 'manual_required': 0}
        db.expire_all()
        snapshot = db.query(SinglePromptPreparedSourceSnapshot).one()
        assert json.loads(snapshot.acquisition_receipt_json) == receipt()
        assert snapshot.canonical_url == URL
        completion = sources.freeze_completion_manifest(db, preparation_id=preparation.preparation_id, created_by='test')
        binding = json.loads(completion.payload_json)['sources'][0]
        assert binding['acquisition_receipt_hash'] == sources._hash(receipt())
        args = dict(analysis_id=analysis.analysis_id, context_id=preparation.context_id, citation_manifest_id=preparation.citation_manifest_id,
                    citation_manifest_hash=preparation.citation_manifest_hash,
                    completion_manifest_id=completion.manifest_id, completion_manifest_hash=completion.payload_hash)
        sources.validate_completion_for_evidence(db, **args)
        changed = copy.deepcopy(receipt())
        changed['documents'][0]['last_modified'] = 'another date'
        snapshot.acquisition_receipt_json = json.dumps(changed)
        db.commit()
        with pytest.raises(HTTPException) as error:
            sources.validate_completion_for_evidence(db, **args)
        assert error.value.status_code == 409
    finally:
        db.close()
        engine.dispose()


def test_reused_snapshot_retains_original_acquisition_time(tmp_path, monkeypatch):
    _configure_artifacts(monkeypatch, tmp_path)
    db, engine = _session(tmp_path)
    try:
        analysis = _seed_frozen_analysis(db, reference_urls=[URL])
        preparation, _ = _create_preparation(db, analysis)
        disposition = db.query(SinglePromptSourceDisposition).one()
        original = sources._snapshot_from_content(db, preparation=preparation, disposition=disposition,
            title='产品说明', clean_text=TEXT, coverage_scope='FULL_PAGE', acquisition_method='AUTO_FETCH',
            submitted_by='test', acquired_at=WHEN, acquisition_receipt=receipt())
        db.commit()
        completion = sources.freeze_completion_manifest(db, preparation_id=preparation.preparation_id, created_by='test')
        from app.modules.single_prompt_v2.service import create_analysis_from_runs, list_prompt_run_pool
        run = list_prompt_run_pool(db, project_id=1, prompt_id=44, page=1, page_size=20)['items'][0]
        another, _ = create_analysis_from_runs(db, project_id=1, prompt_id=44, run_ids=[run['run_id']],
            run_fingerprints={run['run_id']: run['input_fingerprint']}, base_context_id=preparation.context_id,
            idempotency_key='receipt-reuse-analysis')
        target, _ = sources.create_source_preparation(db, analysis_id=another.analysis_id, project_id=1,
            prompt_id=44, idempotency_key='receipt-reuse-preparation', created_by='test')
        reused = sources.reuse_completed_sources(db, preparation_id=target.preparation_id, project_id=1,
            prompt_id=44, source_completion_manifest_id=completion.manifest_id,
            source_completion_manifest_hash=completion.payload_hash, reused_by='test')
        clone = db.query(SinglePromptPreparedSourceSnapshot).filter_by(snapshot_id=reused['reused'][0]['snapshot_id']).one()
        assert clone.acquired_at == WHEN
        assert clone.acquisition_receipt_json == original.acquisition_receipt_json
        assert clone.reused_from_snapshot_id == original.snapshot_id
        assert clone.content_hash == original.content_hash
    finally:
        db.close()
        engine.dispose()


def test_upgrade_preserves_legacy_columns_and_does_not_invent_receipts(tmp_path, monkeypatch):
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, MetaData, Table, text
    from sqlalchemy.exc import IntegrityError
    from scripts.release_upgrade_check import business_columns, business_fingerprint
    from app.models import Base
    path = tmp_path / 'upgrade.db'
    monkeypatch.setenv('GEO_RELEASE_DATABASE_URL', f'sqlite:///{path}')
    config = Config(str(Path(__file__).resolve().parents[1] / 'alembic.release.ini'))
    command.upgrade(config, '20261009_03')
    engine = create_engine(f'sqlite:///{path}')
    name = 'single_prompt_prepared_source_snapshots'
    old = Table(name, MetaData(), autoload_with=engine)
    assert 'acquisition_receipt_json' not in old.columns
    assert set(old.columns.keys()) == set(Base.metadata.tables[name].columns.keys()) - {'acquisition_receipt_json'}
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    analysis = _seed_frozen_analysis(db, reference_urls=[URL])
    preparation, _ = _create_preparation(db, analysis)
    disposition = db.query(SinglePromptSourceDisposition).one()
    # Snapshot fields are deliberately inserted through the actual old schema, not the new ORM.
    with engine.begin() as connection:
        connection.execute(old.insert().values(id=1, snapshot_id='historical', preparation_id=preparation.preparation_id,
            context_id=preparation.context_id, citation_manifest_id=preparation.citation_manifest_id,
            source_key=disposition.source_key, canonical_url=URL, original_urls_json='[]',
            reference_observations_json='[]', occurrence_count=1, title='Historical', content_hash='a'*64,
            clean_text=TEXT, artifact_path='/not-used-in-this-ddl-test', artifact_hash='a'*64,
            passages_json='[]', passages_hash='b'*64, parser_version='old', acquisition_method='MANUAL',
            coverage_scope='FULL_PAGE', acquired_at=WHEN, submitted_by='test', created_at=WHEN))
    columns = business_columns(path)
    before = business_fingerprint(path)
    db.close()
    engine.dispose()
    command.upgrade(config, 'head')
    after = business_fingerprint(path, columns)
    assert {name: after[name] for name in before} == before
    assert set(after) - set(before) == {'supplemental_source_acquisitions'}
    assert after['supplemental_source_acquisitions']['count'] == 0
    engine = create_engine(f'sqlite:///{path}')
    with engine.connect() as connection:
        assert connection.execute(text(f'SELECT acquisition_receipt_json FROM {name}')).scalar_one() == '{}'
        assert connection.execute(text('PRAGMA foreign_key_check')).fetchall() == []
        with pytest.raises(IntegrityError, match='RELEASE_HISTORY_IMMUTABLE'):
            connection.execute(text(f"UPDATE {name} SET acquisition_receipt_json=:receipt"),
                               {'receipt': json.dumps({'made_up': True})})
    engine.dispose()
