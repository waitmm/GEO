"""PR5-A deterministic, read-only execution proposal compiler.

This module deliberately stops before persistence.  It compiles confirmed
Step 7 semantics into auditable Step 8 proposal objects without creating an
Action, Experiment, managed asset, or execution snapshot.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import (
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
    _vertical_resampling_plan,
    infer_strategy_candidate_origin,
)
from app.modules.optimization.strategy_synthesis_shadow import (
    build_strategy_synthesis_context_from_payload,
    run_strategy_synthesis_core,
)
from app.services.serialization import loads


CONTRACT_VERSION = "execution_proposal.pr5_a.v1"
EDIT_CONTRACT_VERSION = "execution_proposal.pr5_b.v1"
METRIC_CONTRACT_VERSION = "execution_metric_contract.pr5_a.v1"
PR5_A_EXTERNAL_LLM = "DISABLED_BY_CONTRACT"
SNAPSHOT_MODE = "READ_ONLY_EPHEMERAL_SNAPSHOT"

VALID_RESOLUTION_STATUSES = {"RESOLVED", "NEEDS_HUMAN_SELECTION", "INVALID"}
VALID_PROPOSAL_READINESS = {"READY_FOR_REVIEW", "NEEDS_HUMAN_SELECTION", "BLOCKED_BY_CONSTRAINT"}
VALID_ASSET_TYPES = {"PRODUCT_PAGE", "FEATURE_PAGE", "HELP_DOC", "FAQ_PAGE", "ARTICLE"}
VALID_SECTION_PURPOSES = {
    "DIRECT_ANSWER",
    "PRODUCT_TRUTH",
    "SCENARIO",
    "BOUNDARY",
    "OPERATION",
    "VALIDATION",
    "FAQ",
}
VALID_CLAIM_POLICIES = {
    "TARGET_ASSERTION_ALLOWED",
    "TARGET_ASSERTION_FORBIDDEN",
    "PLANNING_CONTEXT_ALLOWED",
    "PLANNING_QUESTION",
    "PUBLISHABLE_QUESTION_ALLOWED",
    "UNKNOWN_MUST_REMAIN_UNKNOWN",
    "COMPETITOR_CONTEXT_ONLY",
    "COMPARISON_RESTRICTED",
}
POSITIVE_TRUTH_VALUES = {"TRUE", "SUPPORTED"}
CONFIRMED_TRUTH_PROVENANCE = {"MANUAL_CONFIRMED"}

# These are the calculators already implemented by baseline_metrics_for_fixed_runs.
# PR5-A only projects their existing semantics; it does not register new metrics.
FORMAL_METRIC_CALCULATORS = {
    "brand_mention_rate": {
        "measurement_level": "PROMPT_BRAND",
        "calculator": "baseline_metrics.phase4.v1",
        "proposal_types": {"AUTHORITATIVE_ASSET_INTERVENTION", "CHANNEL_VALIDATION_EXPERIMENT"},
    },
    "brand_recommendation_rate": {
        "measurement_level": "PROMPT_BRAND",
        "calculator": "baseline_metrics.phase4.v1",
        "proposal_types": {"AUTHORITATIVE_ASSET_INTERVENTION", "CHANNEL_VALIDATION_EXPERIMENT"},
    },
    "official_reference_rate": {
        "measurement_level": "PROMPT_BRAND",
        "calculator": "evidence_package.metric.v3",
        "proposal_types": {"AUTHORITATIVE_ASSET_INTERVENTION"},
    },
    "selected_asset_retrieval_presence": {
        "measurement_level": "SELECTED_ASSET",
        "calculator": "baseline_metrics.phase4.v1",
        "proposal_types": {"AUTHORITATIVE_ASSET_INTERVENTION", "CHANNEL_VALIDATION_EXPERIMENT"},
    },
    "selected_asset_citation_presence": {
        "measurement_level": "SELECTED_ASSET",
        "calculator": "baseline_metrics.phase4.v1",
        "proposal_types": {"AUTHORITATIVE_ASSET_INTERVENTION", "CHANNEL_VALIDATION_EXPERIMENT"},
    },
}

SYSTEM_OWNED_FIELDS = [
    "channel_role",
    "proposal_type",
    "strategy_scope",
    "theme_membership",
    "reason_scope",
    "product_truth",
    "claim_authorization",
    "baseline_run_ids",
    "evidence_package",
    "metric_eligibility",
    "measurement_level",
]
HUMAN_EDITABLE_FIELDS = [
    "execute_this_proposal",
    "selected_asset_package_key",
    "selected_managed_asset_id",
    "selected_asset_type",
    "title",
    "section_order",
    "publishing_metadata",
    "selected_observation_window_index",
]
IMMUTABLE_EDIT_CODES = {
    "baseline_run_ids": "IMMUTABLE_BASELINE",
    "baseline_ref": "IMMUTABLE_BASELINE",
    "evidence_package": "IMMUTABLE_BASELINE",
    "evidence_package_id": "IMMUTABLE_BASELINE",
    "theme_ids": "INVALID_PACKAGE_SCOPE_EDIT",
    "theme_membership": "INVALID_PACKAGE_SCOPE_EDIT",
    "reason_ids": "IMMUTABLE_REASON_SCOPE",
    "reason_scope": "IMMUTABLE_REASON_SCOPE",
    "product_truth": "IMMUTABLE_PRODUCT_TRUTH",
    "product_truth_ids": "IMMUTABLE_PRODUCT_TRUTH",
    "claim_usage_policy": "IMMUTABLE_FIELD_EDIT",
    "channel": "IMMUTABLE_FIELD_EDIT",
    "channel_role": "IMMUTABLE_FIELD_EDIT",
    "proposal_type": "IMMUTABLE_FIELD_EDIT",
    "strategy_candidate_id": "IMMUTABLE_FIELD_EDIT",
    "strategy_scope": "IMMUTABLE_FIELD_EDIT",
    "eligible_metrics": "IMMUTABLE_FIELD_EDIT",
    "metric_eligibility": "IMMUTABLE_FIELD_EDIT",
    "input_contract_hash": "IMMUTABLE_FIELD_EDIT",
    "merge_proposal_keys": "PROPOSAL_MERGE_FORBIDDEN",
    "merged_proposal_keys": "PROPOSAL_MERGE_FORBIDDEN",
}


def _stable_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _unique(values: list[Any]) -> list[Any]:
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _slug(value: str) -> str:
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
    return digest


def _validator(errors: list[str]) -> dict:
    return {"status": "VALID" if not errors else "INVALID", "errors": _unique(errors)}


def _truth_is_confirmed(row: dict) -> bool:
    return (
        str(row.get("product_truth_status") or row.get("status") or "").upper() in POSITIVE_TRUTH_VALUES
        and str(row.get("truth_source") or "").upper() in CONFIRMED_TRUTH_PROVENANCE
    )


def _approved_truth_projection(row: dict) -> dict:
    aliases = row.get("approved_aliases") if isinstance(row.get("approved_aliases"), list) else []
    return {
        "product_truth_id": int(row["id"]),
        "capability_key": row.get("capability_key") or "",
        "capability_label": row.get("capability_label") or "",
        "approved_aliases": aliases,
        "product_truth_status": row.get("product_truth_status") or row.get("status") or "UNKNOWN",
        "truth_source": row.get("truth_source") or "",
        "source_reference": row.get("source_reference") or "",
        "reviewed_by": row.get("reviewed_by") or "",
        "reviewed_at": row.get("reviewed_at"),
    }


def _claim_id(policy: str, source: str) -> str:
    return f"claim_policy:{policy.lower()}:{_slug(source)}"


def _assertion(brand_name: str, truth: dict) -> dict:
    claim_id = f"target_assertion:product_truth:{truth['product_truth_id']}"
    return {
        "claim_id": claim_id,
        "policy": "TARGET_ASSERTION_ALLOWED",
        "proposition": {
            "subject": brand_name,
            "predicate": "SUPPORTS",
            "object": truth["capability_label"],
            "qualifier": [],
            "polarity": "AFFIRMATIVE",
            "speech_act": "ASSERTION",
        },
        "product_truth_id": truth["product_truth_id"],
        "truth_value": truth["product_truth_status"],
        "provenance_type": truth["truth_source"],
        "source_ids": [f"product_truth:{truth['product_truth_id']}"],
    }


def _unconfirmed_reason_policies(brand_name: str, reason: dict, approved_truth: dict | None) -> list[dict]:
    original = str(reason.get("original_reason") or "").strip()
    family = str(reason.get("capability_family") or "").strip()
    qualifiers = list(reason.get("qualifier") or [])
    allowed_wording = set()
    if approved_truth:
        allowed_wording.add(approved_truth["capability_label"])
        allowed_wording.update(approved_truth.get("approved_aliases") or [])
    if original in allowed_wording and not qualifiers:
        return []
    source_id = str(reason.get("reason_id") or original)
    forbidden_id = _claim_id("TARGET_ASSERTION_FORBIDDEN", source_id)
    question_id = _claim_id("PLANNING_QUESTION", source_id)
    unknown_id = _claim_id("UNKNOWN_MUST_REMAIN_UNKNOWN", source_id)
    return [
        {
            "claim_id": forbidden_id,
            "policy": "TARGET_ASSERTION_FORBIDDEN",
            "proposition": {
                "subject": brand_name,
                "predicate": "SUPPORTS",
                "object": original,
                "qualifier": qualifiers,
                "polarity": "AFFIRMATIVE",
                "speech_act": "ASSERTION",
            },
            "source_ids": [source_id],
            "reason": "NO_EXACT_CONFIRMED_PRODUCT_TRUTH_FOR_FULL_PROPOSITION",
        },
        {
            "claim_id": question_id,
            "policy": "PLANNING_QUESTION",
            "proposition": {
                "subject": "PLANNER",
                "predicate": "VERIFY_TARGET_CAPABILITY",
                "object": original,
                "qualifier": qualifiers,
                "polarity": "UNKNOWN",
                "speech_act": "QUESTION",
            },
            "source_ids": [source_id],
            "publishable": False,
        },
        {
            "claim_id": unknown_id,
            "policy": "UNKNOWN_MUST_REMAIN_UNKNOWN",
            "proposition": {
                "subject": brand_name,
                "predicate": "SUPPORTS",
                "object": original,
                "qualifier": qualifiers,
                "polarity": "UNKNOWN",
                "speech_act": "INTERNAL_CONSTRAINT",
            },
            "source_ids": [source_id],
        },
    ]


def build_claim_usage_policy(
    brand_name: str,
    truths: list[dict],
    reasons: list[dict],
) -> list[dict]:
    truth_by_id = {int(row["product_truth_id"]): row for row in truths if _truth_is_confirmed(row)}
    policies = [_assertion(brand_name, row) for row in truth_by_id.values()]
    for truth in truth_by_id.values():
        claim_id = _claim_id("PUBLISHABLE_QUESTION_ALLOWED", str(truth["product_truth_id"]))
        policies.append({
            "claim_id": claim_id,
            "policy": "PUBLISHABLE_QUESTION_ALLOWED",
            "proposition": {
                "subject": brand_name,
                "predicate": "SUPPORTS",
                "object": truth["capability_label"],
                "qualifier": [],
                "polarity": "QUESTION",
                "speech_act": "QUESTION",
            },
            "product_truth_id": truth["product_truth_id"],
            "source_ids": [f"product_truth:{truth['product_truth_id']}"],
            "publishable": True,
        })
    for reason in reasons:
        reason_id = str(reason["reason_id"])
        policies.append({
            "claim_id": _claim_id("PLANNING_CONTEXT_ALLOWED", reason_id),
            "policy": "PLANNING_CONTEXT_ALLOWED",
            "proposition": {
                "subject": "OBSERVED_ANSWER_OR_SOURCE",
                "predicate": "CONTAINS_DECISION_REASON",
                "object": reason["original_reason"],
                "qualifier": list(reason.get("qualifier") or []),
                "polarity": "OBSERVED",
                "speech_act": "PLANNING_CONTEXT",
            },
            "source_ids": [reason_id],
        })
        policies.append({
            "claim_id": _claim_id("COMPETITOR_CONTEXT_ONLY", reason_id),
            "policy": "COMPETITOR_CONTEXT_ONLY",
            "proposition": {
                "subject": "NON_TARGET_EVIDENCE_CONTEXT",
                "predicate": "INFORMS_CONTENT_NEED",
                "object": reason["original_reason"],
                "qualifier": list(reason.get("qualifier") or []),
                "polarity": "OBSERVED",
                "speech_act": "PLANNING_CONTEXT",
            },
            "source_ids": [reason_id],
            "may_become_target_fact": False,
        })
        matched_truth = next(
            (truth_by_id[value] for value in reason.get("product_truth_ids") or [] if value in truth_by_id),
            None,
        )
        policies.extend(_unconfirmed_reason_policies(brand_name, reason, matched_truth))
    policies.append({
        "claim_id": _claim_id("COMPARISON_RESTRICTED", brand_name),
        "policy": "COMPARISON_RESTRICTED",
        "proposition": {
            "subject": brand_name,
            "predicate": "COMPARES_WITH",
            "object": "NON_TARGET_BRAND",
            "qualifier": [],
            "polarity": "RESTRICTED",
            "speech_act": "COMPARISON",
        },
        "source_ids": [],
        "rule": "NO_COMPARATIVE_CONCLUSION_WITHOUT_EXPLICIT_COMPARISON_EVIDENCE",
    })
    return policies


def _safety_probe_audit(brand_name: str, truths: list[dict]) -> list[dict]:
    allowed_objects = {
        wording
        for truth in truths
        if _truth_is_confirmed(truth)
        for wording in [truth["capability_label"], *(truth.get("approved_aliases") or [])]
    }
    probes = [
        {"object": "自动生成加密短链", "qualifier": ["自动", "加密"]},
        {"object": "平台备案", "qualifier": ["备案"]},
        {"object": "白名单", "qualifier": []},
        {"object": "防封", "qualifier": []},
        {"object": "7天有效率95%以上", "qualifier": ["7天", "95%以上"]},
    ]
    return [
        {
            "proposition": {
                "subject": brand_name,
                "predicate": "SUPPORTS",
                "object": row["object"],
                "qualifier": row["qualifier"],
                "polarity": "AFFIRMATIVE",
                "speech_act": "ASSERTION",
            },
            "decision": "TARGET_ASSERTION_ALLOWED" if row["object"] in allowed_objects else "TARGET_ASSERTION_FORBIDDEN",
            "audit_only": True,
        }
        for row in probes
    ]


def classify_managed_asset_fit(asset: dict, constraint: dict) -> dict:
    checks = {
        "channel_compatible": str(asset.get("channel") or "").upper() == constraint["channel"],
        "asset_type_compatible": str(asset.get("asset_type") or "").upper() in set(constraint["eligible_asset_types"]),
        "theme_compatible": bool(set(asset.get("theme_ids") or []) & set(constraint["theme_ids"])),
        "purpose_compatible": str(asset.get("purpose") or "").upper() == constraint["asset_purpose"],
        "product_truth_capacity_compatible": set(constraint["approved_product_truth_ids"]).issubset(
            {int(value) for value in asset.get("product_truth_ids") or []}
        ),
    }
    passed = sum(1 for value in checks.values() if value)
    if checks["channel_compatible"] and all(checks.values()):
        fit = "HIGH_FIT"
    elif checks["channel_compatible"] and passed >= 3:
        fit = "MEDIUM_FIT"
    elif checks["channel_compatible"]:
        fit = "LOW_FIT"
    else:
        fit = "INELIGIBLE"
    return {
        "managed_asset_id": asset.get("asset_id"),
        "fit": fit,
        "checks": checks,
        "semantic_projection": {
            key: deepcopy(asset.get(key))
            for key in ("asset_id", "channel", "asset_type", "theme_ids", "purpose", "product_truth_ids", "version")
        },
    }


def resolve_asset_operation(managed_assets: list[dict], constraint: dict) -> dict:
    candidates = [classify_managed_asset_fit(asset, constraint) for asset in managed_assets]
    high_fit = [item for item in candidates if item["fit"] == "HIGH_FIT"]
    if len(high_fit) == 1:
        return {
            "asset_operation": "UPDATE_MANAGED",
            "asset_resolution_status": "RESOLVED",
            "managed_asset_candidates": candidates,
            "selected_managed_asset_id": high_fit[0]["managed_asset_id"],
        }
    if len(high_fit) > 1:
        return {
            "asset_operation": "UPDATE_MANAGED",
            "asset_resolution_status": "NEEDS_HUMAN_SELECTION",
            "managed_asset_candidates": candidates,
            "selected_managed_asset_id": None,
        }
    return {
        "asset_operation": "CREATE_NEW",
        "asset_resolution_status": "RESOLVED",
        "managed_asset_candidates": candidates,
        "selected_managed_asset_id": None,
    }


def _proposal_type(role: str) -> str:
    return "CHANNEL_VALIDATION_EXPERIMENT" if role == "TEST" else "AUTHORITATIVE_ASSET_INTERVENTION"


def _asset_type_resolution(proposal_type: str) -> dict:
    if proposal_type == "CHANNEL_VALIDATION_EXPERIMENT":
        return {
            "asset_type_candidates": ["ARTICLE"],
            "recommended_asset_type": "ARTICLE",
            "asset_type_resolution_status": "RESOLVED",
        }
    return {
        "asset_type_candidates": ["PRODUCT_PAGE", "FEATURE_PAGE", "HELP_DOC"],
        "recommended_asset_type": None,
        "asset_type_resolution_status": "NEEDS_HUMAN_SELECTION",
    }


def _theme_scope_for_channel(channel: dict, themes: list[dict]) -> list[dict]:
    reason_ids = set(channel.get("decision_reason_ids") or [])
    related = [theme for theme in themes if reason_ids & set(theme.get("reason_ids") or [])]
    if channel["role"] != "TEST" or len(related) <= 1:
        return related
    # A TEST is a minimum viable validation asset. Prefer the theme with the
    # most channel-bound reasons, then observed coverage, then stable key.
    ranked = sorted(
        related,
        key=lambda theme: (
            -len(reason_ids & set(theme.get("reason_ids") or [])),
            -int(theme.get("theme_observed_run_count") or 0),
            str(theme.get("theme_key") or ""),
        ),
    )
    return ranked[:1]


def _asset_package_candidate(
    channel: dict,
    selected_themes: list[dict],
    all_themes: list[dict],
    reasons: list[dict],
    truths: list[dict],
    eligible_asset_types: list[str],
    scope_mode: str,
) -> dict:
    selected_ids = [row["theme_key"] for row in selected_themes]
    selected_reason_ids = {
        reason_id
        for theme in selected_themes
        for reason_id in theme.get("reason_ids") or []
    }
    selected_reasons = [row for row in reasons if row["reason_id"] in selected_reason_ids]
    selected_truth_ids = {
        truth_id
        for reason in selected_reasons
        for truth_id in reason.get("product_truth_ids") or []
    }
    selected_truths = [row for row in truths if row["product_truth_id"] in selected_truth_ids]
    excluded_themes = [row for row in all_themes if row["theme_key"] not in set(selected_ids)]
    suffix = {
        "FULL_STRATEGY_SCOPE": "all-themes",
        "P1_FOCUS": "p1-focus",
        "MINIMUM_VALIDATION_SCOPE": "minimum",
    }[scope_mode]
    package_key = f"package:{channel['channel_key'].lower()}:{suffix}"
    share_asset_basis = [
        {
            "condition": "SAME_CHANNEL",
            "status": "PASS",
            "evidence": [str(channel.get("object_id") or f"channel_resolution:{channel['channel_key']}")],
        },
        {
            "condition": (
                "SAME_ASSET_PURPOSE"
                if channel["role"] == "TEST"
                else "SAME_AUTHORITY_ASSET_PURPOSE"
            ),
            "status": "PASS",
            "evidence": [
                "MINIMUM_CHANNEL_VALIDATION"
                if channel["role"] == "TEST"
                else "AUTHORITATIVE_PRODUCT_TRUTH"
            ],
        },
    ]
    if selected_truth_ids and selected_truth_ids.issubset({row["product_truth_id"] for row in truths}):
        share_asset_basis.append({
            "condition": "PRODUCT_TRUTH_COMPATIBLE",
            "status": "PASS",
            "evidence": [f"product_truth:{value}" for value in sorted(selected_truth_ids)],
        })
    tradeoffs_by_mode = {
        "FULL_STRATEGY_SCOPE": [
            {"dimension": "THEME_COVERAGE", "value": "FULL"},
            {"dimension": "CONTENT_FOCUS", "value": "BROADER"},
        ],
        "P1_FOCUS": [
            {"dimension": "THEME_COVERAGE", "value": "P1_ONLY"},
            {"dimension": "CONTENT_FOCUS", "value": "HIGHER"},
        ] + [
            {"dimension": "EXCLUDED_THEME", "value": row["theme_key"]} for row in excluded_themes
        ],
        "MINIMUM_VALIDATION_SCOPE": [
            {"dimension": "THEME_COVERAGE", "value": "MINIMUM_TEST_SCOPE"},
            {"dimension": "CONTENT_FOCUS", "value": "CHANNEL_HYPOTHESIS_ONLY"},
        ],
    }
    tradeoffs = tradeoffs_by_mode[scope_mode]
    return {
        "package_key": package_key,
        "asset_package_key": package_key,
        "package_scope_mode": scope_mode,
        "theme_ids": selected_ids,
        "theme_titles": [row.get("title") or row["theme_key"] for row in selected_themes],
        "excluded_theme_ids": [row["theme_key"] for row in excluded_themes],
        "excluded_theme_titles": [row.get("title") or row["theme_key"] for row in excluded_themes],
        "reason_ids": [row["reason_id"] for row in selected_reasons],
        "reason_titles": [row.get("original_reason") or row["reason_id"] for row in selected_reasons],
        "product_truth_ids": [row["product_truth_id"] for row in selected_truths],
        "product_truth_labels": [row["capability_label"] for row in selected_truths],
        "asset_count": 1,
        "concrete_asset_count": 1,
        "eligible_asset_types": list(eligible_asset_types),
        "share_asset_basis": share_asset_basis,
        "packaging_rationale": {
            "code": "ONE_PACKAGE_ONE_CONCRETE_ASSET",
            "parameters": {
                "channel": channel["channel_key"],
                "scope_mode": scope_mode,
                "theme_count": len(selected_themes),
            },
        },
        "tradeoffs": tradeoffs,
        "selection_implication": {
            "selected_scope_mode": scope_mode,
            "excluded_theme_ids": [row["theme_key"] for row in excluded_themes],
            "future_action_count": 1,
            "future_experiment_count": 1,
        },
    }


def _asset_packages(
    channel: dict,
    themes: list[dict],
    all_themes: list[dict],
    reasons: list[dict],
    truths: list[dict],
    eligible_asset_types: list[str],
) -> dict:
    theme_ids = [item["theme_key"] for item in themes]
    if channel["role"] == "TEST" or len(theme_ids) <= 1:
        scope_mode = "MINIMUM_VALIDATION_SCOPE" if channel["role"] == "TEST" else "FULL_STRATEGY_SCOPE"
        rows = [_asset_package_candidate(
            channel, themes, themes, reasons, truths, eligible_asset_types, scope_mode
        )]
        return {
            "asset_package_candidates": rows,
            "selected_asset_package_key": rows[0]["package_key"],
            "asset_package_resolution_status": "RESOLVED",
        }
    p1_themes = [item for item in themes if item.get("priority") == "P1"]
    candidates = [_asset_package_candidate(
        channel, themes, all_themes, reasons, truths, eligible_asset_types, "FULL_STRATEGY_SCOPE"
    )]
    if p1_themes and [row["theme_key"] for row in p1_themes] != theme_ids:
        candidates.append(_asset_package_candidate(
            channel, p1_themes, all_themes, reasons, truths, eligible_asset_types, "P1_FOCUS"
        ))
    return {
        "asset_package_candidates": candidates,
        "selected_asset_package_key": None if len(candidates) > 1 else candidates[0]["package_key"],
        "asset_package_resolution_status": "NEEDS_HUMAN_SELECTION" if len(candidates) > 1 else "RESOLVED",
    }


def _canonical_title(brand_name: str, channel: str, truths: list[dict]) -> dict:
    segments = [{"segment_type": "BRAND", "text": brand_name, "source_ids": []}]
    for truth in truths:
        segments.append({
            "segment_type": "PRODUCT_TRUTH",
            "text": truth["capability_label"],
            "source_ids": [f"product_truth:{truth['product_truth_id']}"],
            "product_truth_id": truth["product_truth_id"],
        })
    segments.append({"segment_type": "GENERIC_SUFFIX", "text": "能力说明" if channel == "OFFICIAL_SITE" else "使用说明", "source_ids": []})
    title = segments[0]["text"]
    if truths:
        title += "：" + "、".join(row["capability_label"] for row in truths)
    title += segments[-1]["text"]
    return {
        "title_candidate_id": f"title:{channel.lower()}:deterministic",
        "title": title,
        "segments": segments,
        "factual_claim_ids": [f"target_assertion:product_truth:{row['product_truth_id']}" for row in truths],
        "generation_mode": "DETERMINISTIC_EXACT_PRODUCT_TRUTH_WORDING",
    }


def _section_plan(
    proposal_key: str,
    proposal_type: str,
    package: dict,
    themes: list[dict],
    reasons: list[dict],
    truths: list[dict],
    required_signal_ids: list[str],
    policies: list[dict],
    eligible_metrics: list[dict],
    baseline_ref: dict,
) -> tuple[list[dict], list[dict]]:
    package_theme_ids = set(package.get("theme_ids") or [])
    scoped_themes = [row for row in themes if row["theme_key"] in package_theme_ids]
    package_reason_ids = set(package.get("reason_ids") or [])
    scoped_reasons = [row for row in reasons if row["reason_id"] in package_reason_ids]
    package_truth_ids = set(package.get("product_truth_ids") or [])
    scoped_truths = [row for row in truths if row["product_truth_id"] in package_truth_ids]
    package_required_signal_ids = [
        value for value in required_signal_ids
        if len(value.split(":")) > 2 and value.split(":")[1] in {str(item) for item in package_truth_ids}
    ]
    theme_by_reason = {
        reason_id: theme["theme_key"]
        for theme in scoped_themes
        for reason_id in theme.get("reason_ids") or []
    }
    def policy_ids(kind: str, *, reason_ids: set[str] | None = None, truth_id: int | None = None) -> list[str]:
        rows = []
        for policy in policies:
            if policy.get("policy") != kind:
                continue
            if truth_id is not None and policy.get("product_truth_id") != truth_id:
                continue
            if reason_ids is not None and not reason_ids.intersection(set(policy.get("source_ids") or [])):
                continue
            rows.append(policy["claim_id"])
        return rows

    section_specs: list[dict] = []
    truth_ids = [row["product_truth_id"] for row in scoped_truths]
    direct_claim_ids = [
        claim_id
        for truth_id in truth_ids
        for claim_id in policy_ids("TARGET_ASSERTION_ALLOWED", truth_id=truth_id)
    ]
    if scoped_themes and direct_claim_ids:
        section_specs.append({
            "purpose": "DIRECT_ANSWER",
            "display_title": "、".join(row.get("title") or row["theme_key"] for row in scoped_themes),
            "theme_ids": [row["theme_key"] for row in scoped_themes],
            "reason_ids": [],
            "product_truth_ids": truth_ids,
            "allowed_claim_ids": direct_claim_ids,
            "planning_context_ids": [],
            "planning_question_ids": [],
            "required_signal_ids": [],
            "eligible_metric_keys": [],
            "rationale_code": "DIRECTLY_ANSWER_SELECTED_PACKAGE_THEMES",
        })
    for truth in scoped_truths:
        truth_id = truth["product_truth_id"]
        related_reasons = [
            row for row in scoped_reasons if truth_id in set(row.get("product_truth_ids") or [])
        ]
        related_theme_ids = _unique([
            theme_by_reason[row["reason_id"]]
            for row in related_reasons
            if row["reason_id"] in theme_by_reason
        ])
        claim_ids = policy_ids("TARGET_ASSERTION_ALLOWED", truth_id=truth_id)
        section_specs.append({
            "purpose": "PRODUCT_TRUTH",
            "display_title": truth["capability_label"],
            "theme_ids": related_theme_ids,
            "reason_ids": [],
            "product_truth_ids": [truth_id],
            "allowed_claim_ids": claim_ids,
            "planning_context_ids": [],
            "planning_question_ids": [],
            "required_signal_ids": [
                value for value in package_required_signal_ids if f":{truth_id}:" in value
            ],
            "eligible_metric_keys": [],
            "rationale_code": "ESTABLISH_CONFIRMED_PRODUCT_TRUTH",
        })
    scenario_reasons = [
        row for row in scoped_reasons
        if any(str(value).upper() not in {"", "GENERAL", "UNKNOWN"} for value in row.get("scenario") or [])
    ]
    for reason in scenario_reasons:
        reason_id = reason["reason_id"]
        context_ids = policy_ids("PLANNING_CONTEXT_ALLOWED", reason_ids={reason_id})
        if context_ids:
            section_specs.append({
                "purpose": "SCENARIO",
                "display_title": next(
                    (
                        f"{theme.get('title') or theme['theme_key']}使用场景"
                        for theme in scoped_themes
                        if theme["theme_key"] == theme_by_reason.get(reason_id)
                    ),
                    "使用场景",
                ),
                "theme_ids": [theme_by_reason[reason_id]] if reason_id in theme_by_reason else [],
                "reason_ids": [reason_id],
                "product_truth_ids": [],
                "allowed_claim_ids": [],
                "planning_context_ids": context_ids,
                "planning_question_ids": [],
                "required_signal_ids": [],
                "eligible_metric_keys": [],
                "rationale_code": "EXPLAIN_OBSERVED_DECISION_SCENARIO",
            })
    boundary_kinds = {
        "TARGET_ASSERTION_FORBIDDEN",
        "UNKNOWN_MUST_REMAIN_UNKNOWN",
        "COMPARISON_RESTRICTED",
    }
    boundary_policies = [
        row for row in policies
        if row.get("policy") in boundary_kinds
        and (
            row.get("policy") == "COMPARISON_RESTRICTED"
            or package_reason_ids.intersection(set(row.get("source_ids") or []))
        )
    ]
    if boundary_policies:
        boundary_reason_ids = _unique([
            source_id
            for row in boundary_policies
            for source_id in row.get("source_ids") or []
            if source_id in package_reason_ids
        ])
        section_specs.append({
            "purpose": "BOUNDARY",
            "display_title": "事实边界",
            "theme_ids": _unique([theme_by_reason[value] for value in boundary_reason_ids if value in theme_by_reason]),
            "reason_ids": boundary_reason_ids,
            "product_truth_ids": [],
            "allowed_claim_ids": [],
            "planning_context_ids": policy_ids("PLANNING_CONTEXT_ALLOWED", reason_ids=set(boundary_reason_ids)),
            "planning_question_ids": policy_ids("PLANNING_QUESTION", reason_ids=set(boundary_reason_ids)),
            "required_signal_ids": [],
            "eligible_metric_keys": [],
            "rationale_code": "PRESERVE_UNKNOWN_AND_RESTRICTED_CLAIMS",
            "extra_policy_ids": [row["claim_id"] for row in boundary_policies],
        })
    if eligible_metrics or package_required_signal_ids:
        section_specs.append({
            "purpose": "VALIDATION",
            "display_title": "验证观察",
            "theme_ids": [row["theme_key"] for row in scoped_themes],
            "reason_ids": [],
            "product_truth_ids": [],
            "allowed_claim_ids": [],
            "planning_context_ids": [],
            "planning_question_ids": [],
            "required_signal_ids": list(package_required_signal_ids),
            "eligible_metric_keys": [row["metric_key"] for row in eligible_metrics],
            "rationale_code": "DEFINE_NON_CAUSAL_OBSERVATION_PLAN",
        })
    publishable_questions = [row for row in policies if row.get("policy") == "PUBLISHABLE_QUESTION_ALLOWED"]
    if proposal_type == "AUTHORITATIVE_ASSET_INTERVENTION" and publishable_questions:
        section_specs.append({
            "purpose": "FAQ",
            "display_title": "常见问题",
            "theme_ids": [row["theme_key"] for row in scoped_themes],
            "reason_ids": [],
            "product_truth_ids": _unique([row.get("product_truth_id") for row in publishable_questions if row.get("product_truth_id") in package_truth_ids]),
            "allowed_claim_ids": [],
            "planning_context_ids": [],
            "planning_question_ids": [],
            "required_signal_ids": [],
            "eligible_metric_keys": [],
            "rationale_code": "PUBLISH_CONFIRMED_PRODUCT_QUESTIONS_ONLY",
            "extra_policy_ids": [row["claim_id"] for row in publishable_questions if row.get("product_truth_id") in package_truth_ids],
        })
    sections = []
    blocks = []
    for index, spec in enumerate(section_specs, start=1):
        purpose = spec["purpose"]
        package_token = _slug(str(package.get("package_key") or "unknown-package"))
        section_id = f"section:{proposal_key}:{package_token}:{index}:{purpose.lower()}"
        claim_usage_policy_ids = _unique(
            spec["allowed_claim_ids"]
            + spec["planning_context_ids"]
            + spec["planning_question_ids"]
            + spec.get("extra_policy_ids", [])
        )
        section = {
            "section_id": section_id,
            "section_purpose": purpose,
            "display_title": spec["display_title"],
            "theme_ids": spec["theme_ids"],
            "reason_ids": spec["reason_ids"],
            "product_truth_ids": spec["product_truth_ids"],
            "allowed_claim_ids": spec["allowed_claim_ids"],
            "planning_context_ids": spec["planning_context_ids"],
            "planning_question_ids": spec["planning_question_ids"],
            "required_signal_ids": spec["required_signal_ids"],
            "eligible_metric_keys": spec["eligible_metric_keys"],
            "baseline_ref": deepcopy(baseline_ref) if purpose == "VALIDATION" else None,
            "claim_usage_policy_ids": claim_usage_policy_ids,
            "section_rationale_code": spec["rationale_code"],
            "why_this_section_exists": {
                "code": spec["rationale_code"],
                "parameters": {
                    "theme_ids": spec["theme_ids"],
                    "product_truth_ids": spec["product_truth_ids"],
                    "reason_ids": spec["reason_ids"],
                },
            },
        }
        sections.append(section)
        blocks.append({
            "block_id": f"block:{proposal_key}:{package_token}:{index}",
            "block_type": "MINIMUM_VALIDATION_BLOCK" if proposal_type == "CHANNEL_VALIDATION_EXPERIMENT" else "GROUNDED_CONTENT_BLOCK",
            "section_id": section_id,
            "purpose": purpose,
            "theme_ids": list(spec["theme_ids"]),
            "reason_ids": list(spec["reason_ids"]),
            "product_truth_ids": list(spec["product_truth_ids"]),
            "allowed_claim_ids": list(spec["allowed_claim_ids"]),
            "planning_context_ids": list(spec["planning_context_ids"]),
            "planning_question_ids": list(spec["planning_question_ids"]),
            "required_signal_ids": list(spec["required_signal_ids"]),
            "eligible_metric_keys": list(spec["eligible_metric_keys"]),
        })
    return sections, blocks


def _signal_ids_with_prefix(signal_ids: list[str], prefix: str) -> list[str]:
    return [value for value in signal_ids if value.startswith(f"{prefix}:")]


def _channel_opportunity_profile(channel: dict, themes: list[dict], reasons: list[dict]) -> dict:
    signal_ids = _unique([str(value) for value in channel.get("supporting_signal_ids") or []])
    references = _signal_ids_with_prefix(signal_ids, "reference")
    retrievals = _signal_ids_with_prefix(signal_ids, "retrieval")
    claims = _signal_ids_with_prefix(signal_ids, "source_claim")
    documents = _signal_ids_with_prefix(signal_ids, "source_document")
    if retrievals:
        distinction = "EXISTING_RETRIEVAL_EXPOSURE"
    elif references:
        distinction = "REFERENCE_ENVIRONMENT_WITHOUT_RETRIEVAL"
    else:
        distinction = "UNSUPPORTED_PATTERN"
    object_id = str(channel.get("object_id") or "")
    return {
        "channel": channel["channel_key"],
        "reference_observations": len(references),
        "retrieval_observations": len(retrievals),
        "source_claim_count": len(claims),
        "source_document_count": len(documents),
        "reason_ids": [row["reason_id"] for row in reasons],
        "theme_ids": [row["theme_key"] for row in themes],
        "exposure_signals": references + retrievals,
        "reason_relevance_signals": claims + [row["reason_id"] for row in reasons],
        "target_gap_signals": [{"code": "NO_FORMAL_TARGET_DECISION_OR_SUPPORT_ADOPTION", "source_ids": [object_id]}],
        "intervention_fit_signals": [{
            "code": str(channel.get("rationale_path") or "UNRESOLVED"),
            "state": channel.get("intervention_fit") or "UNKNOWN",
            "source_ids": [object_id],
        }],
        "why_test_signals": [{
            "code": "PATH_D_TEST_ONLY",
            "state": channel.get("information_value") or "UNKNOWN",
            "source_ids": [object_id],
        }],
        "why_not_primary_signals": [
            {"code": "NO_ELIGIBLE_TARGET_DECISION_CITATION", "source_ids": [object_id]},
            {"code": "NO_ELIGIBLE_TARGET_ANSWER_SUPPORT", "source_ids": [object_id]},
            {"code": "NO_PATH_A_B_C_QUALIFICATION", "source_ids": [object_id]},
        ],
        "cross_channel_distinction": distinction,
        "resolver_rationale": channel.get("resolver_rationale") or "",
    }


def _test_hypothesis(channel: dict, profile: dict, themes: list[dict], reasons: list[dict]) -> dict:
    pattern = profile["cross_channel_distinction"]
    if pattern == "EXISTING_RETRIEVAL_EXPOSURE":
        text = (
            f"当前{channel['channel_label']}消费范围已有 {profile['retrieval_observations']} 条 Retrieval observation；"
            "验证目标品牌最小资产是否进入或扩大 Retrieval observation，并进一步出现 Citation observation。"
        )
    elif pattern == "REFERENCE_ENVIRONMENT_WITHOUT_RETRIEVAL":
        text = (
            f"当前{channel['channel_label']}消费范围有 {profile['reference_observations']} 条 Reference observation，"
            "没有 Retrieval observation；验证目标品牌最小资产是否先进入 Retrieval，并进一步出现 Citation observation。"
        )
    else:
        text = f"当前{channel['channel_label']}没有可支持自动生成渠道假设的已知 exposure pattern。"
    return {
        "speech_act": "HYPOTHESIS",
        "pattern": pattern,
        "text": text,
        "causal_claim": False,
        "theme_ids": [row["theme_key"] for row in themes],
        "reason_ids": [row["reason_id"] for row in reasons],
        "why_this_channel_is_worth_testing": profile["why_test_signals"],
        "why_not_primary": profile["why_not_primary_signals"],
        "cross_channel_distinction": pattern,
    }


def _package_metric_rows(package_payload: dict) -> dict[str, dict]:
    return {
        str(row.get("metric_name")): deepcopy(row)
        for row in package_payload.get("metrics") or []
        if isinstance(row, dict) and row.get("metric_name")
    }


def _baseline_status(row: dict | None) -> str:
    if not row:
        return "CALCULATION_FAILED"
    status = str(row.get("calculation_status") or "").lower()
    if status == "not_applicable":
        return "NOT_APPLICABLE"
    if status != "ok":
        return "CALCULATION_FAILED"
    denominator = int(row.get("denominator") or 0)
    numerator = int(row.get("numerator") or 0)
    if denominator <= 0:
        return "CALCULATION_FAILED"
    return "ZERO_OBSERVED" if numerator == 0 else "BASELINE_AVAILABLE"


def _eligible_metrics(proposal_type: str, operation: str, package_payload: dict) -> list[dict]:
    package_rows = _package_metric_rows(package_payload)
    preferred = (
        ["official_reference_rate", "brand_mention_rate", "brand_recommendation_rate"]
        if proposal_type == "AUTHORITATIVE_ASSET_INTERVENTION"
        else ["selected_asset_retrieval_presence", "selected_asset_citation_presence", "brand_mention_rate", "brand_recommendation_rate"]
    )
    result = []
    for key in preferred:
        spec = FORMAL_METRIC_CALCULATORS[key]
        if proposal_type not in spec["proposal_types"]:
            continue
        if spec["measurement_level"] == "SELECTED_ASSET" and operation == "CREATE_NEW":
            baseline_status = "NOT_MEASURABLE_YET"
            row = None
        else:
            row = package_rows.get(key)
            baseline_status = _baseline_status(row)
        result.append({
            "metric_key": key,
            "metric_contract_version": METRIC_CONTRACT_VERSION,
            "measurement_level": spec["measurement_level"],
            "calculator": spec["calculator"],
            "baseline_semantics": "FIXED_EVIDENCE_PACKAGE_RUN_SCOPE",
            "baseline_source": (
                "SELECTED_ASSET_NOT_CREATED"
                if baseline_status == "NOT_MEASURABLE_YET"
                else "FROZEN_EVIDENCE_PACKAGE_METRIC"
            ),
            "baseline_status": baseline_status,
            "baseline": deepcopy(row),
        })
    return result


def _snapshot_semantic_projection(context: dict, managed_assets: list[dict]) -> dict:
    truths = [
        {
            "product_truth_id": row["product_truth_id"],
            "capability_label": row["capability_label"],
            "approved_aliases": row.get("approved_aliases") or [],
            "product_truth_status": row["product_truth_status"],
            "truth_source": row["truth_source"],
        }
        for row in context["product_truths"]
    ]
    channels = [
        {
            "channel_key": row["channel_key"],
            "role": row["role"],
            "decision_reason_ids": row.get("decision_reason_ids") or [],
        }
        for row in context["channel_resolutions"]
    ]
    return {
        "contract_version": CONTRACT_VERSION,
        "strategy_candidate_id": context["strategy_candidate_id"],
        "strategy_candidate_semantic_hash": context["strategy_candidate_semantic_hash"],
        "strategy_contract_version": context["strategy_contract_version"],
        "evidence_package_id": context["evidence_package_id"],
        "evidence_package_version": context["evidence_package_version"],
        "metric_spec_version": context["metric_spec_version"],
        "baseline_run_ids": context["baseline_run_ids"],
        "strategy_analyzable_run_ids": context["strategy_analyzable_run_ids"],
        "theme_membership": [
            {"theme_key": row["theme_key"], "reason_ids": row.get("reason_ids") or [], "priority": row.get("priority")}
            for row in context["themes"]
        ],
        "product_truths": truths,
        "channel_roles": channels,
        "managed_asset_semantic_projection": [
            {key: deepcopy(row.get(key)) for key in ("asset_id", "channel", "asset_type", "theme_ids", "purpose", "product_truth_ids", "version")}
            for row in managed_assets
        ],
        "metric_contract_version": METRIC_CONTRACT_VERSION,
    }


def _execution_input_snapshot(context: dict, managed_assets: list[dict]) -> dict:
    semantic = _snapshot_semantic_projection(context, managed_assets)
    reason_ids = [row["reason_id"] for row in context["decision_reasons"]]
    theme_ids = [row["theme_key"] for row in context["themes"]]
    truth_ids = [row["product_truth_id"] for row in context["product_truths"]]
    active_keys = set(context["active_channel_keys"])
    signal_ids = _unique([
        value
        for row in context["channel_resolutions"]
        if row["channel_key"] in active_keys
        for value in row.get("supporting_signal_ids") or []
    ])
    return {
        "snapshot_mode": SNAPSHOT_MODE,
        "snapshot_id": None,
        "strategy_candidate_id": context["strategy_candidate_id"],
        "strategy_candidate_hash": context["strategy_candidate_semantic_hash"],
        "strategy_contract_version": context["strategy_contract_version"],
        "evidence_package_id": context["evidence_package_id"],
        "evidence_package_version": context["evidence_package_version"],
        "baseline_run_ids": context["baseline_run_ids"],
        "strategy_analyzable_run_ids": context["strategy_analyzable_run_ids"],
        "product_truth_snapshot_ref": {
            "object_ids": [f"product_truth:{value}" for value in truth_ids],
            "projection_hash": _stable_hash(semantic["product_truths"]),
        },
        "channel_evidence_snapshot_ref": context["channel_evidence_snapshot_ref"],
        "channel_resolution_snapshot_ref": {
            "object_ids": [row["object_id"] for row in context["channel_resolutions"]],
            "projection_hash": _stable_hash(semantic["channel_roles"]),
        },
        "managed_asset_snapshot_ref": {
            "snapshot_mode": SNAPSHOT_MODE,
            "managed_asset_count": len(managed_assets),
            "projection_hash": _stable_hash(semantic["managed_asset_semantic_projection"]),
        },
        "consumed_theme_ids": theme_ids,
        "consumed_reason_ids": reason_ids,
        "consumed_product_truth_ids": truth_ids,
        "consumed_signal_ids": signal_ids,
        "minimum_evidence_projection": {
            "theme_ids": theme_ids,
            "reason_ids": reason_ids,
            "product_truth_ids": truth_ids,
            "channel_signal_ids": signal_ids,
            "required_signal_ids": context["required_signal_ids"],
            "baseline_ref": {
                "evidence_package_id": context["evidence_package_id"],
                "run_ids_hash": _stable_hash(context["baseline_run_ids"]),
                "run_count": len(context["baseline_run_ids"]),
            },
        },
        "input_contract_hash": _stable_hash(semantic),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _proposal_constraint(
    context: dict,
    channel: dict,
    themes: list[dict],
    reasons: list[dict],
    truths: list[dict],
    required_signals: list[str],
) -> dict:
    proposal_type = _proposal_type(channel["role"])
    type_resolution = _asset_type_resolution(proposal_type)
    return {
        "strategy_snapshot_ref": context["strategy_candidate_id"],
        "channel": channel["channel_key"],
        "channel_role": channel["role"],
        "proposal_type": proposal_type,
        "eligible_channels": [channel["channel_key"]],
        "eligible_intervention_types": [proposal_type],
        "theme_ids": [row["theme_key"] for row in themes],
        "reason_ids": [row["reason_id"] for row in reasons],
        "approved_product_truth_ids": [row["product_truth_id"] for row in truths],
        "eligible_asset_types": type_resolution["asset_type_candidates"],
        "asset_purpose": "MINIMUM_CHANNEL_VALIDATION" if channel["role"] == "TEST" else "AUTHORITATIVE_PRODUCT_TRUTH",
        "required_signals": required_signals,
        "baseline_snapshot": {
            "evidence_package_id": context["evidence_package_id"],
            "baseline_run_ids": context["baseline_run_ids"],
        },
        "forbidden_transforms": [
            "CREATE_PRODUCT_TRUTH",
            "CHANGE_CHANNEL_ROLE",
            "CREATE_UNMANAGED_ASSET_IDENTITY",
            "INVENT_METRIC",
            "REPLACE_BASELINE_RUN_SCOPE",
            "PUBLISH_UNKNOWN_AS_FACT",
        ],
    }


def _build_proposal(context: dict, channel: dict, managed_assets: list[dict]) -> dict:
    themes = _theme_scope_for_channel(channel, context["themes"])
    theme_reason_ids = {value for theme in themes for value in theme.get("reason_ids") or []}
    channel_reason_ids = set(channel.get("decision_reason_ids") or [])
    reason_ids = theme_reason_ids & channel_reason_ids if channel_reason_ids else theme_reason_ids
    reasons = [row for row in context["decision_reasons"] if row["reason_id"] in reason_ids]
    truth_ids = {value for row in reasons for value in row.get("product_truth_ids") or []}
    truths = [row for row in context["product_truths"] if row["product_truth_id"] in truth_ids and _truth_is_confirmed(row)]
    proposal_type = _proposal_type(channel["role"])
    type_resolution = _asset_type_resolution(proposal_type)
    required_signals = _unique([
        value for value in context["required_signal_ids"]
        if not truth_ids or (len(value.split(":")) > 2 and value.split(":")[1] in {str(item) for item in truth_ids})
    ])
    package_resolution = _asset_packages(
        channel,
        themes,
        context["themes"] if channel["role"] != "TEST" else themes,
        reasons,
        truths,
        type_resolution["asset_type_candidates"],
    )
    constraint = _proposal_constraint(context, channel, themes, reasons, truths, required_signals)
    asset_resolution = resolve_asset_operation(managed_assets, constraint)
    policies = build_claim_usage_policy(context["brand_name"], truths, reasons)
    title = _canonical_title(context["brand_name"], channel["channel_key"], truths)
    proposal_key = f"proposal:{context['strategy_candidate_id']}:{channel['channel_key'].lower()}"
    channel_signals = _unique([str(value) for value in channel.get("supporting_signal_ids") or []])
    metrics = _eligible_metrics(proposal_type, asset_resolution["asset_operation"], context["package_payload"])
    baseline_ref = {
        "evidence_package_id": context["evidence_package_id"],
        "evidence_package_version": context["evidence_package_version"],
        "baseline_run_ids": context["baseline_run_ids"],
        "strategy_analyzable_run_ids": context["strategy_analyzable_run_ids"],
    }
    section_plan_candidates = []
    for package in package_resolution["asset_package_candidates"]:
        sections, blocks = _section_plan(
            proposal_key,
            proposal_type,
            package,
            themes,
            reasons,
            truths,
            required_signals,
            policies,
            metrics,
            baseline_ref,
        )
        section_plan_candidates.append({
            "asset_package_key": package["package_key"],
            "section_plan": sections,
            "content_block_plan": blocks,
        })
    selected_package_key = package_resolution["selected_asset_package_key"]
    selected_section_candidate = next(
        (
            row for row in section_plan_candidates
            if row["asset_package_key"] == selected_package_key
        ),
        None,
    )
    sections = deepcopy((selected_section_candidate or {}).get("section_plan") or [])
    blocks = deepcopy((selected_section_candidate or {}).get("content_block_plan") or [])
    has_usable_baseline = any(
        row["baseline_status"] in {"BASELINE_AVAILABLE", "ZERO_OBSERVED"}
        for row in metrics
        if row["measurement_level"] != "SELECTED_ASSET"
    )
    resolution_states = [
        asset_resolution["asset_resolution_status"],
        type_resolution["asset_type_resolution_status"],
        package_resolution["asset_package_resolution_status"],
    ]
    if not has_usable_baseline:
        readiness = "BLOCKED_BY_CONSTRAINT"
    elif "INVALID" in resolution_states:
        readiness = "BLOCKED_BY_CONSTRAINT"
    elif "NEEDS_HUMAN_SELECTION" in resolution_states:
        readiness = "NEEDS_HUMAN_SELECTION"
    else:
        readiness = "READY_FOR_REVIEW"
    new_asset_spec = None
    if asset_resolution["asset_operation"] == "CREATE_NEW":
        new_asset_spec = {
            "spec_type": "NEW_ASSET_SPEC",
            "managed_asset_id": None,
            "published_url": None,
            "channel": channel["channel_key"],
            "asset_type_candidates": type_resolution["asset_type_candidates"],
            "theme_ids": [row["theme_key"] for row in themes],
            "reason_ids": [row["reason_id"] for row in reasons],
            "product_truth_ids": [row["product_truth_id"] for row in truths],
            "title_candidate_ids": [title["title_candidate_id"]],
            "section_ids": [row["section_id"] for row in sections],
            "section_plan_candidate_refs": [
                {
                    "asset_package_key": row["asset_package_key"],
                    "section_ids": [section["section_id"] for section in row["section_plan"]],
                }
                for row in section_plan_candidates
            ],
        }
    hypothesis = None
    opportunity_profile = None
    if channel["role"] == "TEST":
        opportunity_profile = _channel_opportunity_profile(channel, themes, reasons)
        hypothesis = _test_hypothesis(channel, opportunity_profile, themes, reasons)
    proposal = {
        "proposal_key": proposal_key,
        "proposal_status": "SHADOW",
        "channel": channel["channel_key"],
        "channel_label": channel["channel_label"],
        "channel_role": channel["role"],
        "proposal_type": proposal_type,
        "theme_ids": [row["theme_key"] for row in themes],
        "reason_ids": [row["reason_id"] for row in reasons],
        "product_truth_ids": [row["product_truth_id"] for row in truths],
        **asset_resolution,
        **type_resolution,
        **package_resolution,
        "proposal_readiness": readiness,
        "new_asset_spec": new_asset_spec,
        "claim_usage_policy": policies,
        "title_candidates": [title],
        "section_plan": sections,
        "content_block_plan": blocks,
        "section_plan_candidates": section_plan_candidates,
        "section_plan_resolution_status": (
            "RESOLVED" if selected_section_candidate else "NEEDS_HUMAN_SELECTION"
        ),
        "required_signals": required_signals,
        "channel_signal_ids": channel_signals,
        "channel_opportunity_profile": opportunity_profile,
        "eligible_metrics": metrics,
        "intervention_hypothesis": hypothesis,
        "validation_plan": {
            "baseline_ref": {
                "evidence_package_id": context["evidence_package_id"],
                "baseline_run_ids": context["baseline_run_ids"],
                "baseline_run_count": len(context["baseline_run_ids"]),
            },
            "observation_window_candidates": [context["resampling_plan"]],
            "observation_window_resolution_status": "RESOLVED",
            "human_conclusion_required": True,
        },
        "baseline_ref": baseline_ref,
        "execution_constraint": constraint,
        "provenance": {
            "strategy_candidate_id": context["strategy_candidate_id"],
            "channel_resolution_id": channel["object_id"],
            "theme_ids": [row["theme_key"] for row in themes],
            "reason_ids": [row["reason_id"] for row in reasons],
            "product_truth_ids": [row["product_truth_id"] for row in truths],
            "signal_ids": required_signals,
        },
        "attribution_contract": {
            "intervention_proposal_count": 1,
            "required_selected_asset_package_count": 1,
            "current_selected_asset_package_count": 1 if package_resolution["selected_asset_package_key"] else 0,
            "concrete_asset_count": 1,
            "future_action_count": 1,
            "future_experiment_count": 1,
        },
    }
    return proposal


def validate_snapshot(context: dict, snapshot: dict) -> dict:
    errors = []
    if snapshot.get("snapshot_mode") != SNAPSHOT_MODE or snapshot.get("snapshot_id") is not None:
        errors.append("INVALID_EPHEMERAL_SNAPSHOT_IDENTITY")
    if snapshot.get("strategy_candidate_hash") != context["strategy_candidate_semantic_hash"]:
        errors.append("STRATEGY_CANDIDATE_HASH_DRIFT")
    if snapshot.get("evidence_package_id") != context["evidence_package_id"]:
        errors.append("EVIDENCE_PACKAGE_ID_DRIFT")
    if snapshot.get("evidence_package_version") != context["evidence_package_version"]:
        errors.append("EVIDENCE_PACKAGE_VERSION_DRIFT")
    if snapshot.get("baseline_run_ids") != context["baseline_run_ids"]:
        errors.append("BASELINE_RUN_SCOPE_DRIFT")
    if snapshot.get("strategy_analyzable_run_ids") != context["strategy_analyzable_run_ids"]:
        errors.append("STRATEGY_RUN_SCOPE_DRIFT")
    expected_truth_ids = {f"product_truth:{row['product_truth_id']}" for row in context["product_truths"]}
    if set((snapshot.get("product_truth_snapshot_ref") or {}).get("object_ids") or []) != expected_truth_ids:
        errors.append("PRODUCT_TRUTH_SNAPSHOT_REF_DRIFT")
    if not (snapshot.get("channel_resolution_snapshot_ref") or {}).get("object_ids"):
        errors.append("MISSING_CHANNEL_RESOLUTION_REFS")
    return _validator(errors)


def validate_channel_roles(context: dict, proposals: list[dict]) -> dict:
    roles = {row["channel_key"]: row["role"] for row in context["channel_resolutions"]}
    errors = []
    for proposal in proposals:
        channel = proposal.get("channel")
        expected_role = roles.get(channel)
        if expected_role is None:
            errors.append(f"NEW_CHANNEL:{channel}")
            continue
        if proposal.get("channel_role") != expected_role:
            errors.append(f"ROLE_MUTATION:{channel}:{expected_role}->{proposal.get('channel_role')}")
        expected_type = _proposal_type(expected_role)
        if proposal.get("proposal_type") != expected_type:
            errors.append(f"PROPOSAL_TYPE_ROLE_MISMATCH:{channel}")
    return _validator(errors)


def validate_asset_fit(proposals: list[dict], managed_assets: list[dict]) -> dict:
    managed_ids = {row.get("asset_id") for row in managed_assets}
    errors = []
    for proposal in proposals:
        if proposal.get("asset_resolution_status") not in VALID_RESOLUTION_STATUSES:
            errors.append(f"INVALID_ASSET_RESOLUTION:{proposal.get('proposal_key')}")
        operation = proposal.get("asset_operation")
        if operation == "CREATE_NEW":
            spec = proposal.get("new_asset_spec")
            if not spec:
                errors.append(f"CREATE_NEW_WITHOUT_NEW_ASSET_SPEC:{proposal.get('proposal_key')}")
            elif spec.get("managed_asset_id") is not None or spec.get("published_url") is not None:
                errors.append(f"FAKE_MANAGED_ASSET:{proposal.get('proposal_key')}")
            if proposal.get("selected_managed_asset_id") is not None:
                errors.append(f"CREATE_NEW_REFERENCES_MANAGED_ASSET:{proposal.get('proposal_key')}")
        elif operation == "UPDATE_MANAGED":
            if proposal.get("new_asset_spec") is not None:
                errors.append(f"UPDATE_MANAGED_HAS_NEW_ASSET_SPEC:{proposal.get('proposal_key')}")
            selected = proposal.get("selected_managed_asset_id")
            if selected is not None and selected not in managed_ids:
                errors.append(f"UNKNOWN_MANAGED_ASSET:{selected}")
            high_fit = [row for row in proposal.get("managed_asset_candidates") or [] if row.get("fit") == "HIGH_FIT"]
            if not high_fit:
                errors.append(f"UPDATE_MANAGED_WITHOUT_HIGH_FIT:{proposal.get('proposal_key')}")
        else:
            errors.append(f"INVALID_ASSET_OPERATION:{operation}")
    return _validator(errors)


def validate_claim_grounding(context: dict, proposals: list[dict]) -> dict:
    truths = {row["product_truth_id"]: row for row in context["product_truths"]}
    errors = []
    for proposal in proposals:
        for claim in proposal.get("claim_usage_policy") or []:
            policy = claim.get("policy")
            if policy not in VALID_CLAIM_POLICIES:
                errors.append(f"UNKNOWN_CLAIM_POLICY:{policy}")
                continue
            if policy != "TARGET_ASSERTION_ALLOWED":
                continue
            truth = truths.get(claim.get("product_truth_id"))
            proposition = claim.get("proposition") or {}
            allowed_wording = set()
            if truth:
                allowed_wording = {truth["capability_label"], *(truth.get("approved_aliases") or [])}
            if not truth or not _truth_is_confirmed(truth):
                errors.append(f"UNCONFIRMED_TARGET_ASSERTION:{claim.get('claim_id')}")
            elif proposition.get("object") not in allowed_wording or proposition.get("qualifier"):
                errors.append(f"UNAPPROVED_TARGET_ASSERTION_WORDING:{claim.get('claim_id')}")
            if claim.get("source_ids") != [f"product_truth:{claim.get('product_truth_id')}"]:
                errors.append(f"TARGET_ASSERTION_PROVENANCE_MISMATCH:{claim.get('claim_id')}")
    return _validator(errors)


def _render_title_segments(segments: list[dict]) -> str:
    brand = next((row.get("text") for row in segments if row.get("segment_type") == "BRAND"), "")
    truths = [row.get("text") for row in segments if row.get("segment_type") == "PRODUCT_TRUTH"]
    suffix = next((row.get("text") for row in segments if row.get("segment_type") == "GENERIC_SUFFIX"), "")
    return f"{brand}{'：' + '、'.join(truths) if truths else ''}{suffix}"


def validate_title_claims(context: dict, proposals: list[dict]) -> dict:
    truth_by_id = {row["product_truth_id"]: row for row in context["product_truths"]}
    errors = []
    for proposal in proposals:
        allowed_claim_ids = {
            row["claim_id"] for row in proposal.get("claim_usage_policy") or []
            if row.get("policy") == "TARGET_ASSERTION_ALLOWED"
        }
        for title in proposal.get("title_candidates") or []:
            if title.get("title") != _render_title_segments(title.get("segments") or []):
                errors.append(f"NON_CANONICAL_TITLE_TEXT:{title.get('title_candidate_id')}")
            for claim_id in title.get("factual_claim_ids") or []:
                if claim_id not in allowed_claim_ids:
                    errors.append(f"UNGROUNDED_TITLE_CLAIM:{claim_id}")
            for segment in title.get("segments") or []:
                if segment.get("segment_type") != "PRODUCT_TRUTH":
                    continue
                truth = truth_by_id.get(segment.get("product_truth_id"))
                allowed_wording = {truth["capability_label"], *(truth.get("approved_aliases") or [])} if truth else set()
                if not truth or segment.get("text") not in allowed_wording:
                    errors.append(f"UNAPPROVED_TITLE_CAPABILITY:{segment.get('text')}")
    return _validator(errors)


def validate_section_provenance(context: dict, proposals: list[dict]) -> dict:
    valid_themes = {row["theme_key"] for row in context["themes"]}
    valid_reasons = {row["reason_id"] for row in context["decision_reasons"]}
    valid_truths = {row["product_truth_id"] for row in context["product_truths"]}
    errors = []
    for proposal in proposals:
        policies = {row["claim_id"]: row for row in proposal.get("claim_usage_policy") or []}
        policy_ids = set(policies)
        plan_candidates = proposal.get("section_plan_candidates") or []
        packages = {
            row.get("package_key"): row for row in proposal.get("asset_package_candidates") or []
        }
        plans = [
            {
                "asset_package_key": proposal.get("selected_asset_package_key"),
                "section_plan": proposal.get("section_plan") or [],
                "content_block_plan": proposal.get("content_block_plan") or [],
            }
        ] + plan_candidates
        for plan in plans:
            package = packages.get(plan.get("asset_package_key")) or {}
            package_theme_ids = set(package.get("theme_ids") or [])
            package_reason_ids = set(package.get("reason_ids") or [])
            package_truth_ids = set(package.get("product_truth_ids") or [])
            blocks_by_section = {
                row.get("section_id"): row for row in plan.get("content_block_plan") or []
            }
            for section in plan.get("section_plan") or []:
                section_id = section.get("section_id") or "UNKNOWN"
                if section.get("section_purpose") not in VALID_SECTION_PURPOSES:
                    errors.append(f"INVALID_SECTION_PURPOSE:{section_id}")
                if not section.get("display_title") or not section.get("why_this_section_exists"):
                    errors.append(f"SECTION_MISSING_AUDIT_LABEL:{section_id}")
                if not any(section.get(field) for field in (
                    "theme_ids",
                    "reason_ids",
                    "product_truth_ids",
                    "required_signal_ids",
                    "claim_usage_policy_ids",
                    "eligible_metric_keys",
                )):
                    errors.append(f"SECTION_WITHOUT_PROVENANCE:{section_id}")
                if not set(section.get("theme_ids") or []).issubset(valid_themes):
                    errors.append(f"UNKNOWN_SECTION_THEME:{section_id}")
                if not set(section.get("reason_ids") or []).issubset(valid_reasons):
                    errors.append(f"UNKNOWN_SECTION_REASON:{section_id}")
                if not set(section.get("product_truth_ids") or []).issubset(valid_truths):
                    errors.append(f"UNKNOWN_SECTION_PRODUCT_TRUTH:{section_id}")
                if not set(section.get("claim_usage_policy_ids") or []).issubset(policy_ids):
                    errors.append(f"UNKNOWN_SECTION_CLAIM_POLICY:{section_id}")
                if package and (
                    not set(section.get("theme_ids") or []).issubset(package_theme_ids)
                    or not set(section.get("reason_ids") or []).issubset(package_reason_ids)
                    or not set(section.get("product_truth_ids") or []).issubset(package_truth_ids)
                ):
                    errors.append(f"SECTION_PROVENANCE_OVERBROAD:{section_id}")
                purpose = section.get("section_purpose")
                allowed_ids = set(section.get("allowed_claim_ids") or [])
                planning_context_ids = set(section.get("planning_context_ids") or [])
                planning_question_ids = set(section.get("planning_question_ids") or [])
                if allowed_ids and any(
                    (policies.get(value) or {}).get("policy") != "TARGET_ASSERTION_ALLOWED"
                    for value in allowed_ids
                ):
                    errors.append(f"SECTION_ALLOWED_CLAIM_POLICY_MISMATCH:{section_id}")
                if planning_context_ids and any(
                    (policies.get(value) or {}).get("policy") != "PLANNING_CONTEXT_ALLOWED"
                    for value in planning_context_ids
                ):
                    errors.append(f"SECTION_PLANNING_CONTEXT_POLICY_MISMATCH:{section_id}")
                if planning_question_ids and any(
                    (policies.get(value) or {}).get("policy") != "PLANNING_QUESTION"
                    for value in planning_question_ids
                ):
                    errors.append(f"SECTION_PLANNING_QUESTION_POLICY_MISMATCH:{section_id}")
                if purpose == "PRODUCT_TRUTH" and (
                    len(section.get("product_truth_ids") or []) != 1
                    or section.get("reason_ids")
                    or planning_context_ids
                    or planning_question_ids
                ):
                    errors.append(f"SECTION_PROVENANCE_OVERBROAD:{section_id}")
                if purpose == "SCENARIO" and (
                    allowed_ids or section.get("product_truth_ids") or not planning_context_ids
                ):
                    errors.append(f"SECTION_SCENARIO_SCOPE_INVALID:{section_id}")
                if purpose == "BOUNDARY" and allowed_ids:
                    errors.append(f"SECTION_BOUNDARY_ASSERTION_FORBIDDEN:{section_id}")
                if purpose == "VALIDATION" and (
                    section.get("reason_ids")
                    or section.get("product_truth_ids")
                    or not section.get("eligible_metric_keys")
                    or not section.get("baseline_ref")
                ):
                    errors.append(f"SECTION_VALIDATION_SCOPE_INVALID:{section_id}")
                signal_truth_ids = {
                    int(value.split(":")[1])
                    for value in section.get("required_signal_ids") or []
                    if len(value.split(":")) > 2 and value.split(":")[1].isdigit()
                }
                if package and not signal_truth_ids.issubset(package_truth_ids):
                    errors.append(f"SECTION_PROVENANCE_OVERBROAD:{section_id}")
                if purpose == "FAQ":
                    if planning_question_ids:
                        errors.append(f"FAQ_CONTAINS_PLANNING_QUESTION:{section_id}")
                    faq_policy_ids = set(section.get("claim_usage_policy_ids") or [])
                    if any(
                        (policies.get(value) or {}).get("policy") != "PUBLISHABLE_QUESTION_ALLOWED"
                        for value in faq_policy_ids
                    ):
                        errors.append(f"FAQ_CONTAINS_NON_PUBLISHABLE_POLICY:{section_id}")
                if purpose == "OPERATION":
                    errors.append(f"UNSUPPORTED_OPERATION_SECTION:{section_id}")
                block = blocks_by_section.get(section_id)
                if not block:
                    errors.append(f"SECTION_WITHOUT_CONTENT_BLOCK:{section_id}")
                else:
                    inherited_fields = (
                        "theme_ids",
                        "reason_ids",
                        "product_truth_ids",
                        "allowed_claim_ids",
                        "planning_context_ids",
                        "planning_question_ids",
                        "required_signal_ids",
                        "eligible_metric_keys",
                    )
                    if any(block.get(field) != section.get(field) for field in inherited_fields):
                        errors.append(f"CONTENT_BLOCK_PROVENANCE_EXPANSION:{section_id}")
    return _validator(errors)


def _quality_result(errors: list[str], details: dict | None = None) -> dict:
    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": _unique(errors),
        "details": details or {},
    }


def validate_asset_package_quality(proposals: list[dict]) -> dict:
    required_fields = {
        "package_key",
        "package_scope_mode",
        "theme_ids",
        "theme_titles",
        "excluded_theme_ids",
        "excluded_theme_titles",
        "reason_ids",
        "reason_titles",
        "product_truth_ids",
        "product_truth_labels",
        "asset_count",
        "eligible_asset_types",
        "share_asset_basis",
        "packaging_rationale",
        "tradeoffs",
        "selection_implication",
    }
    valid_modes = {"FULL_STRATEGY_SCOPE", "P1_FOCUS", "MINIMUM_VALIDATION_SCOPE"}
    errors = []
    package_count = 0
    for proposal in proposals:
        for package in proposal.get("asset_package_candidates") or []:
            package_count += 1
            key = package.get("package_key") or "UNKNOWN"
            missing = sorted(required_fields - set(package))
            if missing:
                errors.append(f"ASSET_PACKAGE_NOT_SELF_CONTAINED:{key}:{','.join(missing)}")
            if package.get("package_scope_mode") not in valid_modes:
                errors.append(f"INVALID_PACKAGE_SCOPE_MODE:{key}")
            if package.get("asset_count") != 1 or package.get("concrete_asset_count") != 1:
                errors.append(f"ASSET_PACKAGE_MUST_REPRESENT_ONE_ASSET:{key}")
            if len(package.get("theme_ids") or []) != len(package.get("theme_titles") or []):
                errors.append(f"ASSET_PACKAGE_THEME_LABEL_MISMATCH:{key}")
            if len(package.get("reason_ids") or []) != len(package.get("reason_titles") or []):
                errors.append(f"ASSET_PACKAGE_REASON_LABEL_MISMATCH:{key}")
            if len(package.get("product_truth_ids") or []) != len(package.get("product_truth_labels") or []):
                errors.append(f"ASSET_PACKAGE_TRUTH_LABEL_MISMATCH:{key}")
            if not package.get("eligible_asset_types") or not package.get("share_asset_basis"):
                errors.append(f"ASSET_PACKAGE_MISSING_EXECUTION_BASIS:{key}")
            if any(row.get("status") != "PASS" for row in package.get("share_asset_basis") or []):
                errors.append(f"ASSET_PACKAGE_SHARE_BASIS_NOT_PROVEN:{key}")
            if not package.get("tradeoffs"):
                errors.append(f"ASSET_PACKAGE_MISSING_TRADEOFFS:{key}")
    return _quality_result(errors, {"package_count": package_count})


def validate_channel_hypothesis_quality(proposals: list[dict]) -> dict:
    tests = [row for row in proposals if row.get("channel_role") == "TEST"]
    errors = []
    normalized_by_channel = {}
    profiles_by_channel = {}
    for proposal in tests:
        channel = proposal.get("channel") or "UNKNOWN"
        profile = proposal.get("channel_opportunity_profile") or {}
        hypothesis = proposal.get("intervention_hypothesis") or {}
        required_profile_fields = {
            "channel",
            "reference_observations",
            "retrieval_observations",
            "source_claim_count",
            "source_document_count",
            "reason_ids",
            "theme_ids",
            "exposure_signals",
            "reason_relevance_signals",
            "target_gap_signals",
            "intervention_fit_signals",
            "why_test_signals",
            "why_not_primary_signals",
            "cross_channel_distinction",
        }
        if required_profile_fields - set(profile):
            errors.append(f"CHANNEL_OPPORTUNITY_PROFILE_INCOMPLETE:{channel}")
        if profile.get("cross_channel_distinction") == "UNSUPPORTED_PATTERN":
            errors.append(f"CHANNEL_HYPOTHESIS_PATTERN_UNSUPPORTED:{channel}")
        if hypothesis.get("pattern") != profile.get("cross_channel_distinction"):
            errors.append(f"CHANNEL_HYPOTHESIS_PROFILE_MISMATCH:{channel}")
        if hypothesis.get("causal_claim") is not False:
            errors.append(f"CHANNEL_HYPOTHESIS_CAUSAL_OVERREACH:{channel}")
        text = str(hypothesis.get("text") or "")
        normalized_by_channel[channel] = text.replace(str(proposal.get("channel_label") or ""), "{CHANNEL}")
        profiles_by_channel[channel] = {
            key: profile.get(key)
            for key in (
                "reference_observations",
                "retrieval_observations",
                "source_claim_count",
                "source_document_count",
                "cross_channel_distinction",
            )
        }
    for index, left in enumerate(tests):
        left_channel = left.get("channel")
        for right in tests[index + 1:]:
            right_channel = right.get("channel")
            if (
                profiles_by_channel.get(left_channel) != profiles_by_channel.get(right_channel)
                and normalized_by_channel.get(left_channel) == normalized_by_channel.get(right_channel)
            ):
                errors.append(f"GENERIC_CHANNEL_HYPOTHESIS_TEMPLATE:{left_channel}:{right_channel}")
    return _quality_result(errors, {"test_channel_count": len(tests)})


def build_proposal_quality_audit(context: dict, snapshot: dict, proposals: list[dict]) -> dict:
    section_validation = validate_section_provenance(context, proposals)
    title_validation = validate_title_claims(context, proposals)
    claim_validation = validate_claim_grounding(context, proposals)
    metric_validation = validate_metric_eligibility(context, proposals)
    baseline_validation = validate_baseline(context, snapshot, proposals)
    results = {
        "asset_package_quality": validate_asset_package_quality(proposals),
        "title_grounding_quality": _quality_result(title_validation["errors"]),
        "section_quality": _quality_result(section_validation["errors"]),
        "claim_usage_quality": _quality_result(claim_validation["errors"]),
        "channel_hypothesis_quality": validate_channel_hypothesis_quality(proposals),
        "metric_measurement_quality": _quality_result(metric_validation["errors"]),
        "baseline_quality": _quality_result(baseline_validation["errors"]),
    }
    overall = "PASS" if all(row["status"] == "PASS" for row in results.values()) else "FAIL"
    return {**results, "overall_quality": overall}


def validate_baseline(context: dict, snapshot: dict, proposals: list[dict]) -> dict:
    expected = context["baseline_run_ids"]
    errors = []
    if snapshot.get("baseline_run_ids") != expected:
        errors.append("SNAPSHOT_BASELINE_DRIFT")
    for proposal in proposals:
        baseline = (proposal.get("baseline_ref") or {}).get("baseline_run_ids")
        if baseline != expected:
            errors.append(f"PROPOSAL_BASELINE_DRIFT:{proposal.get('proposal_key')}")
        if baseline == context["strategy_analyzable_run_ids"] and expected != context["strategy_analyzable_run_ids"]:
            errors.append(f"STRATEGY_RUNS_USED_AS_BASELINE:{proposal.get('proposal_key')}")
    return _validator(errors)


def validate_metric_eligibility(context: dict, proposals: list[dict]) -> dict:
    package_rows = _package_metric_rows(context["package_payload"])
    valid_statuses = {"BASELINE_AVAILABLE", "ZERO_OBSERVED", "NOT_MEASURABLE_YET", "NOT_APPLICABLE", "CALCULATION_FAILED"}
    errors = []
    for proposal in proposals:
        for metric in proposal.get("eligible_metrics") or []:
            key = metric.get("metric_key")
            spec = FORMAL_METRIC_CALCULATORS.get(key)
            if not spec:
                errors.append(f"INVENTED_METRIC:{key}")
                continue
            if proposal.get("proposal_type") not in spec["proposal_types"]:
                errors.append(f"METRIC_NOT_APPLICABLE_TO_PROPOSAL:{key}")
            if metric.get("measurement_level") != spec["measurement_level"]:
                errors.append(f"METRIC_LEVEL_DRIFT:{key}")
            if metric.get("calculator") != spec["calculator"]:
                errors.append(f"METRIC_CALCULATOR_DRIFT:{key}")
            if metric.get("baseline_status") not in valid_statuses:
                errors.append(f"INVALID_BASELINE_STATUS:{key}")
            if metric.get("baseline_status") in {"BASELINE_AVAILABLE", "ZERO_OBSERVED", "NOT_APPLICABLE"} and key not in package_rows:
                errors.append(f"METRIC_BASELINE_NOT_IN_EVIDENCE_PACKAGE:{key}")
            if metric.get("baseline_status") == "NOT_MEASURABLE_YET" and metric.get("measurement_level") != "SELECTED_ASSET":
                errors.append(f"INVALID_NOT_MEASURABLE_YET:{key}")
    return _validator(errors)


def validate_execution_proposal(context: dict, snapshot: dict, proposals: list[dict], managed_assets: list[dict]) -> dict:
    validators = {
        "SnapshotValidator": validate_snapshot(context, snapshot),
        "ChannelRoleValidator": validate_channel_roles(context, proposals),
        "AssetFitValidator": validate_asset_fit(proposals, managed_assets),
        "ClaimGroundingValidator": validate_claim_grounding(context, proposals),
        "TitleClaimValidator": validate_title_claims(context, proposals),
        "SectionProvenanceValidator": validate_section_provenance(context, proposals),
        "BaselineValidator": validate_baseline(context, snapshot, proposals),
        "MetricEligibilityValidator": validate_metric_eligibility(context, proposals),
    }
    return {
        "status": "VALID" if all(row["status"] == "VALID" for row in validators.values()) else "INVALID",
        "validators": validators,
    }


def build_execution_proposal_portfolio(context: dict, managed_assets: list[dict] | None = None) -> dict:
    managed_assets = deepcopy(managed_assets or [])
    snapshot = _execution_input_snapshot(context, managed_assets)
    active_keys = set(context["active_channel_keys"])
    deferred_keys = set(context["deferred_channel_keys"])
    active_channels = [row for row in context["channel_resolutions"] if row["channel_key"] in active_keys]
    proposals = [_build_proposal(context, row, managed_assets) for row in active_channels]
    validation = validate_execution_proposal(context, snapshot, proposals, managed_assets)
    quality_audit = build_proposal_quality_audit(context, snapshot, proposals)
    safety_probes = _safety_probe_audit(context["brand_name"], context["product_truths"])
    all_policy = [policy for proposal in proposals for policy in proposal["claim_usage_policy"]]
    validator_errors = [
        error
        for row in validation["validators"].values()
        for error in row["errors"]
    ]
    unsupported_target_errors = [
        error for error in validator_errors
        if error.startswith((
            "UNCONFIRMED_TARGET_ASSERTION",
            "UNAPPROVED_TARGET_ASSERTION_WORDING",
            "TARGET_ASSERTION_PROVENANCE_MISMATCH",
            "UNGROUNDED_TITLE_CLAIM",
            "UNAPPROVED_TITLE_CAPABILITY",
        ))
    ]
    return {
        "schema_version": CONTRACT_VERSION,
        "shadow_only": True,
        "formal_output_impact": "NONE",
        "external_llm": PR5_A_EXTERNAL_LLM,
        "external_llm_calls": 0,
        "replay_mode": context["replay_mode"],
        "strategy_view_source": context["strategy_view_source"],
        "execution_input_snapshot": snapshot,
        "managed_asset_snapshot": {
            "snapshot_mode": SNAPSHOT_MODE,
            "managed_asset_count": len(managed_assets),
            "assets": managed_assets,
        },
        "execution_constraints": [proposal["execution_constraint"] for proposal in proposals],
        "active_proposals": proposals,
        "deferred_planning_data": [
            {
                "channel": row["channel_key"],
                "channel_role": row["role"],
                "decision_reason_ids": row.get("decision_reason_ids") or [],
                "supporting_signal_ids": row.get("supporting_signal_ids") or [],
                "status": "DEFERRED_NO_ACTIVE_PROPOSAL",
            }
            for row in context["channel_resolutions"]
            if row["channel_key"] in deferred_keys
        ],
        "claim_safety_probe_audit": safety_probes,
        "validators": validation["validators"],
        "validation_status": validation["status"],
        "proposal_quality_audit": quality_audit,
        "proposal_readiness_summary": {
            status: sum(1 for row in proposals if row["proposal_readiness"] == status)
            for status in sorted(VALID_PROPOSAL_READINESS)
        },
        "safety_audit": {
            "unsupported_target_brand_assertions": len(unsupported_target_errors),
            "new_product_facts": len(unsupported_target_errors),
            "new_channels": sum(1 for error in validator_errors if error.startswith("NEW_CHANNEL")),
            "role_mutations": sum(1 for error in validator_errors if error.startswith("ROLE_MUTATION")),
            "fake_managed_assets": sum(1 for error in validator_errors if "FAKE_MANAGED_ASSET" in error),
            "invented_metrics": sum(1 for error in validator_errors if error.startswith("INVENTED_METRIC")),
            "baseline_drift": sum(1 for error in validator_errors if "BASELINE" in error),
            "sections_without_provenance": sum(1 for error in validator_errors if "SECTION_WITHOUT_PROVENANCE" in error),
            "published_questions_implying_unknown_truth": sum(
                1 for row in all_policy
                if row["policy"] == "PLANNING_QUESTION" and row.get("publishable") is True
            ),
        },
        "edit_contract": {
            "system_owned_fields": SYSTEM_OWNED_FIELDS,
            "human_editable_fields": HUMAN_EDITABLE_FIELDS,
            "post_edit_rule": "REBUILD_CANONICAL_PROPOSAL_AND_RERUN_ALL_VALIDATORS",
        },
        "boundary": {
            "db_writes": 0,
            "actions_created": 0,
            "experiments_created": 0,
            "managed_assets_created": 0,
            "execution_snapshots_created": 0,
            "step8_modified": False,
        },
    }


def _edit_error(code: str, field: str, message: str, **details: Any) -> dict:
    return {
        "error_code": code,
        "field": field,
        "message": message,
        **details,
    }


def _edit_safety_audit(drafts: list[dict], portfolio_errors: list[dict]) -> dict:
    errors = [
        row
        for draft in drafts
        for row in draft.get("edit_errors") or []
    ] + list(portfolio_errors)
    codes = [str(row.get("error_code") or "") for row in errors]
    messages = [str(row.get("message") or "") for row in errors]
    return {
        "unsupported_target_assertions": sum(code == "UNSUPPORTED_TARGET_ASSERTION" for code in codes),
        "new_facts": sum(code in {"UNSUPPORTED_TARGET_ASSERTION", "IMMUTABLE_PRODUCT_TRUTH"} for code in codes),
        "new_channels": sum(code == "UNKNOWN_PROPOSAL_KEY" for code in codes),
        "role_mutations": sum(
            row.get("field") == "channel_role"
            for draft in drafts for row in draft.get("edit_errors") or []
        ),
        "fake_assets": sum(code in {"INVALID_ASSET_TYPE", "INVALID_MANAGED_ASSET_SELECTION"} for code in codes),
        "invented_metrics": sum("INVENTED_METRIC" in message for message in messages),
        "baseline_drift": sum(code == "IMMUTABLE_BASELINE" or "BASELINE" in message for code, message in zip(codes, messages)),
        "ungrounded_sections": sum(code in {"UNGROUNDED_SECTION", "FAQ_CONTAINS_PLANNING_QUESTION"} for code in codes),
        "implicit_unknown_claims": sum(code == "UNSUPPORTED_TARGET_ASSERTION" for code in codes),
    }


def _canonical_edited_title(context: dict, proposal: dict, title_text: str) -> tuple[dict | None, dict | None]:
    title_text = str(title_text or "").strip()
    brand = str(context["brand_name"])
    suffix = "能力说明" if proposal["channel"] == "OFFICIAL_SITE" else "使用说明"
    if not title_text.startswith(brand) or not title_text.endswith(suffix):
        return None, _edit_error(
            "UNSUPPORTED_TARGET_ASSERTION",
            "safe_title_rewrite",
            "标题只能使用品牌名、已确认能力及规定的说明后缀",
            offending_phrase=title_text,
            required_product_truth="missing",
        )
    middle = title_text[len(brand):-len(suffix)]
    if middle.startswith("："):
        middle = middle[1:]
    elif middle:
        return None, _edit_error(
            "UNSUPPORTED_TARGET_ASSERTION",
            "safe_title_rewrite",
            "品牌名与能力之间必须使用全角冒号",
            offending_phrase=middle,
            required_product_truth="missing",
        )
    tokens = [value.strip() for value in middle.split("、") if value.strip()]
    truth_by_wording = {}
    for truth in context["product_truths"]:
        if not _truth_is_confirmed(truth):
            continue
        for wording in [truth["capability_label"], *(truth.get("approved_aliases") or [])]:
            truth_by_wording[wording] = truth
    selected_truths = []
    for token in tokens:
        truth = truth_by_wording.get(token)
        if not truth:
            return None, _edit_error(
                "UNSUPPORTED_TARGET_ASSERTION",
                "safe_title_rewrite",
                "标题包含未由 Product Truth 确认的能力表达",
                offending_phrase=token,
                required_product_truth="missing",
            )
        if truth in selected_truths:
            return None, _edit_error(
                "UNSUPPORTED_TARGET_ASSERTION",
                "safe_title_rewrite",
                "标题不能重复同一 Product Truth",
                offending_phrase=token,
                required_product_truth=f"product_truth:{truth['product_truth_id']}",
            )
        selected_truths.append(truth)
    if not selected_truths:
        return None, _edit_error(
            "UNSUPPORTED_TARGET_ASSERTION",
            "safe_title_rewrite",
            "标题至少需要一个已确认能力",
            offending_phrase=title_text,
            required_product_truth="missing",
        )
    segments = [{"segment_type": "BRAND", "text": brand, "source_ids": []}]
    for token, truth in zip(tokens, selected_truths):
        segments.append({
            "segment_type": "PRODUCT_TRUTH",
            "text": token,
            "source_ids": [f"product_truth:{truth['product_truth_id']}"],
            "product_truth_id": truth["product_truth_id"],
        })
    segments.append({"segment_type": "GENERIC_SUFFIX", "text": suffix, "source_ids": []})
    return {
        "title_candidate_id": f"title:{proposal['channel'].lower()}:human-safe",
        "title": title_text,
        "segments": segments,
        "factual_claim_ids": [
            f"target_assertion:product_truth:{truth['product_truth_id']}"
            for truth in selected_truths
        ],
        "generation_mode": "HUMAN_EDIT_EXACT_PRODUCT_TRUTH_WORDING",
    }, None


def _record_edit(
    rows: list[dict],
    field: str,
    original: Any,
    edited: Any,
    edited_by: str,
    edited_at: str,
    validation_result: str = "ACCEPTED",
) -> None:
    if original == edited:
        return
    rows.append({
        "field": field,
        "original_value": deepcopy(original),
        "edited_value": deepcopy(edited),
        "edited_by": edited_by,
        "edited_at": edited_at,
        "validation_result": validation_result,
    })


def _rebuild_execution_proposal(
    context: dict,
    snapshot: dict,
    source: dict,
    human_edits: dict,
    managed_assets: list[dict],
    edited_by: str,
) -> dict:
    canonical = deepcopy(source)
    errors: list[dict] = []
    diff: list[dict] = []
    edited_at = datetime.now(timezone.utc).isoformat()

    for field in human_edits:
        if field in IMMUTABLE_EDIT_CODES:
            errors.append(_edit_error(
                IMMUTABLE_EDIT_CODES[field],
                field,
                "该字段由已确认策略或证据快照拥有，不能在 Step 8 修改",
            ))
        elif field not in {
            "execute_this_proposal",
            "selected_asset_package_key",
            "selected_managed_asset_id",
            "selected_asset_type",
            "title",
            "section_order",
            "selected_section_ids",
            "publishing_metadata",
            "selected_observation_window_index",
            "section_overrides",
            "new_sections",
        }:
            errors.append(_edit_error("UNKNOWN_EDIT_FIELD", field, "该字段不在 PR5-B 可编辑白名单中"))

    if "section_overrides" in human_edits or "new_sections" in human_edits:
        rows = human_edits.get("section_overrides") or human_edits.get("new_sections") or []
        faq_planning = any(
            str(row.get("section_purpose") or "").upper() == "FAQ"
            and bool(row.get("planning_question_ids"))
            for row in rows if isinstance(row, dict)
        )
        errors.append(_edit_error(
            "FAQ_CONTAINS_PLANNING_QUESTION" if faq_planning else "UNGROUNDED_SECTION",
            "section_overrides",
            "PR5-B 只能选择并排序当前 package 已生成的 provenance-backed sections",
        ))

    execute = human_edits.get("execute_this_proposal")
    if not isinstance(execute, bool):
        errors.append(_edit_error(
            "EXECUTION_SELECTION_REQUIRED",
            "execute_this_proposal",
            "请选择本轮执行或暂缓",
        ))
        execute = None
    canonical["execute_this_proposal"] = execute
    _record_edit(diff, "execute_this_proposal", None, execute, edited_by, edited_at)

    if execute is False:
        canonical["proposal_execution_state"] = "DEFERRED_BY_HUMAN"
        canonical["proposal_readiness"] = "DEFERRED_BY_HUMAN"
        validation = validate_execution_proposal(context, snapshot, [canonical], managed_assets)
        draft_status = "INVALID_EDIT" if errors or validation["status"] != "VALID" else "VALID"
        for row in diff:
            row["validation_result"] = "REJECTED" if draft_status == "INVALID_EDIT" else "ACCEPTED"
        return {
            "source_execution_proposal_hash": _stable_hash(source),
            "canonical_proposal": canonical,
            "human_edit_diff": diff,
            "edit_errors": errors,
            "validator_results": validation["validators"],
            "all_validators_rerun": list(validation["validators"]),
            "draft_status": draft_status,
            "proposal_execution_state": "DEFERRED_BY_HUMAN",
            "proposal_readiness": "DEFERRED_BY_HUMAN",
        }

    package_key = human_edits.get("selected_asset_package_key", source.get("selected_asset_package_key"))
    packages = {row["package_key"]: row for row in source.get("asset_package_candidates") or []}
    package = packages.get(package_key)
    if not package:
        errors.append(_edit_error(
            "INVALID_ASSET_PACKAGE_SELECTION" if package_key else "ASSET_PACKAGE_SELECTION_REQUIRED",
            "selected_asset_package_key",
            "必须从当前 Proposal 的 AssetPackageCandidate 中选择",
            allowed_values=list(packages),
        ))
    else:
        canonical["selected_asset_package_key"] = package_key
        canonical["asset_package_resolution_status"] = "RESOLVED"
        _record_edit(diff, "selected_asset_package_key", source.get("selected_asset_package_key"), package_key, edited_by, edited_at)

    selected_type = human_edits.get("selected_asset_type", source.get("recommended_asset_type"))
    eligible_types = list(source.get("asset_type_candidates") or [])
    if selected_type not in eligible_types:
        errors.append(_edit_error(
            "INVALID_ASSET_TYPE" if selected_type else "ASSET_TYPE_SELECTION_REQUIRED",
            "selected_asset_type",
            "必须从当前 Proposal 的合法资产类型中选择",
            offending_value=selected_type,
            allowed_values=eligible_types,
        ))
    else:
        canonical["selected_asset_type"] = selected_type
        canonical["recommended_asset_type"] = selected_type
        canonical["asset_type_resolution_status"] = "RESOLVED"
        _record_edit(diff, "selected_asset_type", source.get("recommended_asset_type"), selected_type, edited_by, edited_at)

    if source.get("asset_operation") == "UPDATE_MANAGED" and "selected_managed_asset_id" in human_edits:
        selected_asset_id = human_edits.get("selected_managed_asset_id")
        eligible_asset_ids = {
            row.get("managed_asset_id") for row in source.get("managed_asset_candidates") or []
            if row.get("fit") == "HIGH_FIT"
        }
        if selected_asset_id not in eligible_asset_ids:
            errors.append(_edit_error(
                "INVALID_MANAGED_ASSET_SELECTION",
                "selected_managed_asset_id",
                "只能选择当前 Proposal 中 HIGH_FIT 的已有资产",
            ))
        else:
            canonical["selected_managed_asset_id"] = selected_asset_id
            canonical["asset_resolution_status"] = "RESOLVED"
            _record_edit(diff, "selected_managed_asset_id", source.get("selected_managed_asset_id"), selected_asset_id, edited_by, edited_at)

    if package:
        plan = next(
            (row for row in source.get("section_plan_candidates") or [] if row.get("asset_package_key") == package_key),
            None,
        )
        eligible_sections = deepcopy((plan or {}).get("section_plan") or [])
        blocks = deepcopy((plan or {}).get("content_block_plan") or [])
        eligible_by_id = {row["section_id"]: row for row in eligible_sections}
        requested_ids = human_edits.get("section_order", human_edits.get("selected_section_ids"))
        if requested_ids is None:
            requested_ids = [row["section_id"] for row in eligible_sections]
        if not isinstance(requested_ids, list) or len(requested_ids) != len(set(requested_ids)):
            errors.append(_edit_error("INVALID_SECTION_SELECTION", "section_order", "Section 顺序必须是无重复的 ID 列表"))
            requested_ids = []
        unknown = [value for value in requested_ids if value not in eligible_by_id]
        if unknown:
            errors.append(_edit_error(
                "UNGROUNDED_SECTION",
                "section_order",
                "存在不属于当前 AssetPackageCandidate 的 Section",
                offending_section_ids=unknown,
            ))
        selected_ids = [value for value in requested_ids if value in eligible_by_id]
        canonical["section_plan"] = [deepcopy(eligible_by_id[value]) for value in selected_ids]
        block_by_section = {row["section_id"]: row for row in blocks}
        canonical["content_block_plan"] = [deepcopy(block_by_section[value]) for value in selected_ids if value in block_by_section]
        canonical["section_plan_resolution_status"] = "RESOLVED" if selected_ids else "NEEDS_HUMAN_SELECTION"
        _record_edit(
            diff,
            "section_order",
            [row.get("section_id") for row in source.get("section_plan") or []],
            selected_ids,
            edited_by,
            edited_at,
        )
        canonical["theme_ids"] = deepcopy(package.get("theme_ids") or [])
        canonical["reason_ids"] = deepcopy(package.get("reason_ids") or [])
        canonical["product_truth_ids"] = deepcopy(package.get("product_truth_ids") or [])
        canonical["provenance"] = {
            **deepcopy(source.get("provenance") or {}),
            "theme_ids": deepcopy(package.get("theme_ids") or []),
            "reason_ids": deepcopy(package.get("reason_ids") or []),
            "product_truth_ids": deepcopy(package.get("product_truth_ids") or []),
        }
        if canonical.get("new_asset_spec"):
            canonical["new_asset_spec"].update({
                "asset_type": selected_type if selected_type in eligible_types else None,
                "theme_ids": deepcopy(package.get("theme_ids") or []),
                "reason_ids": deepcopy(package.get("reason_ids") or []),
                "product_truth_ids": deepcopy(package.get("product_truth_ids") or []),
                "section_ids": selected_ids,
            })

    title_text = human_edits.get("title")
    if title_text is None:
        title_text = ((source.get("title_candidates") or [{}])[0]).get("title")
    title, title_error = _canonical_edited_title(context, source, str(title_text or ""))
    if title_error:
        errors.append(title_error)
    elif title:
        canonical["title_candidates"] = [title]
        _record_edit(
            diff,
            "title",
            ((source.get("title_candidates") or [{}])[0]).get("title"),
            title_text,
            edited_by,
            edited_at,
        )

    metadata = human_edits.get("publishing_metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    metadata = {
        "publishing_account": str(metadata.get("publishing_account") or "").strip(),
        "publishing_location": str(metadata.get("publishing_location") or "").strip(),
        "url_slug": str(metadata.get("url_slug") or "").strip(),
        "channel_specific_posting_metadata": deepcopy(metadata.get("channel_specific_posting_metadata") or {}),
    }
    canonical["publishing_metadata"] = metadata
    for field in ("publishing_account", "publishing_location", "url_slug"):
        if not metadata[field]:
            errors.append(_edit_error("PUBLISHING_METADATA_REQUIRED", f"publishing_metadata.{field}", "执行方案冻结前必须补齐发布元数据"))
    _record_edit(diff, "publishing_metadata", None, metadata, edited_by, edited_at)

    window_candidates = ((source.get("validation_plan") or {}).get("observation_window_candidates") or [])
    window_index = human_edits.get("selected_observation_window_index", 0 if len(window_candidates) == 1 else None)
    if not isinstance(window_index, int) or window_index < 0 or window_index >= len(window_candidates):
        errors.append(_edit_error(
            "INVALID_OBSERVATION_WINDOW",
            "selected_observation_window_index",
            "观察窗口只能从 Proposal 提供的候选中选择",
            allowed_indexes=list(range(len(window_candidates))),
        ))
    else:
        canonical["validation_plan"]["selected_observation_window"] = deepcopy(window_candidates[window_index])
        canonical["validation_plan"]["selected_observation_window_index"] = window_index
        canonical["validation_plan"]["observation_window_resolution_status"] = "RESOLVED"
        _record_edit(diff, "selected_observation_window_index", None, window_index, edited_by, edited_at)

    validation = validate_execution_proposal(context, snapshot, [canonical], managed_assets)
    validator_errors = [
        _edit_error("VALIDATOR_REJECTED", name, error)
        for name, result in validation["validators"].items()
        for error in result["errors"]
    ]
    errors.extend(validator_errors)
    draft_status = "INVALID_EDIT" if errors or validation["status"] != "VALID" else "VALID"
    ready = (
        draft_status == "VALID"
        and execute is True
        and canonical.get("asset_resolution_status") == "RESOLVED"
        and canonical.get("asset_type_resolution_status") == "RESOLVED"
        and canonical.get("asset_package_resolution_status") == "RESOLVED"
        and canonical.get("section_plan_resolution_status") == "RESOLVED"
        and canonical.get("validation_plan", {}).get("observation_window_resolution_status") == "RESOLVED"
    )
    canonical["proposal_readiness"] = "READY_FOR_CONFIRMATION" if ready else "NEEDS_HUMAN_SELECTION"
    canonical["proposal_execution_state"] = "SELECTED_FOR_EXECUTION" if execute else "DEFERRED_BY_HUMAN"
    for row in diff:
        row["validation_result"] = "REJECTED" if draft_status == "INVALID_EDIT" else "ACCEPTED"
    return {
        "source_execution_proposal_hash": _stable_hash(source),
        "canonical_proposal": canonical,
        "human_edit_diff": diff,
        "edit_errors": errors,
        "validator_results": validation["validators"],
        "all_validators_rerun": list(validation["validators"]),
        "draft_status": draft_status,
        "proposal_execution_state": canonical["proposal_execution_state"],
        "proposal_readiness": canonical["proposal_readiness"],
    }


def revalidate_execution_proposal_portfolio(
    context: dict,
    payload: dict,
    managed_assets: list[dict] | None = None,
) -> dict:
    managed_assets = deepcopy(managed_assets or [])
    source_portfolio = build_execution_proposal_portfolio(context, managed_assets)
    snapshot = source_portfolio["execution_input_snapshot"]
    source_by_key = {row["proposal_key"]: row for row in source_portfolio["active_proposals"]}
    edited_by = str(payload.get("edited_by") or "human")
    raw_edits = payload.get("proposal_edits")
    if not isinstance(raw_edits, list):
        raw_edits = []
    portfolio_errors = []
    for field in payload:
        if field in {"strategy_candidate_id", "edited_by", "proposal_edits"}:
            continue
        code = IMMUTABLE_EDIT_CODES.get(field, "UNKNOWN_EDIT_FIELD")
        portfolio_errors.append(_edit_error(code, field, "该 Portfolio 字段不允许在 PR5-B 修改"))
    if any(field in payload for field in ("merge_proposal_keys", "merged_proposal_keys", "merged_experiment")):
        if not any(row["error_code"] == "PROPOSAL_MERGE_FORBIDDEN" for row in portfolio_errors):
            portfolio_errors.append(_edit_error(
                "PROPOSAL_MERGE_FORBIDDEN",
                "proposal_edits",
                "每个 channel proposal 必须保持独立，PR5-B 不允许合并 Experiment",
            ))
    overlays = {}
    for item in raw_edits:
        if not isinstance(item, dict):
            portfolio_errors.append(_edit_error("INVALID_PROPOSAL_EDIT", "proposal_edits", "Proposal edit 必须是对象"))
            continue
        proposal_key = item.get("proposal_key")
        if proposal_key not in source_by_key:
            portfolio_errors.append(_edit_error("UNKNOWN_PROPOSAL_KEY", "proposal_key", "Proposal 不属于当前 Strategy", offending_value=proposal_key))
            continue
        if proposal_key in overlays:
            portfolio_errors.append(_edit_error("DUPLICATE_PROPOSAL_EDIT", "proposal_key", "同一 Proposal 只能提交一个 overlay", offending_value=proposal_key))
            continue
        overlay = deepcopy(item.get("human_edits")) if isinstance(item.get("human_edits"), dict) else {}
        for field, value in item.items():
            if field not in {"proposal_key", "human_edits", "source_execution_proposal_hash"}:
                overlay[field] = deepcopy(value)
        expected_hash = item.get("source_execution_proposal_hash")
        if expected_hash and expected_hash != _stable_hash(source_by_key[proposal_key]):
            overlay["input_contract_hash"] = expected_hash
        overlays[proposal_key] = overlay

    drafts = []
    for proposal_key, source in source_by_key.items():
        if proposal_key not in overlays:
            source_validation = validate_execution_proposal(context, snapshot, [source], managed_assets)
            drafts.append({
                "source_execution_proposal_hash": _stable_hash(source),
                "canonical_proposal": deepcopy(source),
                "human_edit_diff": [],
                "edit_errors": [_edit_error("EXECUTION_SELECTION_REQUIRED", "execute_this_proposal", "请选择本轮执行或暂缓")],
                "validator_results": source_validation["validators"],
                "all_validators_rerun": list(source_validation["validators"]),
                "draft_status": "NEEDS_HUMAN_SELECTION",
                "proposal_execution_state": "UNDECIDED",
                "proposal_readiness": "NEEDS_HUMAN_SELECTION",
            })
            continue
        drafts.append(_rebuild_execution_proposal(
            context,
            snapshot,
            source,
            overlays[proposal_key],
            managed_assets,
            edited_by,
        ))
    has_invalid = bool(portfolio_errors) or any(row["draft_status"] == "INVALID_EDIT" for row in drafts)
    ready_count = sum(1 for row in drafts if row["proposal_readiness"] == "READY_FOR_CONFIRMATION")
    all_decided = all(row["proposal_execution_state"] in {"SELECTED_FOR_EXECUTION", "DEFERRED_BY_HUMAN"} for row in drafts)
    all_selected_ready = all(
        row["proposal_execution_state"] != "SELECTED_FOR_EXECUTION"
        or row["proposal_readiness"] == "READY_FOR_CONFIRMATION"
        for row in drafts
    )
    if has_invalid:
        readiness = "HAS_INVALID_EDIT"
    elif all_decided and all_selected_ready and ready_count > 0:
        readiness = "READY_FOR_CONFIRMATION"
    else:
        readiness = "NEEDS_HUMAN_SELECTION"
    canonical_proposals = [row["canonical_proposal"] for row in drafts]
    portfolio_validation = validate_execution_proposal(context, snapshot, canonical_proposals, managed_assets)
    return {
        "schema_version": EDIT_CONTRACT_VERSION,
        "shadow_only": True,
        "formal_output_impact": "NONE",
        "external_llm_calls": 0,
        "strategy_candidate_id": context["strategy_candidate_id"],
        "source_execution_input_hash": snapshot["input_contract_hash"],
        "source_portfolio_hash": _stable_hash(source_portfolio["active_proposals"]),
        "proposal_drafts": drafts,
        "canonical_rebuilt_proposals": canonical_proposals,
        "portfolio_errors": portfolio_errors,
        "portfolio_validator_results": portfolio_validation["validators"],
        "safety_audit": _edit_safety_audit(drafts, portfolio_errors),
        "portfolio_readiness": readiness,
        "ready_for_freeze": readiness == "READY_FOR_CONFIRMATION",
        "boundary": {
            "db_writes": 0,
            "actions_created": 0,
            "experiments_created": 0,
            "managed_assets_created": 0,
            "execution_snapshots_created": 0,
            "step8_freeze_performed": False,
        },
    }


def revalidate_execution_proposal(
    context: dict,
    payload: dict,
    managed_assets: list[dict] | None = None,
) -> dict:
    proposal_key = payload.get("proposal_key")
    human_edits = deepcopy(payload.get("human_edits")) if isinstance(payload.get("human_edits"), dict) else {}
    for field, value in payload.items():
        if field not in {"strategy_candidate_id", "proposal_key", "edited_by", "human_edits", "source_execution_proposal_hash"}:
            human_edits[field] = deepcopy(value)
    portfolio_payload = {
        "edited_by": payload.get("edited_by") or "human",
        "proposal_edits": [{
            "proposal_key": proposal_key,
            "human_edits": human_edits,
            "source_execution_proposal_hash": payload.get("source_execution_proposal_hash"),
        }],
    }
    result = revalidate_execution_proposal_portfolio(context, portfolio_payload, managed_assets)
    draft = next(
        (row for row in result["proposal_drafts"] if row["canonical_proposal"].get("proposal_key") == proposal_key),
        None,
    )
    if draft is None:
        return {
            **result,
            "draft_status": "INVALID_EDIT",
            "edit_errors": [_edit_error("UNKNOWN_PROPOSAL_KEY", "proposal_key", "Proposal 不属于当前 Strategy")],
        }
    return {
        "schema_version": EDIT_CONTRACT_VERSION,
        "shadow_only": True,
        "formal_output_impact": "NONE",
        "external_llm_calls": 0,
        "strategy_candidate_id": context["strategy_candidate_id"],
        **draft,
        "safety_audit": result["safety_audit"],
        "boundary": result["boundary"],
    }


def _validated_confirmed_structure(payload: dict) -> dict:
    synthesis = payload.get("strategy_synthesis") or {}
    if synthesis.get("validator_status") != "VALID":
        raise ValueError("Confirmed Strategy 缺少有效的 Strategy Synthesis 校验结果")
    themes = payload.get("intervention_themes") or []
    portfolio = payload.get("strategy_portfolio") or {}
    if not themes or not portfolio:
        raise ValueError("Confirmed Strategy 缺少已验证的 Theme/Portfolio 结构")
    return {"themes": themes, **portfolio}


def _candidate_and_mode(
    db: Session,
    project_id: int,
    prompt_id: int,
    candidate_id: int | None,
) -> tuple[OptimizationStrategyCandidate, OptimizationEvidencePackage, dict, str, str]:
    query = (
        db.query(OptimizationStrategyCandidate)
        .join(OptimizationEvidencePackage, OptimizationEvidencePackage.id == OptimizationStrategyCandidate.evidence_package_id)
        .filter(
            OptimizationStrategyCandidate.project_id == project_id,
            OptimizationEvidencePackage.prompt_id == prompt_id,
        )
    )
    if candidate_id is not None:
        candidate = query.filter(OptimizationStrategyCandidate.id == int(candidate_id)).first()
    else:
        rows = query.order_by(OptimizationStrategyCandidate.created_at.desc(), OptimizationStrategyCandidate.id.desc()).all()
        candidate = next(
            (
                row for row in rows
                if row.review_status in {"ACCEPTED", "ACCEPTED_WITH_EDITS"}
                and infer_strategy_candidate_origin(row) == CURRENT_STEP7_CANDIDATE_ORIGIN
            ),
            None,
        )
        if candidate is None:
            candidate = next(
                (row for row in rows if infer_strategy_candidate_origin(row) == CURRENT_STEP7_CANDIDATE_ORIGIN),
                None,
            )
    if not candidate:
        raise ValueError("当前 Prompt 没有可用于 PR5-A Shadow 的 StrategyCandidate")
    package = db.get(OptimizationEvidencePackage, int(candidate.evidence_package_id))
    effective = loads(candidate.effective_payload_json, {})
    if candidate.review_status in {"ACCEPTED", "ACCEPTED_WITH_EDITS"} and effective:
        return candidate, package, effective, "CONFIRMED_STRATEGY_SHADOW_REPLAY", "CONFIRMED_EFFECTIVE_PAYLOAD"
    structured = loads(candidate.structured_payload_json, {})
    if not structured:
        raise ValueError("历史 StrategyCandidate 没有可用于兼容投影的结构化 payload")
    return candidate, package, structured, "READ_ONLY_COMPATIBILITY_PROJECTION", "READ_ONLY_COMPATIBILITY_PROJECTION"


def _required_signal_ids(payload: dict, truth_rows: list[dict]) -> list[str]:
    by_label = {row["capability_label"]: row["product_truth_id"] for row in truth_rows}
    result = []
    for row in payload.get("required_signals") or []:
        label = str(row.get("capability_label") or "") if isinstance(row, dict) else str(row)
        truth_id = by_label.get(label)
        semantic = {"capability_label": label, "signal": row.get("signal") if isinstance(row, dict) else "", "product_truth_id": truth_id}
        result.append(f"required_signal:{truth_id or 'unknown'}:{_slug(json.dumps(semantic, ensure_ascii=False, sort_keys=True))}")
    return _unique(result)


def _build_db_context(
    db: Session,
    project_id: int,
    prompt_id: int,
    candidate_id: int | None,
) -> tuple[dict, OptimizationStrategyCandidate, OptimizationEvidencePackage]:
    project = db.get(Project, project_id)
    prompt = db.get(Prompt, prompt_id)
    if not project or not prompt or prompt.project_id != project_id:
        raise ValueError("Project/Prompt 不存在")
    candidate, package, payload, replay_mode, strategy_view_source = _candidate_and_mode(
        db, project_id, prompt_id, candidate_id
    )
    synthesis_context = build_strategy_synthesis_context_from_payload(
        db,
        project,
        prompt,
        package,
        payload,
        input_scope_id=(payload.get("strategy_synthesis") or {}).get("input_scope_id") or int(candidate.id),
    )
    if replay_mode == "CONFIRMED_STRATEGY_SHADOW_REPLAY":
        structure = _validated_confirmed_structure(payload)
    else:
        synthesis_result = run_strategy_synthesis_core(synthesis_context, use_llm=False)
        if synthesis_result["validation_status"] != "VALID":
            raise ValueError("历史 StrategyCandidate 兼容投影未通过确定性 Strategy 校验")
        structure = (synthesis_result.get("structural_synthesis") or {}).get("validated_structure") or {}
    truth_ids = sorted({value for row in synthesis_context["decision_reasons"] for value in row.get("product_truth_ids") or []})
    db_truths = db.query(TargetBrandCapabilityTruth).filter(
        TargetBrandCapabilityTruth.project_id == project_id,
        TargetBrandCapabilityTruth.id.in_(truth_ids),
    ).all() if truth_ids else []
    truth_rows = [
        _approved_truth_projection({
            "id": row.id,
            "capability_key": row.capability_key,
            "capability_label": row.capability_label,
            "product_truth_status": row.product_truth_status,
            "truth_source": row.truth_source,
            "source_reference": row.source_reference,
            "reviewed_by": row.reviewed_by,
            "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        })
        for row in db_truths
        if _truth_is_confirmed({"product_truth_status": row.product_truth_status, "truth_source": row.truth_source})
    ]
    portfolio = {
        "primary_interventions": structure.get("primary_interventions") or [],
        "secondary_interventions": structure.get("secondary_interventions") or [],
        "priority_tests": structure.get("priority_tests") or [],
        "deferred_tests": structure.get("deferred_tests") or [],
    }
    active_keys = _unique([
        row["channel_key"]
        for field in ("primary_interventions", "secondary_interventions", "priority_tests")
        for row in portfolio[field]
    ])
    deferred_keys = _unique([row["channel_key"] for row in portfolio["deferred_tests"]])
    baseline_run_ids = [int(value) for value in loads(package.source_run_ids_json, []) if value]
    candidate_semantic = {
        "candidate_id": int(candidate.id),
        "review_status": candidate.review_status,
        "effective_payload_version": candidate.effective_payload_version,
        "strategy_basis": synthesis_context["strategy_basis"],
        "strategy_synthesis_contract": {
            "contract_version": (payload.get("strategy_synthesis") or {}).get("contract_version"),
            "structural_output_hash": (payload.get("strategy_synthesis") or {}).get("structural_output_hash"),
            "input_scope_id": (payload.get("strategy_synthesis") or {}).get("input_scope_id"),
        },
        "decision_reasons": [
            {
                key: deepcopy(row.get(key))
                for key in (
                    "reason_id",
                    "normalized_proposition",
                    "capability_family",
                    "scenario",
                    "qualifier",
                    "observed_run_ids",
                    "product_truth_ids",
                    "gap_item_ids",
                )
            }
            for row in synthesis_context["decision_reasons"]
        ],
        "themes": [
            {
                key: deepcopy(row.get(key))
                for key in ("theme_key", "reason_ids", "priority", "theme_observed_run_ids")
            }
            for row in structure.get("themes") or []
        ],
        "portfolio": {
            field: [
                {
                    key: deepcopy(row.get(key))
                    for key in ("channel_key", "frozen_role", "execution_priority", "decision_reason_ids")
                }
                for row in portfolio[field]
            ]
            for field in ("primary_interventions", "secondary_interventions", "priority_tests", "deferred_tests")
        },
        "required_signals": payload.get("required_signals") or [],
    }
    context = {
        **synthesis_context,
        "strategy_candidate_id": int(candidate.id),
        "strategy_candidate_status": candidate.review_status,
        "strategy_candidate_semantic_hash": _stable_hash(candidate_semantic),
        "strategy_contract_version": (payload.get("strategy_synthesis") or {}).get("contract_version") or synthesis_context.get("contract_version"),
        "replay_mode": replay_mode,
        "strategy_view_source": strategy_view_source,
        "themes": deepcopy(structure.get("themes") or []),
        "active_channel_keys": active_keys,
        "deferred_channel_keys": deferred_keys,
        "product_truths": truth_rows,
        "baseline_run_ids": baseline_run_ids,
        "strategy_analyzable_run_ids": list(synthesis_context["coverage"]["analyzable_run_ids"]),
        "metric_spec_version": package.metric_spec_version,
        "package_payload": loads(package.package_payload_json, {}),
        "required_signal_ids": _required_signal_ids(payload, truth_rows),
        "resampling_plan": _vertical_resampling_plan(prompt, package),
        "channel_evidence_snapshot_ref": {
            "source": "FROZEN_RESOLVER_CHANNEL_EVIDENCE_PROJECTION",
            "evidence_package_id": int(package.id),
            "projection_hash": _stable_hash([
                {
                    "channel_key": row["channel_key"],
                    "supporting_signal_ids": row.get("supporting_signal_ids") or [],
                }
                for row in synthesis_context["channel_resolutions"]
            ]),
        },
    }
    return context, candidate, package


def run_execution_proposal_shadow(
    db: Session,
    project_id: int,
    prompt_id: int,
    candidate_id: int | None = None,
) -> dict:
    context, candidate, _package = _build_db_context(db, project_id, prompt_id, candidate_id)
    before = {
        "candidate_hash": _stable_hash({
            "structured": candidate.structured_payload_json,
            "effective": candidate.effective_payload_json,
            "review_status": candidate.review_status,
        }),
        "actions": db.query(OptimizationAction).count(),
        "experiments": db.query(OptimizationExperiment).count(),
    }
    result = build_execution_proposal_portfolio(context, managed_assets=[])
    refreshed = db.get(OptimizationStrategyCandidate, int(candidate.id))
    after = {
        "candidate_hash": _stable_hash({
            "structured": refreshed.structured_payload_json,
            "effective": refreshed.effective_payload_json,
            "review_status": refreshed.review_status,
        }),
        "actions": db.query(OptimizationAction).count(),
        "experiments": db.query(OptimizationExperiment).count(),
    }
    return {
        **result,
        "project_id": project_id,
        "prompt_id": prompt_id,
        "strategy_candidate_id": int(candidate.id),
        "strategy_candidate_status": candidate.review_status,
        "input_summary": {
            "evidence_package_id": context["evidence_package_id"],
            "evidence_package_version": context["evidence_package_version"],
            "baseline_run_count": len(context["baseline_run_ids"]),
            "strategy_run_count": len(context["strategy_analyzable_run_ids"]),
            "theme_count": len(context["themes"]),
            "reason_count": len(context["decision_reasons"]),
            "product_truth_count": len(context["product_truths"]),
            "channel_roles": context["frozen_semantics"]["resolver_roles"],
            "managed_asset_count": 0,
        },
        "semantic_regression": {
            "strategy_basis": context["strategy_basis"],
            "resolver_roles_unchanged": True,
            "benchmark_signature_unchanged": True,
        },
        "mutation_guard": {
            "candidate_unchanged": before["candidate_hash"] == after["candidate_hash"],
            "action_created": after["actions"] - before["actions"],
            "experiment_created": after["experiments"] - before["experiments"],
            "managed_asset_created": 0,
            "execution_snapshot_created": 0,
            "step8_modified": False,
        },
    }


def _runtime_mutation_snapshot(db: Session, candidate: OptimizationStrategyCandidate) -> dict:
    return {
        "candidate_hash": _stable_hash({
            "structured": candidate.structured_payload_json,
            "effective": candidate.effective_payload_json,
            "review_status": candidate.review_status,
        }),
        "actions": db.query(OptimizationAction).count(),
        "experiments": db.query(OptimizationExperiment).count(),
    }


def _attach_revalidation_runtime_guard(
    db: Session,
    candidate: OptimizationStrategyCandidate,
    result: dict,
    before: dict,
    project_id: int,
    prompt_id: int,
) -> dict:
    refreshed = db.get(OptimizationStrategyCandidate, int(candidate.id))
    after = _runtime_mutation_snapshot(db, refreshed)
    return {
        **result,
        "project_id": project_id,
        "prompt_id": prompt_id,
        "mutation_guard": {
            "candidate_unchanged": before["candidate_hash"] == after["candidate_hash"],
            "action_created": after["actions"] - before["actions"],
            "experiment_created": after["experiments"] - before["experiments"],
            "managed_asset_created": 0,
            "execution_snapshot_created": 0,
            "step8_freeze_performed": False,
        },
    }


def run_execution_proposal_revalidation(
    db: Session,
    project_id: int,
    prompt_id: int,
    payload: dict,
) -> dict:
    candidate_id = payload.get("strategy_candidate_id")
    context, candidate, _package = _build_db_context(db, project_id, prompt_id, candidate_id)
    before = _runtime_mutation_snapshot(db, candidate)
    result = revalidate_execution_proposal(context, payload, managed_assets=[])
    return _attach_revalidation_runtime_guard(db, candidate, result, before, project_id, prompt_id)


def run_execution_proposal_portfolio_revalidation(
    db: Session,
    project_id: int,
    prompt_id: int,
    payload: dict,
) -> dict:
    candidate_id = payload.get("strategy_candidate_id")
    context, candidate, _package = _build_db_context(db, project_id, prompt_id, candidate_id)
    before = _runtime_mutation_snapshot(db, candidate)
    result = revalidate_execution_proposal_portfolio(context, payload, managed_assets=[])
    return _attach_revalidation_runtime_guard(db, candidate, result, before, project_id, prompt_id)
