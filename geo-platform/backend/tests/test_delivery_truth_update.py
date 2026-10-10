from datetime import datetime
import json

from sqlalchemy.orm import sessionmaker

from test_automatic_delivery import scene, simulated_delivery_transport
from app.models import SinglePromptExecutionProposalResult, SinglePromptDiagnosisReview, TargetBrandCapabilityTruth
from app.modules.single_prompt_v2.automatic_delivery import authorize_task, create_task, execute_task, task_view


def test_truth_update_keeps_old_delivery_and_reuses_answer_citation(scene, monkeypatch):
    db, first, args, _ = scene
    calls = simulated_delivery_transport(monkeypatch)
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    def run(task, max_requests):
        authorize_task(db, task, expected_revision=task.revision, input_hash=task.input_hash,
            max_requests=max_requests, max_tokens=400000, max_cost_cny=4,
            conservative_cny_per_million_tokens=10, pricing_source='isolated-test-not-provider-price',
            pricing_checked_at=datetime.utcnow().date().isoformat(), authorized_by='isolated-test')
        execute_task(task.task_id, session_factory=factory)
        db.refresh(task)
        assert task.status.startswith('COMPLETED'), (task.blocker_code, task.blocker_detail)
        return task_view(task)
    original = run(first, 4)
    original_input = first.input_json
    old_versions = {r.result_version: (r.output_hash, r.output_json)
        for r in db.query(SinglePromptExecutionProposalResult).all()}
    # Synthetic, explicit human fact in the isolated fixture; never a real confirmation.
    db.add(TargetBrandCapabilityTruth(project_id=1, capability_key='batch_links',
        capability_label='支持批量生成短链', product_truth_status='SUPPORTED',
        truth_source='MANUAL_CONFIRMED', source_reference='https://target.example.com/docs/batch-links',
        reviewed_by='isolated-human-fixture', reviewed_at=datetime.utcnow()))
    db.commit()
    second, _ = create_task(db, **{**args, 'idempotency_key': 'explicit-truth-change'})
    assert second.input_hash != first.input_hash
    updated = run(second, 2)
    assert len(calls) == 6
    assert updated['usage']['external_requests'] == 2
    assert updated['usage']['cache_hits'] >= 2
    assert all('public_evidence' in c or 'segments' in c for c in calls[4:])
    writer = next(c for c in calls[4:] if 'public_evidence' in c)
    assert json.loads(second.input_json)['truth_snapshot'][0]['capability_label'] == '支持批量生成短链'
    # This fixture has legal zero Answer events: no direction depends on this fact.
    # A new project fact must not bypass the direction's public-use qualification.
    assert not any(e['kind'] == 'TARGET_VERIFIED' for e in writer['public_evidence'])
    db.refresh(first)
    assert first.input_json == original_input and task_view(first) == original
    assert json.loads(original_input)['truth_snapshot'] == []
    for version, original_row in old_versions.items():
        current = db.query(SinglePromptExecutionProposalResult).filter_by(result_version=version).one()
        assert (current.output_hash, current.output_json) == original_row
    assert db.query(SinglePromptDiagnosisReview).count() == 0
