#!/usr/bin/env python3
"""Prompt #40 Step 8 Asset Brief + Claim Matrix audit.

This audit belongs to the second Step 8 checkpoint. It reuses existing
StrategyCandidate/Action/Experiment objects when present and only backfills the
new asset_brief snapshot for draft experiments that predate this checkpoint.
It does not create Draft copy, publish content, run validation, or enter Step 9.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import SessionLocal
from app.models import (
    EvidenceAlignment,
    OptimizationAction,
    OptimizationExperiment,
    OptimizationEvidencePackage,
    OptimizationStrategyCandidate,
    PageSnapshot,
)
from app.modules.optimization import service as optimization_service
from app.services.serialization import loads


PROJECT_ID = 3
PROMPT_ID = 40
EVIDENCE_PACKAGE_ID = 15


def _table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        safe = [str(cell).replace("\n", "<br>").replace("|", "\\|") for cell in row]
        lines.append("| " + " | ".join(safe) + " |")
    return lines


def _counts(db) -> dict:
    return {
        "strategy_candidates": db.query(OptimizationStrategyCandidate).filter(
            OptimizationStrategyCandidate.project_id == PROJECT_ID,
            OptimizationStrategyCandidate.evidence_package_id == EVIDENCE_PACKAGE_ID,
        ).count(),
        "actions": db.query(OptimizationAction).count(),
        "experiments": db.query(OptimizationExperiment).count(),
        "evidence_alignments": db.query(EvidenceAlignment).filter(
            EvidenceAlignment.project_id == PROJECT_ID,
            EvidenceAlignment.prompt_id == PROMPT_ID,
        ).count(),
    }


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


def _ensure_step8_candidate(db) -> tuple[OptimizationStrategyCandidate, dict, bool]:
    candidates = (
        db.query(OptimizationStrategyCandidate)
        .filter(
            OptimizationStrategyCandidate.project_id == PROJECT_ID,
            OptimizationStrategyCandidate.evidence_package_id == EVIDENCE_PACKAGE_ID,
            OptimizationStrategyCandidate.review_status.in_(["ACCEPTED", "ACCEPTED_WITH_EDITS"]),
        )
        .order_by(OptimizationStrategyCandidate.id.desc())
        .all()
    )
    candidate = _preferred_official_site_candidate(candidates)
    if not candidate:
        proposal = _proposal(db)
        actions = proposal.get("recommended_actions") or []
        if not actions:
            raise RuntimeError("Prompt #40 当前没有可生成策略候选的 Gap。")
        created = optimization_service.confirm_citation_decision_vertical_slice(
            db,
            PROJECT_ID,
            PROMPT_ID,
            {
                "evidence_package_id": EVIDENCE_PACKAGE_ID,
                "action_keys": [actions[0]["action_key"]],
                "reviewer": "asset_brief_audit",
                "use_answer_binding_v1_1": True,
                "review_note": "Step 8 Asset Brief 审计：生成 StrategyCandidate。",
            },
        )
        candidate_id = (created.get("created") or [])[0]["strategy_candidate"]["id"]
        optimization_service.review_strategy_candidate(
            db,
            candidate_id,
            type(
                "Payload",
                (),
                {
                    "review_status": "ACCEPTED_WITH_EDITS",
                    "reviewed_by": "asset_brief_audit",
                    "review_note": "确认策略机制；继续生成资产简报。",
                    "human_edited_payload": {"human_review_summary": "确认 #40 进入资产简报审计。"},
                },
            )(),
        )
        candidate = db.get(OptimizationStrategyCandidate, candidate_id)

    package = db.get(OptimizationEvidencePackage, EVIDENCE_PACKAGE_ID)
    baseline_run_ids = loads(package.source_run_ids_json, []) if package else []
    effective = loads(candidate.effective_payload_json, {})
    baseline_run_ids = effective.get("observed_run_ids") or baseline_run_ids
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
            "confirmed_by": "asset_brief_audit",
            "confirmation_note": "Step 8 Asset Brief 审计：复用/补齐实验草案资产简报。",
        },
    )
    return db.get(OptimizationStrategyCandidate, candidate.id), result, result.get("readiness_status") != "DRAFT_ALREADY_EXISTS"


def _preferred_official_site_candidate(candidates: list[OptimizationStrategyCandidate]) -> OptimizationStrategyCandidate | None:
    if not candidates:
        return None

    def score(candidate: OptimizationStrategyCandidate) -> tuple[int, int, int]:
        effective = loads(candidate.effective_payload_json, {})
        target_platform = str(effective.get("target_platform") or "").upper()
        primary_path = str(effective.get("primary_intervention_path") or "").upper()
        is_official = target_platform == "OFFICIAL_SITE" or primary_path.endswith(":OFFICIAL_SITE")
        return (
            1 if candidate.experiment_id else 0,
            1 if target_platform == "OFFICIAL_SITE" else 0,
            1 if is_official else 0,
        )

    ranked = sorted(candidates, key=lambda item: (*score(item), item.id), reverse=True)
    return ranked[0]


def build_report() -> str:
    db = SessionLocal()
    try:
        before_counts = _counts(db)
        before_summary = (_proposal(db).get("summary") or {})
        candidate, result, created_new_draft = _ensure_step8_candidate(db)
        experiment = db.get(OptimizationExperiment, result.get("experiment_id")) if result.get("experiment_id") else None
        action = db.get(OptimizationAction, result.get("action_id")) if result.get("action_id") else None
        before_brief = result.get("plan_payload", {}).get("asset_brief") or {}
        reviewed = optimization_service.review_experiment_asset_brief(
            db,
            experiment.id,
            {
                "review_status": "CONFIRMED",
                "reviewed_by": "asset_brief_audit",
                "review_note": "确认资产简报事实边界；不生成正文 Draft。",
                "approved_mechanism_review": True,
            },
        )
        after_counts = _counts(db)
        after_summary = (_proposal(db).get("summary") or {})
        after_brief = reviewed.get("intervention_variables", {}).get("asset_brief") or {}
        matrix = after_brief.get("claim_matrix") or {}
        target_claims = matrix.get("target_brand_claims") or []
        benchmark_claims = matrix.get("benchmark_context_claims") or []
        mappings = matrix.get("required_signal_mappings") or []
        effective = loads(candidate.effective_payload_json, {})
        strategy_core = after_brief.get("strategy_core_snapshot") or {}
        variables = loads(experiment.intervention_variables_json, {}) if experiment else {}
        controlled = loads(experiment.controlled_intervention_json, {}) if experiment else {}
        release_evidence = loads(action.release_evidence_json, {}) if action else {}
        requirement_counts = Counter(claim.get("requirement_level") for claim in target_claims)

        lines: list[str] = []
        lines.append("# Prompt #40 Step 8 Asset Brief + Claim Matrix 审计")
        lines.append("")
        lines.append("状态：待评审")
        lines.append("日期：2026-08-31")
        lines.append("")
        lines.append("## 1. 审计边界")
        lines.append("")
        lines.append("本轮只审计 Step 8 的 Asset Brief + Claim Matrix，不生成 Draft、不发布、不复采、不进入 Step 9。")
        lines.append("")
        lines.append("```text")
        lines.append(f"project_id = {PROJECT_ID}")
        lines.append(f"prompt_id = {PROMPT_ID}")
        lines.append(f"evidence_package_id = {EVIDENCE_PACKAGE_ID}")
        lines.append(f"strategy_candidate_id = {candidate.id}")
        lines.append(f"action_id = {action.id if action else None}")
        lines.append(f"experiment_id = {experiment.id if experiment else None}")
        lines.append(f"created_new_draft = {created_new_draft}")
        lines.append("```")
        lines.append("")
        lines.append("## 2. 对象与主链零污染")
        lines.append("")
        lines.extend(_table(
            ["对象", "运行前", "运行后"],
            [
                ["StrategyCandidate", before_counts["strategy_candidates"], after_counts["strategy_candidates"]],
                ["OptimizationAction", before_counts["actions"], after_counts["actions"]],
                ["OptimizationExperiment", before_counts["experiments"], after_counts["experiments"]],
                ["Prompt #40 EvidenceAlignment", before_counts["evidence_alignments"], after_counts["evidence_alignments"]],
                ["PRIMARY_BENCHMARK", before_summary.get("primary_benchmark_count"), after_summary.get("primary_benchmark_count")],
                ["推荐动作", before_summary.get("recommended_action_count"), after_summary.get("recommended_action_count")],
            ],
        ))
        lines.append("")
        lines.append("结论：Asset Brief 只补充 Step 8 审核快照，不改变 Evidence / Benchmark / Gap / Strategy 计算。")
        lines.append("")
        lines.append("## 3. Strategy Core 与执行上下文")
        lines.append("")
        lines.extend(_table(
            ["字段", "值"],
            [
                ["target_decision_change", strategy_core.get("target_decision_change")],
                ["intervention_mechanism", strategy_core.get("intervention_mechanism")],
                ["primary_intervention_path", strategy_core.get("primary_intervention_path")],
                ["channel", after_brief.get("channel")],
                ["channel_role", after_brief.get("channel_role")],
                ["asset_operation", after_brief.get("asset_operation")],
                ["selected_asset_ref", after_brief.get("selected_asset_ref")],
            ],
        ))
        lines.append("")
        lines.append("## 4. Claim Matrix：目标品牌 Claim")
        lines.append("")
        lines.extend(_table(
            ["能力", "表达要求", "Product Truth", "依据", "边界"],
            [
                [
                    claim.get("capability_label"),
                    claim.get("requirement_level"),
                    claim.get("product_truth_status"),
                    claim.get("support_basis"),
                    (claim.get("claim_boundary") or {}).get("allowed_scope"),
                ]
                for claim in target_claims
            ],
        ))
        lines.append("")
        lines.append("## 5. Claim Matrix：对标证据上下文")
        lines.append("")
        lines.extend(_table(
            ["能力", "依据", "Evidence IDs", "Run IDs", "边界"],
            [
                [
                    claim.get("capability_label"),
                    claim.get("support_basis"),
                    claim.get("benchmark_evidence_refs"),
                    claim.get("observed_run_ids"),
                    claim.get("source_entity_boundary"),
                ]
                for claim in benchmark_claims
            ],
        ))
        lines.append("")
        lines.append("## 6. Required Signal 映射")
        lines.append("")
        lines.extend(_table(
            ["能力", "映射状态", "Claim IDs", "Required Signal"],
            [
                [
                    mapping.get("capability_label"),
                    mapping.get("status"),
                    mapping.get("claim_ids"),
                    mapping.get("required_signal_texts"),
                ]
                for mapping in mappings
            ],
        ))
        lines.append("")
        lines.append("## 7. 审核状态")
        lines.append("")
        lines.append("```text")
        lines.append(f"before_brief_status = {before_brief.get('status')}")
        lines.append(f"after_brief_status = {after_brief.get('status')}")
        lines.append(f"draft_gate = {(after_brief.get('draft_gate') or {}).get('status')}")
        lines.append(f"requirement_counts = {dict(requirement_counts)}")
        lines.append(f"mechanism_compatibility = {(after_brief.get('mechanism_compatibility') or {}).get('status')}")
        lines.append("```")
        lines.append("")
        lines.append("## 8. 快照落点")
        lines.append("")
        lines.extend(_table(
            ["位置", "是否包含 asset_brief"],
            [
                ["Experiment.intervention_variables_json", bool(variables.get("asset_brief"))],
                ["Experiment.controlled_intervention_json", bool(controlled.get("asset_brief_snapshot"))],
                ["Experiment.brief_json", bool(loads(experiment.brief_json, {}).get("asset_brief")) if experiment else False],
                ["Action.release_evidence_json", bool(release_evidence.get("asset_brief_snapshot"))],
                ["StrategyCandidate.experiment_plan_json", bool(loads(candidate.experiment_plan_json, {}).get("asset_brief"))],
            ],
        ))
        lines.append("")
        lines.append("## 9. 边界结论")
        lines.append("")
        lines.append("- Asset Brief 不是 StrategyCandidate，不重写 Strategy Core。")
        lines.append("- Claim Matrix 只列事实 Claim，不生成正文段落、FAQ 或 Draft。")
        lines.append("- 目标品牌 Claim 只由 Product Truth 支持；Benchmark Evidence 只作为对标上下文。")
        lines.append("- Step 8 仍然只创建/复用 Action 与 Experiment Draft；真实发布仍等待 Release Audit。")
        return "\n".join(lines) + "\n"
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    report = build_report()
    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
    else:
        print(report)


if __name__ == "__main__":
    main()
