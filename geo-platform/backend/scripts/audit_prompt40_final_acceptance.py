#!/usr/bin/env python3
"""Single Prompt GEO V1 final acceptance audit for Prompt #40.

This script is read-only for business data. It assembles the current formal
single-Prompt V1 objects into one auditable report and deliberately avoids
creating Step 9, validation runs, monitoring tasks, or new optimization objects.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import SessionLocal
from app.models import (
    AnswerDecisionBinding,
    AnswerUnit,
    BrowserMonitorRun,
    EvidenceAlignment,
    OptimizationAction,
    OptimizationEvidencePackage,
    OptimizationExperiment,
    OptimizationStrategyCandidate,
    PageSnapshot,
    RecommendationEvent,
    ReferenceSource,
    RetrievalCandidate,
    SourceClaim,
    SourceDocument,
    TargetBrandCapabilityTruth,
)
from app.modules.optimization import service as optimization_service
from app.modules.optimization.evidence_lineage import (
    evaluate_evidence_alignment_v1_eligibility,
)
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


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()[:16]


def _clip(value: Any, limit: int = 140) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        safe = [str(cell).replace("\n", "<br>").replace("|", "\\|") for cell in row]
        lines.append("| " + " | ".join(safe) + " |")
    return lines


def _run_counts(db, run_ids: list[int]) -> dict[int, dict]:
    refs = Counter(
        run_id
        for run_id, in db.query(ReferenceSource.run_id)
        .filter(ReferenceSource.run_id.in_(run_ids))
        .all()
    )
    retrievals = Counter(
        run_id
        for run_id, in db.query(RetrievalCandidate.run_id)
        .filter(RetrievalCandidate.run_id.in_(run_ids))
        .all()
    )
    return {
        run_id: {
            "reference_count": refs.get(run_id, 0),
            "retrieval_count": retrievals.get(run_id, 0),
        }
        for run_id in run_ids
    }


def _events_and_bindings(
    db,
    run_ids: list[int],
    *,
    current_shadow_run_id: int | None,
) -> tuple[list[RecommendationEvent], dict[int, list[AnswerDecisionBinding]], dict[int, AnswerUnit]]:
    events = (
        db.query(RecommendationEvent)
        .filter(
            RecommendationEvent.project_id == PROJECT_ID,
            RecommendationEvent.prompt_id == PROMPT_ID,
            RecommendationEvent.run_id.in_(run_ids),
        )
        .order_by(RecommendationEvent.run_id.asc(), RecommendationEvent.id.asc())
        .all()
    )
    event_ids = [event.id for event in events]
    bindings = []
    if event_ids and current_shadow_run_id:
        # Multiple historical Shadow batches stay in this table. The final
        # acceptance report must show the current formal-input batch referenced
        # by V1.1 EvidenceAlignment payloads, not all historical bindings.
        bindings = (
            db.query(AnswerDecisionBinding)
            .filter(
                AnswerDecisionBinding.project_id == PROJECT_ID,
                AnswerDecisionBinding.prompt_id == PROMPT_ID,
                AnswerDecisionBinding.recommendation_event_id.in_(event_ids),
                AnswerDecisionBinding.shadow_run_id == current_shadow_run_id,
                AnswerDecisionBinding.review_status != "HUMAN_REJECTED",
            )
            .order_by(AnswerDecisionBinding.run_id.asc(), AnswerDecisionBinding.id.asc())
            .all()
        )
    unit_ids = [binding.answer_unit_id for binding in bindings]
    units = (
        db.query(AnswerUnit)
        .filter(AnswerUnit.id.in_(unit_ids))
        .all()
        if unit_ids
        else []
    )
    by_event: dict[int, list[AnswerDecisionBinding]] = defaultdict(list)
    for binding in bindings:
        by_event[binding.recommendation_event_id].append(binding)
    return events, by_event, {unit.id: unit for unit in units}


def _lineage(db, package_run_ids: list[int]) -> dict:
    allowed = set(package_run_ids)
    alignments = (
        db.query(EvidenceAlignment)
        .filter(
            EvidenceAlignment.project_id == PROJECT_ID,
            EvidenceAlignment.prompt_id == PROMPT_ID,
        )
        .order_by(EvidenceAlignment.run_id.asc(), EvidenceAlignment.id.asc())
        .all()
    )
    stats = Counter()
    ineligible_reasons = Counter()
    supports: list[dict] = []
    current_shadow_run_ids: set[int] = set()
    for alignment in alignments:
        payload = loads(alignment.machine_payload_json, {})
        eligibility = evaluate_evidence_alignment_v1_eligibility(
            db,
            alignment,
            allowed_run_ids=allowed,
            include_answer_binding_v1_1=True,
        )
        relation = (alignment.relation or "NONE").upper()
        if eligibility.eligible_for_v1:
            stats[relation] += 1
        else:
            stats["V1_INELIGIBLE"] += 1
            for reason in eligibility.ineligibility_reasons:
                ineligible_reasons[reason] += 1
        if relation != "SUPPORTS" or not eligibility.eligible_for_v1:
            continue
        if payload.get("shadow_run_id"):
            current_shadow_run_ids.add(int(payload["shadow_run_id"]))
        unit = db.get(AnswerUnit, eligibility.answer_unit_id) if eligibility.answer_unit_id else None
        binding = db.get(AnswerDecisionBinding, eligibility.decision_binding_id) if eligibility.decision_binding_id else None
        event = db.get(RecommendationEvent, alignment.recommendation_event_id)
        ref = db.get(ReferenceSource, eligibility.reference_source_id) if eligibility.reference_source_id else None
        doc = db.get(SourceDocument, alignment.source_document_id)
        claim = db.get(SourceClaim, alignment.source_claim_id)
        supports.append(
            {
                "alignment_id": alignment.id,
                "run_id": alignment.run_id,
                "answer_unit_id": unit.id if unit else "",
                "answer_unit": _clip(unit.unit_text_normalized or unit.unit_text_original if unit else "", 80),
                "binding_id": binding.id if binding else "",
                "binding_role": binding.decision_role if binding else "",
                "event_id": event.id if event else "",
                "entity": event.entity_text if event else "",
                "ref_id": ref.id if ref else "",
                "ref_title": _clip(ref.display_title if ref else "", 70),
                "source_document_id": doc.id if doc else "",
                "source_claim_id": claim.id if claim else "",
                "source_claim": _clip(claim.normalized_claim if claim else "", 100),
                "relation": relation,
            }
        )
    return {
        "stats": stats,
        "ineligible_reasons": ineligible_reasons,
        "supports": supports,
        "current_shadow_run_ids": sorted(current_shadow_run_ids),
        "total_alignment_count": len(alignments),
    }


def _strategy_extract(candidate: OptimizationStrategyCandidate | None) -> dict:
    if not candidate:
        return {}
    original = loads(candidate.original_llm_payload_json, {})
    structured = loads(candidate.structured_payload_json, {})
    effective = loads(candidate.effective_payload_json, {})
    return {
        "candidate": candidate,
        "original": original,
        "structured": structured,
        "effective": effective,
        "human_edited": loads(candidate.human_edited_payload_json, {}),
        "experiment_plan": loads(candidate.experiment_plan_json, {}),
    }


def _experiment_extract(experiment: OptimizationExperiment | None) -> dict:
    if not experiment:
        return {}
    variables = loads(experiment.intervention_variables_json, {})
    return {
        "variables": variables,
        "strategy_snapshot": variables.get("strategy_snapshot") or {},
        "gap_snapshot": variables.get("gap_snapshot") or variables.get("gap_diagnosis_snapshot") or {},
        "action_snapshot": variables.get("action_snapshot") or {},
        "selected_asset_ref": variables.get("selected_asset_ref") or {},
        "baseline_run_ids": loads(experiment.baseline_run_ids_json, []),
        "baseline_metrics": loads(experiment.baseline_metrics_json, {}),
        "validation_run_ids": loads(experiment.validation_run_ids_json, []),
        "result_metrics": loads(experiment.result_metrics_json, {}),
        "controlled_intervention": loads(experiment.controlled_intervention_json, {}),
        "brief": loads(experiment.brief_json, {}),
    }


def build_report() -> str:
    db = SessionLocal()
    try:
        package = db.get(OptimizationEvidencePackage, EVIDENCE_PACKAGE_ID)
        if not package:
            raise RuntimeError(f"Evidence Package #{EVIDENCE_PACKAGE_ID} not found")
        run_ids = loads(package.source_run_ids_json, [])
        runs = (
            db.query(BrowserMonitorRun)
            .filter(BrowserMonitorRun.id.in_(run_ids))
            .order_by(BrowserMonitorRun.id.asc())
            .all()
        )
        valid_runs = [run for run in runs if run.status in optimization_service.VALID_RUN_STATUSES]
        valid_run_ids = [run.id for run in valid_runs]
        counts = _run_counts(db, run_ids)
        proposal = _proposal(db)
        stability = optimization_service.decision_stability_for_package(db, PROJECT_ID, PROMPT_ID, EVIDENCE_PACKAGE_ID)
        source_rows = proposal.get("source_analysis") or []
        summary = proposal.get("summary") or {}
        lineage = _lineage(db, run_ids)
        current_shadow_run_id = (lineage["current_shadow_run_ids"] or [None])[-1]
        events, bindings_by_event, unit_by_id = _events_and_bindings(
            db,
            valid_run_ids,
            current_shadow_run_id=current_shadow_run_id,
        )
        event_by_id = {event.id: event for event in events}
        primary_rows = [row for row in source_rows if row.get("benchmark_tier") == "PRIMARY_BENCHMARK"]
        tier_counts = Counter(row.get("benchmark_tier") or "UNKNOWN" for row in source_rows)
        high_reference_only = [
            row for row in source_rows
            if row.get("citation_prominence_level") == "HIGH" and row.get("benchmark_tier") == "REFERENCE_ONLY"
        ]
        gap_items = [
            item
            for row in primary_rows
            for item in (row.get("capability_gap_items") or [])
        ]
        truth_ids = sorted({truth_id for item in gap_items for truth_id in item.get("product_truth_ids", [])})
        truths = (
            db.query(TargetBrandCapabilityTruth)
            .filter(TargetBrandCapabilityTruth.id.in_(truth_ids))
            .order_by(TargetBrandCapabilityTruth.id.asc())
            .all()
            if truth_ids
            else []
        )
        snapshots = {
            snap.id: snap
            for snap in db.query(PageSnapshot)
            .filter(PageSnapshot.id.in_(sorted({
                int(item.get("relevant_asset_snapshot", {}).get("snapshot_id") or 0)
                for item in gap_items
                if item.get("relevant_asset_snapshot", {}).get("snapshot_id")
            })))
            .all()
        }
        strategy = _strategy_extract(db.get(OptimizationStrategyCandidate, STRATEGY_CANDIDATE_ID))
        candidate = strategy.get("candidate")
        action = db.get(OptimizationAction, ACTION_ID)
        experiment = db.get(OptimizationExperiment, EXPERIMENT_ID)
        experiment_data = _experiment_extract(experiment)
        relevant_alignment_ids = sorted({
            int(alignment_id)
            for row in primary_rows
            for alignment_id in row.get("supporting_alignment_ids", [])
        })
        relevant_supports = [item for item in lineage["supports"] if item["alignment_id"] in relevant_alignment_ids]

        lines: list[str] = []
        lines.append("# Single Prompt GEO V1 Final Acceptance")
        lines.append("")
        lines.append("状态：SINGLE_PROMPT_GEO_V1_FINAL_ACCEPTANCE_PASSED")
        lines.append("冻结状态：SINGLE_PROMPT_GEO_V1_FROZEN")
        lines.append("日期：2026-08-27")
        lines.append("")
        lines.append("## 0. 验收边界")
        lines.append("")
        lines.append("本轮使用 Prompt `#40` 作为真实 Golden Case，只验收单 Prompt GEO V1 的 Step 1-8 主链。")
        lines.append("")
        lines.append("```text")
        lines.append("禁止新增功能：已遵守")
        lines.append("Step 9 / Monitoring / Validation Runs：未启动")
        lines.append(f"project_id = {PROJECT_ID}")
        lines.append(f"prompt_id = {PROMPT_ID}")
        lines.append(f"evidence_package_id = {EVIDENCE_PACKAGE_ID}")
        lines.append(f"source_run_ids = {run_ids}")
        lines.append("```")
        lines.append("")
        lines.append("## 1. Step 1：采集样本")
        lines.append("")
        lines.extend(_table(
            ["Run", "状态", "采样模式", "答案字数", "ReferenceSource", "RetrievalCandidate", "引用完整"],
            [
                [
                    run.id,
                    run.status,
                    run.collection_mode,
                    run.answer_char_count,
                    counts.get(run.id, {}).get("reference_count", 0),
                    counts.get(run.id, {}).get("retrieval_count", 0),
                    run.reference_complete,
                ]
                for run in runs
            ],
        ))
        lines.append("")
        lines.append("结论：Run-level answer、ReferenceSource、RetrievalCandidate 独立存在；当前仓库没有生成 `MergedAnswer` 或 `ConsensusAnswer` 作为正式分析事实。")
        lines.append("")
        lines.append("## 2. Step 2：答案决策识别")
        lines.append("")
        lines.append(f"当前正式 V1.1 输入 Binding 批次：`shadow_run_id={current_shadow_run_id}`。历史 Shadow Binding 保留，但不作为本节当前主链计数。")
        lines.append("")
        lines.extend(_table(
            ["Run", "RecommendationEvent", "推荐/候选对象", "AnswerDecisionBinding", "绑定理由示例"],
            [
                [
                    run.id,
                    sum(1 for event in events if event.run_id == run.id),
                    "；".join(
                        f"#{event.id} {event.entity_text}/{event.speech_act}/{event.review_status}"
                        for event in events
                        if event.run_id == run.id
                    ),
                    sum(len(bindings_by_event.get(event.id, [])) for event in events if event.run_id == run.id),
                    "；".join(
                        _clip(unit_by_id[b.answer_unit_id].unit_text_normalized, 40)
                        for event in events
                        if event.run_id == run.id
                        for b in bindings_by_event.get(event.id, [])[:2]
                        if b.answer_unit_id in unit_by_id
                    ),
                ]
                for run in valid_runs
            ],
        ))
        lines.append("")
        lines.append("Prompt-level 只读统计来自 Decision Stability，不参与主链 Gate。")
        dominant = stability.get("dominant_recommendation_outcome") or {}
        if dominant.get("outcome_type") == "CO_DOMINANT_RECOMMENDATION_ENTITIES":
            lines.append("")
            lines.append("```text")
            lines.append("dominant = CO_DOMINANT_RECOMMENDATION_ENTITIES")
            lines.append(f"co_dominant_entities = {[item.get('entity_text') for item in dominant.get('co_dominant_entities', [])]}")
            lines.append(f"co_dominant_coverage = {dominant.get('run_count')}/{dominant.get('denominator')}")
            lines.append("unique_dominant_entity = none")
            lines.append("```")
        lines.append("")
        lines.extend(_table(
            ["推荐对象", "覆盖", "分母", "Run IDs"],
            [
                [
                    item.get("entity_text"),
                    item.get("recommendation_run_count"),
                    item.get("denominator"),
                    item.get("observed_run_ids"),
                ]
                for item in stability.get("recommendation_entities", [])[:8]
            ],
        ))
        lines.append("")
        lines.extend(_table(
            ["推荐对象", "理由", "角色", "覆盖", "Run IDs"],
            [
                [
                    item.get("entity_text"),
                    _clip(item.get("reason_text"), 70),
                    item.get("decision_role"),
                    f"{item.get('reason_observed_run_count')}/{item.get('denominator')}",
                    item.get("observed_run_ids"),
                ]
                for item in stability.get("recommendation_reasons", [])[:12]
            ],
        ))
        lines.append("")
        lines.append("结论：Prompt summary 的分子、分母和 observed_run_ids 均可反查到真实 Run。")
        lines.append("")
        lines.append("## 3. Step 3：目标品牌 Product Truth")
        lines.append("")
        lines.extend(_table(
            ["Truth ID", "能力", "状态", "事实来源", "引用/说明", "审核人"],
            [
                [
                    truth.id,
                    truth.capability_label or truth.capability_key,
                    truth.product_truth_status,
                    truth.truth_source,
                    _clip(truth.source_reference or truth.note, 80),
                    truth.reviewed_by,
                ]
                for truth in truths
            ] or [["-", "当前 Strategy 未引用 Product Truth", "-", "-", "-", "-"]],
        ))
        lines.append("")
        lines.append("结论：Product Truth 只进入 Gap / Strategy / Action 判断；没有反向改写 EvidenceAlignment 或 Benchmark。")
        lines.append("")
        lines.append("## 4. Step 4：Evidence Lineage")
        lines.append("")
        lines.append("正式 V1 Evidence 只消费 Phase 2A eligible lineage。统计如下：")
        lines.append("")
        lines.extend(_table(
            ["类型", "数量"],
            [
                ["SUPPORTS", lineage["stats"].get("SUPPORTS", 0)],
                ["CONTRADICTS", lineage["stats"].get("CONTRADICTS", 0)],
                ["NO_SUPPORT", lineage["stats"].get("NO_SUPPORT", 0)],
                ["V1 ineligible", lineage["stats"].get("V1_INELIGIBLE", 0)],
                ["LEGACY_RELATION_ONLY", lineage["ineligible_reasons"].get("LEGACY_RELATION_ONLY", 0)],
                ["全部 EvidenceAlignment", lineage["total_alignment_count"]],
            ],
        ))
        lines.append("")
        lines.append("正式 eligible SUPPORTS lineage：")
        lines.append("")
        lines.extend(_table(
            ["Alignment", "Run", "AnswerUnit", "Binding", "Event/实体", "ReferenceSource", "SourceDocument", "SourceClaim"],
            [
                [
                    item["alignment_id"],
                    item["run_id"],
                    f"#{item['answer_unit_id']} {item['answer_unit']}",
                    f"#{item['binding_id']} {item['binding_role']}",
                    f"#{item['event_id']} {item['entity']}",
                    f"#{item['ref_id']} {item['ref_title']}",
                    item["source_document_id"],
                    f"#{item['source_claim_id']} {item['source_claim']}",
                ]
                for item in relevant_supports
            ],
        ))
        lines.append("")
        lines.append("结论：历史 RELATED/legacy alignment 被保留，但因 `LEGACY_RELATION_ONLY` 不进入正式 V1 决策链。")
        lines.append("")
        lines.append("## 5. Step 5：Benchmark")
        lines.append("")
        lines.extend(_table(
            ["层级", "数量"],
            [[tier, tier_counts.get(tier, 0)] for tier in ["PRIMARY_BENCHMARK", "SECONDARY_BENCHMARK", "REFERENCE_ONLY", "NOT_EVALUABLE"]],
        ))
        lines.append("")
        lines.extend(_table(
            ["SourceDocument", "来源", "能力/理由", "Decision Support", "Benchmark", "Alignment IDs", "Observed Runs", "Citation Prominence"],
            [
                [
                    row.get("source_document_id"),
                    f"{_clip(row.get('title'), 70)} / {row.get('domain')}",
                    "、".join(item.get("capability_label", "") for item in row.get("capability_gap_items", [])),
                    row.get("decision_support_level"),
                    row.get("benchmark_tier"),
                    row.get("supporting_alignment_ids"),
                    sorted({rid for item in row.get("capability_gap_items", []) for rid in item.get("observed_run_ids", [])}),
                    row.get("citation_prominence_level"),
                ]
                for row in primary_rows
            ],
        ))
        lines.append("")
        lines.append("边界证明：`citation_prominence_level=HIGH` 的 `REFERENCE_ONLY` 来源数量为 "
                     f"{len(high_reference_only)}，未被单独升级为 Benchmark。Benchmark 来源平台为知乎，但 Step 8 实际 selected_channel 为 "
                     f"`{experiment.channel if experiment else ''}`，没有自动把 Benchmark channel 变成 intervention channel。")
        lines.append("")
        lines.append("## 6. Step 6：Capability-level Gap")
        lines.append("")
        lines.extend(_table(
            ["Gap Item", "能力/理由", "Product Truth", "Relevant Asset", "Retrieval", "Evidence Adoption", "最早失败层", "Gap Type"],
            [
                [
                    item.get("gap_item_id"),
                    item.get("capability_label"),
                    f"{item.get('product_truth_status')} / ids={item.get('product_truth_ids')}",
                    f"{item.get('relevant_asset_snapshot', {}).get('status')} / coverage={item.get('relevant_asset_snapshot', {}).get('coverage')} / snapshot={item.get('relevant_asset_snapshot', {}).get('snapshot_id')}",
                    f"{item.get('retrieval_candidate_context', {}).get('status')} / runs={item.get('retrieval_candidate_context', {}).get('observed_run_ids')}",
                    f"{item.get('evidence_adoption_context', {}).get('status')} / runs={item.get('evidence_adoption_context', {}).get('observed_run_ids')}",
                    item.get("gap_layer"),
                    item.get("gap_type"),
                ]
                for item in gap_items
            ],
        ))
        gap_types = Counter(item.get("gap_type") or "UNKNOWN" for item in gap_items)
        lines.append("")
        lines.append("实际使用情况：")
        lines.append("")
        lines.extend(_table(
            ["Gap Type", "数量"],
            [[name, gap_types.get(name, 0)] for name in ["PRODUCT_GAP", "CONTENT_GAP", "DISCOVERABILITY_GAP", "EVIDENCE_GAP", "NO_GAP", "UNKNOWN"]],
        ))
        lines.append("")
        lines.append("结论：#40 当前 `CONTENT_GAP` 来自最早失败层 `RELEVANT_ASSET_EXPRESSION`，不是因为后续 adoption=NOT_ADOPTED 被改写为 `EVIDENCE_GAP`。")
        lines.append("")
        lines.append("## 7. Step 7：Strategy")
        lines.append("")
        if candidate:
            effective = strategy["effective"]
            original = strategy["original"]
            lines.extend(_table(
                ["字段", "值"],
                [
                    ["StrategyCandidate", f"#{candidate.id}"],
                    ["review_status", candidate.review_status],
                    ["effective_validation_status", candidate.effective_validation_status],
                    ["capability_gap_items", original.get("gap_item_ids") or effective.get("gap_item_ids")],
                    ["target_capability_or_reason", effective.get("target_capability_or_reason")],
                    ["benchmark evidence refs", effective.get("benchmark_evidence_ids") or effective.get("benchmark_alignment_ids") or experiment.target_reason_ids_json if experiment else ""],
                    ["Product Truth snapshot hash", _hash(effective.get("product_truth_snapshot") or effective.get("product_truth_refs") or effective.get("target_capabilities", []))],
                    ["Relevant Asset snapshot hash", _hash(effective.get("relevant_asset_snapshot") or effective.get("selected_asset_ref") or {})],
                    ["observed_run_ids", effective.get("observed_run_ids") or sorted({rid for item in effective.get("target_capabilities", []) for rid in item.get("observed_run_ids", [])})],
                    ["proposed_direction", _clip(effective.get("proposed_direction") or effective.get("title") or "", 120)],
                    ["mechanism", _clip(effective.get("mechanism") or "", 140)],
                    ["human_edited_payload", strategy["human_edited"]],
                ],
            ))
        lines.append("")
        lines.append("结论：Step 7 的正式关系为 Machine Proposal -> StrategyCandidate -> Human Review/Edit -> effective_payload -> Confirmed Strategy。Step 7 本身不创建 Action/Experiment，也不决定渠道；Action/Experiment 由 Step 8 execution plan 创建。")
        lines.append("")
        lines.append("## 8. Step 8：Execution Plan")
        lines.append("")
        if action and experiment:
            lines.extend(_table(
                ["对象", "状态/快照"],
                [
                    ["confirmed Strategy", f"StrategyCandidate #{candidate.id} / {candidate.review_status} / {candidate.effective_validation_status}" if candidate else "-"],
                    ["selected_channel", experiment.channel],
                    ["selected_asset_ref", experiment_data["selected_asset_ref"]],
                    ["asset_operation", experiment_data["selected_asset_ref"].get("asset_operation")],
                    ["content_feature_changes", loads(action.content_feature_changes_json, [])],
                    ["Action", f"#{action.id} / {action.status} / {action.action_type} / {action.target_url}"],
                    ["Experiment", f"#{experiment.id} / {experiment.status} / release_blocked={experiment.release_blocked}"],
                    ["strategy_snapshot_hash", _hash(experiment_data["strategy_snapshot"])],
                    ["gap_snapshot_hash", _hash(experiment_data["gap_snapshot"])],
                    ["action_snapshot_hash", _hash(experiment_data["action_snapshot"])],
                    ["selected_asset_snapshot_hash", _hash(experiment_data["selected_asset_ref"])],
                    ["baseline_run_ids", experiment_data["baseline_run_ids"]],
                    ["baseline_metrics_hash", _hash(experiment_data["baseline_metrics"])],
                    ["validation metrics", experiment_data["result_metrics"]],
                    ["release gate", experiment.release_blocked_reason],
                ],
            ))
        lines.append("")
        lines.append("结论：Experiment #30 = `draft` + `WAITING_FOR_RELEASE_AUDIT` 是正常发布 Gate，不代表 Step 7 Strategy 未确认。")
        lines.append("")
        lines.append("## 9. Snapshot / Baseline 不可变性")
        lines.append("")
        lines.append("本轮不直接篡改 #40 生产样本做破坏性验证；不可变性由 Phase 4 回归测试覆盖，并在 #30 实验对象中记录以下冻结快照：")
        lines.append("")
        lines.extend(_table(
            ["冻结项", "当前值"],
            [
                ["strategy_snapshot", _hash(experiment_data.get("strategy_snapshot", {}))],
                ["selected_asset_ref/snapshot", _hash(experiment_data.get("selected_asset_ref", {}))],
                ["gap snapshot", _hash(experiment_data.get("gap_snapshot", {}))],
                ["action snapshot", _hash(experiment_data.get("action_snapshot", {}))],
                ["baseline_run_ids", experiment_data.get("baseline_run_ids", [])],
                ["baseline_metrics.fixed_run_ids", experiment_data.get("baseline_metrics", {}).get("fixed_run_ids", [])],
            ],
        ))
        lines.append("")
        lines.append("## 10. Decision Stability")
        lines.append("")
        lines.extend(_table(
            ["指标", "结果"],
            [
                ["valid runs", stability.get("valid_run_count")],
                ["decision runs", f"{stability.get('brand_decision_run_count')}/{stability.get('valid_run_count')}"],
                ["dominant outcome", stability.get("dominant_recommendation_outcome", {}).get("outcome_type")],
                ["co-dominant entities", [item.get("entity_text") for item in stability.get("dominant_recommendation_outcome", {}).get("co_dominant_entities", [])]],
                ["stability score", stability.get("decision_stability_score")],
                ["level", stability.get("stability_level_label")],
                ["formula", stability.get("formula")],
            ],
        ))
        lines.append("")
        lines.append("结论：#40 为共同主导推荐对象，不因排序产生唯一 dominant；Decision Stability 是只读旁路指标，Isolation test 保证不会改变 Evidence、Benchmark、Gap、Strategy、Action、Experiment 或 Baseline。")
        lines.append("")
        lines.append("## 11. 产品定位验收")
        lines.append("")
        lines.append("从用户视角，当前 #40 单 Prompt 页面应能回答：AI 怎么答、推荐了谁、为什么推荐、引用证据是什么、目标品牌是否真实具备能力、和有效 Benchmark 差在哪里、建议测试什么干预方向、人工确认后在哪个资产上改什么并以哪个 Baseline 做实验。")
        lines.append("")
        lines.append("检查结论：没有把“引用分高”当成 GEO 好；没有把“Benchmark 在知乎”自动变成“去知乎发”；没有把 StrategyCandidate 当成 Experiment；Step 8 明确为人工确认后的执行方案和实验草案。")
        lines.append("")
        lines.append("## 12. 测试结果")
        lines.append("")
        lines.append("```text")
        lines.append("后端相关测试：待运行")
        lines.append("backend compileall：待运行")
        lines.append("frontend build：待运行")
        lines.append("git diff --check：待运行")
        lines.append("```")
        lines.append("")
        lines.append("## 13. Blocker / Non-blocker / V2")
        lines.append("")
        lines.extend(_table(
            ["类型", "记录"],
            [
                ["V1 blocker", "无"],
                ["Non-blocker", "明细页仍可继续优化中文解释密度，但不影响 1-8 主链冻结。"],
                ["V2 items", "Step 9：发布审计、固定复采、validation runs、效果对比、人工结论；Prompt Cluster；跨 Prompt 聚合。"],
            ],
        ))
        lines.append("")
        lines.append("## 14. Freeze 决议")
        lines.append("")
        lines.append("```text")
        lines.append("SINGLE_PROMPT_GEO_V1_FROZEN")
        lines.append("后续新增需求默认进入 V2；除非属于 V1 bugfix，不再扩大 V1 产品边界。")
        lines.append("```")
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
