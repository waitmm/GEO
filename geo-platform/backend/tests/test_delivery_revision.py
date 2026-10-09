import copy
import json
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app.models import SinglePromptExecutionProposalResult
from app.modules.single_prompt_v2.automatic_delivery import authorize_task, execute_task, task_view
from app.modules.single_prompt_v2.delivery_revision import create_revision_task
from app.modules.single_prompt_v2.execution import generate_complete_execution_deliverable
from test_automatic_delivery import scene, simulated_delivery_transport


@pytest.fixture
def delivered(scene, monkeypatch):
    db, parent, _, _ = scene
    def qa(payload):
        return {'checks': [{'segment_id': s['segment_id'],
            'verdict': 'UNSUPPORTED' if '99元' in s['text'] else 'PASS',
            'rationale': '该价格没有依据。' if '99元' in s['text'] else '仅是核对建议。'} for s in payload['segments']]}
    calls = simulated_delivery_transport(monkeypatch, qa_response=qa)
    authorize_task(db, parent, expected_revision=parent.revision, input_hash=parent.input_hash,
        max_requests=4, max_tokens=400000, max_cost_cny=4,
        conservative_cny_per_million_tokens=10, pricing_source='isolated-not-provider-billing',
        pricing_checked_at=datetime.utcnow().date().isoformat(), authorized_by='offline-test')
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    execute_task(parent.task_id, session_factory=factory)
    db.refresh(parent)
    assert parent.status.startswith('COMPLETED'), parent.blocker_detail
    binding = task_view(parent)['objects']['deliveries'][0]
    base = db.query(SinglePromptExecutionProposalResult).filter_by(result_version=binding['result_version']).one()
    output = json.loads(base.output_json)
    draft = copy.deepcopy(output['generation_receipt']['original_draft'])
    draft['sections'][0]['blocks'].append({'kind': 'INSTRUCTION', 'text': '目标产品价格为99元。', 'evidence_ids': []})
    args = dict(parent_task_id=parent.task_id, project_id=1, prompt_id=44,
        proposal_id=binding['proposal_id'], result_version=base.result_version, result_hash=base.output_hash,
        draft=draft, idempotency_key='text-revision-isolated', editor='offline-editor')
    yield db, parent, base, calls, factory, args


def test_revision_is_pending_without_authority_then_one_qa_repairs_actual_text(delivered):
    db, parent, base, calls, factory, args = delivered
    before = base.output_json
    parent_before = parent.progress_json
    row, created = create_revision_task(db, **args)
    assert created and task_view(row)['task_kind'] == 'TEXT_REVISION'
    assert task_view(row)['pending_draft'] == args['draft']
    execute_task(row.task_id, session_factory=factory)
    db.refresh(row)
    assert row.status == 'WAITING_AUTHORIZATION', row.blocker_detail
    assert len(calls) == 4 and task_view(row)['objects'].get('deliveries') is None
    values = dict(expected_revision=row.revision, input_hash=row.input_hash,
        max_requests=1, max_tokens=100000, max_cost_cny=1,
        conservative_cny_per_million_tokens=10, pricing_source='isolated-not-provider-billing',
        pricing_checked_at=datetime.utcnow().date().isoformat(), authorized_by='offline-test')
    with pytest.raises(HTTPException, match='一次'):
        authorize_task(db, row, **{**values, 'max_requests': 2})
    authorize_task(db, row, **values)
    execute_task(row.task_id, session_factory=factory)
    db.refresh(row)
    assert row.status.startswith('COMPLETED'), row.blocker_detail
    assert len(calls) == 5 and 'segments' in calls[-1]
    assert task_view(row)['usage']['external_requests'] == 1
    result_binding = task_view(row)['objects']['deliveries'][0]
    new = db.query(SinglePromptExecutionProposalResult).filter_by(result_version=result_binding['result_version']).one()
    output = json.loads(new.output_json)
    assert new.parent_result_version == base.result_version and new.version_number == base.version_number + 1
    assert output['text_revision']['submitted_draft_hash']
    assert '99元' not in output['publication_draft']['body_markdown']
    assert output['automatic_qa']['findings'][0]['original_text'] == '目标产品价格为99元。'
    assert output['automatic_qa']['repairs'][0]['after'] == ''
    assert output['automatic_qa']['repairs'][0]['recheck'] == 'PASS'
    db.refresh(base); db.refresh(parent)
    assert base.output_json == before and parent.progress_json == parent_before
    repeated, created = create_revision_task(db, **args)
    assert not created and repeated.task_id == row.task_id
    execute_task(row.task_id, session_factory=factory)
    assert len(calls) == 5
    fixed = json.loads(row.input_json)['delivery_revision']
    class NoNetwork:
        def structured_generate_sync(self, **kwargs):
            raise AssertionError('Committed revision must be recovered without another request')
    recovered, created = generate_complete_execution_deliverable(db, proposal_id=base.proposal_id,
        base_result_version=base.result_version, base_result_hash=base.output_hash,
        reviewable_set_hash=base.reviewable_set_hash, generation_client=NoNetwork(), submitted_draft=fixed['draft'],
        revision_identity={'task_id': row.task_id, 'input_hash': row.input_hash, 'editor': fixed['editor']})
    assert not created and recovered.result_version == new.result_version


def test_revision_rejects_wrong_scope_hash_and_unbound_new_target_facts(delivered):
    from app.modules.single_prompt_v2.delivery_generation import editable_draft
    db, parent, base, calls, _, args = delivered
    unchanged, created = create_revision_task(db, **{**args,
        'draft': editable_draft(json.loads(base.output_json)['generation_receipt'])})
    assert not created and unchanged.task_id == parent.task_id
    for change in [{'project_id': 999}, {'result_hash': '0' * 64}, {'result_version': 'execution-v999:wrong'}]:
        with pytest.raises(HTTPException):
            create_revision_task(db, **{**args, **change})
    unbound = copy.deepcopy(args['draft'])
    unbound['sections'][0]['blocks'][-1].update(kind='TARGET_STATEMENT', evidence_ids=['invented'])
    with pytest.raises(HTTPException, match='不合法'):
        create_revision_task(db, **{**args, 'draft': unbound})
    assert len(calls) == 4
    row, _ = create_revision_task(db, **args)
    changed = copy.deepcopy(args['draft'])
    changed['sections'][0]['heading'] = '不同输入'
    with pytest.raises(HTTPException, match='幂等键'):
        create_revision_task(db, **{**args, 'draft': changed})
    assert task_view(row)['usage']['external_requests'] == 0


def test_new_revision_uses_only_current_text_contracts_not_parent_analysis_contracts(delivered, monkeypatch):
    from app.modules.single_prompt_v2 import automatic_delivery
    from app.modules.single_prompt_v2.delivery_revision import revision_computation_contracts
    db, parent, base, calls, factory, args = delivered
    historical_input = parent.input_json
    monkeypatch.setattr(automatic_delivery, 'computation_contracts', lambda: {'answer': 'isolated-new-answer-contract'})
    row, created = create_revision_task(db, **args)
    assert created
    assert json.loads(row.input_json)['computation_contracts'] == revision_computation_contracts()
    execute_task(row.task_id, session_factory=factory)
    db.refresh(row); db.refresh(parent)
    assert row.status == 'WAITING_AUTHORIZATION', row.blocker_detail
    assert parent.input_json == historical_input and len(calls) == 4
    assert json.loads(row.input_json)['delivery_revision']['base_result_hash'] == base.output_hash
