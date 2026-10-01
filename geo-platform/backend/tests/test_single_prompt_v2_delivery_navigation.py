from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (
    Base, SinglePromptAnalysis, SinglePromptExecutionProposal,
    SinglePromptExecutionProposalResult, SinglePromptStrategyExecution,
)
from app.modules.single_prompt_v2 import service


def test_saved_deliveries_are_scoped_read_only_and_never_selected_by_latest(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'navigation.db'}")
    Base.metadata.create_all(engine)
    # This query-only fixture exercises navigation, not strategy eligibility or generation.
    identity = dict(analysis_id="analysis-1", context_id="context-1", project_id=1,
                    prompt_id=1, diagnosis_id="diagnosis-1")
    common = dict(**identity, input_fingerprint="f" * 64, input_snapshot_json="{}",
                  input_snapshot_hash="i" * 64, validation_contract_version="fixture")
    with Session(engine) as db:
        db.add(SinglePromptAnalysis(
            analysis_id="analysis-1", project_id=1, prompt_id=1, idempotency_key="analysis",
            prompt_text_snapshot="prompt", sampling_plan_json="{}", sampling_plan_hash="p" * 64,
        ))
        db.add(SinglePromptStrategyExecution(
            **common, strategy_id="strategy-1", idempotency_key="strategy",
            diagnosis_result_version="answer-v1", diagnosis_result_hash="d" * 64,
            diagnosis_review_id="review-1", review_snapshot_hash="r" * 64,
        ))
        for index in (1, 2):
            db.add(SinglePromptExecutionProposal(
                **common, proposal_id=f"proposal-{index}", strategy_id="strategy-1",
                direction_id=f"direction-{index}", idempotency_key=f"proposal-{index}",
                strategy_result_version="strategy-v1", strategy_result_hash="s" * 64,
                active_result_version=f"execution-{index}-v1",
            ))
            for version in (1, 99):
                db.add(SinglePromptExecutionProposalResult(
                    proposal_id=f"proposal-{index}", result_version=f"execution-{index}-v{version}",
                    version_number=version, output_json="{}", output_hash="o" * 64,
                    reviewable_set_hash="r" * 64,
                ))
        db.commit()
        monkeypatch.setattr(service, "get_analysis_status", lambda db, analysis_id: {
            "analysis": {"analysis_id": analysis_id}, "sampling": {}, "result_version": "raw-v1",
            "context_id": "context-1", "created_at": None, "finished_at": None,
        })
        before = db.connection().connection.driver_connection.total_changes
        deliveries = service.list_analysis_statuses(db, project_id=1, prompt_id=1)[0]["saved_deliveries"]
        assert [row["proposal_id"] for row in deliveries] == ["proposal-1", "proposal-2"]
        assert [row["result_version"] for row in deliveries] == ["execution-1-v1", "execution-2-v1"]
        assert all(row["diagnosis_result_version"] == "answer-v1" for row in deliveries)
        assert all(row["strategy_result_version"] == "strategy-v1" for row in deliveries)
        assert service.list_analysis_statuses(db, project_id=2, prompt_id=1) == []
        assert service.list_analysis_statuses(db, project_id=1, prompt_id=2) == []
        assert db.connection().connection.driver_connection.total_changes == before
    engine.dispose()
