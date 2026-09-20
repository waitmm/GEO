"""PR4-A.1 read-only, deterministic-first Strategy Synthesis shadow.

The strategy candidate and channel resolver remain the fact/eligibility layer.
This module computes all unambiguous structure deterministically. An LLM may
only resolve one explicit, bounded ambiguity and never writes workflow state.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import itertools
import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    AnswerUnit,
    BrowserMonitorRun,
    OptimizationAction,
    OptimizationEvidencePackage,
    OptimizationExperiment,
    OptimizationStrategyCandidate,
    Project,
    Prompt,
    TargetBrandCapabilityTruth,
)
from app.modules.optimization.service import (
    CURRENT_STEP7_CANDIDATE_ORIGIN,
    _resolve_vertical_slice_package,
    infer_strategy_candidate_origin,
)
from app.services.semantic_llm.base import SemanticLLMError
from app.services.semantic_llm.deepseek import DeepSeekClient
from app.services.serialization import loads


CONTRACT_VERSION = "strategy_synthesis.v1.1"
STRUCTURAL_PROMPT_VERSION = "strategy_bounded_ambiguity.v1"
PRESENTATION_PROMPT_VERSION = "strategy_presentation.v1"
STRUCTURAL_SCHEMA_VERSION = "strategy_bounded_ambiguity.schema.v1"
PRESENTATION_SCHEMA_VERSION = "strategy_presentation.schema.v1"
VALID_EXECUTION_PRIORITIES = {"P1", "P2"}
VALID_CHANNEL_ROLES = {"PRIMARY", "SECONDARY", "TEST", "OBSERVE"}
CAUSAL_PATTERNS = (
    "一定",
    "必然",
    "显著改善",
    "显著提升",
    "最有效",
    "最优",
    "最佳",
    "保证",
    "必定",
    "能够提升",
    "会提升",
    "将提升",
    "导致",
)
UNSUPPORTED_FACT_PATTERNS = (
    "永久防封",
    "白名单",
    "官方认证",
    "已有白皮书",
    "现有白皮书",
    "已有官网专题页",
    "现有官网专题页",
)
ALLOWED_EVIDENCE_LANGUAGE = (
    "值得验证",
    "当前观察到",
    "存在机会",
    "用于测试",
    "验证是否",
    "当前证据支持",
    "已有观察表明",
)
ALLOWED_TRANSFORMATIONS = ["GROUP", "SELECT", "PRIORITIZE", "SUMMARIZE", "VERBALIZE"]
FORBIDDEN_TRANSFORMATIONS = [
    "CREATE_FACT",
    "CREATE_PRODUCT_CAPABILITY",
    "CREATE_DECISION_REASON",
    "CREATE_PRODUCT_TRUTH",
    "CREATE_CHANNEL",
    "CREATE_ASSET",
    "CREATE_URL",
    "CREATE_CITATION",
    "CHANGE_CHANNEL_ROLE",
    "CHANGE_PRODUCT_TRUTH",
    "CHANGE_EVIDENCE_VERDICT",
    "CHANGE_BENCHMARK_ELIGIBILITY",
    "CHANGE_RUN_COVERAGE",
    "INFER_CAUSALITY",
    "UPGRADE_OBSERVE_TO_TEST",
    "UPGRADE_TEST_TO_PRIMARY",
]
TARGET_OUTCOME = "CANDIDATE_CITATION_OR_RECOMMENDATION_REASON_PRESENCE"


def _stable_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _unique(values: list[Any]) -> list[Any]:
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _normalized_text(value: str) -> str:
    return re.sub(r"[\s\u200c\u200d\ufeff]+", "", str(value or "")).strip()


def _scenario_tags(text: str) -> list[str]:
    normalized = _normalized_text(text)
    tags = []
    for token, tag in (
        ("抖音", "DOUYIN"),
        ("微信", "WECHAT"),
        ("投放", "PAID_MARKETING"),
        ("营销", "MARKETING"),
        ("巨量", "PAID_MARKETING"),
        ("外链", "EXTERNAL_LINK"),
        ("短链", "SHORT_LINK"),
        ("分享", "SHARING"),
        ("统计", "MEASUREMENT"),
        ("回传", "MEASUREMENT"),
    ):
        if token in normalized:
            tags.append(tag)
    return _unique(tags) or ["GENERAL"]


def _mechanism_tags(text: str, gap_type: str) -> list[str]:
    normalized = _normalized_text(text)
    tags = []
    if any(token in normalized for token in ("短链", "链接", "跳转")):
        tags.append("LINK_EXPRESSION")
    if any(token in normalized for token in ("统计", "回传", "效果", "投放")):
        tags.append("MEASUREMENT_EXPRESSION")
    if any(token in normalized for token in ("合规", "备案", "风控", "限制")):
        tags.append("COMPLIANCE_EXPRESSION")
    if str(gap_type or "").upper() == "CONTENT_GAP":
        tags.append("CONTENT_EXPRESSION")
    elif str(gap_type or "").upper() == "EVIDENCE_GAP":
        tags.append("EVIDENCE_EXPRESSION")
    return _unique(tags) or ["UNSPECIFIED_MECHANISM"]


def _qualifiers(text: str) -> list[str]:
    normalized = _normalized_text(text)
    values = [token for token in ("自动", "一键", "加密", "合规", "备案", "第三方") if token in normalized]
    values.extend(re.findall(r"\d+(?:\.\d+)?(?:天|%|个|次)?", normalized))
    return _unique(values)


def _asset_constraint(gap_item: dict) -> str:
    snapshot = gap_item.get("relevant_asset_snapshot") or {}
    if snapshot.get("status") == "AVAILABLE" or snapshot.get("snapshot_id"):
        return "EXISTING_RELEVANT_ASSET"
    if str(gap_item.get("gap_type") or "").upper() == "EVIDENCE_GAP":
        return "AUTHORITATIVE_EVIDENCE_ASSET"
    return "UNRESOLVED_ASSET_CLASS"


def _scenario_compatible(left: dict, right: dict) -> bool:
    left_tags = set(left["scenario"])
    right_tags = set(right["scenario"])
    if "GENERAL" in left_tags or "GENERAL" in right_tags:
        return True
    return bool(left_tags & right_tags)


def _reason_pair_constraint(left: dict, right: dict) -> dict:
    shared_truth = sorted(set(left["product_truth_ids"]) & set(right["product_truth_ids"]))
    family_compatible = bool(
        left["capability_family"] == right["capability_family"]
        or shared_truth
    )
    shared_mechanisms = sorted(set(left["intervention_mechanisms"]) & set(right["intervention_mechanisms"]))
    meaningful_shared_mechanisms = [
        value for value in shared_mechanisms if value not in {"EVIDENCE_EXPRESSION", "CONTENT_EXPRESSION"}
    ]
    mechanism_compatible = bool(meaningful_shared_mechanisms) or (
        left["capability_family"] == right["capability_family"]
        and bool(shared_mechanisms)
    )
    scenario_compatible = _scenario_compatible(left, right)
    asset_compatible = left["required_asset_type"] == right["required_asset_type"]
    allowed = family_compatible and mechanism_compatible and scenario_compatible and asset_compatible
    blockers = []
    if not family_compatible:
        blockers.append("CAPABILITY_FAMILY_INCOMPATIBLE")
    if not mechanism_compatible:
        blockers.append("INTERVENTION_MECHANISM_INCOMPATIBLE")
    if not scenario_compatible:
        blockers.append("SCENARIO_INCOMPATIBLE")
    if not asset_compatible:
        blockers.append("REQUIRED_ASSET_TYPE_INCOMPATIBLE")
    return {
        "reason_ids": [left["reason_id"], right["reason_id"]],
        "allowed": allowed,
        "shared_product_truth_ids": shared_truth,
        "shared_intervention_mechanisms": shared_mechanisms,
        "checks": {
            "capability_family_compatible": family_compatible,
            "scenario_compatible": scenario_compatible,
            "intervention_mechanism_compatible": mechanism_compatible,
            "required_asset_type_compatible": asset_compatible,
        },
        "decision": "ALLOW_MERGE" if allowed else "KEEP_SEPARATE",
        "reason": "COMPATIBILITY_CONSTRAINTS_PASSED" if allowed else blockers[0],
        "blockers": blockers,
    }


def _reason_id(gap_item: dict) -> str:
    if gap_item.get("decision_reason_id"):
        return str(gap_item["decision_reason_id"])
    if gap_item.get("answer_unit_id"):
        return f"answer_unit:{int(gap_item['answer_unit_id'])}"
    return f"gap_item:{gap_item.get('gap_item_id')}"


def _channel_object_id(input_scope_id: str | int, channel_key: str) -> str:
    return f"channel_resolution:{input_scope_id}:{channel_key}"


def _candidate_channels(payload: dict, input_scope_id: str | int) -> list[dict]:
    raw_channels = payload.get("channels") or payload.get("planned_channels") or []
    by_key: dict[str, dict] = {}
    for raw in raw_channels:
        key = str(raw.get("channel_key") or raw.get("channel") or "").upper()
        role = str(raw.get("role") or raw.get("intervention_priority") or "").upper()
        if not key or role not in VALID_CHANNEL_ROLES:
            continue
        existing = by_key.get(key)
        if existing and existing.get("role") != "OBSERVE":
            continue
        reason_ids = [str(value) for value in raw.get("decision_reason_ids") or [] if value]
        signal_ids = [str(value) for value in raw.get("supporting_signal_ids") or [] if value]
        relevance = raw.get("reason_relevance") or {}
        reason_results = relevance.get("reason_results") or []
        if not reason_ids:
            reason_ids = _unique([
                str(item.get("reason_id"))
                for item in reason_results
                if item.get("reason_id") and item.get("state") == "PASS"
            ])
        test_hypothesis = raw.get("test_hypothesis") or {}
        exposure = raw.get("exposure_signals") or {}
        target_gap = raw.get("target_gap") or {}
        intervention_fit = raw.get("intervention_fit") or {}
        measurability = "HIGH" if test_hypothesis.get("success_metric") and test_hypothesis.get("observation_window") else "UNKNOWN"
        information_value = (
            "HIGH"
            if role == "TEST"
            and exposure.get("state") == "PASS"
            and target_gap.get("state") == "PASS"
            and intervention_fit.get("state") == "PASS"
            and measurability == "HIGH"
            and bool(reason_ids)
            else "UNKNOWN"
        )
        by_key[key] = {
            "object_id": _channel_object_id(input_scope_id, key),
            "channel_key": key,
            "channel_label": raw.get("channel_label") or key,
            "role": role,
            "rationale_path": raw.get("rationale_path") or "UNRESOLVED",
            "decision_reason_ids": reason_ids,
            "supporting_signal_ids": signal_ids,
            "exposure": exposure.get("state") or "UNKNOWN",
            "reason_coverage_count": len(reason_ids),
            "target_brand_gap": target_gap.get("state") or "UNKNOWN",
            "intervention_fit": intervention_fit.get("state") or "UNKNOWN",
            "measurability": measurability,
            "information_value": information_value,
            "test_metric": test_hypothesis.get("success_metric"),
            "resolver_rationale": raw.get("why_primary") or raw.get("why_test") or raw.get("why_not_primary") or raw.get("selection_basis") or "",
            "supported_reason_texts": [str(value) for value in raw.get("supported_reasons") or [] if value],
            "gap_item_ids": [str(value) for value in (raw.get("gap_basis") or {}).get("gap_item_ids") or [] if value],
        }
    return sorted(by_key.values(), key=lambda item: (item["role"], item["channel_key"]))


def _gap_items(payload: dict) -> list[dict]:
    items = (payload.get("evidence_summary") or {}).get("gap_items") or payload.get("target_capabilities") or []
    return [item for item in items if isinstance(item, dict) and item.get("gap_item_id")]


def _build_reason_objects(db: Session, payload: dict) -> list[dict]:
    items = _gap_items(payload)
    answer_unit_ids = sorted({int(item["answer_unit_id"]) for item in items if item.get("answer_unit_id")})
    answer_units = {
        int(row.id): row
        for row in db.query(AnswerUnit).filter(AnswerUnit.id.in_(answer_unit_ids)).all()
    } if answer_unit_ids else {}
    reasons = []
    for item in items:
        unit = answer_units.get(int(item.get("answer_unit_id") or 0))
        original_reason = str(
            item.get("answer_decision_reason")
            or (unit.unit_text_original if unit else "")
            or item.get("capability_label")
            or ""
        ).strip()
        normalized = str(
            (unit.unit_text_normalized if unit else "")
            or item.get("capability_label")
            or original_reason
        ).strip()
        family = str(item.get("capability_label") or normalized or original_reason).strip()
        reasons.append({
            "reason_id": _reason_id(item),
            "original_reason": original_reason,
            "normalized_proposition": normalized,
            "capability_family": family,
            "scenario": _scenario_tags(original_reason),
            "qualifier": _qualifiers(original_reason),
            "intervention_mechanisms": _mechanism_tags(original_reason, item.get("gap_type") or payload.get("gap_type") or ""),
            "required_asset_type": _asset_constraint(item),
            "observed_run_ids": sorted({int(value) for value in item.get("observed_run_ids") or [] if value}),
            "product_truth_ids": sorted({int(value) for value in item.get("product_truth_ids") or [] if value}),
            "gap_item_ids": [str(item["gap_item_id"])],
            "gap_type": item.get("gap_type") or payload.get("gap_type") or "UNKNOWN",
            "gap_layer": item.get("gap_layer") or "UNKNOWN",
            "benchmark_tier": item.get("benchmark_tier") or "UNKNOWN",
            "benchmark_source_document_ids": sorted({
                int(value)
                for value in [item.get("source_document_id"), (item.get("benchmark_source") or {}).get("source_document_id")]
                if value
            }),
        })
    return reasons


def _eligible_metrics(package: OptimizationEvidencePackage) -> list[dict]:
    package_payload = loads(package.package_payload_json, {})
    result = []
    for row in package_payload.get("metrics") or []:
        key = str(row.get("metric_name") or "")
        if not key or row.get("calculation_status") != "ok":
            continue
        result.append({
            "object_id": f"metric:{key}",
            "metric_key": key,
            "calculation_status": "ok",
            "numerator": row.get("numerator"),
            "denominator": row.get("denominator"),
            "value": row.get("value"),
        })
    return result


def _build_constraints(reasons: list[dict], channels: list[dict]) -> dict:
    pair_rows = [_reason_pair_constraint(left, right) for left, right in itertools.combinations(reasons, 2)]
    test_channels = [item for item in channels if item["role"] == "TEST"]
    max_reason_coverage = max((item["reason_coverage_count"] for item in test_channels), default=0)
    test_priority_eligibility = []
    for channel in test_channels:
        gates = {
            "exposure": channel["exposure"] == "PASS",
            "decision_reason_coverage": channel["reason_coverage_count"] == max_reason_coverage and max_reason_coverage > 0,
            "target_brand_gap": channel["target_brand_gap"] == "PASS",
            "intervention_fit": channel["intervention_fit"] == "PASS",
            "measurability": channel["measurability"] == "HIGH",
            "information_value": channel["information_value"] == "HIGH",
        }
        test_priority_eligibility.append({
            "channel_key": channel["channel_key"],
            "eligible_for_p1": all(gates.values()),
            "gates": gates,
            "decision": "TEST_P1_ELIGIBLE" if all(gates.values()) else "TEST_P2_OR_DEFERRED",
        })
    return {
        "reason_compatibility_graph": pair_rows,
        "allowed_merge_pairs": [row["reason_ids"] for row in pair_rows if row["allowed"]],
        "keep_separate_pairs": [row for row in pair_rows if not row["allowed"]],
        "test_priority_method": "AUDITABLE_GATE_NO_WEIGHTED_SCORE",
        "test_priority_eligibility": test_priority_eligibility,
        "priority_test_budget": 2,
    }


def _bind_legacy_channel_reasons(reasons: list[dict], channels: list[dict]) -> None:
    """Recover stable reason IDs only when an older resolver payload omitted them."""
    for channel in channels:
        if channel["decision_reason_ids"]:
            continue
        matched = []
        supported_texts = [_normalized_text(value) for value in channel.get("supported_reason_texts") or []]
        gap_item_ids = set(channel.get("gap_item_ids") or [])
        for reason in reasons:
            reason_texts = {
                _normalized_text(reason["original_reason"]),
                _normalized_text(reason["normalized_proposition"]),
                _normalized_text(reason["capability_family"]),
            }
            text_match = any(
                left and right and (left in right or right in left)
                for left in supported_texts
                for right in reason_texts
            )
            gap_match = bool(gap_item_ids & set(reason["gap_item_ids"]))
            if text_match or gap_match:
                matched.append(reason["reason_id"])
        channel["decision_reason_ids"] = _unique(matched)
        channel["reason_coverage_count"] = len(channel["decision_reason_ids"])


def _greedy_theme_groups(reason_ids: list[str], allowed_pairs: list[list[str]]) -> list[list[str]]:
    allowed = {tuple(sorted(pair)) for pair in allowed_pairs}
    groups: list[list[str]] = []
    for reason_id in reason_ids:
        placed = False
        for group in groups:
            if all(tuple(sorted((reason_id, other))) in allowed for other in group):
                group.append(reason_id)
                placed = True
                break
        if not placed:
            groups.append([reason_id])
    return groups


def _minimum_clique_partitions(
    reason_ids: list[str],
    allowed_pairs: list[list[str]],
    *,
    max_reason_count: int = 8,
) -> tuple[list[list[list[str]]], bool]:
    """Return all minimum-group clique partitions for small shadow inputs."""
    if len(reason_ids) > max_reason_count:
        return [_greedy_theme_groups(reason_ids, allowed_pairs)], True
    allowed = {tuple(sorted(pair)) for pair in allowed_pairs}
    partitions: list[list[list[str]]] = []

    def visit(index: int, groups: list[list[str]]) -> None:
        if index == len(reason_ids):
            partitions.append(deepcopy(groups))
            return
        reason_id = reason_ids[index]
        for group_index, group in enumerate(groups):
            if all(tuple(sorted((reason_id, other))) in allowed for other in group):
                groups[group_index].append(reason_id)
                visit(index + 1, groups)
                groups[group_index].pop()
        groups.append([reason_id])
        visit(index + 1, groups)
        groups.pop()

    visit(0, [])
    minimum = min((len(item) for item in partitions), default=0)
    unique: dict[str, list[list[str]]] = {}
    for partition in partitions:
        if len(partition) != minimum:
            continue
        normalized = sorted((sorted(group) for group in partition), key=lambda group: tuple(group))
        unique[_stable_hash(normalized)] = normalized
    return list(unique.values()), False


def detect_synthesis_ambiguities(context: dict) -> list[dict]:
    reason_ids = [item["reason_id"] for item in context["decision_reasons"]]
    partitions, enumeration_limited = _minimum_clique_partitions(
        reason_ids,
        context["constraints"]["allowed_merge_pairs"],
    )
    ambiguities = []
    if enumeration_limited or len(partitions) > 1:
        ambiguities.append({
            "ambiguity_type": "AMBIGUOUS_THEME_GROUPING",
            "reason_ids": reason_ids,
            "allowed_partition_options": partitions if not enumeration_limited else [],
            "fallback": "NEEDS_HUMAN_THEME_GROUPING",
            "enumeration_limited": enumeration_limited,
        })
    eligible_tests = [
        row["channel_key"]
        for row in context["constraints"]["test_priority_eligibility"]
        if row["eligible_for_p1"]
    ]
    budget = int(context["constraints"]["priority_test_budget"])
    if len(eligible_tests) > budget:
        ambiguities.append({
            "ambiguity_type": "AMBIGUOUS_TEST_PRIORITY",
            "channel_keys": eligible_tests,
            "priority_test_budget": budget,
            "fallback": "NEEDS_HUMAN_TEST_PRIORITY",
        })
    return ambiguities


def _themes_for_groups(context: dict, groups: list[list[str]]) -> list[dict]:
    reason_by_id = {item["reason_id"]: item for item in context["decision_reasons"]}
    coverage_by_group = [
        len({run_id for reason_id in group for run_id in reason_by_id[reason_id]["observed_run_ids"]})
        for group in groups
    ]
    max_coverage = max(coverage_by_group, default=0)
    return [
        {
            "theme_key": f"T{index + 1}",
            "reason_ids": group,
            "priority": "P1" if coverage == max_coverage else "P2",
        }
        for index, (group, coverage) in enumerate(zip(groups, coverage_by_group))
    ]


def _deterministic_structural_proposal(context: dict) -> dict:
    reason_ids = [item["reason_id"] for item in context["decision_reasons"]]
    groups = _greedy_theme_groups(reason_ids, context["constraints"]["allowed_merge_pairs"])
    themes = _themes_for_groups(context, groups)
    channels = context["channel_resolutions"]
    p1_eligible = [
        row["channel_key"]
        for row in context["constraints"]["test_priority_eligibility"]
        if row["eligible_for_p1"]
    ]
    needs_human = len(p1_eligible) > context["constraints"]["priority_test_budget"]
    priority_keys = [] if needs_human else p1_eligible
    target_metric = context.get("candidate_target_metric")
    metric_keys = [item["metric_key"] for item in context["eligible_metrics"]]
    selected_metrics = []
    if target_metric in metric_keys:
        selected_metrics.append(target_metric)
    if any(item["channel_key"] == "OFFICIAL_SITE" and item["role"] == "PRIMARY" for item in channels):
        if "official_reference_rate" in metric_keys:
            selected_metrics.append("official_reference_rate")
    if "brand_recommendation_rate" in metric_keys:
        selected_metrics.append("brand_recommendation_rate")
    return {
        "themes": themes,
        "primary_interventions": [
            {"channel_key": item["channel_key"], "frozen_role": "PRIMARY", "execution_priority": "P1"}
            for item in channels if item["role"] == "PRIMARY"
        ],
        "secondary_interventions": [
            {"channel_key": item["channel_key"], "frozen_role": "SECONDARY", "execution_priority": "P2"}
            for item in channels if item["role"] == "SECONDARY"
        ],
        "priority_tests": [
            {"channel_key": key, "frozen_role": "TEST", "execution_priority": "P1"}
            for key in priority_keys
        ],
        "deferred_tests": [
            {"channel_key": item["channel_key"], "frozen_role": "TEST", "execution_priority": "P2"}
            for item in channels if item["role"] == "TEST" and item["channel_key"] not in priority_keys
        ],
        "observe_channels": [
            {"channel_key": item["channel_key"], "frozen_role": "OBSERVE", "execution_priority": "P2"}
            for item in channels if item["role"] == "OBSERVE"
        ],
        "selected_success_metrics": _unique(selected_metrics),
        "target_outcome": TARGET_OUTCOME,
        "needs_human_prioritization": needs_human,
    }


def _allowed_pair_set(constraints: dict) -> set[tuple[str, str]]:
    return {tuple(sorted(pair)) for pair in constraints.get("allowed_merge_pairs") or []}


def validate_structural_synthesis(context: dict, proposal: dict) -> dict:
    errors = []
    if not isinstance(proposal, dict):
        return {
            "status": "INVALID_SYNTHESIS",
            "errors": ["MALFORMED_STRUCTURAL_SCHEMA"],
            "validated_at": datetime.now(timezone.utc).isoformat(),
        }
    allowed_root_fields = {
        "themes",
        "primary_interventions",
        "secondary_interventions",
        "priority_tests",
        "deferred_tests",
        "observe_channels",
        "selected_success_metrics",
        "target_outcome",
        "needs_human_prioritization",
    }
    for field in proposal:
        if field not in allowed_root_fields:
            errors.append(f"UNKNOWN_STRUCTURAL_FIELD:{field}")
    reason_ids = {item["reason_id"] for item in context["decision_reasons"]}
    channel_roles = {item["channel_key"]: item["role"] for item in context["channel_resolutions"]}
    metric_keys = {item["metric_key"] for item in context["eligible_metrics"]}
    allowed_pairs = _allowed_pair_set(context["constraints"])
    themes = proposal.get("themes") if isinstance(proposal.get("themes"), list) else []
    seen_reasons = []
    theme_keys = set()
    for theme in themes:
        if not isinstance(theme, dict):
            errors.append("MALFORMED_THEME_SCHEMA")
            continue
        for field in theme:
            if field not in {"theme_key", "reason_ids", "priority"}:
                errors.append(f"UNKNOWN_THEME_FIELD:{field}")
        key = str(theme.get("theme_key") or "")
        if not key or key in theme_keys:
            errors.append(f"INVALID_THEME_KEY:{key or 'EMPTY'}")
        theme_keys.add(key)
        current_reason_ids = [str(value) for value in theme.get("reason_ids") or []]
        if not current_reason_ids:
            errors.append(f"EMPTY_THEME:{key}")
        for reason_id in current_reason_ids:
            if reason_id not in reason_ids:
                errors.append(f"UNKNOWN_REASON_ID:{reason_id}")
            seen_reasons.append(reason_id)
        for left, right in itertools.combinations(current_reason_ids, 2):
            if tuple(sorted((left, right))) not in allowed_pairs:
                errors.append(f"DISALLOWED_THEME_MERGE:{left}|{right}")
        if theme.get("priority") not in VALID_EXECUTION_PRIORITIES:
            errors.append(f"INVALID_THEME_PRIORITY:{key}")
    if Counter(seen_reasons) != Counter(reason_ids):
        errors.append("REASON_PARTITION_MISMATCH")

    portfolio_fields = (
        "primary_interventions",
        "secondary_interventions",
        "priority_tests",
        "deferred_tests",
        "observe_channels",
    )
    expected_role = {
        "primary_interventions": "PRIMARY",
        "secondary_interventions": "SECONDARY",
        "priority_tests": "TEST",
        "deferred_tests": "TEST",
        "observe_channels": "OBSERVE",
    }
    seen_channels = []
    for field in portfolio_fields:
        rows = proposal.get(field) if isinstance(proposal.get(field), list) else []
        for row in rows:
            if not isinstance(row, dict):
                errors.append(f"MALFORMED_PORTFOLIO_SCHEMA:{field}")
                continue
            for item_field in row:
                if item_field not in {"channel_key", "frozen_role", "execution_priority"}:
                    errors.append(f"UNKNOWN_PORTFOLIO_FIELD:{field}:{item_field}")
            key = str(row.get("channel_key") or "").upper()
            if key not in channel_roles:
                errors.append(f"UNKNOWN_CHANNEL:{key or 'EMPTY'}")
                continue
            if row.get("frozen_role") != channel_roles[key] or channel_roles[key] != expected_role[field]:
                errors.append(f"CHANNEL_ROLE_MUTATION:{key}:{channel_roles[key]}->{row.get('frozen_role') or expected_role[field]}")
            if row.get("execution_priority") not in VALID_EXECUTION_PRIORITIES:
                errors.append(f"INVALID_EXECUTION_PRIORITY:{key}")
            seen_channels.append(key)
    if Counter(seen_channels) != Counter(channel_roles.keys()):
        errors.append("CHANNEL_PARTITION_MISMATCH")
    for metric in proposal.get("selected_success_metrics") or []:
        if metric not in metric_keys:
            errors.append(f"UNKNOWN_METRIC:{metric}")
    if proposal.get("target_outcome") != TARGET_OUTCOME:
        errors.append(f"UNKNOWN_TARGET_OUTCOME:{proposal.get('target_outcome')}")
    return {
        "status": "VALID" if not errors else "INVALID_SYNTHESIS",
        "errors": _unique(errors),
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }


def validate_business_rules(context: dict, proposal: dict) -> dict:
    errors = []
    p1_eligible = {
        row["channel_key"]
        for row in context["constraints"]["test_priority_eligibility"]
        if row["eligible_for_p1"]
    }
    selected = {str(row.get("channel_key") or "").upper() for row in proposal.get("priority_tests") or []}
    budget = int(context["constraints"]["priority_test_budget"])
    if not selected.issubset(p1_eligible):
        errors.append("TEST_P1_OUTSIDE_ELIGIBLE_SET")
    if len(selected) > budget:
        errors.append("PRIORITY_TEST_BUDGET_EXCEEDED")
    bounded_test_resolved = "AMBIGUOUS_TEST_PRIORITY" in set(context.get("resolved_ambiguity_types") or [])
    if len(p1_eligible) > budget and selected and proposal.get("needs_human_prioritization"):
        errors.append("AMBIGUOUS_TEST_PRIORITY_MUST_NOT_BE_AUTOMATICALLY_SELECTED")
    if len(p1_eligible) > budget and not proposal.get("needs_human_prioritization") and not bounded_test_resolved:
        errors.append("AMBIGUOUS_TEST_PRIORITY_REQUIRES_HUMAN")
    return {
        "status": "VALID" if not errors else "INVALID_SYNTHESIS",
        "errors": errors,
        "weighted_score_used": False,
    }


def _deterministic_theme_title(reason_rows: list[dict]) -> str:
    family_labels = _unique([item["capability_family"] for item in reason_rows if item["capability_family"]])
    return " / ".join(family_labels) if family_labels else "未命名主题"


def _enrich_structure(context: dict, proposal: dict) -> dict:
    reason_by_id = {item["reason_id"]: item for item in context["decision_reasons"]}
    channel_by_key = {item["channel_key"]: item for item in context["channel_resolutions"]}
    themes = []
    reason_to_theme = {}
    denominator = context["coverage"]["total_analyzable_runs"]
    for theme in proposal["themes"]:
        reason_rows = [reason_by_id[value] for value in theme["reason_ids"]]
        observed = sorted({run_id for item in reason_rows for run_id in item["observed_run_ids"]})
        truth_ids = sorted({value for item in reason_rows for value in item["product_truth_ids"]})
        gap_ids = sorted({value for item in reason_rows for value in item["gap_item_ids"]})
        source_ids = sorted({value for item in reason_rows for value in item["benchmark_source_document_ids"]})
        title = _deterministic_theme_title(reason_rows)
        theme_coverage = (len(observed) / denominator) if denominator else 0.0
        row = {
            **theme,
            "title": title,
            "original_reasons": [item["original_reason"] for item in reason_rows],
            "product_truth_ids": truth_ids,
            "gap_item_ids": gap_ids,
            "benchmark_source_document_ids": source_ids,
            "theme_observed_runs": len(observed),
            "coverage": f"{len(observed)}/{denominator}",
            "observed_run_ids": observed,
            "theme_observed_run_ids": observed,
            "theme_observed_run_count": len(observed),
            "theme_coverage": theme_coverage,
            "provenance_ids": (
                list(theme["reason_ids"])
                + [f"product_truth:{value}" for value in truth_ids]
                + [f"gap_item:{value}" for value in gap_ids]
                + [f"source_document:{value}" for value in source_ids]
            ),
        }
        themes.append(row)
        for reason_id in theme["reason_ids"]:
            reason_to_theme[reason_id] = theme["theme_key"]

    def enrich_portfolio(field: str) -> list[dict]:
        result = []
        for item in proposal.get(field) or []:
            source = channel_by_key[item["channel_key"]]
            reason_rows = [reason_by_id[value] for value in source["decision_reason_ids"] if value in reason_by_id]
            result.append({
                **item,
                "channel_label": source["channel_label"],
                "rationale_path": source["rationale_path"],
                "decision_reason_ids": source["decision_reason_ids"],
                "decision_reason_texts": [row["original_reason"] for row in reason_rows],
                "supporting_signal_ids": source["supporting_signal_ids"],
                "reason_coverage_count": source["reason_coverage_count"],
                "reason_coverage_denominator": len(reason_by_id),
                "measurability": source["measurability"],
                "information_value": source["information_value"],
                "provenance_ids": [source["object_id"]] + source["decision_reason_ids"] + source["supporting_signal_ids"],
            })
        return result

    return {
        **proposal,
        "themes": themes,
        "reason_to_theme_map": reason_to_theme,
        "primary_interventions": enrich_portfolio("primary_interventions"),
        "secondary_interventions": enrich_portfolio("secondary_interventions"),
        "priority_tests": enrich_portfolio("priority_tests"),
        "deferred_tests": enrich_portfolio("deferred_tests"),
        "observe_channels": enrich_portfolio("observe_channels"),
    }


def validate_theme_coverage(context: dict, structure: dict) -> dict:
    errors = []
    reason_by_id = {item["reason_id"]: item for item in context["decision_reasons"]}
    denominator = int(context["coverage"]["total_analyzable_runs"])
    for theme in structure.get("themes") or []:
        reason_ids = theme.get("reason_ids") or []
        expected_ids = sorted({
            run_id
            for reason_id in reason_ids
            for run_id in reason_by_id.get(reason_id, {}).get("observed_run_ids", [])
        })
        expected_count = len(expected_ids)
        expected_coverage = (expected_count / denominator) if denominator else 0.0
        key = theme.get("theme_key") or "UNKNOWN"
        if theme.get("theme_observed_run_ids") != expected_ids:
            errors.append(f"THEME_RUN_ID_UNION_MISMATCH:{key}")
        if theme.get("theme_observed_run_count") != expected_count:
            errors.append(f"THEME_RUN_COUNT_MISMATCH:{key}")
        if theme.get("theme_coverage") != expected_coverage:
            errors.append(f"THEME_COVERAGE_MISMATCH:{key}")
    return {"status": "VALID" if not errors else "INVALID_SYNTHESIS", "errors": errors}


def validate_theme_titles(context: dict, structure: dict) -> dict:
    errors = []
    reason_by_id = {item["reason_id"]: item for item in context["decision_reasons"]}
    for theme in structure.get("themes") or []:
        reason_rows = [reason_by_id[value] for value in theme.get("reason_ids") or [] if value in reason_by_id]
        expected = _deterministic_theme_title(reason_rows)
        if theme.get("title") != expected:
            errors.append(f"UNSUPPORTED_THEME_TITLE:{theme.get('theme_key') or 'UNKNOWN'}")
    return {
        "status": "VALID" if not errors else "UNGROUNDED",
        "errors": errors,
        "fallback_policy": "DETERMINISTIC_CAPABILITY_FAMILY_LABEL",
    }


def _all_allowed_ids(context: dict) -> set[str]:
    result = {item["reason_id"] for item in context["decision_reasons"]}
    result.update(f"product_truth:{item['id']}" for item in context["product_truths"])
    result.update(f"gap_item:{value}" for item in context["decision_reasons"] for value in item["gap_item_ids"])
    result.update(f"source_document:{value}" for item in context["decision_reasons"] for value in item["benchmark_source_document_ids"])
    result.update(item["object_id"] for item in context["channel_resolutions"])
    result.update(value for item in context["channel_resolutions"] for value in item["supporting_signal_ids"])
    result.update(item["object_id"] for item in context["eligible_metrics"])
    return result


def validate_provenance(context: dict, structure: dict) -> dict:
    errors = []
    allowed_ids = _all_allowed_ids(context)
    rows = list(structure.get("themes") or [])
    for field in ("primary_interventions", "secondary_interventions", "priority_tests", "deferred_tests", "observe_channels"):
        rows.extend(structure.get(field) or [])
    for row in rows:
        provenance_ids = row.get("provenance_ids") or []
        if not provenance_ids:
            errors.append(f"MISSING_PROVENANCE:{row.get('theme_key') or row.get('channel_key')}")
        for value in provenance_ids:
            if value not in allowed_ids:
                errors.append(f"UNKNOWN_SOURCE_ID:{value}")
    return {
        "status": "VALID" if not errors else "UNGROUNDED",
        "errors": _unique(errors),
    }


def _deterministic_decision_view(context: dict, structure: dict) -> dict:
    brand = context["brand_name"]
    themes = structure.get("themes") or []
    primary = structure.get("primary_interventions") or []
    secondary = structure.get("secondary_interventions") or []
    priority_tests = structure.get("priority_tests") or []
    deferred = structure.get("deferred_tests") or []
    denominator = context["coverage"]["total_analyzable_runs"]
    all_reason_ids = [item["reason_id"] for item in context["decision_reasons"]]
    theme_names = "、".join(item["title"] for item in themes) or "当前已确认理由"

    def channel_claim(item: dict, prefix: str) -> dict:
        reason_text = "、".join(item.get("decision_reason_texts") or []) or "当前理由"
        return {
            "text": (
                f"{prefix}{item['channel_label']}，围绕「{reason_text}」观察是否形成新的检索、引用或推荐理由信号；"
                f"渠道角色仍为 {item['frozen_role']}。"
            ),
            "provenance_ids": item["provenance_ids"],
        }

    return {
        "current_ai_decision_opportunity": {
            "text": f"当前策略输入包含 {len(all_reason_ids)} 条原子理由，统一按 {denominator} 个可分析 Run 计算覆盖。",
            "provenance_ids": all_reason_ids,
        },
        "target_change": {
            "text": f"验证「{brand}」与「{theme_names}」是否更稳定地进入后续回答的候选、引用或推荐理由。",
            "provenance_ids": all_reason_ids,
        },
        "intervention_themes": [
            {
                "theme_key": item["theme_key"],
                "text": f"{item['title']}：覆盖 {item['coverage']} 个可分析 Run。",
                "provenance_ids": item["provenance_ids"],
            }
            for item in themes
        ],
        "primary_interventions": [channel_claim(item, "主干预渠道：") for item in primary],
        "secondary_interventions": [channel_claim(item, "辅助干预渠道：") for item in secondary],
        "priority_validation_tests": [channel_claim(item, "优先验证渠道：") for item in priority_tests],
        "deferred_tests": [channel_claim(item, "暂缓验证渠道：") for item in deferred],
        "observe_summary": {
            "text": f"其余 {len(structure.get('observe_channels') or [])} 个渠道保持 OBSERVE，不进入本轮最小执行组合。",
            "provenance_ids": (
                [item["provenance_ids"][0] for item in structure.get("observe_channels") or []]
                or [item["object_id"] for item in context["channel_resolutions"]]
            ),
        },
        "expected_decision_change": {
            "text": "目标是观察候选、引用或推荐理由是否出现变化，不预先宣称干预有效或存在因果提升。",
            "provenance_ids": all_reason_ids,
        },
        "success_metrics": [
            {"text": metric, "provenance_ids": [f"metric:{metric}"]}
            for metric in structure.get("selected_success_metrics") or []
        ],
    }


def _presentation_claims(view: dict) -> list[dict]:
    rows = []
    for value in view.values():
        if isinstance(value, dict) and "text" in value:
            rows.append(value)
        elif isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict) and "text" in item)
    return rows


def validate_presentation(context: dict, view: dict) -> dict:
    errors = []
    if not isinstance(view, dict):
        return {
            "status": "UNGROUNDED",
            "errors": ["MALFORMED_PRESENTATION_SCHEMA"],
            "unsupported_causal_claims": 0,
            "unknown_source_ids": 0,
        }
    allowed_root_fields = {
        "current_ai_decision_opportunity",
        "target_change",
        "intervention_themes",
        "primary_interventions",
        "secondary_interventions",
        "priority_validation_tests",
        "deferred_tests",
        "observe_summary",
        "expected_decision_change",
        "success_metrics",
    }
    for field in view:
        if field not in allowed_root_fields:
            errors.append(f"UNKNOWN_PRESENTATION_FIELD:{field}")
    allowed_ids = _all_allowed_ids(context)
    unsupported_causal_claims = 0
    unknown_source_ids = 0
    allowed_numbers = {
        str(len(context.get("decision_reasons") or [])),
        str(len(context.get("channel_resolutions") or [])),
        str((context.get("coverage") or {}).get("total_analyzable_runs") or 0),
    }
    denominator = int((context.get("coverage") or {}).get("total_analyzable_runs") or 0)
    allowed_numbers.update(str(value) for value in range(denominator + 1))
    allowed_numbers.update(
        str(len(set(item.get("observed_run_ids") or [])))
        for item in context.get("decision_reasons") or []
    )
    allowed_numbers.update(
        str(sum(1 for item in context.get("channel_resolutions") or [] if item.get("role") == role))
        for role in VALID_CHANNEL_ROLES
    )
    for metric in context.get("eligible_metrics") or []:
        for field in ("numerator", "denominator", "value"):
            if metric.get(field) is not None:
                allowed_numbers.update(re.findall(r"\d+(?:\.\d+)?", str(metric[field])))
    grounded_text_by_id: dict[str, str] = {}
    for item in context.get("decision_reasons") or []:
        grounded_text_by_id[item["reason_id"]] = " ".join(str(item.get(field) or "") for field in (
            "original_reason", "normalized_proposition", "capability_family"
        ))
    for item in context.get("product_truths") or []:
        grounded_text_by_id[f"product_truth:{item['id']}"] = " ".join(str(item.get(field) or "") for field in (
            "capability_key", "capability_label", "status", "truth_source"
        ))
    for item in context.get("channel_resolutions") or []:
        grounded_text_by_id[item["object_id"]] = " ".join(str(item.get(field) or "") for field in (
            "channel_key", "channel_label", "role", "resolver_rationale"
        ))
    for item in context.get("eligible_metrics") or []:
        grounded_text_by_id[item["object_id"]] = str(item.get("metric_key") or "")
    for grounded_text in grounded_text_by_id.values():
        allowed_numbers.update(re.findall(r"\d+(?:\.\d+)?", grounded_text))
    for claim in _presentation_claims(view):
        if any(field not in {"theme_key", "text", "provenance_ids"} for field in claim):
            errors.append("UNKNOWN_PRESENTATION_CLAIM_FIELD")
        text = str(claim.get("text") or "").strip()
        provenance_ids = [str(value) for value in claim.get("provenance_ids") or []]
        if not text:
            errors.append("EMPTY_PRESENTATION_CLAIM")
        if not provenance_ids:
            errors.append(f"UNGROUNDED_PRESENTATION:{text[:40]}")
        for value in provenance_ids:
            if value not in allowed_ids:
                unknown_source_ids += 1
                errors.append(f"UNKNOWN_PRESENTATION_SOURCE_ID:{value}")
        for pattern in CAUSAL_PATTERNS:
            if pattern in text:
                unsupported_causal_claims += 1
                errors.append(f"UNSUPPORTED_CAUSAL_CLAIM:{pattern}")
        grounded_text = " ".join(grounded_text_by_id.get(value, "") for value in provenance_ids)
        for pattern in UNSUPPORTED_FACT_PATTERNS:
            if pattern in text and pattern not in grounded_text:
                errors.append(f"UNSUPPORTED_FACTUAL_CLAIM:{pattern}")
        for number in re.findall(r"\d+(?:\.\d+)?", text):
            if number not in allowed_numbers:
                errors.append(f"UNSUPPORTED_NUMERIC_CLAIM:{number}")
    return {
        "status": "VALID" if not errors else "UNGROUNDED",
        "errors": _unique(errors),
        "unsupported_causal_claims": unsupported_causal_claims,
        "unknown_source_ids": unknown_source_ids,
        "phrase_policy": {
            "allowed_observational_language": ALLOWED_EVIDENCE_LANGUAGE,
            "forbidden_causal_language": CAUSAL_PATTERNS,
        },
    }


def _bounded_system_prompt(ambiguity_type: str) -> str:
    if ambiguity_type == "AMBIGUOUS_THEME_GROUPING":
        shape = (
            '{"ambiguity_type":"AMBIGUOUS_THEME_GROUPING",'
            '"decision":"SELECT_GROUPING|NEEDS_HUMAN",'
            '"selected_partition":[["reason-id"]],"rationale_source_ids":["reason-id"]}'
        )
    else:
        shape = (
            '{"ambiguity_type":"AMBIGUOUS_TEST_PRIORITY",'
            '"decision":"SELECT|NEEDS_HUMAN",'
            '"channel_keys":["CHANNEL_KEY"],"rationale_source_ids":["allowed-id"]}'
        )
    return f"""You resolve exactly one supplied ambiguity in a closed world.
Return one JSON object only with this exact shape: {shape}
Use only supplied IDs and only an explicitly allowed option. Do not create or
change facts, channels, roles, capabilities, assets, metrics, coverage, or
causal claims. If the supplied facts do not distinguish the options, choose
NEEDS_HUMAN. Do not return prose outside JSON."""


def _bounded_llm_payload(context: dict, ambiguity: dict) -> dict:
    ambiguity_type = ambiguity["ambiguity_type"]
    if ambiguity_type == "AMBIGUOUS_THEME_GROUPING":
        reason_ids = set(ambiguity["reason_ids"])
        reasons = [
            {
                "reason_id": item["reason_id"],
                "normalized_proposition": item["normalized_proposition"],
                "capability_family": item["capability_family"],
                "scenario": item["scenario"],
                "qualifier": item["qualifier"],
                "intervention_mechanisms": item["intervention_mechanisms"],
                "required_asset_type": item["required_asset_type"],
            }
            for item in context["decision_reasons"]
            if item["reason_id"] in reason_ids
        ]
        return {
            "contract_version": CONTRACT_VERSION,
            "ambiguity_type": ambiguity_type,
            "reasons": reasons,
            "allowed_partition_options": ambiguity["allowed_partition_options"],
            "allowed_source_ids": sorted(reason_ids),
        }
    channel_keys = set(ambiguity["channel_keys"])
    channels = [
        {
            "object_id": item["object_id"],
            "channel_key": item["channel_key"],
            "frozen_role": item["role"],
            "decision_reason_ids": item["decision_reason_ids"],
            "reason_coverage_count": item["reason_coverage_count"],
            "measurability": item["measurability"],
            "information_value": item["information_value"],
        }
        for item in context["channel_resolutions"]
        if item["channel_key"] in channel_keys
    ]
    allowed_source_ids = {
        value
        for item in channels
        for value in [item["object_id"], *item["decision_reason_ids"]]
    }
    return {
        "contract_version": CONTRACT_VERSION,
        "ambiguity_type": ambiguity_type,
        "channels": channels,
        "priority_test_budget": ambiguity["priority_test_budget"],
        "allowed_channel_keys": ambiguity["channel_keys"],
        "allowed_source_ids": sorted(allowed_source_ids),
    }


def validate_bounded_llm_proposal(context: dict, ambiguity: dict, proposal: Any) -> dict:
    errors = []
    if not isinstance(proposal, dict):
        return {"status": "INVALID_SYNTHESIS", "errors": ["MALFORMED_BOUNDED_SCHEMA"]}
    ambiguity_type = ambiguity["ambiguity_type"]
    if proposal.get("ambiguity_type") != ambiguity_type:
        errors.append("AMBIGUITY_TYPE_MISMATCH")
    rationale_ids = proposal.get("rationale_source_ids")
    if not isinstance(rationale_ids, list):
        rationale_ids = []
        errors.append("MALFORMED_RATIONALE_SOURCE_IDS")
    payload = _bounded_llm_payload(context, ambiguity)
    allowed_source_ids = set(payload["allowed_source_ids"])
    for source_id in rationale_ids:
        if source_id not in allowed_source_ids:
            errors.append(f"UNKNOWN_BOUNDED_SOURCE_ID:{source_id}")

    if ambiguity_type == "AMBIGUOUS_THEME_GROUPING":
        allowed_fields = {"ambiguity_type", "decision", "selected_partition", "rationale_source_ids"}
        decision = proposal.get("decision")
        if decision not in {"SELECT_GROUPING", "NEEDS_HUMAN"}:
            errors.append("INVALID_THEME_GROUPING_DECISION")
        partition = proposal.get("selected_partition")
        if decision == "SELECT_GROUPING":
            valid_partition_shape = (
                isinstance(partition, list)
                and all(isinstance(group, list) for group in partition)
                and all(isinstance(reason_id, str) for group in partition for reason_id in group)
            )
            normalized = (
                sorted((sorted(group) for group in partition), key=lambda group: tuple(group))
                if valid_partition_shape else None
            )
            if valid_partition_shape:
                allowed_reason_ids = set(ambiguity["reason_ids"])
                for reason_id in {value for group in partition for value in group} - allowed_reason_ids:
                    errors.append(f"UNKNOWN_REASON_ID:{reason_id}")
            if normalized not in ambiguity["allowed_partition_options"]:
                errors.append("ILLEGAL_THEME_PARTITION")
        elif partition not in (None, []):
            errors.append("NEEDS_HUMAN_MUST_NOT_SELECT_PARTITION")
    else:
        allowed_fields = {"ambiguity_type", "decision", "channel_keys", "rationale_source_ids"}
        decision = proposal.get("decision")
        if decision not in {"SELECT", "NEEDS_HUMAN"}:
            errors.append("INVALID_TEST_PRIORITY_DECISION")
        channel_keys = proposal.get("channel_keys")
        if not isinstance(channel_keys, list):
            channel_keys = []
            errors.append("MALFORMED_CHANNEL_KEYS")
        elif len(channel_keys) != len(set(channel_keys)):
            errors.append("DUPLICATE_CHANNEL_KEY")
        unknown = set(channel_keys) - set(ambiguity["channel_keys"])
        errors.extend(f"UNKNOWN_CHANNEL:{value}" for value in sorted(unknown))
        if decision == "SELECT" and (not channel_keys or len(channel_keys) > ambiguity["priority_test_budget"]):
            errors.append("INVALID_TEST_SELECTION_SIZE")
        if decision == "NEEDS_HUMAN" and channel_keys:
            errors.append("NEEDS_HUMAN_MUST_NOT_SELECT_CHANNEL")
    for field in proposal:
        if field not in allowed_fields:
            errors.append(f"UNKNOWN_BOUNDED_FIELD:{field}")
    return {"status": "VALID" if not errors else "INVALID_SYNTHESIS", "errors": _unique(errors)}


def _apply_bounded_proposal(context: dict, structure: dict, ambiguity: dict, proposal: dict) -> dict:
    result = deepcopy(structure)
    if proposal["decision"] == "NEEDS_HUMAN":
        return result
    if ambiguity["ambiguity_type"] == "AMBIGUOUS_THEME_GROUPING":
        groups = sorted((sorted(group) for group in proposal["selected_partition"]), key=lambda group: tuple(group))
        result["themes"] = _themes_for_groups(context, groups)
        return result
    selected = set(proposal["channel_keys"])
    tests = [item for item in context["channel_resolutions"] if item["role"] == "TEST"]
    result["priority_tests"] = [
        {"channel_key": item["channel_key"], "frozen_role": "TEST", "execution_priority": "P1"}
        for item in tests if item["channel_key"] in selected
    ]
    result["deferred_tests"] = [
        {"channel_key": item["channel_key"], "frozen_role": "TEST", "execution_priority": "P2"}
        for item in tests if item["channel_key"] not in selected
    ]
    result["needs_human_prioritization"] = False
    return result


def apply_bounded_llm_outputs_or_fallback(
    context: dict,
    deterministic_baseline: dict,
    ambiguities: list[dict],
    outputs: list[Any],
) -> tuple[dict, dict]:
    if len(outputs) != len(ambiguities):
        return deepcopy(deterministic_baseline), {
            "status": "LLM_SYNTHESIS_REJECTED",
            "errors": ["BOUNDED_OUTPUT_COUNT_MISMATCH"],
            "deterministic_strategy_preserved": True,
        }
    result = deepcopy(deterministic_baseline)
    validations = []
    for ambiguity, output in zip(ambiguities, outputs):
        validation = validate_bounded_llm_proposal(context, ambiguity, output)
        validations.append(validation)
        if validation["status"] != "VALID":
            return deepcopy(deterministic_baseline), {
                "status": "LLM_SYNTHESIS_REJECTED",
                "errors": validation["errors"],
                "validations": validations,
                "deterministic_strategy_preserved": True,
            }
        result = _apply_bounded_proposal(context, result, ambiguity, output)
    return result, {
        "status": "LLM_SYNTHESIS_ACCEPTED",
        "errors": [],
        "validations": validations,
        "deterministic_strategy_preserved": result == deterministic_baseline,
    }


def apply_structural_proposal_or_fallback(
    context: dict,
    deterministic_baseline: dict,
    proposal: Any,
    *,
    resolved_ambiguity_types: list[str] | None = None,
) -> tuple[dict, dict]:
    validation_context = {
        **context,
        "resolved_ambiguity_types": resolved_ambiguity_types or [],
    }
    structural = validate_structural_synthesis(validation_context, proposal)
    business = validate_business_rules(validation_context, proposal) if structural["status"] == "VALID" else {
        "status": "NOT_RUN",
        "errors": [],
        "weighted_score_used": False,
    }
    errors = _unique(list(structural["errors"]) + list(business["errors"]))
    if not errors and proposal != deterministic_baseline and not resolved_ambiguity_types:
        errors.append("LLM_NOT_ALLOWED_WITHOUT_EXPLICIT_AMBIGUITY")
    if errors:
        return deepcopy(deterministic_baseline), {
            "status": "LLM_SYNTHESIS_REJECTED",
            "errors": errors,
            "structural_validator": structural,
            "business_validator": business,
            "deterministic_strategy_preserved": True,
        }
    return deepcopy(proposal), {
        "status": "LLM_SYNTHESIS_ACCEPTED",
        "errors": [],
        "structural_validator": structural,
        "business_validator": business,
        "deterministic_strategy_preserved": proposal == deterministic_baseline,
    }


def apply_presentation_or_fallback(
    context: dict,
    deterministic_reference: dict,
    proposal: Any,
) -> tuple[dict, dict]:
    validator = validate_presentation(context, proposal)
    if validator["status"] == "VALID" and proposal != deterministic_reference:
        validator = {
            **validator,
            "status": "UNGROUNDED",
            "errors": [
                *validator["errors"],
                "PRESENTATION_VARIANCE_NOT_ALLOWED_WITHOUT_EXPLICIT_AMBIGUITY",
            ],
        }
    if validator["status"] != "VALID":
        return deepcopy(deterministic_reference), {
            "status": "LLM_SYNTHESIS_REJECTED",
            "errors": validator["errors"],
            "validator": validator,
            "deterministic_presentation_preserved": True,
        }
    return deepcopy(proposal), {
        "status": "PRESENTATION_ACCEPTED",
        "errors": [],
        "validator": validator,
        "deterministic_presentation_preserved": proposal == deterministic_reference,
    }


def _call_bounded_llm(context: dict, ambiguities: list[dict]) -> tuple[list[dict], dict]:
    client = DeepSeekClient()
    outputs = []
    request_audit = []
    try:
        for ambiguity in ambiguities:
            if ambiguity.get("enumeration_limited"):
                raise SemanticLLMError("Theme grouping options exceeded deterministic enumeration limit")
            payload = _bounded_llm_payload(context, ambiguity)
            output = client.structured_generate_sync(
                system_prompt=_bounded_system_prompt(ambiguity["ambiguity_type"]),
                user_payload=payload,
                response_schema=dict,
                prompt_version=STRUCTURAL_PROMPT_VERSION,
                schema_version=f"{STRUCTURAL_SCHEMA_VERSION}:{ambiguity['ambiguity_type']}",
                max_tokens=2048,
            )
            outputs.append(output)
            request_audit.append({
                "ambiguity_type": ambiguity["ambiguity_type"],
                "input_hash": _stable_hash(payload),
                "input_reason_count": len(payload.get("reasons") or []),
                "input_channel_count": len(payload.get("channels") or []),
            })
        return outputs, {
            "status": "COMPLETED",
            "provider": client.provider,
            "model": client.settings.deepseek_model,
            "temperature": 0.0,
            "external_llm_calls": client.call_count,
            "token_count": client.token_count,
            "requests": request_audit,
        }
    except SemanticLLMError as exc:
        return outputs, {
            "status": "LLM_UNAVAILABLE",
            "provider": client.provider,
            "model": client.settings.deepseek_model,
            "temperature": 0.0,
            "external_llm_calls": client.call_count,
            "token_count": client.token_count,
            "requests": request_audit,
            "error": str(exc),
        }


def run_synthetic_deepseek_safety_replay() -> dict:
    """Call the real provider with synthetic objects only; never reads or writes DB data."""
    reasons = [
        {
            "reason_id": "synthetic-reason-a",
            "original_reason": "Synthetic capability A",
            "normalized_proposition": "Synthetic capability A",
            "capability_family": "SYNTHETIC_CAPABILITY",
            "scenario": ["GENERAL"],
            "qualifier": [],
            "intervention_mechanisms": ["EVIDENCE_EXPRESSION"],
            "required_asset_type": "AUTHORITATIVE_EVIDENCE_ASSET",
            "observed_run_ids": [1001],
            "product_truth_ids": [9001],
            "gap_item_ids": ["synthetic-gap-a"],
            "gap_type": "EVIDENCE_GAP",
            "gap_layer": "EVIDENCE_ADOPTION",
            "benchmark_tier": "NO_ELIGIBLE_BENCHMARK",
            "benchmark_source_document_ids": [],
        }
    ]
    channels = []
    for key, role in (
        ("SYNTHETIC_PRIMARY", "PRIMARY"),
        ("SYNTHETIC_TEST_A", "TEST"),
        ("SYNTHETIC_TEST_B", "TEST"),
        ("SYNTHETIC_TEST_C", "TEST"),
    ):
        is_test = role == "TEST"
        channels.append({
            "object_id": f"synthetic-channel:{key}",
            "channel_key": key,
            "channel_label": key,
            "role": role,
            "rationale_path": "SYNTHETIC",
            "decision_reason_ids": ["synthetic-reason-a"],
            "supporting_signal_ids": [],
            "exposure": "PASS" if is_test else "UNKNOWN",
            "reason_coverage_count": 1,
            "target_brand_gap": "PASS" if is_test else "UNKNOWN",
            "intervention_fit": "PASS" if is_test else "UNKNOWN",
            "measurability": "HIGH" if is_test else "UNKNOWN",
            "information_value": "HIGH" if is_test else "UNKNOWN",
            "test_metric": "synthetic_metric" if is_test else None,
            "resolver_rationale": "synthetic non-sensitive fixture",
        })
    context = {
        "decision_reasons": reasons,
        "product_truths": [{"id": 9001, "object_id": "product_truth:9001"}],
        "channel_resolutions": channels,
        "eligible_metrics": [{"object_id": "metric:synthetic_metric", "metric_key": "synthetic_metric"}],
        "candidate_target_metric": "synthetic_metric",
        "coverage": {"total_analyzable_runs": 1},
        "constraints": _build_constraints(reasons, channels),
    }
    baseline = _deterministic_structural_proposal(context)
    ambiguities = detect_synthesis_ambiguities(context)
    outputs, runtime = _call_bounded_llm(context, ambiguities)
    final_structure, acceptance = apply_bounded_llm_outputs_or_fallback(
        context,
        baseline,
        ambiguities,
        outputs,
    ) if runtime["status"] == "COMPLETED" else (
        deepcopy(baseline),
        {
            "status": "LLM_SYNTHESIS_REJECTED",
            "errors": [runtime.get("error") or "LLM_UNAVAILABLE"],
            "deterministic_strategy_preserved": True,
        },
    )
    return {
        "replay_scope": "SYNTHETIC_NON_SENSITIVE_ONLY",
        "real_project_data_sent": False,
        "ambiguities": ambiguities,
        "runtime": runtime,
        "raw_outputs": outputs,
        "acceptance": acceptance,
        "final_structure_valid": validate_structural_synthesis(context, final_structure)["status"] == "VALID",
        "deterministic_fallback_preserved": (
            final_structure == baseline if acceptance["status"] == "LLM_SYNTHESIS_REJECTED" else True
        ),
    }


def _current_candidate(
    db: Session,
    project_id: int,
    prompt_id: int,
    package: OptimizationEvidencePackage,
    candidate_id: int | None,
) -> OptimizationStrategyCandidate:
    if candidate_id:
        candidate = db.get(OptimizationStrategyCandidate, int(candidate_id))
        if not candidate or candidate.project_id != project_id or candidate.evidence_package_id != package.id:
            raise ValueError("指定 StrategyCandidate 不属于当前 Project/Prompt/Evidence Package")
        return candidate
    candidates = (
        db.query(OptimizationStrategyCandidate)
        .filter(
            OptimizationStrategyCandidate.project_id == project_id,
            OptimizationStrategyCandidate.evidence_package_id == package.id,
            OptimizationStrategyCandidate.review_status == "PENDING_REVIEW",
        )
        .order_by(OptimizationStrategyCandidate.created_at.desc(), OptimizationStrategyCandidate.id.desc())
        .all()
    )
    candidate = next(
        (item for item in candidates if infer_strategy_candidate_origin(item) == CURRENT_STEP7_CANDIDATE_ORIGIN),
        None,
    )
    if not candidate:
        raise ValueError("当前 Prompt 没有可用于 PR4-A Shadow 的待审核 StrategyCandidate")
    return candidate


def _synthesis_source_payload(payload: dict) -> dict:
    source = deepcopy(payload)
    for key in (
        "strategy_synthesis",
        "decision_reasons",
        "intervention_themes",
        "strategy_portfolio",
        "strategy_decision_view",
        "strategy_audit_view",
    ):
        source.pop(key, None)
    return source


def build_strategy_synthesis_context_from_payload(
    db: Session,
    project: Project,
    prompt: Prompt,
    package: OptimizationEvidencePackage,
    payload: dict,
    *,
    input_scope_id: str | int,
) -> dict:
    reasons = _build_reason_objects(db, payload)
    if not reasons:
        raise ValueError("当前 StrategyCandidate 没有带稳定 ID 的 Decision Reason/Gap Item")
    channels = _candidate_channels(payload, input_scope_id)
    if not channels:
        raise ValueError("当前 StrategyCandidate 没有可用的 Channel Resolution 对象")
    _bind_legacy_channel_reasons(reasons, channels)
    truth_ids = sorted({value for item in reasons for value in item["product_truth_ids"]})
    truth_rows = db.query(TargetBrandCapabilityTruth).filter(TargetBrandCapabilityTruth.id.in_(truth_ids)).all() if truth_ids else []
    product_truths = [
        {
            "id": int(item.id),
            "object_id": f"product_truth:{int(item.id)}",
            "capability_key": item.capability_key,
            "capability_label": item.capability_label,
            "status": item.product_truth_status,
            "truth_source": item.truth_source,
        }
        for item in truth_rows
    ]
    all_observed_runs = sorted({run_id for item in reasons for run_id in item["observed_run_ids"]})
    for reason in reasons:
        reason["reason_observed_runs"] = len(reason["observed_run_ids"])
        reason["coverage"] = f"{reason['reason_observed_runs']}/{len(all_observed_runs)}"
    package_run_ids = [int(value) for value in loads(package.source_run_ids_json, []) if value]
    valid_run_count = db.query(BrowserMonitorRun).filter(
        BrowserMonitorRun.id.in_(package_run_ids),
        BrowserMonitorRun.status.in_(["success", "partial_success"]),
    ).count() if package_run_ids else 0
    constraints = _build_constraints(reasons, channels)
    benchmark_signature = sorted({
        (item["benchmark_tier"], value)
        for item in reasons
        for value in item["benchmark_source_document_ids"]
    })
    context = {
        "contract_version": CONTRACT_VERSION,
        "project_id": int(project.id),
        "prompt_id": int(prompt.id),
        "evidence_package_id": int(package.id),
        "evidence_package_version": int(package.version),
        "input_scope_id": str(input_scope_id),
        "brand_name": project.brand_name or "目标品牌",
        "strategy_basis": payload.get("strategy_basis") or "BENCHMARK_BACKED_STRATEGY",
        "decision_reasons": reasons,
        "product_truths": product_truths,
        "channel_resolutions": channels,
        "eligible_metrics": _eligible_metrics(package),
        "candidate_target_metric": payload.get("target_metric"),
        "coverage": {
            "total_analyzable_runs": len(all_observed_runs),
            "decision_bearing_runs": len(all_observed_runs),
            "package_valid_runs": valid_run_count,
            "analyzable_run_ids": all_observed_runs,
            "denominator_rule": "UNION_OF_CURRENT_REASON_OBSERVED_RUN_IDS",
            "detail_rule": "PACKAGE_VALID_RUNS_IS_AUDIT_CONTEXT_ONLY",
        },
        "constraints": constraints,
        "frozen_semantics": {
            "resolver_roles": {item["channel_key"]: item["role"] for item in channels},
            "benchmark_signature": benchmark_signature,
            "strategy_basis": payload.get("strategy_basis") or "BENCHMARK_BACKED_STRATEGY",
        },
        "old_strategy_semantic_structure": {
            "target_decision_change": payload.get("target_decision_change") or "",
            "primary_intervention_path": payload.get("primary_intervention_path") or "",
            "priority_capabilities": [
                {
                    "gap_item_id": item.get("gap_item_id"),
                    "capability_label": item.get("capability_label"),
                    "priority_band": item.get("priority_band"),
                    "reason_run_coverage": item.get("reason_run_coverage"),
                }
                for item in payload.get("priority_capabilities") or []
            ],
            "channel_roles": {item["channel_key"]: item["role"] for item in channels},
            "strategy_basis": payload.get("strategy_basis") or "BENCHMARK_BACKED_STRATEGY",
            "benchmark_signature": benchmark_signature,
        },
        "source_payload_hash": _stable_hash(_synthesis_source_payload(payload)),
    }
    return context


def build_strategy_synthesis_context(
    db: Session,
    project_id: int,
    prompt_id: int,
    candidate_id: int | None = None,
) -> tuple[dict, OptimizationStrategyCandidate]:
    project = db.get(Project, project_id)
    prompt = db.get(Prompt, prompt_id)
    if not project or not prompt or prompt.project_id != project_id:
        raise ValueError("Project/Prompt 不存在")
    package = _resolve_vertical_slice_package(db, project_id, prompt_id, None)
    candidate = _current_candidate(db, project_id, prompt_id, package, candidate_id)
    payload = loads(candidate.structured_payload_json, {})
    synthesis_audit = payload.get("strategy_synthesis") or {}
    input_scope_id = synthesis_audit.get("input_scope_id") or int(candidate.id)
    context = build_strategy_synthesis_context_from_payload(
        db,
        project,
        prompt,
        package,
        payload,
        input_scope_id=input_scope_id,
    )
    context["strategy_candidate_id"] = int(candidate.id)
    return context, candidate


def run_strategy_synthesis_core(
    context: dict,
    *,
    use_llm: bool = False,
    structural_proposal: Any = None,
    presentation_proposal: Any = None,
) -> dict:
    deterministic_proposal = _deterministic_structural_proposal(context)
    ambiguities = detect_synthesis_ambiguities(context)
    structural_runtime = {
        "status": "NOT_REQUESTED",
        "provider": "deterministic_constraint_reference",
        "model": "none",
        "temperature": 0.0,
        "external_llm_calls": 0,
        "token_count": 0,
    }
    llm_outputs: list[Any] = []
    proposal = deterministic_proposal
    synthesis_mode = "DETERMINISTIC_SHADOW_BASELINE"
    llm_acceptance = {
        "status": "LLM_NOT_REQUESTED",
        "errors": [],
        "deterministic_strategy_preserved": True,
    }
    resolved_ambiguity_types: list[str] = []

    if structural_proposal is not None:
        proposal = structural_proposal
        synthesis_mode = "INJECTED_ADVERSARIAL_VALIDATION"
        llm_outputs = [structural_proposal]
    elif use_llm and not ambiguities:
        structural_runtime["status"] = "SKIPPED_NOT_NECESSARY"
        llm_acceptance["status"] = "LLM_NOT_NEEDED"
        synthesis_mode = "DETERMINISTIC_FIRST_NO_AMBIGUITY"
    elif use_llm:
        llm_outputs, structural_runtime = _call_bounded_llm(context, ambiguities)
        synthesis_mode = "BOUNDED_LLM_AMBIGUITY_ONLY"
        if structural_runtime["status"] == "COMPLETED":
            proposal, llm_acceptance = apply_bounded_llm_outputs_or_fallback(
                context,
                deterministic_proposal,
                ambiguities,
                llm_outputs,
            )
            if llm_acceptance["status"] == "LLM_SYNTHESIS_ACCEPTED":
                resolved_ambiguity_types = [
                    ambiguity["ambiguity_type"]
                    for ambiguity, output in zip(ambiguities, llm_outputs)
                    if isinstance(output, dict) and output.get("decision") != "NEEDS_HUMAN"
                ]
        else:
            llm_acceptance = {
                "status": "LLM_SYNTHESIS_REJECTED",
                "errors": [structural_runtime.get("error") or "LLM_UNAVAILABLE"],
                "deterministic_strategy_preserved": True,
            }

    if llm_acceptance["status"] == "LLM_SYNTHESIS_REJECTED":
        synthesis_mode = f"{synthesis_mode}_DETERMINISTIC_FALLBACK"

    proposal, proposal_gate = apply_structural_proposal_or_fallback(
        context,
        deterministic_proposal,
        proposal,
        resolved_ambiguity_types=resolved_ambiguity_types,
    )
    proposal_validator = proposal_gate["structural_validator"]
    proposal_business_validator = proposal_gate["business_validator"]
    if proposal_gate["status"] == "LLM_SYNTHESIS_REJECTED":
        llm_acceptance = proposal_gate
        if not synthesis_mode.endswith("_DETERMINISTIC_FALLBACK"):
            synthesis_mode = f"{synthesis_mode}_DETERMINISTIC_FALLBACK"
        resolved_ambiguity_types = []
    elif structural_proposal is not None:
        llm_acceptance = proposal_gate

    final_context = {**context, "resolved_ambiguity_types": resolved_ambiguity_types}
    structural_validator = validate_structural_synthesis(final_context, proposal)
    business_validator = validate_business_rules(final_context, proposal) if structural_validator["status"] == "VALID" else {
        "status": "NOT_RUN",
        "errors": [],
        "weighted_score_used": False,
    }
    structurally_valid = structural_validator["status"] == "VALID" and business_validator["status"] == "VALID"
    structure = _enrich_structure(context, proposal) if structurally_valid else None
    provenance_validator = validate_provenance(context, structure) if structure else {"status": "NOT_RUN", "errors": []}
    coverage_validator = validate_theme_coverage(context, structure) if structure else {"status": "NOT_RUN", "errors": []}
    title_validator = validate_theme_titles(context, structure) if structure else {"status": "NOT_RUN", "errors": []}
    fully_valid = all(
        item["status"] == "VALID"
        for item in (structural_validator, business_validator, provenance_validator, coverage_validator, title_validator)
    )

    reference_view = _deterministic_decision_view(context, structure) if fully_valid else None
    presentation_runtime = {
        "status": "SKIPPED_NOT_NECESSARY",
        "provider": "deterministic_closed_world_verbalizer",
        "model": "none",
        "temperature": 0.0,
        "external_llm_calls": 0,
        "token_count": 0,
    }
    presentation_acceptance = {"status": "PRESENTATION_NOT_REQUESTED", "errors": []}
    decision_view = reference_view
    presentation_proposal_validator = None
    if presentation_proposal is not None:
        decision_view, presentation_acceptance = apply_presentation_or_fallback(
            context,
            reference_view,
            presentation_proposal,
        )
        presentation_proposal_validator = presentation_acceptance["validator"]
    unsupported_validator = validate_presentation(context, decision_view) if decision_view else {
        "status": "NOT_RUN",
        "errors": [],
        "unsupported_causal_claims": 0,
        "unknown_source_ids": 0,
    }
    presentation_valid = unsupported_validator["status"] == "VALID"

    roles_after = {item["channel_key"]: item["role"] for item in context["channel_resolutions"]}
    benchmark_after = context["frozen_semantics"]["benchmark_signature"]
    all_valid = fully_valid and presentation_valid
    validation_status = "VALID" if all_valid else "SYNTHESIS_VALIDATION_FAILED"
    unresolved_ambiguity_types = [
        item["ambiguity_type"]
        for item in ambiguities
        if item["ambiguity_type"] not in resolved_ambiguity_types
    ]
    input_object_ids = sorted(_all_allowed_ids(context))
    output_hash = _stable_hash({"structure": structure, "decision_view": decision_view}) if all_valid else ""
    bounded_input_payloads = [_bounded_llm_payload(context, item) for item in ambiguities]
    attempted_errors = list(proposal_validator.get("errors") or []) + list(llm_acceptance.get("errors") or [])
    if presentation_proposal_validator:
        attempted_errors.extend(presentation_proposal_validator.get("errors") or [])
    attempted_errors = _unique(attempted_errors)
    synthesis_summary = {
        "input_decision_reasons": len(context["decision_reasons"]),
        "input_channel_roles": context["frozen_semantics"]["resolver_roles"],
        "allowed_merge_pairs": context["constraints"]["allowed_merge_pairs"],
        "themes": structure.get("themes") if structure else [],
        "reason_to_theme_map": structure.get("reason_to_theme_map") if structure else {},
        "theme_priority": {
            item["theme_key"]: item["priority"] for item in structure.get("themes") or []
        } if structure else {},
        "primary_interventions": structure.get("primary_interventions") if structure else [],
        "secondary_interventions": structure.get("secondary_interventions") if structure else [],
        "priority_tests": structure.get("priority_tests") if structure else [],
        "deferred_tests": structure.get("deferred_tests") if structure else [],
        "observe_count": len(structure.get("observe_channels") or []) if structure else 0,
        "expected_decision_change": (
            (decision_view.get("expected_decision_change") or {}).get("text")
            if decision_view else ""
        ),
        "selected_success_metrics": structure.get("selected_success_metrics") if structure else [],
        "needs_human_prioritization": structure.get("needs_human_prioritization") if structure else True,
    }
    return {
        "schema_version": "strategy_synthesis_core.pr4_b.v1",
        "project_id": context["project_id"],
        "prompt_id": context["prompt_id"],
        "evidence_package_id": context["evidence_package_id"],
        "validation_status": validation_status,
        "can_persist_current_candidate": all_valid,
        "needs_human_synthesis": not all_valid or bool(unresolved_ambiguity_types),
        "synthesis_mode": synthesis_mode,
        "ambiguity_resolution": {
            "detected": ambiguities,
            "resolved_types": resolved_ambiguity_types,
            "unresolved_types": unresolved_ambiguity_types,
            "needs_human_theme_grouping": "AMBIGUOUS_THEME_GROUPING" in unresolved_ambiguity_types,
            "needs_human_test_priority": "AMBIGUOUS_TEST_PRIORITY" in unresolved_ambiguity_types,
            "needs_human_portfolio_selection": "AMBIGUOUS_PORTFOLIO_SELECTION" in unresolved_ambiguity_types,
        },
        "llm_acceptance": llm_acceptance,
        "contract": {
            "version": CONTRACT_VERSION,
            "world_model": "CLOSED_WORLD",
            "principles": [
                "NO_SOURCE_ID_NO_FACTUAL_CLAIM",
                "NO_ELIGIBLE_OBJECT_NO_NEW_OBJECT",
                "UNKNOWN_MUST_REMAIN_UNKNOWN",
                "OBSERVATION_IS_NOT_CAUSAL_CONCLUSION",
                "DETERMINISTIC_FIRST_LLM_ONLY_WHEN_NECESSARY",
            ],
            "allowed_transformations": ALLOWED_TRANSFORMATIONS,
            "forbidden_transformations": FORBIDDEN_TRANSFORMATIONS,
            "phrase_policy": {
                "allowed_observational_language": ALLOWED_EVIDENCE_LANGUAGE,
                "forbidden_causal_language": CAUSAL_PATTERNS,
            },
            "boundary": "PR4-A only synthesizes current Step 7 objects; it does not create or change Step 8 objects.",
        },
        "version_audit": {
            "strategy_synthesis_contract_version": CONTRACT_VERSION,
            "structural_prompt_version": STRUCTURAL_PROMPT_VERSION,
            "presentation_prompt_version": PRESENTATION_PROMPT_VERSION,
            "structural_model": structural_runtime.get("model"),
            "presentation_model": presentation_runtime.get("model"),
            "input_object_ids": input_object_ids,
            "input_hash": _stable_hash(bounded_input_payloads or {"source_payload_hash": context["source_payload_hash"]}),
            "output_hash": output_hash,
        },
        "input": {
            "decision_reasons": context["decision_reasons"],
            "product_truths": context["product_truths"],
            "channel_roles": context["frozen_semantics"]["resolver_roles"],
            "eligible_metrics": context["eligible_metrics"],
            "strategy_basis": context["strategy_basis"],
            "coverage": context["coverage"],
        },
        "allowed_merge_graph": context["constraints"]["reason_compatibility_graph"],
        "test_priority_constraints": {
            "method": context["constraints"]["test_priority_method"],
            "budget": context["constraints"]["priority_test_budget"],
            "eligibility": context["constraints"]["test_priority_eligibility"],
        },
        "strategy_synthesis_summary": synthesis_summary,
        "structural_synthesis": {
            "runtime": structural_runtime,
            "raw_output": llm_outputs if llm_outputs else None,
            "proposal_validator": proposal_validator,
            "proposal_business_validator": proposal_business_validator,
            "validated_structure": structure,
            "deterministic_baseline": deterministic_proposal,
            "deterministic_audit_fallback": deterministic_proposal if llm_acceptance["status"] == "LLM_SYNTHESIS_REJECTED" else None,
        },
        "presentation": {
            "runtime": presentation_runtime,
            "acceptance": presentation_acceptance,
            "proposal_validator": presentation_proposal_validator,
            "decision_view": decision_view,
            "deterministic_reference_view": reference_view,
        },
        "audit_view": {
            "strategy_basis": context["strategy_basis"],
            "reason_ids": [item["reason_id"] for item in context["decision_reasons"]],
            "product_truth_ids": [item["id"] for item in context["product_truths"]],
            "coverage_denominator": context["coverage"],
            "resolver_roles": context["frozen_semantics"]["resolver_roles"],
            "benchmark_signature": context["frozen_semantics"]["benchmark_signature"],
            "merge_constraints": context["constraints"],
            "structural_llm_output": llm_outputs if (use_llm or structural_proposal is not None) else None,
            "bounded_llm_inputs": bounded_input_payloads,
        },
        "validators": {
            "structural": structural_validator,
            "provenance": provenance_validator,
            "business_rules": business_validator,
            "theme_coverage": coverage_validator,
            "theme_title": title_validator,
            "unsupported_claim": unsupported_validator,
        },
        "hallucination_audit": {
            "new_factual_claims_introduced": len([error for error in attempted_errors if "UNSUPPORTED_FACTUAL_CLAIM" in error]),
            "unknown_source_ids": len([error for error in attempted_errors if "UNKNOWN_" in error and ("ID" in error or "SOURCE" in error)]),
            "role_mutations": len([error for error in attempted_errors if error.startswith("CHANNEL_ROLE_MUTATION")]),
            "new_channels": len([error for error in attempted_errors if error.startswith("UNKNOWN_CHANNEL")]),
            "new_assets": len([error for error in attempted_errors if "ASSET" in error.upper()]),
            "unsupported_causal_claims": len([error for error in attempted_errors if error.startswith("UNSUPPORTED_CAUSAL_CLAIM")]),
        },
        "semantic_regression": {
            "resolver_roles_unchanged": roles_after == context["frozen_semantics"]["resolver_roles"],
            "benchmark_semantics_unchanged": benchmark_after == context["frozen_semantics"]["benchmark_signature"],
            "strategy_basis_unchanged": context["strategy_basis"] == context["frozen_semantics"]["strategy_basis"],
        },
        "comparison": {
            "old_strategy_semantic_structure": context["old_strategy_semantic_structure"],
            "new_synthesis_structure": synthesis_summary,
            "resolver_roles_unchanged": roles_after == context["frozen_semantics"]["resolver_roles"],
            "benchmark_semantics_unchanged": benchmark_after == context["frozen_semantics"]["benchmark_signature"],
        },
    }


def run_strategy_synthesis_shadow(
    db: Session,
    project_id: int,
    prompt_id: int,
    candidate_id: int | None = None,
    *,
    use_llm: bool = False,
    structural_proposal: Any = None,
    presentation_proposal: Any = None,
) -> dict:
    context, candidate = build_strategy_synthesis_context(db, project_id, prompt_id, candidate_id)
    before_counts = {
        "strategy_candidates": db.query(OptimizationStrategyCandidate).filter(
            OptimizationStrategyCandidate.project_id == project_id
        ).count(),
        "actions": db.query(OptimizationAction).count(),
        "experiments": db.query(OptimizationExperiment).count(),
    }
    before_hash = _stable_hash({
        "structured_payload_json": candidate.structured_payload_json,
        "review_status": candidate.review_status,
        "effective_payload_json": candidate.effective_payload_json,
    })
    result = run_strategy_synthesis_core(
        context,
        use_llm=use_llm,
        structural_proposal=structural_proposal,
        presentation_proposal=presentation_proposal,
    )
    after_candidate = db.get(OptimizationStrategyCandidate, int(candidate.id))
    after_counts = {
        "strategy_candidates": db.query(OptimizationStrategyCandidate).filter(
            OptimizationStrategyCandidate.project_id == project_id
        ).count(),
        "actions": db.query(OptimizationAction).count(),
        "experiments": db.query(OptimizationExperiment).count(),
    }
    after_hash = _stable_hash({
        "structured_payload_json": after_candidate.structured_payload_json,
        "review_status": after_candidate.review_status,
        "effective_payload_json": after_candidate.effective_payload_json,
    })
    return {
        **result,
        "schema_version": "strategy_synthesis_shadow.pr4_b.v1",
        "shadow_only": True,
        "formal_output_impact": "NONE",
        "strategy_candidate_id": int(candidate.id),
        "candidate_review_status": candidate.review_status,
        "mutation_guard": {
            "candidate_unchanged": before_hash == after_hash,
            "candidate_before_hash": before_hash,
            "candidate_after_hash": after_hash,
            "strategy_candidate_created": after_counts["strategy_candidates"] - before_counts["strategy_candidates"],
            "action_created": after_counts["actions"] - before_counts["actions"],
            "experiment_created": after_counts["experiments"] - before_counts["experiments"],
            "step8_modified": (
                after_counts["actions"] != before_counts["actions"]
                or after_counts["experiments"] != before_counts["experiments"]
            ),
        },
    }
