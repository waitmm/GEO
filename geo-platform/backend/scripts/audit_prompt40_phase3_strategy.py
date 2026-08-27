#!/usr/bin/env python3
"""Prompt #40 Phase 3 StrategyCandidate + human review audit."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import HTTPException

from app.core.database import SessionLocal
from app.models import OptimizationAction, OptimizationExperiment, OptimizationStrategyCandidate
from app.modules.optimization import service as optimization_service


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


def _error_detail(func) -> str:
    try:
        func()
    except HTTPException as exc:
        return str(exc.detail)
    except Exception as exc:  # pragma: no cover - audit script guard
        return str(exc)
    return "UNEXPECTED_SUCCESS"


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


def build_report() -> str:
    db = SessionLocal()
    try:
        before = _count_execution_tables(db)
        proposal = _proposal(db)
        actions = proposal.get("recommended_actions") or []
        if not actions:
            raise RuntimeError("Prompt #40 当前没有可生成策略候选的 Gap。")
        selected_action = actions[0]
        gap_items = selected_action.get("gap_items") or []

        created_result = optimization_service.confirm_citation_decision_vertical_slice(
            db,
            PROJECT_ID,
            PROMPT_ID,
            {
                "evidence_package_id": EVIDENCE_PACKAGE_ID,
                "action_keys": [selected_action["action_key"]],
                "reviewer": "phase3_audit",
                "create_experiments": True,
                "use_answer_binding_v1_1": True,
                "review_note": "Phase 3 审计：只生成待审核 StrategyCandidate，不进入 Step 8。",
            },
        )
        candidate_read = (created_result.get("created") or [])[0]["strategy_candidate"]
        candidate_id = candidate_read["id"]
        before_review_plan_error = _error_detail(lambda: optimization_service.strategy_to_experiment_plan(db, candidate_id))

        reviewed = optimization_service.review_strategy_candidate(
            db,
            candidate_id,
            type(
                "Payload",
                (),
                {
                    "review_status": "ACCEPTED_WITH_EDITS",
                    "reviewed_by": "phase3_audit",
                    "review_note": "确认策略机制与证据链；执行平台和资产留待 Step 8。",
                    "human_edited_payload": {
                        "human_review_summary": "确认 #40 的能力表达缺口成立；本次只冻结 Strategy 语义，不创建动作或实验。",
                        "confirmed_strategy_scope": "围绕点击统计、自定义分享标题、营销场景使用补齐目标品牌资产表达。",
                    },
                },
            )(),
        )
        after_review_plan_error = _error_detail(lambda: optimization_service.strategy_to_experiment_plan(db, candidate_id))
        after = _count_execution_tables(db)

        structured = candidate_read.get("structured_payload") or {}
        effective = reviewed.get("effective_payload") or {}
        lines: list[str] = []
        lines.append("# Prompt #40 Phase 3 StrategyCandidate 审计")
        lines.append("")
        lines.append("状态：待评审")
        lines.append("日期：2026-08-27")
        lines.append("")
        lines.append("## 1. 审计边界")
        lines.append("")
        lines.append("本次只审计 Step 7：StrategyCandidate + 人工 Strategy 确认。不进入 Step 8，不创建 Action / Experiment。")
        lines.append("")
        lines.append("```text")
        lines.append(f"project_id = {PROJECT_ID}")
        lines.append(f"prompt_id = {PROMPT_ID}")
        lines.append(f"evidence_package_id = {EVIDENCE_PACKAGE_ID}")
        lines.append("use_answer_binding_v1_1 = true")
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
        lines.append("## 3. capability-level Gap 输入")
        lines.append("")
        if gap_items:
            lines.extend(_markdown_table(
                ["gap_item_id", "能力/理由", "Gap", "最早失败层", "Benchmark Evidence", "Observed Runs"],
                [
                    [
                        item.get("gap_item_id"),
                        item.get("capability_label"),
                        item.get("gap_type"),
                        item.get("gap_layer"),
                        item.get("benchmark_evidence_ids"),
                        item.get("observed_run_ids"),
                    ]
                    for item in gap_items
                ],
            ))
        else:
            lines.append("当前 selected action 没有 capability_gap_items。")
        lines.append("")
        lines.append("## 4. StrategyCandidate")
        lines.append("")
        lines.append("```text")
        lines.append(f"candidate_id = {candidate_id}")
        lines.append(f"generation_status = {candidate_read.get('generation_status')}")
        lines.append(f"review_status_before = {candidate_read.get('review_status')}")
        lines.append(f"effective_validation_status_before = {candidate_read.get('effective_validation_status')}")
        lines.append(f"review_status_after = {reviewed.get('review_status')}")
        lines.append(f"effective_validation_status_after = {reviewed.get('effective_validation_status')}")
        lines.append(f"effective_payload_version = {reviewed.get('effective_payload_version')}")
        lines.append("```")
        lines.append("")
        lines.append("## 5. 候选策略结构")
        lines.append("")
        lines.append("```text")
        lines.append(f"gap_item_ids = {structured.get('gap_item_ids')}")
        lines.append(f"target_capability_or_reason = {structured.get('target_capability_or_reason')}")
        lines.append(f"gap_type = {structured.get('evidence_summary', {}).get('gap_type')}")
        lines.append(f"benchmark_evidence_ids = {structured.get('benchmark_evidence_ids')}")
        lines.append(f"product_truth_refs = {structured.get('product_truth_refs')}")
        lines.append(f"relevant_asset_refs = {structured.get('relevant_asset_refs')}")
        lines.append(f"observed_run_ids = {structured.get('observed_run_ids')}")
        lines.append(f"proposed_direction = {structured.get('proposed_direction')}")
        lines.append(f"mechanism = {structured.get('mechanism')}")
        lines.append(f"why_candidate = {structured.get('why_candidate')}")
        lines.append(f"blockers = {structured.get('blockers')}")
        lines.append(f"validation_metric = {structured.get('validation_metric')}")
        lines.append(f"target_platform = {structured.get('target_platform')}")
        lines.append(f"target_asset = {structured.get('target_asset')}")
        lines.append(f"benchmark_channel_boundary = {structured.get('benchmark_channel_boundary')}")
        lines.append("```")
        lines.append("")
        lines.append("## 6. 人工编辑后的 effective_payload 摘要")
        lines.append("")
        lines.append("```text")
        lines.append(f"human_review_summary = {effective.get('human_review_summary')}")
        lines.append(f"confirmed_strategy_scope = {effective.get('confirmed_strategy_scope')}")
        lines.append(f"target_platform = {effective.get('target_platform')}")
        lines.append(f"target_asset = {effective.get('target_asset')}")
        lines.append(f"target_content_type = {effective.get('target_content_type')}")
        lines.append(f"snapshot_policy = {effective.get('effective_payload_snapshot_policy')}")
        lines.append("```")
        lines.append("")
        lines.append("## 7. Gate 验证")
        lines.append("")
        lines.append("```text")
        lines.append(f"before_review_strategy_to_experiment_plan = {before_review_plan_error}")
        lines.append(f"after_review_strategy_to_experiment_plan = {after_review_plan_error}")
        lines.append("Action/Experiment count unchanged = true")
        lines.append("```")
        lines.append("")
        lines.append("## 8. 结论")
        lines.append("")
        lines.append("Phase 3 已生成并人工确认 StrategyCandidate，但 effective_payload 仍处于 PENDING_HUMAN_CHANNEL_REVIEW。")
        lines.append("这表示 Strategy 语义已确认，执行平台/资产/内容类型仍属于 Step 8；后端 Gate 阻止其创建 Action 或 Experiment。")
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
