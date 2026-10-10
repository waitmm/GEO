"""BASIC context consumption through the automatic worker, with simulated transport."""
from datetime import datetime
import json

from sqlalchemy.orm import sessionmaker

from test_automatic_delivery import scene, simulated_delivery_transport
from app.models import SinglePromptExecutionProposalResult, SinglePromptDiagnosisReview
from app.modules.single_prompt_v2.automatic_delivery import (
    authorize_task, create_task, execute_task, task_view,
)
from app.modules.single_prompt_v2.context_provider import save_context


def test_context_update_preserves_frozen_delivery_and_reuses_unaffected_computation(scene, monkeypatch):
    db, _, args, _ = scene
    first_text = '短链工具的内部选题方向：优先解释团队交接时需要核对的问题。'
    second_text = '短链工具的内部选题方向：优先解释采购前需要核对的问题。'
    unrelated = '办公室搬迁安排由行政另行通知。'
    first = save_context(db, project_id=1, expected_version=0, title='内部资料',
        content=first_text + '\n\n' + unrelated, source_reference='隔离测试资料，不是产品事实')
    task1, _ = create_task(db, **{**args, 'idempotency_key': 'context-first'},
        brand_context_version_id=first.context_version_id)
    frozen = task1.input_json
    second = save_context(db, project_id=1, expected_version=1, title='更新内部资料',
        content=second_text, source_reference='隔离测试资料，不是产品事实')
    calls = simulated_delivery_transport(monkeypatch)
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)

    def run(task, maximum):
        authorize_task(db, task, expected_revision=task.revision, input_hash=task.input_hash,
            max_requests=maximum, max_tokens=400000, max_cost_cny=4,
            conservative_cny_per_million_tokens=10, pricing_source='isolated-test-not-provider-price',
            pricing_checked_at=datetime.utcnow().date().isoformat(), authorized_by='isolated-test')
        execute_task(task.task_id, session_factory=factory)
        db.refresh(task)
        assert task.status.startswith('COMPLETED'), (task.blocker_code, task.blocker_detail)
        return task_view(task)

    initial = run(task1, 4)
    assert len(calls) == 4
    writer1 = next(c for c in calls if 'public_evidence' in c)
    assert writer1['internal_context']['context_version_id'] == first.context_version_id
    assert [p['text'] for p in writer1['internal_context']['passages']] == [first_text]
    assert writer1['internal_context']['allowed_use'] == 'INTERNAL_CONTEXT_NOT_PUBLIC_FACT'
    assert second_text not in json.dumps(calls, ensure_ascii=False)
    assert unrelated not in json.dumps(calls, ensure_ascii=False)
    assert not any(first_text in e['text'] for e in writer1['public_evidence'])
    original_rows = {r.result_version: (r.output_hash, r.output_json)
        for r in db.query(SinglePromptExecutionProposalResult).all()}

    task2, _ = create_task(db, **{**args, 'idempotency_key': 'context-second'},
        brand_context_version_id=second.context_version_id)
    assert task2.input_hash != task1.input_hash
    updated = run(task2, 2)
    assert len(calls) == 6, 'Only the affected draft and actual-text QA may need new model requests'
    assert updated['usage']['external_requests'] == 2
    assert updated['usage']['cache_hits'] >= 2
    assert all('public_evidence' in c or 'segments' in c for c in calls[4:])
    writer2 = next(c for c in calls[4:] if 'public_evidence' in c)
    assert writer2['internal_context']['context_version_id'] == second.context_version_id
    assert [p['text'] for p in writer2['internal_context']['passages']] == [second_text]
    assert writer1['public_evidence'] == writer2['public_evidence']
    db.refresh(task1)
    assert task1.input_json == frozen
    assert task_view(task1) == initial
    for version, contents in original_rows.items():
        row = db.query(SinglePromptExecutionProposalResult).filter_by(result_version=version).one()
        assert (row.output_hash, row.output_json) == contents
    assert db.query(SinglePromptDiagnosisReview).count() == 0
