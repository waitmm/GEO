from datetime import datetime
import json

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models import (Project, TargetBrandCapabilityTruth, SinglePromptTruthCorrection,
    SinglePromptExecutionProposalResult, SinglePromptDiagnosisReview, SinglePromptStrategyResult,
    BrowserMonitorRun, SinglePromptAnalysisContext)
from app.modules.single_prompt_v2.automatic_delivery import create_task, execute_task, authorize_task, task_view
from app.modules.single_prompt_v2.truth_corrections import (project_truths, task_truths, preview_correction,
    correct_truth, correction_view, create_reprojection_task, affected_directions, validate_reprojection)
from app.modules.single_prompt_v2.delivery_text import digest
from test_automatic_delivery import scene, simulated_delivery_transport


def grounded_brand_answer(_):
    return {'events': [{'entity_text': '甲工具', 'entity_type': 'PRODUCT', 'speech_act': 'RECOMMEND',
        'recommendation_strength': 'STRONG', 'polarity': 'POSITIVE',
        'answer_span': '甲工具值得推荐，因为支持批量生成短链。',
        'reasons': [{'normalized_reason': '支持批量生成短链', 'reason_scope': 'ENTITY_SPECIFIC', 'reason_span': '支持批量生成短链'}]}],
        'selection_criteria': [], 'unresolved_items': []}


@pytest.fixture
def fact_delivery(scene, monkeypatch):
    db, _, args, _ = scene
    db.get(Project, 1).brand_name = '甲工具'
    truth = TargetBrandCapabilityTruth(project_id=1, capability_key='支持批量生成短链', capability_label='支持批量生成短链',
        product_truth_status='SUPPORTED', truth_source='MANUAL_CONFIRMED', source_reference='https://example.com/product',
        reviewed_by='isolated-human-fixture', reviewed_at=datetime.utcnow())
    db.add(truth); db.commit()
    row, _ = create_task(db, **{**args, 'idempotency_key': 'truth-correction-parent'})
    calls = simulated_delivery_transport(monkeypatch, answer_response=grounded_brand_answer)
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    def run(task, maximum=4):
        authorize_task(db, task, expected_revision=task.revision, input_hash=task.input_hash,
            max_requests=maximum, max_tokens=800000, max_cost_cny=8,
            conservative_cny_per_million_tokens=10, pricing_source='isolated-fixture-not-real-billing',
            pricing_checked_at=datetime.utcnow().date().isoformat(), authorized_by='isolated-human')
        execute_task(task.task_id, session_factory=factory); db.refresh(task)
        assert task.status.startswith('COMPLETED'), (task.blocker_code, task.blocker_detail)
    run(row)
    truths = project_truths(db, 1)
    values = dict(parent_task_id=row.task_id, project_id=1, prompt_id=44, truth_id=truth.id,
        base_hash=digest(truths[0]), expected_set_hash=digest(truths), capability_label=truth.capability_label,
        product_truth_status='UNKNOWN', source_reference=truth.source_reference, reason='隔离人工纠错：原资料不能确认当前能力')
    return db, row, truth, calls, values, run


def test_truth_correction_append_only_and_scoped_reprojection_reuses_upstream(fact_delivery):
    db, parent, truth, calls, values, run = fact_delivery
    old_task = (parent.input_json, parent.progress_json)
    old_results = {r.result_version: (r.output_json, r.output_hash) for r in db.query(SinglePromptExecutionProposalResult)}
    preview = preview_correction(db, **values)
    assert preview['impact']['affected_reason_ids']
    assert preview['impact']['affected_direction_ids']
    correction, created = correct_truth(db, **values, preview_hash=preview['preview_hash'],
        actor='isolated-human', idempotency_key='truth-correction-request')
    assert created
    assert correct_truth(db, **values, preview_hash=preview['preview_hash'],
        actor='isolated-human', idempotency_key='truth-correction-request')[1] is False
    assert correction_view(correction)['output']['statement_eligibility']['status'] == 'VERIFY_FIRST'
    assert project_truths(db, 1)[0]['product_truth_status'] == 'UNKNOWN'
    db.refresh(truth)
    assert truth.product_truth_status == 'SUPPORTED'
    assert task_truths(db, parent_task_id=parent.task_id, project_id=1, prompt_id=44)['truths'][0]['can_correct'] is False
    with pytest.raises(HTTPException, match='版本已变化'):
        preview_correction(db, **values)
    # Configuration changes cannot leak into a task whose only intent is this correction.
    db.get(Project, 1).brand_name = '之后修改的项目名称'; db.commit()
    task, created = create_reprojection_task(db, parent_task_id=parent.task_id, project_id=1, prompt_id=44,
        correction_id=correction.correction_id, idempotency_key='local-truth-reprojection')
    assert created and task_view(task)['authorization']['policy'] == 'CACHE_ONLY'
    assert task_view(task)['task_kind'] == 'TRUTH_REPROJECTION'
    validate_reprojection(db, task)
    frozen = json.loads(task.input_json)
    assert frozen['brand'] == json.loads(parent.input_json)['brand']
    assert frozen['source_fetch_authorized'] is False and frozen['source_input']
    before_count = len(calls)
    run(task, 2)
    assert len(calls) == before_count + 2
    assert all('public_evidence' in c or 'segments' in c for c in calls[before_count:])
    assert task_view(task)['usage']['cache_hits'] >= 2
    assert not any(e['kind'] == 'TARGET_VERIFIED' for c in calls[before_count:] for e in c.get('public_evidence', []))
    db.refresh(parent)
    assert (parent.input_json, parent.progress_json) == old_task
    for version, prior in old_results.items():
        row = db.query(SinglePromptExecutionProposalResult).filter_by(result_version=version).one()
        assert (row.output_json, row.output_hash) == prior
    assert db.query(SinglePromptDiagnosisReview).count() == 0
    correction.reason = 'attempt overwrite'
    with pytest.raises(IntegrityError, match='IMMUTABLE'):
        db.commit()
    db.rollback()
    db.delete(correction)
    with pytest.raises(IntegrityError, match='IMMUTABLE'):
        db.commit()
    db.rollback()


def test_truth_correction_refuses_wrong_identity_stale_preview_and_unsupported_assertion(fact_delivery):
    db, _, _, _, values, _ = fact_delivery
    for change in ({'project_id': 999}, {'base_hash': '0'*64}, {'expected_set_hash': '0'*64},
            {'capability_label': '支持甲，同时支持乙'}, {'capability_label': '!!!'},
            {'product_truth_status': 'SUPPORTED', 'source_reference': ''}):
        with pytest.raises(HTTPException):
            preview_correction(db, **{**values, **change})
    with pytest.raises(HTTPException, match='预览已变化'):
        correct_truth(db, **values, actor='isolated-human', idempotency_key='mismatch-preview', preview_hash='0'*64)
    assert db.query(SinglePromptTruthCorrection).count() == 0


def test_direction_filter_never_rewrites_unaffected_actions():
    ref = {'impact': {'affected_reason_ids': ['r1'], 'affected_direction_ids': ['old'], 'unaffected_direction_ids': ['keep']}}
    rows = [{'strategy_id': 'new', 'reason_ids': ['r1']}, {'strategy_id': 'keep', 'reason_ids': ['r2']},
        {'strategy_id': 'discovery', 'reason_ids': [], 'direction_type': 'DISCOVERY'}]
    assert affected_directions(rows, ref) == rows[:1]
    ref['impact']['unaffected_direction_ids'] = []
    assert affected_directions(rows, ref) == rows


@pytest.mark.parametrize('correct_selected', [True, False])
def test_correction_replaces_selected_direction_with_existing_qualified_candidate(scene, monkeypatch, correct_selected):
    from app.modules.single_prompt_v2.service import create_analysis, claim_analysis, finalize_analysis
    db, _, _, _ = scene
    db.get(Project, 1).brand_name = '甲工具'
    labels = ['支持批量生成短链', '支持自定义域名']
    for label in labels:
        db.add(TargetBrandCapabilityTruth(project_id=1, capability_key=label, capability_label=label,
            product_truth_status='SUPPORTED', truth_source='MANUAL_CONFIRMED', source_reference='https://example.com/product',
            reviewed_by='isolated-human', reviewed_at=datetime.utcnow()))
    db.commit()
    analysis, _ = create_analysis(db, project_id=1, prompt_id=44, sample_count=1, idempotency_key='two-reasons-one-direction')
    token = claim_analysis(db, analysis.analysis_id)
    sample = db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).one()
    sample.status = sample.stage = 'success'
    sample.answer_text = '甲工具值得推荐，因为支持批量生成短链和支持自定义域名。'
    sample.answer_char_count = len(sample.answer_text)
    sample.reference_complete = True
    db.commit()
    assert finalize_analysis(db, analysis.analysis_id, token)
    context = db.query(SinglePromptAnalysisContext).filter_by(analysis_id=analysis.analysis_id).one()
    parent, _ = create_task(db, analysis_id=analysis.analysis_id, project_id=1, prompt_id=44,
        raw_output_hash=context.raw_output_hash, idempotency_key='two-reasons-parent')
    def answer(_):
        return {'events': [{'entity_text': '甲工具', 'entity_type': 'PRODUCT', 'speech_act': 'RECOMMEND',
            'recommendation_strength': 'STRONG', 'polarity': 'POSITIVE', 'answer_span': sample.answer_text,
            'reasons': [{'normalized_reason': label, 'reason_scope': 'ENTITY_SPECIFIC', 'reason_span': label} for label in labels]}],
            'selection_criteria': [], 'unresolved_items': []}
    calls = simulated_delivery_transport(monkeypatch, answer_response=answer)
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    def authorized_run(task, maximum):
        authorize_task(db, task, expected_revision=task.revision, input_hash=task.input_hash,
            max_requests=maximum, max_tokens=800000, max_cost_cny=8, conservative_cny_per_million_tokens=10,
            pricing_source='isolated-not-real-billing', pricing_checked_at=datetime.utcnow().date().isoformat(), authorized_by='isolated-human')
        execute_task(task.task_id, session_factory=factory)
        db.refresh(task)
        assert task.status.startswith('COMPLETED'), task.blocker_detail
    def selected_direction(task):
        objects = task_view(task)['objects']
        result = db.query(SinglePromptStrategyResult).filter_by(strategy_id=objects['strategy_id'],
            result_version=objects['strategy_result_version']).one()
        directions = json.loads(result.output_json)['directions']
        assert len(directions) == 1 and directions[0]['direction_type'] == 'MECHANISM'
        return directions[0]
    authorized_run(parent, 4)
    direction = selected_direction(parent)
    assert len(task_view(parent)['objects']['deliveries']) == 1
    original = (parent.input_json, parent.progress_json)
    truths = project_truths(db, 1)
    truth = next(t for t in truths if (t['truth_id'] in direction['truth_ids']) == correct_selected)
    values = dict(parent_task_id=parent.task_id, project_id=1, prompt_id=44, truth_id=truth['truth_id'],
        base_hash=digest(truth), expected_set_hash=digest(truths), capability_label=truth['capability_label'],
        product_truth_status='UNKNOWN', source_reference=truth['source_reference'], reason='隔离测试：原选中事实依据不足')
    preview = preview_correction(db, **values)
    assert preview['impact']['affected_direction_ids'] == ([direction['strategy_id']] if correct_selected else [])
    assert preview['impact']['unaffected_direction_ids'] == ([] if correct_selected else [direction['strategy_id']])
    correction, _ = correct_truth(db, **values, preview_hash=preview['preview_hash'], actor='isolated-human', idempotency_key='candidate-correction')
    task, _ = create_reprojection_task(db, parent_task_id=parent.task_id, project_id=1, prompt_id=44,
        correction_id=correction.correction_id, idempotency_key='candidate-reprojection')
    before = len(calls)
    if not correct_selected:
        execute_task(task.task_id, session_factory=factory)
        db.refresh(task)
        assert task.status == 'COMPLETED_WITH_LIMITATIONS'
        assert not task_view(task)['objects'].get('deliveries')
        assert task_view(task)['objects']['truth_reprojection']['new_affected_direction_ids'] == []
        assert len(calls) == before
        db.refresh(parent)
        assert (parent.input_json, parent.progress_json) == original
        return
    authorized_run(task, 2)
    chosen = selected_direction(task)
    assert truth['truth_id'] not in chosen['truth_ids']
    assert chosen['strategy_id'] != direction['strategy_id']
    objects = task_view(task)['objects']
    assert objects['truth_reprojection']['new_affected_direction_ids'] == [chosen['strategy_id']]
    assert len(objects['deliveries']) == 1
    assert len(calls) == before + 2
    assert all('public_evidence' in c or 'segments' in c for c in calls[before:])
    db.refresh(parent)
    assert (parent.input_json, parent.progress_json) == original


def test_api_requires_human_confirmation_and_retains_independent_actor_history(fact_delivery):
    from fastapi import FastAPI, Depends
    from release_test_client import TestClient
    from app.modules.single_prompt_v2.release_api import router, get_db
    from app.core.release_access import install_access, require_project_access
    db, parent, _, _, values, _ = fact_delivery
    app = FastAPI()
    install_access(app, ['http://127.0.0.1:5173'])
    app.include_router(router, dependencies=[Depends(require_project_access)])
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 8000))
    base = f'/api/v2/single-prompt/optimization-tasks/{parent.task_id}'
    body = {k: v for k, v in values.items() if k != 'parent_task_id'}
    preview = client.post(base + '/truth-corrections/preview', json=body)
    assert preview.status_code == 200, preview.text
    body.update(preview_hash=preview.json()['preview_hash'], idempotency_key='scoped-api-correction')
    for extra in ({}, {'human_confirmed': False}, {'human_confirmed': True, 'actor': 'forged'}):
        assert client.post(base + '/truth-corrections', json={**body, **extra}).status_code == 422
    result = client.post(base + '/truth-corrections', json={**body, 'human_confirmed': True})
    assert result.status_code == 201, result.text
    assert result.json()['actor'] != 'forged'
    assert client.get(base + '/truths?project_id=999&prompt_id=44').status_code == 404
    history = client.get(base + '/truths?project_id=1&prompt_id=44').json()['history']
    assert history[0]['correction_id'] == result.json()['correction_id']
    args = {'project_id': 1, 'prompt_id': 44, 'correction_id': result.json()['correction_id'], 'idempotency_key': 'api-reproject-correction'}
    queued = client.post(base + '/truth-reprojections', json=args)
    assert queued.status_code == 201, queued.text
    assert queued.json()['authorization']['policy'] == 'CACHE_ONLY'
    assert client.post(base + '/truth-reprojections', json=args).status_code == 200


def test_upstream_request_guard_cannot_spend_correction_authority(fact_delivery):
    from test_automatic_delivery import identity
    from app.modules.single_prompt_v2.automatic_delivery import scoped_client, encode
    from app.services.semantic_llm.base import SemanticLLMError
    db, parent, _, calls, values, _ = fact_delivery
    preview = preview_correction(db, **values)
    correction, _ = correct_truth(db, **values, actor='isolated-human', preview_hash=preview['preview_hash'], idempotency_key='guard-correction')
    row, _ = create_reprojection_task(db, parent_task_id=parent.task_id, project_id=1, prompt_id=44,
        correction_id=correction.correction_id, idempotency_key='guard-reprojection')
    authorize_task(db, row, expected_revision=row.revision, input_hash=row.input_hash,
        max_requests=2, max_tokens=800000, max_cost_cny=8, conservative_cny_per_million_tokens=10,
        pricing_source='isolated-no-real-billing', pricing_checked_at=datetime.utcnow().date().isoformat(), authorized_by='isolated-human')
    row.status = 'RUNNING'
    before = len(calls)
    for stage in ('ANSWER', 'CITATION', 'TRUTH'):
        row.progress_json = encode({'stage': stage, 'requests': []}); db.commit()
        client = scoped_client(db, row)
        assert client.cache_only is True
        with pytest.raises(SemanticLLMError, match='FORBIDS_UPSTREAM'):
            client.request_guard({**identity(row), 'prompt_version': 'answer_semantic'})
    assert len(calls) == before and task_view(row)['usage']['external_requests'] == 0
