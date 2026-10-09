"""Finite task authority and durable audit, on a migrated isolated database."""
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from test_release_first_slice import _migrated_session, _seed_citation_contribution_fixture
from app.models import SinglePromptAnalysisContext, SinglePromptDiagnosisReview
from app.modules.single_prompt_v2.automatic_delivery import (
    authorize_task, cancel_task, create_task, encode, scoped_client, task_view, execute_task,
    recover_interrupted_tasks, resume_task,
)
from app.services.semantic_llm.base import SemanticLLMError


@pytest.fixture
def scene(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path, reviewed=False)
    context = db.query(SinglePromptAnalysisContext).one()
    args = dict(analysis_id=fixture['analysis'].analysis_id, project_id=1, prompt_id=44,
        raw_output_hash=context.raw_output_hash, idempotency_key='finite-delivery')
    row, _ = create_task(db, **args)
    yield db, row, args, tmp_path
    db.close()
    engine.dispose()


def authorize(db, row):
    return authorize_task(db, row, expected_revision=row.revision, input_hash=row.input_hash,
        max_requests=1, max_tokens=1000, max_cost_cny=0.01,
        conservative_cny_per_million_tokens=10, pricing_source='isolated-test-not-provider-price',
        pricing_checked_at=datetime.utcnow().date().isoformat(), authorized_by='test-operator')


def identity(row):
    inputs = json.loads(row.input_json)
    return dict(provider=inputs['provider'], requested_model_alias=inputs['requested_model'],
        effective_request_model=inputs['effective_request_model'], structured_output_mode='JSON_SCHEMA',
        input_token_upper_bound=500, max_output_tokens=500, input_hash='test-request',
        provider_payload_hash='test-payload')


def test_creation_is_idempotent_and_never_confers_external_or_review_authority(scene):
    db, row, args, _ = scene
    again, created = create_task(db, **args)
    assert not created and again.task_id == row.task_id
    other, created = create_task(db, **{**args, 'idempotency_key': 'another-browser-click'})
    assert not created and other.task_id == row.task_id
    assert task_view(row)['authorization']['policy'] == 'CACHE_ONLY'
    assert db.query(SinglePromptDiagnosisReview).count() == 0
    with pytest.raises(HTTPException):
        create_task(db, **{**args, 'raw_output_hash': '0' * 64})


def test_source_version_is_explicit_and_changes_task_identity_without_replacing_history(scene):
    from app.models import SinglePromptSourceCompletionManifest, SinglePromptSourceDisposition
    from app.modules.single_prompt_v2.source_preparation import freeze_completion_manifest
    db, original, args, _ = scene
    complete = db.query(SinglePromptSourceCompletionManifest).one()
    explicit, _ = create_task(db, **{**args, 'idempotency_key': 'explicit-source-v1'},
        completion_manifest_id=complete.manifest_id, completion_manifest_hash=complete.payload_hash)
    first = explicit.input_json
    source = db.query(SinglePromptSourceDisposition).filter_by(state='READY').one()
    source.state = 'MANUAL_REQUIRED'
    source.active_snapshot_id = None
    db.commit()
    changed = freeze_completion_manifest(db, preparation_id=source.preparation_id, created_by='isolated-fixture', allow_partial=True)
    second, _ = create_task(db, **{**args, 'idempotency_key': 'explicit-source-v2'},
        completion_manifest_id=changed.manifest_id, completion_manifest_hash=changed.payload_hash)
    assert len({original.input_hash, explicit.input_hash, second.input_hash}) == 3
    db.refresh(explicit)
    assert explicit.input_json == first and complete.status == 'FROZEN'
    assert task_view(second)['source_input']['completion_manifest_id'] == changed.manifest_id
    for extra in [dict(completion_manifest_id=complete.manifest_id),
            dict(completion_manifest_id=complete.manifest_id, completion_manifest_hash='0'*64),
            dict(completion_manifest_id=complete.manifest_id, completion_manifest_hash=complete.payload_hash, source_fetch_authorized=True)]:
        with pytest.raises(HTTPException):
            create_task(db, **{**args, 'idempotency_key': 'invalid-source-choice'}, **extra)


def test_authority_and_request_reservation_survive_new_client_and_do_not_reset(scene):
    db, row, _, _ = scene
    authorize(db, row)
    row.status = 'RUNNING'
    db.commit()
    client = scoped_client(db, row)
    client.request_guard(identity(row))
    db.refresh(row)
    assert task_view(row)['usage']['external_requests'] == 1
    assert task_view(row)['usage']['reserved_cost_cny'] == 0.01
    with pytest.raises(SemanticLLMError, match='NO_AUTOMATIC_RETRY'):
        scoped_client(db, row).request_guard(identity(row))
    with pytest.raises(SemanticLLMError, match='BUDGET_EXHAUSTED'):
        scoped_client(db, row).request_guard({**identity(row), 'provider_payload_hash': 'next-request'})
    row.status = 'WAITING_AUTHORIZATION'
    db.commit()
    with pytest.raises(HTTPException, match='重置额度'):
        authorize(db, row)


@pytest.mark.parametrize('usage', [{'total_tokens': 731, 'input_tokens': 631, 'output_tokens': 100}, {}])
def test_inflight_response_after_cancel_preserves_cancellation_and_full_artifact(scene, usage):
    db, row, _, _ = scene
    authorize(db, row)
    row.status = 'RUNNING'
    db.commit()
    client = scoped_client(db, row)
    request = identity(row)
    client.request_guard(request)
    db.refresh(row)
    cancel_task(db, row, row.revision)
    client.response_audit_sink({'request_identity': request, 'response_source': 'PROVIDER',
        'token_usage': usage, 'validation_status': 'FAIL', 'raw_response': {'complete': 'provider machine output'}})
    db.refresh(row)
    assert row.status == 'CANCELLED'
    view = task_view(row)
    assert view['usage']['actual_tokens'] == (731 if usage else 0)
    assert view['usage']['unsettled_requests'] == (0 if usage else 1)
    record = json.loads(row.progress_json)['requests'][0]
    path = Path(record['artifact']['path'])
    assert sha256(path.read_bytes()).hexdigest() == record['artifact']['sha256']
    assert json.loads(path.read_text())['raw_response']['complete'] == 'provider machine output'
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(SemanticLLMError, match='NOT_RUNNING'):
        client.request_guard(request)


def test_payload_model_change_and_stale_cancel_are_rejected_before_request(scene):
    db, row, _, _ = scene
    authorize(db, row)
    row.status = 'RUNNING'
    db.commit()
    with pytest.raises(SemanticLLMError, match='MODEL_IDENTITY_CHANGED'):
        scoped_client(db, row).request_guard({**identity(row), 'requested_model_alias': 'another-model'})
    assert task_view(row)['usage']['external_requests'] == 0
    with pytest.raises(HTTPException):
        cancel_task(db, row, row.revision - 1)
    db.refresh(row)
    assert row.status == 'RUNNING'


def test_cache_only_worker_does_not_call_network_or_fabricate_review(scene, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app.services.semantic_llm import deepseek
    db, row, _, _ = scene
    def no_network(*args, **kwargs):
        raise AssertionError('No external permission')
    monkeypatch.setattr(deepseek.httpx, 'Client', no_network)
    execute_task(row.task_id, session_factory=sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    db.refresh(row)
    assert row.status == 'WAITING_AUTHORIZATION', row.blocker_detail
    assert task_view(row)['usage']['external_requests'] == 0
    assert task_view(row)['objects']['answer_coverage']['valid_compute_run_ids'] == []
    assert db.query(SinglePromptDiagnosisReview).count() == 0


def test_interruption_requires_explicit_recovery_and_keeps_budget(scene):
    db, row, _, _ = scene
    authorize(db, row)
    row.status = 'RUNNING'
    db.commit()
    scoped_client(db, row).request_guard(identity(row))
    assert recover_interrupted_tasks(db) == 1
    db.refresh(row)
    assert row.status == 'INTERRUPTED' and task_view(row)['usage']['external_requests'] == 1
    with pytest.raises(HTTPException, match='未核实用量'):
        resume_task(db, row, row.revision)


def test_budget_rejected_answer_is_pending_not_failed_and_has_no_external_call(scene, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app.services.semantic_llm import deepseek
    from app.models import SinglePromptDiagnosisResult
    db, row, _, _ = scene
    authorize(db, row)  # Its 1,000-token ceiling is below this request's input.
    monkeypatch.setattr(deepseek.get_settings(), 'deepseek_api_key', 'isolated-never-real')
    def no_network(*args, **kwargs):
        raise AssertionError('Budget denial must precede network')
    monkeypatch.setattr(deepseek.httpx, 'Client', no_network)
    execute_task(row.task_id, session_factory=sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    db.refresh(row)
    view = task_view(row)
    assert row.status == 'BLOCKED' and row.blocker_code == 'ANSWER_AUTHORIZATION_INSUFFICIENT'
    assert view['usage']['external_requests'] == 0
    assert view['objects']['answer_coverage']['actual_failure_run_ids'] == []
    assert view['objects']['answer_coverage']['pending_external_authorization_run_ids'] == view['scope']
    result = db.query(SinglePromptDiagnosisResult).filter_by(result_version=view['objects']['answer_result_version']).one()
    payload = json.loads(result.output_json)
    assert payload['answer_diagnosis']['failures'] == []
    assert payload['answer_diagnosis']['answer_jobs'][0]['result_source'] == 'REQUEST_NOT_SENT'


def simulated_delivery_transport(monkeypatch, on_request=None, qa_response=None, citation_response=None,
                                 source_response=None, fact_response=None, draft_response=None):
    """Test-only Responses/chat boundary for offline API and browser wiring checks."""
    from app.services.semantic_llm import deepseek
    calls = []
    class Response:
        status_code = 200
        text = ''
        def __init__(self, body): self.body = body
        def json(self): return self.body
    class Http:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, headers, json):
            import json as codec
            payload = codec.loads(json.get('input') or json['messages'][-1]['content'])
            calls.append(payload)
            if on_request:
                on_request(payload)
            if 'untrusted_source_passage' in payload and source_response:
                response = source_response(payload)
            elif payload.get('contract_version') == 'delivery_official_attestation.v1' and fact_response:
                response = fact_response(payload)
            elif 'segments' in payload:
                response = qa_response(payload) if qa_response else {'checks': [{'segment_id': s['segment_id'], 'verdict': 'PASS', 'rationale': '仅给查证步骤，不增加事实。'} for s in payload['segments']]}
            elif 'public_evidence' in payload:
                response = draft_response(payload) if draft_response else {'sections': [{'heading': '选用工具前的核对顺序', 'blocks': [{'kind': 'INSTRUCTION',
                    'text': '先列出需要处理的链接数量和使用场景，再向服务方核对当前限制；以实际说明为准，不把答案中的工具名称当成能力保证。', 'evidence_ids': []}]}]}
            elif 'frozen_candidate_pairs' in payload:
                response = citation_response(payload) if citation_response else {'evaluations': [{**pair, 'answer_span': None, 'source_span': None,
                    'correspondence_mode': 'NO_CORRESPONDENCE', 'evidence_relation': 'NO_MATCH',
                    'rationale': '已逐项检查该固定候选，模拟结果为没有内容对应。'}
                    for pair in payload['frozen_candidate_pairs']], 'no_binding_reason': None}
            else:
                response = {'events': [], 'selection_criteria': [], 'unresolved_items': []}
            content = codec.dumps(response, ensure_ascii=False)
            usage = {'input_tokens': 100, 'output_tokens': 50, 'total_tokens': 150}
            if url.endswith('/responses'):
                return Response({'model': json['model'], 'status': 'completed', 'usage': usage,
                    'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': content}]}]})
            return Response({'model': json['model'], 'usage': usage,
                'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]})
    monkeypatch.setattr(deepseek.httpx, 'Client', Http)
    monkeypatch.setattr(deepseek.get_settings(), 'deepseek_api_key', 'isolated-never-real')
    return calls


def test_worker_real_stage_wiring_with_simulated_transport_not_real_llm(scene, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app.models import Project, SinglePromptExecutionProposalResult
    db, row, _, _ = scene
    authorize_task(db, row, expected_revision=row.revision, input_hash=row.input_hash,
        max_requests=4, max_tokens=400000, max_cost_cny=4,
        conservative_cny_per_million_tokens=10, pricing_source='isolated-fixture-not-real-pricing',
        pricing_checked_at=datetime.utcnow().date().isoformat(), authorized_by='isolated-test')
    db.get(Project, 1).brand_name = '创建任务之后修改的品牌'
    db.commit()
    stages = []
    def capture_stage(payload):
        db.refresh(row)
        stage = task_view(row)['stage']
        stages.append(stage)
        if 'segments' in payload:
            assert stage == 'TEXT_QA'
        elif 'public_evidence' in payload:
            assert stage == 'DRAFT'
    calls = simulated_delivery_transport(monkeypatch, on_request=capture_stage)
    execute_task(row.task_id, session_factory=sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    db.refresh(row)
    assert row.status in {'COMPLETED', 'COMPLETED_WITH_LIMITATIONS'}, (row.blocker_code, row.blocker_detail, task_view(row))
    view = task_view(row)
    assert len(calls) == 4 and view['usage']['external_requests'] == 4
    assert stages == ['ANSWER', 'CITATION', 'DRAFT', 'TEXT_QA']
    assert view['usage']['actual_tokens'] == 600 and view['usage']['unsettled_requests'] == 0
    assert '创建任务之后修改的品牌' not in json.dumps(calls, ensure_ascii=False)
    from app.models import SinglePromptCitationContributionResult
    reference = view['objects']['citation_results'][0]
    contribution = json.loads(db.query(SinglePromptCitationContributionResult).filter_by(result_version=reference['result_version']).one().output_json)
    assert sum(c['processing_status'] == 'DONE' for c in contribution['citations']) == 1, [c.get('failure_detail') for c in contribution['citations']]
    assert sum(c['processing_status'] == 'FAILED' for c in contribution['citations']) == 0
    assert contribution['bindings'] == []
    assert len(contribution['evaluations']) == len(next(c['frozen_candidate_pairs'] for c in calls if 'frozen_candidate_pairs' in c))
    assert db.query(SinglePromptDiagnosisReview).count() == 0
    delivery = view['objects']['deliveries'][0]
    saved = db.query(SinglePromptExecutionProposalResult).filter_by(result_version=delivery['result_version']).one()
    assert json.loads(saved.output_json)['validation']['content_delivery_status'] == 'READY'
    execute_task(row.task_id, session_factory=sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    assert len(calls) == 4


def test_multi_run_task_preserves_each_contribution_version_and_never_reads_latest(scene, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app.models import BrowserMonitorRun, ReferenceSource, SinglePromptCitationContributionResult, SinglePromptCitationContributionExecution
    from app.modules.single_prompt_v2.service import list_prompt_run_pool, create_analysis_from_runs
    from app.modules.single_prompt_v2.qualification import _load_current_contribution_scope
    db, _, _, _ = scene
    first = db.query(BrowserMonitorRun).one()
    second = BrowserMonitorRun(**{c.name: getattr(first, c.name) for c in first.__table__.columns
        if c.name not in {'id', 'created_at', 'updated_at'}})
    db.add(second)
    db.flush()
    for reference in db.query(ReferenceSource).filter_by(run_id=first.id).all():
        db.add(ReferenceSource(**{c.name: getattr(reference, c.name) for c in reference.__table__.columns
            if c.name not in {'id', 'run_id'}}, run_id=second.id))
    db.commit()
    pool = list_prompt_run_pool(db, project_id=1, prompt_id=44, page=1, page_size=20)
    selected = [first.id, second.id]
    analysis, _ = create_analysis_from_runs(db, project_id=1, prompt_id=44, run_ids=selected,
        run_fingerprints={r['run_id']: r['input_fingerprint'] for r in pool['items']},
        idempotency_key='two-run-offline-scope', base_context_id=None)
    context = db.query(SinglePromptAnalysisContext).filter_by(analysis_id=analysis.analysis_id).one()
    from app.models import SinglePromptSourceCompletionManifest
    from app.modules.single_prompt_v2.source_preparation import create_source_preparation, reuse_completed_sources
    source_version = db.query(SinglePromptSourceCompletionManifest).one()
    preparation, _ = create_source_preparation(db, analysis_id=analysis.analysis_id, project_id=1,
        prompt_id=44, idempotency_key='two-run-sources', created_by='isolated-test')
    reuse_completed_sources(db, preparation_id=preparation.preparation_id, project_id=1, prompt_id=44,
        source_completion_manifest_id=source_version.manifest_id,
        source_completion_manifest_hash=source_version.payload_hash, reused_by='isolated-test')
    task, _ = create_task(db, analysis_id=analysis.analysis_id, project_id=1, prompt_id=44,
        raw_output_hash=context.raw_output_hash, idempotency_key='two-run-delivery')
    authorize_task(db, task, expected_revision=task.revision, input_hash=task.input_hash,
        max_requests=8, max_tokens=800000, max_cost_cny=8,
        conservative_cny_per_million_tokens=10, pricing_source='isolated-test-not-real-pricing',
        pricing_checked_at=datetime.utcnow().date().isoformat(), authorized_by='isolated-test')
    calls = simulated_delivery_transport(monkeypatch)
    execute_task(task.task_id, session_factory=sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    db.refresh(task)
    view = task_view(task)
    assert task.status in {'COMPLETED', 'COMPLETED_WITH_LIMITATIONS'}, (task.blocker_detail, view)
    assert view['objects']['answer_coverage']['valid_compute_run_ids'] == selected
    references = view['objects']['citation_results']
    assert {r['run_id'] for r in references} == set(selected)
    versions = [r['result_version'] for r in references]
    args = dict(analysis_id=analysis.analysis_id, context_id=context.context_id,
        answer_result_version=view['objects']['answer_result_version'], answer_result_hash=view['objects']['answer_result_hash'])
    original = _load_current_contribution_scope(db, **args, result_versions=versions)
    assert original['run_ids'] == selected
    assert _load_current_contribution_scope(db, **args, result_versions=versions[::-1]) == original
    owner = db.query(SinglePromptCitationContributionExecution).filter_by(contribution_id=references[0]['contribution_id']).one()
    old = db.query(SinglePromptCitationContributionResult).filter_by(result_version=versions[0]).one()
    newer = SinglePromptCitationContributionResult(contribution_id=owner.contribution_id,
        result_version='contribution-v2:isolated-same-owner', version_number=2,
        output_json=old.output_json, output_hash=old.output_hash, reviewable_set_hash=old.reviewable_set_hash)
    db.add(newer)
    owner.active_result_version = newer.result_version
    db.commit()
    assert _load_current_contribution_scope(db, **args, result_versions=versions) == original
    with pytest.raises(HTTPException, match='同一 Run'):
        _load_current_contribution_scope(db, **args, result_versions=[versions[0], newer.result_version])
    with pytest.raises(HTTPException):
        _load_current_contribution_scope(db, **{**args, 'answer_result_hash': '0'*64}, result_versions=versions)
    assert _load_current_contribution_scope(db, **args, result_versions=[])['status'] == 'UNAVAILABLE'
    assert db.query(SinglePromptDiagnosisReview).count() == 0 and len(calls) <= 8


def test_official_task_api_is_scoped_read_only_and_requires_exact_authorization(scene):
    from release_test_client import TestClient
    from app.core.release_database import get_release_db
    from app.release_main import create_release_app
    from app.models import SinglePromptOptimizationTask
    db, row, args, _ = scene
    app = create_release_app(validate_on_startup=False)
    app.dependency_overrides[get_release_db] = lambda: db
    client = TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 55000))
    root = '/api/v2/single-prompt'
    path = f"{root}/analyses/{args['analysis_id']}/optimization-tasks"
    value = {k: v for k, v in args.items() if k != 'analysis_id'}
    assert client.post(path, json=value).status_code == 200
    count = db.query(SinglePromptOptimizationTask).count()
    for _ in range(2):
        listing = client.get(path + '?project_id=1&prompt_id=44')
        assert listing.status_code == 200 and listing.json()[0]['task_id'] == row.task_id
        response = client.get(f'{root}/optimization-tasks/{row.task_id}/deliveries?project_id=1&prompt_id=44')
        assert response.status_code == 200 and response.json() == []
    assert db.query(SinglePromptOptimizationTask).count() == count
    assert client.get(path + '?project_id=2&prompt_id=44').status_code == 404
    assert client.get(f'{root}/optimization-tasks/{row.task_id}?project_id=2&prompt_id=44').status_code == 404
    bad = client.post(f'{root}/optimization-tasks/{row.task_id}/authorization', json={
        'project_id': 1, 'prompt_id': 44, 'expected_revision': row.revision, 'input_hash': '0' * 64,
        'max_requests': 1, 'max_tokens': 1000, 'max_cost_cny': 0.01, 'conservative_cny_per_million_tokens': 10,
        'pricing_source': 'isolated-test-price', 'pricing_checked_at': datetime.utcnow().date().isoformat()})
    assert bad.status_code == 409
    assert client.post(f'{root}/optimization-tasks/{row.task_id}/cancel', json={
        'project_id': 1, 'prompt_id': 44, 'expected_revision': row.revision}).status_code == 200
    db.refresh(row)
    assert row.status == 'CANCELLED'
