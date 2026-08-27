#!/usr/bin/env python3
"""Prompt #40 Phase 4 execution-plan + experiment draft audit."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import SessionLocal
from app.models import OptimizationAction, OptimizationExperiment, OptimizationStrategyCandidate, PageSnapshot
from app.modules.optimization import service as optimization_service
from app.services.serialization import loads


PROJECT_ID = 3
PROMPT_ID = 40
EVIDENCE_PACKAGE_ID = 15


def _count_execution_tables(db) -> dict:
    return {
        "strategy_candidates": db.query(OptimizationStrategyCandidate).filter(
            OptimizationStrategyCandidate.project_id == PROJECT_ID,
            OptimizationStrategyCandidate.evidence_package_id == EVIDENCE_PACKAGE_ID,
        ).count(),
        "actions": db.query(OptimizationAction).count(),
        "experiments": db.query(OptimizationExperiment).count(),
    }


def _markdown_table(headers: list[str], rows: list[list[object]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return lines


def _proposal(db) -> dict:
    original_limit = optimization_service.SOURCE_METADATA_FETCH_LIMIT
    optimization_service.SOURCE_METADATA_FETCH_LIMIT = 0
    try:
        return optimization_service.citation_decision_vertical_slice(
            db,
            PROJECT_ID,
            PROMPT_ID,
            evidence_package_id=EVIDENCE_PACKAGE_ID,
            use_answer_binding_v1_1=True,
        )
    finally:
        optimization_service.SOURCE_METADATA_FETCH_LIMIT = original_limit


def _ensure_confirmed_candidate(db) -> OptimizationStrategyCandidate:
    candidate = (
        db.query(OptimizationStrategyCandidate)
        .filter(
            OptimizationStrategyCandidate.project_id == PROJECT_ID,
            OptimizationStrategyCandidate.evidence_package_id == EVIDENCE_PACKAGE_ID,
            OptimizationStrategyCandidate.experiment_id.is_(None),
            OptimizationStrategyCandidate.review_status.in_(["ACCEPTED", "ACCEPTED_WITH_EDITS"]),
        )
        .order_by(OptimizationStrategyCandidate.id.desc())
        .first()
    )
    if candidate:
        return candidate

    proposal = _proposal(db)
    actions = proposal.get("recommended_actions") or []
    if not actions:
        raise RuntimeError("Prompt #40 当前没有可生成策略候选的 Gap。")
    created_result = optimization_service.confirm_citation_decision_vertical_slice(
        db,
        PROJECT_ID,
        PROMPT_ID,
        {
            "evidence_package_id": EVIDENCE_PACKAGE_ID,
            "action_keys": [actions[0]["action_key"]],
            "reviewer": "phase4_audit",
            "use_answer_binding_v1_1": True,
            "review_note": "Phase 4 审计：生成 Step 7 StrategyCandidate 以进入 Step 8。",
        },
    )
    candidate_id = (created_result.get("created") or [])[0]["strategy_candidate"]["id"]
    optimization_service.review_strategy_candidate(
        db,
        candidate_id,
        type(
            "Payload",
            (),
            {
                "review_status": "ACCEPTED_WITH_EDITS",
                "reviewed_by": "phase4_audit",
                "review_note": "确认策略机制；渠道和资产进入 Step 8 人工确认。",
                "human_edited_payload": {
                    "human_review_summary": "确认 #40 的能力级缺口进入执行方案评审。",
                },
            },
        )(),
    )
    return db.get(OptimizationStrategyCandidate, candidate_id)


def _asset_snapshot_id(db, candidate: OptimizationStrategyCandidate) -> int:
    effective = loads(candidate.effective_payload_json, {})
    refs = effective.get("relevant_asset_refs") or []
    for ref in refs:
        if isinstance(ref, dict) and ref.get("snapshot_id"):
            return int(ref["snapshot_id"])
    row = (
        db.query(PageSnapshot)
        .filter(PageSnapshot.project_id == PROJECT_ID, PageSnapshot.capture_status == "success")
        .order_by(PageSnapshot.id.desc())
        .first()
    )
    if not row:
        raise RuntimeError("Prompt #40 当前没有可用于 Step 8 的 PageSnapshot 资产。")
    return int(row.id)


def build_report() -> str:
    db = SessionLocal()
    try:
        before = _count_execution_tables(db)
        candidate = _ensure_confirmed_candidate(db)
        effective_before = loads(candidate.effective_payload_json, {})
        baseline_run_ids = effective_before.get("observed_run_ids") or loads(db.get(
            optimization_service.OptimizationEvidencePackage,
            EVIDENCE_PACKAGE_ID,
        ).source_run_ids_json, [])
        snapshot_id = _asset_snapshot_id(db, candidate)
        result = optimization_service.confirm_strategy_execution_plan(
            db,
            candidate.id,
            {
                "channel": "OFFICIAL_SITE",
                "asset_operation": "UPDATE_EXISTING",
                "selected_asset_id": snapshot_id,
                "selected_asset_type": "ARTICLE",
                "target_content_type": "ARTICLE",
                "target_object": "CONTENT_ASSET",
                "baseline_run_ids": baseline_run_ids,
                "confirmed_by": "phase4_audit",
                "confirmation_note": "Phase 4 审计：官网已有品牌资产更新，创建实验草案。",
            },
        )
        after = _count_execution_tables(db)
        experiment = db.get(OptimizationExperiment, result.get("experiment_id")) if result.get("experiment_id") else None
        action = db.get(OptimizationAction, result.get("action_id")) if result.get("action_id") else None
        candidate = db.get(OptimizationStrategyCandidate, candidate.id)
        plan = result.get("plan_payload") or {}
        variables = loads(experiment.intervention_variables_json, {}) if experiment else {}

        lines: list[str] = []
        lines.append("# Prompt #40 Phase 4 实验方案落地审计")
        lines.append("")
        lines.append("状态：待评审")
        lines.append("日期：2026-08-27")
        lines.append("")
        lines.append("## 1. 审计边界")
        lines.append("")
        lines.append("本次只审计 Step 8：人工确认渠道/资产执行方案，并创建 Experiment 草案。不进入发布、复采或效果结论。")
        lines.append("")
        lines.append("```text")
        lines.append(f"project_id = {PROJECT_ID}")
        lines.append(f"prompt_id = {PROMPT_ID}")
        lines.append(f"evidence_package_id = {EVIDENCE_PACKAGE_ID}")
        lines.append(f"strategy_candidate_id = {candidate.id}")
        lines.append("channel = OFFICIAL_SITE")
        lines.append("asset_operation = UPDATE_EXISTING")
        lines.append(f"selected_asset_id = {snapshot_id}")
        lines.append(f"baseline_run_ids = {baseline_run_ids}")
        lines.append("```")
        lines.append("")
        lines.append("## 2. 执行表变化")
        lines.append("")
        lines.extend(_markdown_table(
            ["对象", "运行前", "运行后"],
            [
                ["StrategyCandidate", before["strategy_candidates"], after["strategy_candidates"]],
                ["OptimizationAction", before["actions"], after["actions"]],
                ["OptimizationExperiment", before["experiments"], after["experiments"]],
            ],
        ))
        lines.append("")
        lines.append("## 3. Step 7 -> Step 8 状态")
        lines.append("")
        lines.append("```text")
        lines.append(f"review_status = {candidate.review_status}")
        lines.append(f"effective_validation_status = {candidate.effective_validation_status}")
        lines.append(f"effective_payload_version = {candidate.effective_payload_version}")
        lines.append("PENDING_HUMAN_CHANNEL_REVIEW 表示 Strategy 已确认但待 Step 8；Step 8 后变为 VALIDATED。")
        lines.append("```")
        lines.append("")
        lines.append("## 4. selected_asset_ref")
        lines.append("")
        lines.append("```text")
        selected = plan.get("selected_asset_ref") or {}
        lines.append(f"asset_ref_type = {selected.get('asset_ref_type')}")
        lines.append(f"asset_id = {selected.get('asset_id')}")
        lines.append(f"canonical_url = {selected.get('canonical_url')}")
        lines.append(f"asset_type = {selected.get('asset_type')}")
        lines.append(f"channel = {selected.get('channel')}")
        lines.append(f"asset_operation = {selected.get('asset_operation')}")
        lines.append("```")
        lines.append("")
        lines.append("## 5. Baseline Metrics")
        lines.append("")
        metrics = plan.get("baseline_metrics") or {}
        metric_rows = metrics.get("metrics") or {}
        lines.extend(_markdown_table(
            ["指标", "层级", "分子", "分母", "Run IDs"],
            [
                [name, row.get("level"), row.get("numerator"), row.get("denominator"), row.get("source_run_ids")]
                for name, row in metric_rows.items()
                if name in {
                    "brand_mention",
                    "brand_candidate",
                    "brand_recommendation",
                    "target_reason_adoption",
                    "brand_retrieval_presence",
                    "brand_citation_presence",
                    "selected_asset_retrieval_presence",
                    "selected_asset_citation_presence",
                }
            ],
        ))
        lines.append("")
        lines.append("## 6. Action / Experiment 草案")
        lines.append("")
        lines.append("```text")
        lines.append(f"action_id = {action.id if action else None}")
        lines.append(f"action_status = {action.status if action else None}")
        lines.append(f"experiment_id = {experiment.id if experiment else None}")
        lines.append(f"experiment_status = {experiment.status if experiment else None}")
        lines.append(f"release_blocked = {experiment.release_blocked if experiment else None}")
        lines.append(f"release_blocked_reason = {experiment.release_blocked_reason if experiment else None}")
        lines.append(f"experiment_baseline_run_ids = {loads(experiment.baseline_run_ids_json, []) if experiment else []}")
        lines.append("```")
        lines.append("")
        lines.append("## 7. 快照冻结")
        lines.append("")
        lines.append("```text")
        strategy_snapshot = variables.get("strategy_snapshot") or {}
        frozen_effective = strategy_snapshot.get("effective_payload") or {}
        lines.append(f"strategy_snapshot.strategy_candidate_id = {strategy_snapshot.get('strategy_candidate_id')}")
        lines.append(f"strategy_snapshot.effective_validation_status = {strategy_snapshot.get('effective_validation_status')}")
        lines.append(f"strategy_snapshot.target_platform = {frozen_effective.get('target_platform')}")
        lines.append(f"strategy_snapshot.target_asset = {frozen_effective.get('target_asset')}")
        lines.append(f"strategy_snapshot.target_content_type = {frozen_effective.get('target_content_type')}")
        lines.append(f"intervention_variables.selected_asset_ref = {variables.get('selected_asset_ref')}")
        lines.append("```")
        lines.append("")
        lines.append("## 8. 结论")
        lines.append("")
        lines.append("Phase 4 复用现有 StrategyCandidate/effective_payload、OptimizationAction 和 OptimizationExperiment。")
        lines.append("Step 8 已将人工确认的渠道、资产操作和资产引用冻结进 Experiment 草案；Baseline Metrics 明确绑定固定 Run IDs，属于 Experiment 语义。")
        lines.append("本次不进入自动发布、Release Audit、固定复采或 Step 9。")
        lines.append("")
        return "\n".join(lines)
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    report = build_report()
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report)


if __name__ == "__main__":
    main()
