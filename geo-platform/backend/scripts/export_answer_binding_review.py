from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal, init_db
from app.models import (
    AnswerClaim,
    AnswerDecisionBinding,
    AnswerEvidenceShadowResult,
    AnswerEvidenceShadowRun,
    AnswerUnit,
    RecommendationEvent,
)
from app.services.serialization import loads


def _clean(text: str) -> str:
    return " ".join((text or "").replace("\u200c", "").split())


def _clip(text: str, length: int = 80) -> str:
    text = _clean(text)
    if len(text) <= length:
        return text
    return text[: length - 1] + "..."


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shadow-run-id", type=int, required=True)
    parser.add_argument("--max-rows", type=int, default=200)
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        shadow_run = db.get(AnswerEvidenceShadowRun, args.shadow_run_id)
        if not shadow_run:
            raise SystemExit(f"ShadowRun #{args.shadow_run_id} 不存在")

        bindings = (
            db.query(AnswerDecisionBinding)
            .filter(
                AnswerDecisionBinding.shadow_run_id == args.shadow_run_id,
                AnswerDecisionBinding.decision_role.in_(["DIRECT_REASON", "SUPPORTING_REASON", "COUNTER_REASON"]),
            )
            .order_by(AnswerDecisionBinding.run_id, AnswerDecisionBinding.id)
            .all()
        )
        units = {
            row.id: row
            for row in db.query(AnswerUnit)
            .filter(AnswerUnit.id.in_([binding.answer_unit_id for binding in bindings]))
            .all()
        }
        events = {
            row.id: row
            for row in db.query(RecommendationEvent)
            .filter(RecommendationEvent.id.in_([binding.recommendation_event_id for binding in bindings]))
            .all()
        }
        claims = {
            row.id: row
            for row in db.query(AnswerClaim)
            .filter(AnswerClaim.id.in_([unit.answer_claim_id for unit in units.values()]))
            .all()
        }
        results = (
            db.query(AnswerEvidenceShadowResult)
            .filter(AnswerEvidenceShadowResult.shadow_run_id == args.shadow_run_id)
            .all()
        )
        by_binding: dict[int, list[AnswerEvidenceShadowResult]] = defaultdict(list)
        for result in results:
            by_binding[result.decision_binding_id].append(result)

        support_by_unit: dict[str, Counter] = defaultdict(Counter)
        binding_by_unit: dict[str, Counter] = defaultdict(Counter)
        evidence_role_by_unit: dict[str, Counter] = defaultdict(Counter)
        for binding in bindings:
            unit = units.get(binding.answer_unit_id)
            if not unit:
                continue
            unit_text = _clean(unit.unit_text_normalized)
            binding_by_unit[unit_text][binding.run_id] += 1
            for result in by_binding.get(binding.id, []):
                if result.alignment_relation == "SUPPORTS":
                    support_by_unit[unit_text][binding.run_id] += 1
                    evidence_role_by_unit[unit_text][result.evidence_classification] += 1

        summary = loads(shadow_run.summary_json, {})
        print(f"# ShadowRun #{shadow_run.id} AnswerDecisionBinding 人工审计表")
        print()
        print("## 基本信息")
        print()
        print(f"- 项目：{shadow_run.project_id}")
        print(f"- 问题：{shadow_run.prompt_id}")
        print(f"- 证据包：{shadow_run.evidence_package_id}")
        print(f"- Run 集合：{loads(shadow_run.source_run_ids_json, [])}")
        print(f"- 状态：{shadow_run.status}")
        print(f"- 正式链影响：{shadow_run.formal_output_impact}")
        print(f"- 实体过滤：{summary.get('entity_filter') or 'ALL'}")
        print()
        print("## 5 个能力单元稳定矩阵")
        print()
        print("| AnswerUnit | Binding 覆盖 | SUPPORTS 覆盖 | Evidence Role |")
        print("| --- | ---: | ---: | --- |")
        run_count = len(loads(shadow_run.source_run_ids_json, [])) or 1
        for unit_text in sorted(binding_by_unit):
            binding_runs = len(binding_by_unit[unit_text])
            support_runs = len(support_by_unit.get(unit_text, {}))
            roles = ", ".join(f"{key} x{value}" for key, value in evidence_role_by_unit.get(unit_text, Counter()).most_common()) or "-"
            print(f"| {unit_text} | {binding_runs}/{run_count} | {support_runs}/{run_count} | {roles} |")
        print()
        print("## 30 条 Binding 人审清单")
        print()
        print("| # | Run | 实体 | AnswerUnit | 机器角色 | 说明作用域 | 支撑数 | 代表来源主张 | 人审结论 | 备注 |")
        print("| ---: | ---: | --- | --- | --- | --- | ---: | --- | --- | --- |")
        for index, binding in enumerate(bindings[: args.max_rows], start=1):
            event = events.get(binding.recommendation_event_id)
            unit = units.get(binding.answer_unit_id)
            claim = claims.get(unit.answer_claim_id) if unit else None
            support_results = [row for row in by_binding.get(binding.id, []) if row.alignment_relation == "SUPPORTS"]
            representative = support_results[0].source_claim_text if support_results else ""
            role = f"{binding.decision_role}/{binding.binding_strength}"
            entity = event.entity_text if event else ""
            answer_unit = unit.unit_text_normalized if unit else ""
            note = f"AnswerClaim #{claim.id}" if claim else ""
            scope = f"{binding.scope_type or '-'}: {binding.scope_reason or '-'}"
            print(
                f"| {index} | {binding.run_id} | {_clean(entity)} | {_clip(answer_unit, 60)} | "
                f"{role} | {_clip(scope, 70)} | {len(support_results)} | {_clip(representative, 80)} | "
                f"待人工审计 | {note} |"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
