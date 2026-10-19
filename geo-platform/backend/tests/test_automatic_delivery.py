"""Finite task authority and durable audit, on a migrated isolated database."""
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from test_release_first_slice import _migrated_session, _seed_citation_contribution_fixture
from app.api.release_catalog import _record_project_configuration
from app.models import Project, SinglePromptAnalysis, SinglePromptAnalysisContext, SinglePromptDiagnosisReview, SinglePromptOptimizationTask
from app.modules.single_prompt_v2.automatic_delivery import (
    _draft_evidence_qualification,
    _validate_delivery_result,
    authorize_task, cancel_task, create_task, encode, scoped_client, task_view, execute_task,
    recover_interrupted_tasks, require_task, resume_task,
)
from app.modules.single_prompt_v2.delivery_text import digest, text_digest
from app.services.semantic_llm.base import SemanticLLMError


@pytest.fixture
def scene(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path, reviewed=False)
    _record_project_configuration(db, db.get(Project, 1))
    db.commit()
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
    transport = inputs['model_call_transport_identity']
    return dict(provider=inputs['provider'], requested_model_alias=inputs['requested_model'],
        effective_request_model=inputs['effective_request_model'], structured_output_mode='JSON_SCHEMA',
        derived_call_identity_contract_version=transport['contract_version'],
        cache_identity_version=transport['cache_identity_version'], endpoint=transport['endpoint'],
        endpoint_path=transport['endpoint_path'], transport_kind=transport['transport_kind'],
        transport_version=transport['transport_version'], call_identity_hash='1' * 64,
        input_scope_hash='2' * 64, input_token_upper_bound=500, max_output_tokens=500,
        input_hash='test-request', provider_payload_hash='test-payload')


def test_draft_evidence_gate_does_not_erase_independent_truth_only_use():
    row = SimpleNamespace(task_id='task-1', input_hash='f' * 64,
        analysis_id='analysis-1', context_id='context-1', project_id=1, prompt_id=2)
    direction = {"direction_id": "direction-truth", "direction_type": "MECHANISM",
        "truth_ids": [7], "reason_run_ids": [7], "evidence_relation_ids": [], "dependencies": [{
            "object_type": "CITATION_CONTRIBUTION_SCOPE", "object_id": "contribution-v1:x",
            "required_for": ["STRATEGY_DIRECTION"], "state": "LIMITED"}]}
    truth_snapshot = {"truth_id": 7, "capability_label": "提供公开帮助文档",
        "product_truth_status": "TRUE", "truth_source": "MANUAL_CONFIRMED",
        "source_reference": "https://example.com/help"}
    delivery = {"identity": {"analysis_id": "analysis-1", "context_id": "context-1",
        "project_id": 1, "prompt_id": 2, "strategy_id": "strategy-1",
        "strategy_result_version": "strategy-v1:x", "strategy_result_hash": "a" * 64,
        "answer_result_version": "answer-v1:x", "answer_result_hash": "b" * 64},
        "strategy_direction": direction, "answers": [{"run_id": 7}], "selected_evidence": [],
        "answer_result_version": "answer-v1:x", "answer_result_hash": "b" * 64,
        "truths": [{"product_truth_id": 7, "public_use_eligibility": "CONSUMABLE",
            "truth_snapshot": truth_snapshot, "truth_snapshot_hash": digest(truth_snapshot)}]}
    base_output = {"proposal_id": "proposal-1", "direction": direction,
        "input_identity": delivery["identity"], "delivery_input": delivery,
        "evidence_processing_audit": {"selected_binding_ids": []}}
    result = _draft_evidence_qualification(row=row, fixed={"run_ids": [7]}, strategy_id='strategy-1',
        strategy_result_version='strategy-v1:x', strategy_result_hash='a' * 64,
        direction=direction, base_output=base_output, proposal_id="proposal-1",
        proposal_result_version="execution-v1:x", proposal_result_hash=digest(base_output))
    assert result['status'] == 'NOT_APPLICABLE'
    assert result['code'] == 'DRAFT_SOURCE_EVIDENCE_NOT_REQUIRED'
    assert result['requirements'] == {'identity_and_frozen_scope_match': True,
        'truth_allowlist_match': True}
    assert result['qualification_plan']


def test_non_citation_direction_rejects_foreign_identity_without_plan():
    row = SimpleNamespace(task_id='task-1', input_hash='f' * 64,
        analysis_id='analysis-1', context_id='context-1', project_id=1, prompt_id=2)
    direction = {"direction_id": "direction-truth", "reason_run_ids": [7],
        "evidence_relation_ids": [], "dependencies": []}
    delivery = {"identity": {"analysis_id": "foreign-analysis", "context_id": "context-1",
        "project_id": 1, "prompt_id": 2, "strategy_id": "strategy-1",
        "strategy_result_version": "strategy-v1:x", "strategy_result_hash": "a" * 64,
        "answer_result_version": "answer-v1:x", "answer_result_hash": "b" * 64},
        "strategy_direction": direction, "answers": [{"run_id": 7}], "selected_evidence": [],
        "answer_result_version": "answer-v1:x", "answer_result_hash": "b" * 64, "truths": []}
    base_output = {"proposal_id": "proposal-1", "direction": direction,
        "input_identity": delivery["identity"], "delivery_input": delivery,
        "evidence_processing_audit": {"selected_binding_ids": []}}
    result = _draft_evidence_qualification(row=row, fixed={"run_ids": [7]}, strategy_id='strategy-1',
        strategy_result_version='strategy-v1:x', strategy_result_hash='a' * 64,
        direction=direction, base_output=base_output, proposal_id="proposal-1",
        proposal_result_version="execution-v1:x", proposal_result_hash=digest(base_output))
    assert result['status'] == 'BLOCKED'
    assert result['gaps'] == ['DELIVERY_IDENTITY_OR_FROZEN_SCOPE_MISMATCH']
    assert 'qualification_plan' not in result


def test_non_citation_direction_rejects_foreign_evidence_without_plan():
    row = SimpleNamespace(task_id='task-1', input_hash='f' * 64,
        analysis_id='analysis-1', context_id='context-1', project_id=1, prompt_id=2)
    direction = {"direction_id": "direction-clean", "reason_run_ids": [7],
        "truth_ids": [], "evidence_relation_ids": [], "dependencies": []}
    identity = {"analysis_id": "analysis-1", "context_id": "context-1",
        "project_id": 1, "prompt_id": 2, "strategy_id": "strategy-1",
        "strategy_result_version": "strategy-v1:x", "strategy_result_hash": "a" * 64,
        "answer_result_version": "answer-v1:x", "answer_result_hash": "b" * 64}
    text = "历史范围中的正文，不属于当前方向。"
    delivery = {"identity": identity, "strategy_direction": direction,
        "answers": [{"run_id": 7}], "answer_result_version": "answer-v1:x",
        "answer_result_hash": "b" * 64, "truths": [], "selected_evidence": [{
            "section_id": "history:evidence", "binding_id": "history:binding",
            "evidence_relation": "SUPPORTS_FULL", "snapshot_id": "history:snapshot",
            "passage_id": "history:passage", "passage_text": text,
            "passage_hash": text_digest(text)}]}
    base_output = {"proposal_id": "proposal-1", "direction": direction,
        "input_identity": identity, "delivery_input": delivery,
        "evidence_processing_audit": {"selected_binding_ids": []}}
    result = _draft_evidence_qualification(row=row, fixed={"run_ids": [7]},
        strategy_id='strategy-1', strategy_result_version='strategy-v1:x',
        strategy_result_hash='a' * 64, direction=direction, base_output=base_output,
        proposal_id="proposal-1", proposal_result_version="execution-v1:x",
        proposal_result_hash=digest(base_output))
    assert result['status'] == 'BLOCKED'
    assert {'EVIDENCE_SCOPE_OR_VERSION_MISMATCH', 'STRATEGY_EVIDENCE_NOT_BOUND',
        'DRAFT_EVIDENCE_ALLOWLIST_INVALID'} <= set(result['gaps'])
    assert 'qualification_plan' not in result


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


def test_tasks_bind_exact_project_configuration_versions_without_replacing_history(scene):
    db, first, args, _ = scene
    first_input = first.input_json
    v1 = json.loads(first_input)['project_configuration_version']
    assert v1['version_number'] == 1 and len(v1['snapshot_hash']) == 64
    assert task_view(first)['project_configuration_version'] == v1

    project = db.get(Project, 1)
    project.brand_name = 'Target V2'
    project.brand_aliases_json = '["target-v2"]'
    db.flush()
    v2_row = _record_project_configuration(db, project)
    db.commit()
    second, created = create_task(db, **{**args, 'idempotency_key': 'finite-delivery-v2'})
    assert created and second.input_hash != first.input_hash
    v2 = json.loads(second.input_json)['project_configuration_version']
    assert v2 == {"configuration_version_id": v2_row.configuration_version_id,
        "version_number": 2, "snapshot_hash": v2_row.snapshot_hash}
    assert json.loads(second.input_json)['brand']['brand_name'] == 'Target V2'
    db.refresh(first)
    assert first.input_json == first_input
    assert require_task(db, first.task_id, 1, 44).task_id == first.task_id


def test_task_configuration_binding_rejects_cross_project_or_changed_identity_and_marks_legacy(scene):
    db, row, _, _ = scene
    frozen = json.loads(row.input_json)
    project = db.get(Project, 1)
    other = Project(organization_id=project.organization_id, name='Other', brand_name='Other')
    db.add(other)
    db.flush()
    foreign = _record_project_configuration(db, other)
    db.commit()
    forged = dict(frozen)
    forged['project_configuration_version'] = {
        'configuration_version_id': foreign.configuration_version_id,
        'version_number': foreign.version_number, 'snapshot_hash': foreign.snapshot_hash}
    forged_row = SinglePromptOptimizationTask(task_id='forged-config-task', project_id=1, prompt_id=44,
        analysis_id=row.analysis_id, context_id=row.context_id, idempotency_key='forged-config-task',
        input_json=encode(forged), input_hash=digest(forged), authorization_json=row.authorization_json,
        progress_json=row.progress_json)
    db.add(forged_row)
    db.commit()
    with pytest.raises(HTTPException, match='不存在或不属于当前项目'):
        require_task(db, forged_row.task_id, 1, 44)
    from sqlalchemy.orm import sessionmaker
    execute_task(forged_row.task_id, session_factory=sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    db.refresh(forged_row)
    assert forged_row.status == 'BLOCKED' and '不属于当前项目' in forged_row.blocker_detail

    changed = dict(frozen)
    changed['project_configuration_version'] = dict(changed['project_configuration_version'], snapshot_hash='0' * 64)
    changed_row = SinglePromptOptimizationTask(task_id='changed-config-task', project_id=1, prompt_id=44,
        analysis_id=row.analysis_id, context_id=row.context_id, idempotency_key='changed-config-task',
        input_json=encode(changed), input_hash=digest(changed), authorization_json=row.authorization_json,
        progress_json=row.progress_json)
    db.add(changed_row)
    db.commit()
    with pytest.raises(HTTPException, match='内容或 hash 已变化'):
        require_task(db, changed_row.task_id, 1, 44)

    legacy = dict(frozen)
    legacy.pop('project_configuration_version')
    legacy_row = SinglePromptOptimizationTask(task_id='legacy-config-task', project_id=1, prompt_id=44,
        analysis_id=row.analysis_id, context_id=row.context_id, idempotency_key='legacy-config-task',
        input_json=encode(legacy), input_hash=digest(legacy), authorization_json=row.authorization_json,
        progress_json=row.progress_json)
    db.add(legacy_row)
    db.commit()
    assert require_task(db, legacy_row.task_id, 1, 44).task_id == legacy_row.task_id
    assert task_view(legacy_row)['project_configuration_version'] == {'binding_status': 'LEGACY_UNBOUND'}


def test_task_read_guard_rejects_flush_and_bulk_business_writes(scene):
    from sqlalchemy import update
    from app.core.release_database import ReadOnlyBusinessQueryError, read_only_release_session
    from app.models import SinglePromptOptimizationTask
    db, row, _, _ = scene
    original_status = row.status

    with pytest.raises(ReadOnlyBusinessQueryError, match='business write'):
        with read_only_release_session(db):
            row.status = 'CANCELLED'
            db.commit()
    db.refresh(row)
    assert row.status == original_status

    with pytest.raises(ReadOnlyBusinessQueryError, match='business write'):
        with read_only_release_session(db):
            db.execute(update(SinglePromptOptimizationTask).where(
                SinglePromptOptimizationTask.id == row.id,
            ).values(status='CANCELLED'))
    db.refresh(row)
    assert row.status == original_status


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
                                 source_response=None, fact_response=None, draft_response=None, answer_response=None):
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
                if citation_response:
                    response = citation_response(payload)
                else:
                    response = {'evaluations': [], 'no_binding_reason': None}
                    for index, pair in enumerate(payload['frozen_candidate_pairs']):
                        supported = index == 0
                        response['evaluations'].append({**pair,
                            'answer_span': payload['untrusted_answer_units'][pair['answer_unit_index']]['raw_text'] if supported else None,
                            'source_span': payload['untrusted_source_passages'][pair['passage_index']]['text'] if supported else None,
                            'correspondence_mode': 'FAITHFUL_PARAPHRASE' if supported else 'NO_CORRESPONDENCE',
                            'evidence_relation': 'SUPPORTS_PARTIAL' if supported else 'NO_MATCH',
                            'rationale': ('固定回答与来源片段形成受限支持。' if supported
                                else '已逐项检查该固定候选，模拟结果为没有内容对应。')})
            else:
                response = answer_response(payload) if answer_response else {'events': [], 'selection_criteria': [], 'unresolved_items': []}
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
    assert contribution['bindings']
    assert len(contribution['evaluations']) == len(next(c['frozen_candidate_pairs'] for c in calls if 'frozen_candidate_pairs' in c))
    assert db.query(SinglePromptDiagnosisReview).count() == 0
    gate = view['objects']['draft_eligibility']
    assert gate['status'] == 'QUALIFIED' and gate['evidence_count'] >= 1
    assert all(gate['requirements'].values())
    delivery = view['objects']['deliveries'][0]
    saved = db.query(SinglePromptExecutionProposalResult).filter_by(result_version=delivery['result_version']).one()
    saved_output = json.loads(saved.output_json)
    assert saved_output['validation']['content_delivery_status'] == 'READY'
    selected = saved_output['delivery_input']['selected_evidence']
    assert selected and {item['binding_id'] for item in selected} == set(gate['binding_ids'])
    assert set(saved_output['direction']['evidence_relation_ids']) == set(gate['binding_ids'])
    execute_task(row.task_id, session_factory=sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    assert len(calls) == 4


@pytest.mark.parametrize('interrupted_stage,completed_requests', [('CITATION', 1), ('DRAFT', 2), ('TEXT_QA', 3)])
def test_stage_restart_preserves_exact_objects_budget_and_cached_draft(scene, monkeypatch, interrupted_stage, completed_requests):
    from sqlalchemy.orm import sessionmaker
    from app.models import Project, SinglePromptExecutionProposalResult
    from app.modules.single_prompt_v2 import automatic_delivery
    db, row, _, _ = scene
    authorize_task(db, row, expected_revision=row.revision, input_hash=row.input_hash,
        max_requests=4, max_tokens=400000, max_cost_cny=4,
        conservative_cny_per_million_tokens=10, pricing_source='isolated-recovery-not-provider-pricing',
        pricing_checked_at=datetime.utcnow().date().isoformat(), authorized_by='isolated-test')
    fixed_input, authority = row.input_json, row.authorization_json
    calls = simulated_delivery_transport(monkeypatch)
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    checkpoint = automatic_delivery.checkpoint

    class WorkerExit(BaseException):
        pass

    def interrupt_after_checkpoint(*args, **kwargs):
        checkpoint(*args, **kwargs)
        if kwargs.get('stage') == interrupted_stage:
            raise WorkerExit()

    with monkeypatch.context() as crash:
        crash.setattr(automatic_delivery, 'checkpoint', interrupt_after_checkpoint)
        with pytest.raises(WorkerExit):
            execute_task(row.task_id, session_factory=factory)
    db.refresh(row)
    before = task_view(row)
    assert row.status == 'RUNNING' and before['stage'] == interrupted_stage
    assert len(calls) == completed_requests == before['usage']['external_requests']
    assert before['usage']['unsettled_requests'] == 0
    db.get(Project, 1).brand_name = '中断后修改，不属于原任务'
    db.commit()
    # A fresh DB session stands in for the restarted worker, not a patched status.
    with factory() as restarted:
        assert recover_interrupted_tasks(restarted) == 1
        restored = automatic_delivery.require_task(restarted, row.task_id, 1, 44)
        assert restored.status == 'INTERRUPTED'
        assert task_view(restored)['usage'] == before['usage']
        resume_task(restarted, restored, restored.revision)
    execute_task(row.task_id, session_factory=factory)
    db.refresh(row)
    after = task_view(row)
    assert row.status.startswith('COMPLETED'), (row.blocker_code, row.blocker_detail)
    assert row.input_json == fixed_input and row.authorization_json == authority
    for key in ['completion_manifest_id', 'completion_manifest_hash', 'diagnosis_id',
                'answer_result_version', 'answer_result_hash', 'citation_results',
                'strategy_id', 'strategy_result_version', 'strategy_result_hash']:
        if key in before['objects']:
            assert after['objects'][key] == before['objects'][key]
    assert len(calls) == 4 == after['usage']['external_requests']
    assert after['usage']['actual_tokens'] == 600 and after['usage']['unsettled_requests'] == 0
    assert '中断后修改' not in json.dumps(calls, ensure_ascii=False)
    if interrupted_stage == 'TEXT_QA':
        assert after['usage']['cache_hits'] >= 1
    versions = [(r.result_version, r.output_hash) for r in db.query(SinglePromptExecutionProposalResult).all()]
    execute_task(row.task_id, session_factory=factory)
    assert versions == [(r.result_version, r.output_hash) for r in db.query(SinglePromptExecutionProposalResult).all()]
    assert len(calls) == 4 and db.query(SinglePromptDiagnosisReview).count() == 0


def test_unavailable_source_delivers_l3_action_only_and_preserves_inputs(scene, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app.models import SinglePromptSourceDisposition, SinglePromptSourceCompletionManifest, SinglePromptExecutionProposalResult, SinglePromptCitationManifest
    db, row, _, _ = scene
    context = db.query(SinglePromptAnalysisContext).one()
    citation = db.query(SinglePromptCitationManifest).one()
    original_raw = context.raw_output_json
    original_citation = citation.payload_json
    source = db.query(SinglePromptSourceDisposition).filter_by(state='READY').one()
    original_states = {s.id: s.state for s in db.query(SinglePromptSourceDisposition).all()}
    source.state = 'MANUAL_REQUIRED'
    source.active_snapshot_id = None
    db.commit()
    authorize_task(db, row, expected_revision=row.revision, input_hash=row.input_hash,
        max_requests=3, max_tokens=400000, max_cost_cny=4,
        conservative_cny_per_million_tokens=10, pricing_source='isolated-missing-source-not-provider-pricing',
        pricing_checked_at=datetime.utcnow().date().isoformat(), authorized_by='isolated-test')
    calls = simulated_delivery_transport(monkeypatch)
    execute_task(row.task_id, session_factory=sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    db.refresh(row); db.refresh(source)
    view = task_view(row)
    assert row.status == 'COMPLETED_WITH_LIMITATIONS', (row.blocker_code, row.blocker_detail)
    assert source.state == 'MANUAL_REQUIRED' and source.active_snapshot_id is None
    assert {s.id: s.state for s in db.query(SinglePromptSourceDisposition).all()} == {**original_states, source.id: 'MANUAL_REQUIRED'}
    assert len(calls) == 3 and not any('frozen_candidate_pairs' in p for p in calls)
    draft_request = next(p for p in calls if 'public_evidence' in p)
    assert draft_request['public_evidence'] == []
    assert draft_request['delivery_qualification_plan']['planned_delivery_level'] == 'L3_ACTIONABLE_WITHOUT_FACT_CLAIMS'
    assert view['usage']['external_requests'] == 3
    assert view['objects']['citation_results'] == []
    assert any(limit['code'] == 'CITATION_NOT_EVALUATED' for limit in view['limitations'])
    completion = db.query(SinglePromptSourceCompletionManifest).filter_by(manifest_id=view['objects']['completion_manifest_id']).one()
    assert completion.status != 'FROZEN'
    gate = view['objects']['draft_eligibility']
    assert gate['status'] == 'QUALIFIED_CONSTRAINED' and gate['evidence_count'] == 0
    assert gate['requirements']['action_only_mode'] is True
    assert gate['gaps'] == []
    assert view['objects']['deliveries']
    plan = view['objects']['delivery_qualification_plans'][0]
    result = view['objects']['delivery_qualification_results'][0]
    assert result['plan_hash'] == plan['plan_hash']
    assert result['admitted_delivery_level'] == 'L3_ACTIONABLE_WITHOUT_FACT_CLAIMS'
    assert result['product_outcome'] == 'CONTENT_DELIVERED'
    assert view['objects']['delivery_outcome']['all_directions_l1'] is False
    db.refresh(context); db.refresh(citation)
    assert context.raw_output_json == original_raw and citation.payload_json == original_citation
    assert db.query(SinglePromptDiagnosisReview).count() == 0


def test_rejected_qualification_is_audited_but_never_current_delivery(scene, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app.models import SinglePromptExecutionProposalResult
    db, row, _, _ = scene
    authorize_task(db, row, expected_revision=row.revision, input_hash=row.input_hash,
        max_requests=4, max_tokens=400000, max_cost_cny=4,
        conservative_cny_per_million_tokens=10, pricing_source='isolated-rejected-delivery',
        pricing_checked_at=datetime.utcnow().date().isoformat(), authorized_by='isolated-test')

    def reject_every_segment(payload):
        return {'checks': [{'segment_id': segment['segment_id'], 'verdict': 'UNSUPPORTED',
            'rationale': '测试中拒绝全部正文。'} for segment in payload['segments']]}

    calls = simulated_delivery_transport(monkeypatch, qa_response=reject_every_segment)
    execute_task(row.task_id, session_factory=sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    db.refresh(row)
    view = task_view(row)
    assert len(calls) == 4
    assert row.status == 'BLOCKED'
    assert row.blocker_code == 'DELIVERY_QUALIFICATION_REJECTED'
    assert not view['objects'].get('deliveries')
    assert view['objects']['delivery_outcome']['product_outcome'] == 'NONE'
    result = view['objects']['delivery_qualification_results'][0]
    assert result['admitted_delivery_level'] == 'REJECTED'
    assert result['product_outcome'] == 'NONE'
    saved_outputs = [json.loads(item.output_json) for item in db.query(SinglePromptExecutionProposalResult).all()]
    assert any(item.get('delivery_qualification_result', {}).get('result_id') == result['result_id']
        for item in saved_outputs)


def test_multi_run_task_preserves_each_contribution_version_and_never_reads_latest(scene, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from app.models import BrowserMonitorRun, ReferenceSource, SinglePromptCitationContributionResult, SinglePromptCitationContributionExecution
    from app.modules.single_prompt_v2.service import list_prompt_run_pool, create_analysis_from_runs
    from app.modules.single_prompt_v2.qualification import _load_current_contribution_scope
    db, _, _, _ = scene
    first = db.query(BrowserMonitorRun).one()
    second = BrowserMonitorRun(**{c.name: getattr(first, c.name) for c in first.__table__.columns
        if c.name not in {'id', 'created_at', 'updated_at'}})
    second.logical_run_id = f"{first.logical_run_id}-second"
    second.attempt_id = f"{first.attempt_id}-second"
    db.add(second)
    db.flush()
    for reference in db.query(ReferenceSource).filter_by(run_id=first.id).all():
        db.add(ReferenceSource(**{c.name: getattr(reference, c.name) for c in reference.__table__.columns
            if c.name not in {'id', 'run_id'}}, run_id=second.id))
    db.commit()
    pool = list_prompt_run_pool(db, project_id=1, prompt_id=44, page=1, page_size=20)
    selected = [first.id, second.id]
    source_analysis = db.query(SinglePromptAnalysis).filter_by(task_id=first.task_id).one()
    prompt_version = json.loads(source_analysis.sampling_plan_json)["prompt_version"]
    analysis, _ = create_analysis_from_runs(db, project_id=1, prompt_id=44, run_ids=selected,
        prompt_version_id=prompt_version["prompt_version_id"],
        snapshot_hash=prompt_version["snapshot_hash"],
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
    from sqlalchemy import event
    from scripts.release_upgrade_check import business_fingerprint
    db, row, args, _ = scene
    app = create_release_app(validate_on_startup=False)
    app.dependency_overrides[get_release_db] = lambda: db
    client = TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 55000))
    root = '/api/v2/single-prompt'
    path = f"{root}/analyses/{args['analysis_id']}/optimization-tasks"
    value = {k: v for k, v in args.items() if k != 'analysis_id'}
    assert client.post(path, json=value).status_code == 200
    before = business_fingerprint(db.get_bind().url.database)
    statements = []

    def record_statement(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().split(None, 1)[0].upper())

    event.listen(db.get_bind(), 'before_cursor_execute', record_statement)
    for _ in range(2):
        listing = client.get(path + '?project_id=1&prompt_id=44')
        assert listing.status_code == 200 and listing.json()[0]['task_id'] == row.task_id
        detail = client.get(f'{root}/optimization-tasks/{row.task_id}?project_id=1&prompt_id=44')
        assert detail.status_code == 200 and detail.json()['task_id'] == row.task_id
        response = client.get(f'{root}/optimization-tasks/{row.task_id}/deliveries?project_id=1&prompt_id=44')
        assert response.status_code == 200 and response.json() == []
    event.remove(db.get_bind(), 'before_cursor_execute', record_statement)
    assert statements and set(statements) == {'SELECT'}
    assert business_fingerprint(db.get_bind().url.database) == before
    assert not db.new and not db.dirty and not db.deleted
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
