import json
from datetime import datetime

import pytest
from fastapi import HTTPException

from app.models import SinglePromptExecutionProposalResult
from app.modules.single_prompt_v2.automatic_delivery import authorize_task, execute_task, task_view
from app.modules.single_prompt_v2.delivery_revision import create_revision_task
from app.modules.single_prompt_v2.execution import generate_complete_execution_deliverable
from test_delivery_revision import delivered, scene


def arguments(args):
    return {**{key: value for key, value in args.items() if key != 'draft'},
        'regenerate': True, 'idempotency_key': 'explicit-regeneration-test'}


def test_regeneration_is_explicit_bounded_and_preserves_analysis_and_old_draft(delivered):
    db, parent, base, calls, factory, args = delivered
    previous = (parent.input_json, parent.progress_json, base.output_json)
    row, created = create_revision_task(db, **arguments(args))
    assert created and task_view(row)['task_kind'] == 'TEXT_REGENERATION'
    duplicate, created = create_revision_task(db, **{**arguments(args), 'idempotency_key': 'duplicate-button-submit'})
    assert not created and duplicate.task_id == row.task_id
    execute_task(row.task_id, session_factory=factory)
    db.refresh(row)
    assert row.status == 'WAITING_AUTHORIZATION', row.blocker_detail
    assert len(calls) == 4
    authority = dict(expected_revision=row.revision, input_hash=row.input_hash, max_requests=2,
        max_tokens=200000, max_cost_cny=2, conservative_cny_per_million_tokens=10,
        pricing_source='isolated-only-not-provider-billing', pricing_checked_at=datetime.utcnow().date().isoformat(),
        authorized_by='offline-test')
    with pytest.raises(HTTPException, match='两次'):
        authorize_task(db, row, **{**authority, 'max_requests': 3})
    authorize_task(db, row, **authority)
    execute_task(row.task_id, session_factory=factory)
    db.refresh(row)
    assert row.status.startswith('COMPLETED'), row.blocker_detail
    assert len(calls) == 5, 'Identical output must reuse its compatible QA; only writer is new'
    assert calls[-1]['explicit_regeneration']['task_id'] == row.task_id
    assert set(calls[-1]['explicit_regeneration']) == {'task_id', 'input_hash'}
    assert task_view(row)['usage']['external_requests'] == 1
    assert task_view(row)['usage']['cache_hits'] >= 1
    binding = task_view(row)['objects']['deliveries'][0]
    result = db.query(SinglePromptExecutionProposalResult).filter_by(result_version=binding['result_version']).one()
    output = json.loads(result.output_json)
    assert result.parent_result_version == base.result_version
    assert output['delivery_input'] == json.loads(base.output_json)['delivery_input']
    assert output['text_regeneration']['input_hash'] == row.input_hash
    assert output['system_revision']['source_refetches'] == 0
    db.refresh(parent); db.refresh(base)
    assert (parent.input_json, parent.progress_json, base.output_json) == previous
    class NoNetwork:
        def structured_generate_sync(self, **kwargs):
            raise AssertionError('Committed result must recover without paid requests')
    recovered, created = generate_complete_execution_deliverable(db, proposal_id=base.proposal_id,
        base_result_version=base.result_version, base_result_hash=base.output_hash,
        reviewable_set_hash=base.reviewable_set_hash, generation_client=NoNetwork(),
        regeneration_identity=output['text_regeneration'])
    assert not created and recovered.result_version == result.result_version
    with pytest.raises(HTTPException, match='已变化'):
        create_revision_task(db, **{**arguments(args), 'idempotency_key': 'stale-new-intent', 'editor': 'other'})


def test_regeneration_rejects_wrong_scope_and_mixed_edit_input(delivered):
    db, _, _, calls, _, args = delivered
    for invalid in [{'project_id': 999}, {'result_hash': '0' * 64}, {'draft': args['draft']}]:
        with pytest.raises(HTTPException):
            create_revision_task(db, **{**arguments(args), **invalid})
    assert len(calls) == 4
