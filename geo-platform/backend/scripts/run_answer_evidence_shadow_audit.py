from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal, init_db
from app.models import (
    AnswerClaim,
    AnswerDecisionBinding,
    AnswerEvidenceShadowResult,
    AnswerUnit,
    EvidenceAlignment,
    Project,
    RecommendationEvent,
    SourceClaim,
)
from app.modules.optimization.answer_evidence_shadow import run_answer_evidence_shadow_chain
from app.modules.optimization.service import citation_decision_vertical_slice
from app.services.serialization import loads


def _clip(text: str, length: int = 160) -> str:
    text = " ".join((text or "").split())
    if len(text) <= length:
        return text
    return text[: length - 1] + "..."


def _formal_counts(db, project_id: int, prompt_id: int, package_id: int | None) -> dict:
    source_claims = db.query(SourceClaim).filter(SourceClaim.project_id == project_id).count()
    alignments = db.query(EvidenceAlignment).filter(EvidenceAlignment.project_id == project_id, EvidenceAlignment.prompt_id == prompt_id).count()
    citation = citation_decision_vertical_slice(db, project_id, prompt_id, package_id)
    summary = citation.get("summary") or {}
    return {
        "source_claims": source_claims,
        "evidence_alignments": alignments,
        "primary_benchmark_count": summary.get("primary_benchmark_count", 0),
        "secondary_benchmark_count": summary.get("secondary_benchmark_count", 0),
        "recommended_action_count": summary.get("recommended_action_count", 0),
        "channel_opportunity_count": summary.get("channel_opportunity_count", 0),
        "citation_status": citation.get("status", ""),
    }


def _print_formal_diff(before: dict, after: dict) -> None:
    print("## 正式 V1 零污染对比")
    for key in [
        "source_claims",
        "evidence_alignments",
        "primary_benchmark_count",
        "secondary_benchmark_count",
        "recommended_action_count",
        "channel_opportunity_count",
        "citation_status",
    ]:
        print(f"- {key}: {before.get(key)} -> {after.get(key)}")
    changed = {key: (before.get(key), after.get(key)) for key in before if before.get(key) != after.get(key)}
    print(f"- formal_output_impact: {'CHANGED' if changed else 'NONE'}")
    if changed:
        print(f"- changed_fields: {changed}")


def _print_shadow_chain(db, shadow_run_id: int, max_items: int = 80) -> None:
    print("\n## Shadow 逐级结果")
    units = db.query(AnswerUnit).filter(AnswerUnit.shadow_run_id == shadow_run_id).order_by(AnswerUnit.run_id, AnswerUnit.unit_index, AnswerUnit.id).all()
    bindings = db.query(AnswerDecisionBinding).filter(AnswerDecisionBinding.shadow_run_id == shadow_run_id).order_by(AnswerDecisionBinding.run_id, AnswerDecisionBinding.id).all()
    results = db.query(AnswerEvidenceShadowResult).filter(AnswerEvidenceShadowResult.shadow_run_id == shadow_run_id).order_by(AnswerEvidenceShadowResult.run_id, AnswerEvidenceShadowResult.id).all()
    claims = {
        claim.id: claim
        for claim in db.query(AnswerClaim).filter(AnswerClaim.id.in_([unit.answer_claim_id for unit in units])).all()
    } if units else {}
    events = {
        event.id: event
        for event in db.query(RecommendationEvent).filter(RecommendationEvent.id.in_([binding.recommendation_event_id for binding in bindings])).all()
    } if bindings else {}

    bindings_by_unit: dict[int, list[AnswerDecisionBinding]] = defaultdict(list)
    for binding in bindings:
        bindings_by_unit[binding.answer_unit_id].append(binding)
    results_by_binding: dict[int, list[AnswerEvidenceShadowResult]] = defaultdict(list)
    for result in results:
        results_by_binding[result.decision_binding_id].append(result)

    printed = 0
    for unit in units:
        related_bindings = bindings_by_unit.get(unit.id, [])
        if not related_bindings:
            continue
        claim = claims.get(unit.answer_claim_id)
        print(f"\n### Run #{unit.run_id} / AnswerClaim #{unit.answer_claim_id} / AnswerUnit #{unit.id}")
        print(f"- AnswerClaim: {_clip(claim.raw_text if claim else '')}")
        print(f"- AnswerUnit: {_clip(unit.unit_text_normalized)}")
        print(f"- grounding: status={unit.review_status}, raw_start={unit.raw_start}, raw_end={unit.raw_end}, source_span={_clip(unit.source_span, 80)}")
        for binding in related_bindings:
            event = events.get(binding.recommendation_event_id)
            print(f"- Binding #{binding.id}: entity={event.entity_text if event else ''}, speech_act={event.speech_act if event else ''}, role={binding.decision_role}, strength={binding.binding_strength}, method={binding.binding_method}")
            print(f"  - event_span: {_clip(event.answer_span if event else '')}")
            for result in results_by_binding.get(binding.id, []):
                print(f"  - Retrieved Passage: doc#{result.source_document_id}, ref#{result.reference_source_id}, passage={result.passage_id}, bm25={result.retrieval_score}")
                print(f"    - passage_text: {_clip(result.passage_text)}")
                print(f"    - Shadow SourceClaim: status={result.source_claim_review_status}, subject={result.source_claim_subject}, claim={_clip(result.source_claim_text)}")
                print(f"    - Shadow EvidenceAlignment: relation={result.alignment_relation}, class={result.evidence_classification}, impact={result.formal_output_impact}")
        printed += 1
        if printed >= max_items:
            remaining = len([unit for unit in units if bindings_by_unit.get(unit.id)]) - printed
            if remaining > 0:
                print(f"\n... 已截断，还有 {remaining} 个绑定 AnswerUnit 未打印。")
            break


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", type=int, default=3)
    parser.add_argument("--prompt-id", type=int, default=40)
    parser.add_argument("--package-id", type=int, default=15)
    parser.add_argument("--run-ids", default="238,239,240,253,254,255")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--max-items", type=int, default=80)
    parser.add_argument("--rule-binding-only", action="store_true")
    parser.add_argument("--entity-filter", default="")
    parser.add_argument("--max-bindings", type=int, default=0)
    parser.add_argument("--include-procedural-context", action="store_true")
    parser.add_argument("--include-unbound-answer-units", action="store_true")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        project = db.get(Project, args.project_id)
        if not project:
            raise SystemExit(f"Project #{args.project_id} 不存在")
        run_ids = [int(part.strip()) for part in args.run_ids.split(",") if part.strip()]
        before = _formal_counts(db, args.project_id, args.prompt_id, args.package_id)
        print("# Prompt #40 V1.1 Shadow Evidence Chain 审计")
        print(f"\n- project_id: {args.project_id}")
        print(f"- prompt_id: {args.prompt_id}")
        print(f"- evidence_package_id: {args.package_id}")
        print(f"- source_run_ids: {run_ids}")
        print(f"- use_llm_binding: {not args.rule_binding_only}")
        print(f"- entity_filter: {args.entity_filter.strip() or 'ALL'}")
        print(f"- max_bindings: {args.max_bindings or 'unlimited'}")
        print(f"- include_procedural_context: {args.include_procedural_context}")
        print(f"- include_unbound_answer_units: {args.include_unbound_answer_units}")
        print(f"- top_k: {args.top_k}")
        print("\n## 运行前正式 V1 基线")
        for key, value in before.items():
            print(f"- {key}: {value}")

        shadow = run_answer_evidence_shadow_chain(
            db,
            args.project_id,
            args.prompt_id,
            evidence_package_id=args.package_id,
            run_ids=run_ids,
            top_k=args.top_k,
            use_llm_binding=not args.rule_binding_only,
            entity_filter=args.entity_filter.strip() or None,
            max_bindings=args.max_bindings or None,
            include_procedural_context=args.include_procedural_context,
            include_unbound_answer_units=args.include_unbound_answer_units,
        )
        print("\n## Shadow Run 汇总")
        print(f"- shadow_run_id: {shadow['id']}")
        print(f"- status: {shadow['status']}")
        print(f"- formal_output_impact: {shadow['formal_output_impact']}")
        for key, value in (shadow.get("summary") or {}).items():
            print(f"- {key}: {value}")

        _print_shadow_chain(db, shadow["id"], args.max_items)

        after = _formal_counts(db, args.project_id, args.prompt_id, args.package_id)
        print()
        _print_formal_diff(before, after)
    finally:
        db.close()


if __name__ == "__main__":
    main()
