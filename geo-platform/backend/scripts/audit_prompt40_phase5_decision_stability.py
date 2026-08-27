#!/usr/bin/env python3
"""Prompt #40 Phase 5 Decision Stability read-only audit."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import SessionLocal
from app.models import EvidenceAlignment, OptimizationAction, OptimizationExperiment, OptimizationStrategyCandidate
from app.modules.optimization import service as optimization_service
from app.services.serialization import loads


PROJECT_ID = 3
PROMPT_ID = 40
EVIDENCE_PACKAGE_ID = 15
STRATEGY_CANDIDATE_ID = 41
ACTION_ID = 30
EXPERIMENT_ID = 30


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


def _main_chain_identity(db, proposal: dict) -> dict:
    rows = proposal.get("source_analysis") or []
    candidate = db.get(OptimizationStrategyCandidate, STRATEGY_CANDIDATE_ID)
    action = db.get(OptimizationAction, ACTION_ID)
    experiment = db.get(OptimizationExperiment, EXPERIMENT_ID)
    return {
        "evidence_alignment_count": db.query(EvidenceAlignment).filter(
            EvidenceAlignment.project_id == PROJECT_ID,
            EvidenceAlignment.prompt_id == PROMPT_ID,
        ).count(),
        "formal_supports": db.query(EvidenceAlignment).filter(
            EvidenceAlignment.project_id == PROJECT_ID,
            EvidenceAlignment.prompt_id == PROMPT_ID,
            EvidenceAlignment.relation == "SUPPORTS",
        ).count(),
        "primary_benchmark_count": proposal.get("summary", {}).get("primary_benchmark_count"),
        "secondary_benchmark_count": proposal.get("summary", {}).get("secondary_benchmark_count"),
        "content_gap_count": sum(1 for row in rows if row.get("source_gap_type") == "CONTENT_GAP"),
        "recommended_action_count": proposal.get("summary", {}).get("recommended_action_count"),
        "strategy_candidate_41": {
            "exists": bool(candidate),
            "review_status": candidate.review_status if candidate else None,
            "effective_validation_status": candidate.effective_validation_status if candidate else None,
            "experiment_id": candidate.experiment_id if candidate else None,
        },
        "action_30": {
            "exists": bool(action),
            "status": action.status if action else None,
        },
        "experiment_30": {
            "exists": bool(experiment),
            "status": experiment.status if experiment else None,
            "release_blocked_reason": experiment.release_blocked_reason if experiment else None,
            "baseline_run_ids": loads(experiment.baseline_run_ids_json, []) if experiment else [],
        },
    }


def _same_identity(before: dict, after: dict) -> bool:
    return before == after


def _markdown_table(headers: list[str], rows: list[list[object]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return lines


def _dominant_text(dominant: dict) -> str:
    if dominant.get("outcome_type") == "CO_DOMINANT_RECOMMENDATION_ENTITIES":
        names = [
            str(item.get("entity_text"))
            for item in dominant.get("co_dominant_entities") or []
            if item.get("entity_text")
        ]
        return (
            f"CO_DOMINANT {len(names)} 个并列，均为 "
            f"{dominant.get('run_count')}/{dominant.get('denominator')}: {names}"
        )
    return f"{dominant.get('outcome_type')} {dominant.get('entity_text') or ''}".strip()


def build_report() -> str:
    db = SessionLocal()
    try:
        before_proposal = _proposal(db)
        before_identity = _main_chain_identity(db, before_proposal)
        stability = optimization_service.decision_stability_for_package(
            db,
            PROJECT_ID,
            PROMPT_ID,
            EVIDENCE_PACKAGE_ID,
        )
        after_proposal = _proposal(db)
        after_identity = _main_chain_identity(db, after_proposal)

        top_entities = stability.get("recommendation_entities") or []
        top_reasons = stability.get("recommendation_reasons") or []
        dominant = stability.get("dominant_recommendation_outcome") or {}

        lines: list[str] = []
        lines.append("# Prompt #40 Phase 5 决策稳定性审计")
        lines.append("")
        lines.append("状态：待评审")
        lines.append("日期：2026-08-27")
        lines.append("")
        lines.append("## 1. 审计边界")
        lines.append("")
        lines.append("本次只审计 Decision Stability 后置描述指标，不改变单 Prompt V1 1-8 主链。")
        lines.append("")
        lines.append("```text")
        lines.append(f"project_id = {PROJECT_ID}")
        lines.append(f"prompt_id = {PROMPT_ID}")
        lines.append(f"evidence_package_id = {EVIDENCE_PACKAGE_ID}")
        lines.append(f"version = {stability.get('version')}")
        lines.append(f"metric_role = {stability.get('metric_role')}")
        lines.append("```")
        lines.append("")
        lines.append("## 2. #40 稳定性结果")
        lines.append("")
        lines.append("```text")
        lines.append(f"valid_run_ids = {stability.get('valid_run_ids')}")
        lines.append(f"valid_run_count = {stability.get('valid_run_count')}")
        lines.append(f"brand_decision_run_count = {stability.get('brand_decision_run_count')}")
        lines.append(f"dominant_recommendation_outcome = {_dominant_text(dominant)}")
        if dominant.get("outcome_type") == "CO_DOMINANT_RECOMMENDATION_ENTITIES":
            lines.append("unique_dominant_entity = none")
        lines.append(f"dominant_observed_run_ids = {dominant.get('observed_run_ids')}")
        lines.append(f"decision_stability_score = {stability.get('decision_stability_score')} / 100")
        lines.append(f"stability_level = {stability.get('stability_level')} ({stability.get('stability_level_label')})")
        lines.append(f"formula = {stability.get('formula')}")
        lines.append("```")
        lines.append("")
        lines.append("## 3. 推荐对象覆盖")
        lines.append("")
        lines.extend(_markdown_table(
            ["推荐对象", "覆盖", "分母", "Run IDs"],
            [
                [
                    item.get("entity_text"),
                    item.get("recommendation_run_count"),
                    item.get("denominator"),
                    item.get("observed_run_ids"),
                ]
                for item in top_entities[:10]
            ] or [["-", 0, stability.get("valid_run_count"), []]],
        ))
        lines.append("")
        lines.append("## 4. 推荐理由覆盖")
        lines.append("")
        lines.extend(_markdown_table(
            ["推荐对象", "理由", "角色", "覆盖", "分母", "Run IDs"],
            [
                [
                    item.get("entity_text"),
                    item.get("reason_text"),
                    item.get("decision_role"),
                    item.get("reason_observed_run_count"),
                    item.get("denominator"),
                    item.get("observed_run_ids"),
                ]
                for item in top_reasons[:12]
            ] or [["-", "-", "-", 0, 0, []]],
        ))
        lines.append("")
        lines.append("## 5. 主链零影响对比")
        lines.append("")
        lines.extend(_markdown_table(
            ["对象", "调用稳定性前", "调用稳定性后"],
            [
                ["EvidenceAlignment 总数", before_identity["evidence_alignment_count"], after_identity["evidence_alignment_count"]],
                ["正式 SUPPORTS", before_identity["formal_supports"], after_identity["formal_supports"]],
                ["PRIMARY_BENCHMARK", before_identity["primary_benchmark_count"], after_identity["primary_benchmark_count"]],
                ["SECONDARY_BENCHMARK", before_identity["secondary_benchmark_count"], after_identity["secondary_benchmark_count"]],
                ["CONTENT_GAP", before_identity["content_gap_count"], after_identity["content_gap_count"]],
                ["推荐动作", before_identity["recommended_action_count"], after_identity["recommended_action_count"]],
                ["StrategyCandidate #41", before_identity["strategy_candidate_41"], after_identity["strategy_candidate_41"]],
                ["Action #30", before_identity["action_30"], after_identity["action_30"]],
                ["Experiment #30", before_identity["experiment_30"], after_identity["experiment_30"]],
            ],
        ))
        lines.append("")
        lines.append("```text")
        lines.append(f"decision_stability_formal_output_impact = {'NONE' if _same_identity(before_identity, after_identity) else 'CHANGED'}")
        lines.append("```")
        lines.append("")
        lines.append("## 6. 边界说明")
        lines.append("")
        lines.append(stability.get("boundary_note", ""))
        lines.append("")
        lines.append("本阶段不进入 Step 9，不创建复采任务，不产生实验结论。")
        lines.append("")
        return "\n".join(lines)
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_report()
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report)


if __name__ == "__main__":
    main()
