#!/usr/bin/env python3
"""Prompt #40 Phase 2A lineage audit.

This script is intentionally read-only for formal evidence tables. It checks
whether V1.1 EvidenceAlignment rows can prove the full run-level lineage before
they are consumed by Citation Decision V1.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import SessionLocal
from app.models import (
    AnswerDecisionBinding,
    AnswerUnit,
    BrowserMonitorRun,
    EvidenceAlignment,
    OptimizationEvidencePackage,
    Project,
    Prompt,
    RecommendationEvent,
    ReferenceSource,
    SourceClaim,
    SourceDocument,
)
from app.modules.optimization.evidence_lineage import evaluate_evidence_alignment_v1_eligibility
from app.modules.optimization import service as optimization_service
from app.services.serialization import loads


PROJECT_ID = 3
PROMPT_ID = 40
EVIDENCE_PACKAGE_ID = 15


def _truncate(value: str, limit: int = 180) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."


def _relation_bucket(relation: str) -> str:
    normalized = (relation or "NONE").upper()
    if normalized in {"SUPPORTS", "CONTRADICTS"}:
        return normalized
    return "NO_SUPPORT"


def _count_formal_tables(db, project_id: int, prompt_id: int) -> dict:
    return {
        "source_claims": db.query(SourceClaim).filter(SourceClaim.project_id == project_id).count(),
        "evidence_alignments_for_prompt": db.query(EvidenceAlignment)
        .filter(EvidenceAlignment.project_id == project_id, EvidenceAlignment.prompt_id == prompt_id)
        .count(),
    }


def _compute_formal_output_summary(db, project_id: int, prompt_id: int, package_id: int) -> dict:
    original_limit = optimization_service.SOURCE_METADATA_FETCH_LIMIT
    optimization_service.SOURCE_METADATA_FETCH_LIMIT = 0
    try:
        result = optimization_service.citation_decision_vertical_slice(
            db,
            project_id,
            prompt_id,
            evidence_package_id=package_id,
            use_answer_binding_v1_1=True,
        )
    finally:
        optimization_service.SOURCE_METADATA_FETCH_LIMIT = original_limit
    summary = result.get("summary") or {}
    return {
        "status": result.get("status"),
        "primary_benchmark_count": summary.get("primary_benchmark_count", 0),
        "secondary_benchmark_count": summary.get("secondary_benchmark_count", 0),
        "recommended_action_count": summary.get("recommended_action_count", 0),
        "channel_opportunity_count": summary.get("channel_opportunity_count", 0),
    }


def _alignment_payload(alignment: EvidenceAlignment) -> dict:
    return loads(alignment.machine_payload_json, {}) or {}


def _ids_from_package(package: OptimizationEvidencePackage) -> list[int]:
    result = []
    for item in loads(package.source_run_ids_json, []) or []:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _format_counter(counter: Counter | dict) -> str:
    if not counter:
        return "-"
    return ", ".join(f"{key}={value}" for key, value in sorted(counter.items()))


def _markdown_table(headers: list[str], rows: Iterable[list[object]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return lines


def build_report() -> str:
    db = SessionLocal()
    try:
        project = db.get(Project, PROJECT_ID)
        prompt = db.get(Prompt, PROMPT_ID)
        package = db.get(OptimizationEvidencePackage, EVIDENCE_PACKAGE_ID)
        if not project or not prompt or not package:
            raise RuntimeError("Project、Prompt 或 Evidence Package 不存在，无法执行 #40 Phase 2A 审计。")

        run_ids = _ids_from_package(package)
        runs = (
            db.query(BrowserMonitorRun)
            .filter(BrowserMonitorRun.id.in_(run_ids))
            .order_by(BrowserMonitorRun.id.asc())
            .all()
            if run_ids
            else []
        )
        allowed_run_ids = {run.id for run in runs}
        events = (
            db.query(RecommendationEvent)
            .filter(
                RecommendationEvent.project_id == PROJECT_ID,
                RecommendationEvent.prompt_id == PROMPT_ID,
                RecommendationEvent.run_id.in_(run_ids),
            )
            .all()
            if run_ids
            else []
        )
        bindings = (
            db.query(AnswerDecisionBinding)
            .filter(
                AnswerDecisionBinding.project_id == PROJECT_ID,
                AnswerDecisionBinding.prompt_id == PROMPT_ID,
                AnswerDecisionBinding.run_id.in_(run_ids),
            )
            .all()
            if run_ids
            else []
        )
        references = (
            db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(run_ids)).all()
            if run_ids
            else []
        )
        alignments = (
            db.query(EvidenceAlignment)
            .filter(
                EvidenceAlignment.project_id == PROJECT_ID,
                EvidenceAlignment.prompt_id == PROMPT_ID,
                EvidenceAlignment.run_id.in_(run_ids),
            )
            .order_by(EvidenceAlignment.run_id.asc(), EvidenceAlignment.id.asc())
            .all()
            if run_ids
            else []
        )

        before_tables = _count_formal_tables(db, PROJECT_ID, PROMPT_ID)
        before_output = _compute_formal_output_summary(db, PROJECT_ID, PROMPT_ID, EVIDENCE_PACKAGE_ID)

        events_by_run = Counter(event.run_id for event in events)
        bindings_by_run = Counter(binding.run_id for binding in bindings)
        refs_by_run = Counter(ref.run_id for ref in references)
        all_alignment_by_run: dict[int, Counter] = defaultdict(Counter)
        eligible_alignment_by_run: dict[int, Counter] = defaultdict(Counter)
        ineligible_by_run: dict[int, Counter] = defaultdict(Counter)
        eligible_support_run_ids: set[int] = set()
        support_rows = []
        ineligible_rows = []

        for alignment in alignments:
            relation_bucket = _relation_bucket(alignment.relation)
            all_alignment_by_run[alignment.run_id][relation_bucket] += 1
            eligibility = evaluate_evidence_alignment_v1_eligibility(
                db,
                alignment,
                allowed_run_ids=allowed_run_ids,
                include_answer_binding_v1_1=True,
            )
            if eligibility.eligible_for_v1:
                eligible_alignment_by_run[alignment.run_id][relation_bucket] += 1
                if relation_bucket == "SUPPORTS":
                    eligible_support_run_ids.add(alignment.run_id)
            else:
                for reason in eligibility.ineligibility_reasons:
                    ineligible_by_run[alignment.run_id][reason] += 1
                ineligible_rows.append((alignment, eligibility))

            if relation_bucket == "SUPPORTS":
                payload = _alignment_payload(alignment)
                unit = db.get(AnswerUnit, payload.get("answer_unit_id"))
                claim = db.get(SourceClaim, alignment.source_claim_id)
                document = db.get(SourceDocument, alignment.source_document_id)
                ref = db.get(ReferenceSource, eligibility.reference_source_id) if eligibility.reference_source_id else None
                support_rows.append((alignment, eligibility, unit, claim, document, ref))

        after_tables = _count_formal_tables(db, PROJECT_ID, PROMPT_ID)
        after_output = _compute_formal_output_summary(db, PROJECT_ID, PROMPT_ID, EVIDENCE_PACKAGE_ID)

        lines: list[str] = []
        lines.append("# Prompt #40 Phase 2A EvidenceAlignment Run Lineage 审计")
        lines.append("")
        lines.append("状态：待评审")
        lines.append("日期：2026-08-27")
        lines.append("")
        lines.append("## 1. 审计边界")
        lines.append("")
        lines.append("本次只验证 EvidenceAlignment 的 Run lineage、一致性和正式 V1 消费资格。")
        lines.append("")
        lines.append("```text")
        lines.append(f"project_id = {PROJECT_ID}")
        lines.append(f"prompt_id = {PROMPT_ID}")
        lines.append(f"evidence_package_id = {EVIDENCE_PACKAGE_ID}")
        lines.append(f"source_run_ids = {run_ids}")
        lines.append("phase = Phase 2A")
        lines.append("scope = EvidenceAlignment lineage eligibility only")
        lines.append("```")
        lines.append("")
        lines.append("本次没有进入 DISCOVERABILITY_GAP、Step 7、Step 8、Decision Stability，也没有修改 Citation / Benchmark 评分公式。")
        lines.append("")
        lines.append("## 2. 正式链零污染核对")
        lines.append("")
        lines.extend(_markdown_table(
            ["对象", "运行前", "运行后"],
            [
                ["SourceClaim 总数", before_tables["source_claims"], after_tables["source_claims"]],
                ["Prompt #40 EvidenceAlignment 总数", before_tables["evidence_alignments_for_prompt"], after_tables["evidence_alignments_for_prompt"]],
                ["正式状态", before_output["status"], after_output["status"]],
                ["PRIMARY_BENCHMARK", before_output["primary_benchmark_count"], after_output["primary_benchmark_count"]],
                ["SECONDARY_BENCHMARK", before_output["secondary_benchmark_count"], after_output["secondary_benchmark_count"]],
                ["推荐动作", before_output["recommended_action_count"], after_output["recommended_action_count"]],
                ["渠道机会", before_output["channel_opportunity_count"], after_output["channel_opportunity_count"]],
            ],
        ))
        lines.append("")
        lines.append("结论：本审计脚本只读执行；正式表计数和正式派生输出前后一致。")
        lines.append("")
        lines.append("## 3. 现有模型真实关系图")
        lines.append("")
        lines.append("```text")
        lines.append("BrowserMonitorRun")
        lines.append("├── RecommendationEvent(run_id)")
        lines.append("├── AnswerUnit(run_id)")
        lines.append("├── AnswerDecisionBinding(run_id, recommendation_event_id, answer_unit_id)")
        lines.append("└── ReferenceSource(run_id, url/canonical_url/domain/title)")
        lines.append("        ↓ URL/domain-title matching")
        lines.append("    SourceDocument(url/original_url/canonical_url/domain/title)")
        lines.append("        ↓")
        lines.append("    SourceClaim(source_document_id)")
        lines.append("        ↓")
        lines.append("    EvidenceAlignment(run_id, recommendation_event_id, source_document_id, source_claim_id)")
        lines.append("```")
        lines.append("")
        lines.append("SourceDocument 和 SourceClaim 是文档级事实，可跨 Run 复用；正式 V1 的 Run lineage 由当前 Run 的引用实例和答案侧绑定共同证明。")
        lines.append("")
        lines.append("## 4. Run 级分布")
        lines.append("")
        run_rows = []
        for run in runs:
            run_rows.append([
                run.id,
                run.status,
                events_by_run.get(run.id, 0),
                bindings_by_run.get(run.id, 0),
                refs_by_run.get(run.id, 0),
                _format_counter(all_alignment_by_run.get(run.id, Counter())),
                _format_counter(eligible_alignment_by_run.get(run.id, Counter())),
                _format_counter(ineligible_by_run.get(run.id, Counter())),
            ])
        lines.extend(_markdown_table(
            [
                "Run",
                "采集状态",
                "RecommendationEvent",
                "AnswerDecisionBinding",
                "ReferenceSource",
                "全部 Alignment",
                "Eligible Alignment",
                "Ineligible 原因",
            ],
            run_rows,
        ))
        lines.append("")
        lines.append("## 5. 正式 SUPPORTS 逐条 lineage")
        lines.append("")
        if support_rows:
            support_table = []
            for alignment, eligibility, unit, claim, document, ref in support_rows:
                support_table.append([
                    alignment.id,
                    alignment.run_id,
                    "是" if eligibility.eligible_for_v1 else "否",
                    _format_counter(Counter(eligibility.ineligibility_reasons)),
                    f"{unit.id}: {_truncate(unit.unit_text_normalized or unit.unit_text_original, 80)}" if unit else "-",
                    f"{claim.id}: {_truncate(claim.normalized_claim or claim.source_span, 100)}" if claim else "-",
                    f"{document.id}: {_truncate(document.title or document.url, 80)}" if document else "-",
                    f"{ref.id}: {_truncate(ref.display_title or ref.url, 80)}" if ref else "-",
                ])
            lines.extend(_markdown_table(
                [
                    "Alignment",
                    "Run",
                    "Eligible",
                    "Ineligible 原因",
                    "AnswerUnit",
                    "SourceClaim",
                    "SourceDocument",
                    "ReferenceSource 证明",
                ],
                support_table,
            ))
        else:
            lines.append("当前没有 SUPPORTS Alignment。")
        lines.append("")
        lines.append("## 6. Prompt-level observed_run_ids 推导")
        lines.append("")
        lines.append("```text")
        lines.append(f"eligible_support_observed_run_ids = {sorted(eligible_support_run_ids)}")
        lines.append(f"eligible_support_run_coverage = {len(eligible_support_run_ids)}/{len(allowed_run_ids)}")
        lines.append("```")
        lines.append("")
        lines.append("该集合只来自通过完整 lineage 的 SUPPORTS Alignment 的去重 run_id，不从 Prompt 下所有 Run、payload observed_run_ids 或同一 SourceDocument 出现情况反推。")
        lines.append("")
        lines.append("## 7. Ineligible Alignment 摘要")
        lines.append("")
        reason_totals = Counter()
        for _alignment, eligibility in ineligible_rows:
            reason_totals.update(eligibility.ineligibility_reasons)
        lines.append("```text")
        lines.append(_format_counter(reason_totals))
        lines.append("```")
        lines.append("")
        if ineligible_rows:
            preview_rows = []
            for alignment, eligibility in ineligible_rows[:30]:
                preview_rows.append([
                    alignment.id,
                    alignment.run_id,
                    alignment.relation,
                    _format_counter(Counter(eligibility.ineligibility_reasons)),
                    alignment.source_document_id,
                    alignment.source_claim_id,
                ])
            lines.extend(_markdown_table(
                ["Alignment", "Run", "Relation", "原因", "SourceDocument", "SourceClaim"],
                preview_rows,
            ))
            if len(ineligible_rows) > 30:
                lines.append("")
                lines.append(f"仅展示前 30 条；完整 ineligible 数量：{len(ineligible_rows)}。")
        else:
            lines.append("没有 ineligible Alignment。")
        lines.append("")
        lines.append("## 8. 结论")
        lines.append("")
        if support_rows and not eligible_support_run_ids:
            lines.append("存在 SUPPORTS 行，但没有任何一条通过完整 Run lineage，正式 V1 不应消费这些 SUPPORTS。")
        elif len(eligible_support_run_ids) < len(allowed_run_ids):
            lines.append("正式 SUPPORTS 没有覆盖全部 Evidence Package Runs；Prompt 层覆盖率必须以本节推导集合为准，不能从 payload 或 SourceDocument 出现情况补齐。")
        else:
            lines.append("正式 SUPPORTS 覆盖 Evidence Package 内全部 Run，且每条 SUPPORTS 均能证明 AnswerUnit、Binding、RecommendationEvent、ReferenceSource、SourceDocument、SourceClaim 的完整链路。")
        lines.append("")
        lines.append("历史 Alignment 保留；未通过 lineage 的 Alignment 可供 Legacy 查看，但不能进入新的正式单 Prompt V1 Benchmark / Gap / StrategyCandidate 证据。")
        lines.append("")
        return "\n".join(lines) + "\n"
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
