#!/usr/bin/env python3
"""Prompt #40 Phase 2B capability-level gap regression audit."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import SessionLocal
from app.models import EvidenceAlignment, SourceClaim
from app.modules.optimization import service as optimization_service


PROJECT_ID = 3
PROMPT_ID = 40
EVIDENCE_PACKAGE_ID = 15


def _truncate(value: str, limit: int = 140) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."


def _markdown_table(headers: list[str], rows: list[list[object]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return lines


def _count_formal_tables(db) -> dict:
    return {
        "source_claims": db.query(SourceClaim).filter(SourceClaim.project_id == PROJECT_ID).count(),
        "evidence_alignments": db.query(EvidenceAlignment)
        .filter(EvidenceAlignment.project_id == PROJECT_ID, EvidenceAlignment.prompt_id == PROMPT_ID)
        .count(),
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


def build_report() -> str:
    db = SessionLocal()
    try:
        before = _count_formal_tables(db)
        result = _proposal(db)
        after = _count_formal_tables(db)
        rows = result.get("source_analysis") or []
        benchmark_rows = [
            row for row in rows if row.get("benchmark_tier") in {"PRIMARY_BENCHMARK", "SECONDARY_BENCHMARK"}
        ]
        gap_counts = Counter(row.get("source_gap_type") or "null" for row in rows)
        layer_counts = Counter(row.get("capability_gap_layer") or "EMPTY" for row in rows)
        benchmark_gap_counts = Counter(row.get("source_gap_type") or "null" for row in benchmark_rows)
        benchmark_layer_counts = Counter(row.get("capability_gap_layer") or "EMPTY" for row in benchmark_rows)

        lines: list[str] = []
        lines.append("# Prompt #40 Phase 2B Capability Gap 回归审计")
        lines.append("")
        lines.append("状态：待评审")
        lines.append("日期：2026-08-27")
        lines.append("")
        lines.append("## 1. 审计边界")
        lines.append("")
        lines.append("本次只审计 capability/reason-level Gap Diagnosis，不进入 Step 7，不创建动作或实验。")
        lines.append("")
        lines.append("```text")
        lines.append(f"project_id = {PROJECT_ID}")
        lines.append(f"prompt_id = {PROMPT_ID}")
        lines.append(f"evidence_package_id = {EVIDENCE_PACKAGE_ID}")
        lines.append("use_answer_binding_v1_1 = true")
        lines.append("decision_tree = Product Truth -> Relevant Asset Expression -> RetrievalCandidate -> Evidence Adoption")
        lines.append("```")
        lines.append("")
        lines.append("## 2. 零污染核对")
        lines.append("")
        lines.extend(_markdown_table(
            ["对象", "运行前", "运行后"],
            [
                ["SourceClaim 总数", before["source_claims"], after["source_claims"]],
                ["Prompt #40 EvidenceAlignment 总数", before["evidence_alignments"], after["evidence_alignments"]],
            ],
        ))
        lines.append("")
        lines.append("## 3. Proposal 摘要")
        lines.append("")
        summary = result.get("summary") or {}
        lines.append("```text")
        lines.append(f"status = {result.get('status')}")
        lines.append(f"source_count = {summary.get('source_count')}")
        lines.append(f"primary_benchmark_count = {summary.get('primary_benchmark_count')}")
        lines.append(f"secondary_benchmark_count = {summary.get('secondary_benchmark_count')}")
        lines.append(f"existing_downstream_recommended_action_count = {summary.get('recommended_action_count')}")
        lines.append(f"existing_downstream_channel_opportunity_count = {summary.get('channel_opportunity_count')}")
        lines.append(f"all_source_gap_counts = {dict(sorted(gap_counts.items()))}")
        lines.append(f"all_capability_gap_layer_counts = {dict(sorted(layer_counts.items()))}")
        lines.append(f"benchmark_gap_counts = {dict(sorted(benchmark_gap_counts.items()))}")
        lines.append(f"benchmark_layer_counts = {dict(sorted(benchmark_layer_counts.items()))}")
        lines.append("```")
        lines.append("")
        lines.append("说明：以上下游动作/渠道计数来自现有 `citation_decision_vertical_slice` 摘要，用于提示当前接口仍会投影后续结果；Phase 2B 本身没有开发或创建 Step 7/Step 8 对象。")
        lines.append("")
        lines.append("## 4. 核心/辅助对标来源 Gap 逐条结果")
        lines.append("")
        if not benchmark_rows:
            lines.append("当前没有核心/辅助对标来源，因此不进入 capability-level Gap。")
        else:
            table_rows = []
            for row in benchmark_rows:
                diagnosis = row.get("capability_gap_diagnosis") or {}
                asset = row.get("relevant_asset_snapshot") or {}
                retrieval = row.get("retrieval_candidate_context") or {}
                adoption = row.get("evidence_adoption_context") or {}
                table_rows.append([
                    row.get("source_document_id"),
                    _truncate(row.get("title") or row.get("url") or ""),
                    row.get("benchmark_tier"),
                    row.get("source_gap_type"),
                    row.get("capability_gap_layer"),
                    " / ".join(target.get("label", "") for target in row.get("capability_truth_targets", [])[:5]),
                    " / ".join(row.get("unmatched_capability_truth_targets", [])[:5]),
                    row.get("matched_product_truth_status"),
                    asset.get("snapshot_id"),
                    asset.get("coverage"),
                    retrieval.get("status"),
                    adoption.get("status"),
                    diagnosis.get("failure_layer"),
                ])
            lines.extend(_markdown_table(
                [
                    "SourceDocument",
                    "来源",
                    "对标层级",
                    "缺口类型",
                    "最早失败层",
                    "能力目标",
                    "未匹配能力",
                    "Product Truth",
                    "资产快照",
                    "资产覆盖",
                    "检索状态",
                    "采纳状态",
                    "冻结 failure_layer",
                ],
                table_rows,
            ))
        lines.append("")
        lines.append("## 5. 冻结诊断快照示例")
        lines.append("")
        for row in benchmark_rows[:3]:
            lines.append("```text")
            lines.append(f"source_document_id = {row.get('source_document_id')}")
            lines.append(f"source_gap_type = {row.get('source_gap_type')}")
            lines.append(f"source_gap_precondition = {row.get('source_gap_precondition')}")
            lines.append(f"source_gap_reason = {row.get('source_gap_reason')}")
            lines.append(f"capability_gap_layer = {row.get('capability_gap_layer')}")
            lines.append(f"capability_truth_targets = {row.get('capability_truth_targets')}")
            lines.append(f"unmatched_capability_truth_targets = {row.get('unmatched_capability_truth_targets')}")
            lines.append(f"relevant_asset_snapshot = {row.get('relevant_asset_snapshot')}")
            lines.append(f"retrieval_candidate_context = {row.get('retrieval_candidate_context')}")
            lines.append(f"evidence_adoption_context = {row.get('evidence_adoption_context')}")
            lines.append(f"eligible_evidence_lineage = {(row.get('capability_gap_diagnosis') or {}).get('eligible_evidence_lineage')}")
            lines.append("```")
            lines.append("")
        lines.append("## 6. 结论")
        lines.append("")
        lines.append("本次 #40 回归只验证 Gap 诊断层：Product Truth、资产表达、有效检索、引用/采纳上下文均写入可审计快照。")
        lines.append("推荐动作和实验草案不属于 Phase 2B，本次未进入 Step 7。")
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
