"""PR3-A read-only Channel Resolver shadow.

This module compares the current Step 7 channel decision with a deterministic
resolver that separates evidence-backed channels from testable opportunities.
It never mutates StrategyCandidate/Action/Experiment state and never calls an
LLM.  SourceClaim and source text are used only for Path D relevance diagnosis;
they do not change the frozen Phase 2A evidence eligibility.
"""

from __future__ import annotations

from collections import defaultdict
import re
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    OptimizationEvidencePackage,
    OptimizationStrategyCandidate,
    Project,
    Prompt,
    ReferenceSource,
    RetrievalCandidate,
    SourceClaim,
    SourceDocument,
    TargetBrandCapabilityTruth,
)
from app.modules.optimization.channel_evidence import build_channel_evidence_landscape
from app.modules.optimization.passage_retrieval import tokenize_zh
from app.modules.optimization.service import (
    CURRENT_STEP7_CANDIDATE_ORIGIN,
    _current_step7_strategy_rows_for_package,
    _resolve_vertical_slice_package,
    infer_strategy_candidate_origin,
)
from app.services.serialization import loads
from app.services.url_identity import build_url_identity


SHADOW_VERSION = "strategy_channel_resolver.v1_1"
ANSWER_DECISION_EVIDENCE_GAP = "ANSWER_DECISION_EVIDENCE_GAP"
EVIDENCE_ROLES = {"PRIMARY", "SECONDARY"}
EXECUTABLE_ROLES = {"PRIMARY", "SECONDARY", "TEST"}
KNOWN_TEST_CHANNELS = {
    "BAIJIAHAO": "搜索分发型知识内容",
    "BILIBILI": "视频教程或操作演示",
    "CSDN": "技术说明或操作教程",
    "DOUYIN": "短视频演示或场景验证",
    "JIANSHU": "解释型文章",
    "JUEJIN": "技术说明或操作教程",
    "SOHU": "搜索分发型解释内容",
    "WECHAT": "一方或行业解释内容",
    "XIAOHONGSHU": "场景化经验内容",
    "ZHIHU": "专业问答、对比或场景解释",
}
_STRONG_RELEVANCE = 0.34
_WEAK_RELEVANCE = 0.12


def _compact(text: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", (text or "").casefold())


def _lexical_relevance(reason_text: str, evidence_text: str) -> float:
    reason_tokens = set(tokenize_zh(reason_text))
    evidence_tokens = set(tokenize_zh(evidence_text[:12_000]))
    if not reason_tokens or not evidence_tokens:
        return 0.0
    compact_reason = _compact(reason_text)
    compact_evidence = _compact(evidence_text)
    if compact_reason and compact_reason in compact_evidence:
        return 1.0
    return len(reason_tokens & evidence_tokens) / len(reason_tokens)


def _role(channel: dict, name: str) -> dict:
    return (channel.get("role_counts") or {}).get(name) or {}


def _signal_ids(role_payload: dict) -> list[str]:
    sources = role_payload.get("role_source_ids") or {}
    result = []
    for field, prefix in (
        ("evidence_alignment_ids", "alignment"),
        ("decision_binding_ids", "decision_binding"),
        ("source_claim_ids", "source_claim"),
        ("source_document_ids", "source_document"),
        ("reference_source_ids", "reference"),
        ("retrieval_candidate_ids", "retrieval"),
    ):
        result.extend(f"{prefix}:{value}" for value in sources.get(field, []) if value)
    return result


def _truth_is_confirmed(truth: dict) -> bool:
    return str(truth.get("status") or "").upper() in {"TRUE", "SUPPORTED", "CONFIRMED_TRUE"}


def _truth_is_stable(truth: dict) -> bool:
    source = str(truth.get("truth_source") or "").upper()
    return _truth_is_confirmed(truth) and (
        source.startswith("MANUAL")
        or source.startswith("HUMAN")
        or bool(truth.get("reviewed_at"))
    )


def _channel_reasons(channel_key: str, reason_breakdown: list[dict]) -> list[dict]:
    result = []
    for reason in reason_breakdown:
        matched = next(
            (
                item
                for item in reason.get("channels") or []
                if item.get("channel_key") == channel_key
            ),
            None,
        )
        if matched:
            result.append({**reason, "channel_role_counts": matched.get("role_counts") or {}})
    return result


def _reason_matches_need(reason_text: str, decision_reasons: list[dict]) -> bool:
    left = _compact(reason_text)
    for reason in decision_reasons:
        right = _compact(str(reason.get("text") or ""))
        if not left or not right:
            continue
        if left in right or right in left:
            return True
        left_tokens = set(tokenize_zh(left))
        right_tokens = set(tokenize_zh(right))
        if left_tokens and right_tokens and len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens)) >= 0.5:
            return True
    return False


def _path_a(channel: dict, context: dict) -> dict:
    decision = _role(channel, "DECISION_CITATION")
    observed_reasons = [
        item
        for item in _channel_reasons(channel["channel_key"], context.get("reason_breakdown") or [])
        if int((item.get("channel_role_counts") or {}).get("DECISION_CITATION", {}).get("semantic_relation_count") or 0) > 0
        and _reason_matches_need(item.get("reason_text") or "", context["decision_reasons"])
    ]
    has_decision = int(decision.get("semantic_relation_count") or 0) > 0 and bool(observed_reasons)
    intervention_fit = context["intervention_need"]["route"] in {"CONTENT", "EVIDENCE"}
    asset_opportunity = context["product_truth_confirmed"] and not channel["channel_key"].startswith("COMPETITOR_")
    eligible = has_decision and intervention_fit and asset_opportunity
    blockers = []
    if not has_decision:
        blockers.append("NO_CURRENT_REASON_ELIGIBLE_DECISION_CITATION")
    if not intervention_fit:
        blockers.append("INTERVENTION_NEED_NOT_CHANNEL_ADDRESSABLE")
    if not asset_opportunity:
        blockers.append("NO_TARGET_ASSET_OR_CREATABLE_ASSET_OPPORTUNITY")
    return {
        "path": "OBSERVED_DECISION_CHANNEL",
        "eligible": eligible,
        "reason": (
            "当前 Decision Reason 在该渠道存在 Phase 2A eligible Decision Citation，且目标品牌具备可创建的对应内容资产机会。"
            if eligible
            else "；".join(blockers)
        ),
        "matched_decision_reasons": [item.get("reason_text") for item in observed_reasons],
        "supporting_signal_ids": _signal_ids(decision) if eligible else [],
        "blocking_signals": blockers,
    }


def _path_b(channel: dict, context: dict) -> dict:
    benchmark_ids = set(context.get("benchmark_evidence_ids") or [])
    decision = _role(channel, "DECISION_CITATION")
    channel_alignment_ids = {
        int(item)
        for item in (decision.get("role_source_ids") or {}).get("evidence_alignment_ids", [])
        if item
    }
    channel_benchmark_ids = sorted(benchmark_ids & channel_alignment_ids)
    has_pattern = bool(channel_benchmark_ids)
    target_gap = context["channel_target_gaps"].get(channel["channel_key"], {}).get("state") == "PASS"
    eligible = has_pattern and context["product_truth_confirmed"] and target_gap
    blockers = []
    if not benchmark_ids:
        blockers.append("NO_ELIGIBLE_BENCHMARK")
    elif not has_pattern:
        blockers.append("BENCHMARK_NOT_ATTRIBUTED_TO_CHANNEL_DECISION_PATTERN")
    if not context["product_truth_confirmed"]:
        blockers.append("TARGET_PRODUCT_TRUTH_NOT_CONFIRMED")
    if not target_gap:
        blockers.append("NO_TARGET_RETRIEVAL_OR_CITATION_GAP")
    return {
        "path": "BENCHMARK_INTERVENTION_PATTERN",
        "eligible": eligible,
        "reason": (
            "eligible Benchmark 在该渠道形成当前理由的决策优势，目标品牌能力已确认且该渠道仍存在目标品牌采纳缺口。"
            if eligible
            else "；".join(blockers)
        ),
        "benchmark_evidence_ids": channel_benchmark_ids,
        "supporting_signal_ids": [f"alignment:{item}" for item in channel_benchmark_ids],
        "blocking_signals": blockers,
    }


def _path_c(channel: dict, context: dict) -> dict:
    is_official = channel["channel_key"] == "OFFICIAL_SITE"
    stable_truths = [item for item in context["product_truths"] if _truth_is_stable(item)]
    stable_truth_by_id = {
        int(item["id"]): item
        for item in stable_truths
        if item.get("id")
    }
    relevant_assets = context.get("relevant_official_assets") or []
    authority_required = bool(context["intervention_need"].get("first_party_authority_required"))
    if relevant_assets:
        asset_status = "EXISTING_ASSET"
        asset_ref = relevant_assets[0]
    elif authority_required:
        asset_status = "MISSING_BUT_REQUIRED_ASSET"
        asset_ref = None
    else:
        asset_status = "UNAVAILABLE"
        asset_ref = None
    reason_evidence = []
    for reason in context["decision_reasons"]:
        requested_truth_ids = {
            int(value)
            for value in reason.get("product_truth_ids") or []
            if value
        }
        matched_truths = [stable_truth_by_id[value] for value in sorted(requested_truth_ids & set(stable_truth_by_id))]
        truth_refs = [
            {
                "id": item.get("id"),
                "capability_label": item.get("capability_label"),
                "truth_source": item.get("truth_source"),
                "source_reference": item.get("source_reference"),
            }
            for item in matched_truths
        ]
        truth_confirmed = bool(requested_truth_ids) and requested_truth_ids.issubset(stable_truth_by_id)
        reason_eligible = bool(
            is_official
            and truth_confirmed
            and asset_status in {"EXISTING_ASSET", "MISSING_BUT_REQUIRED_ASSET"}
            and authority_required
        )
        reason_evidence.append({
            "decision_reason_id": reason.get("id"),
            "decision_reason_text": reason.get("text"),
            "product_truth_refs": truth_refs,
            "product_truth_confirmed": truth_confirmed,
            "authority_asset": {
                "status": asset_status,
                "asset_ref": asset_ref,
            },
            "authority_rationale": (
                "该具体 Decision Reason 已由其直接关联的目标品牌 Product Truth 确认；"
                "需要由目标品牌一方权威资产承载可摘录事实，不能借用其他 Reason 的 Product Truth。"
                if reason_eligible
                else "该 Reason 尚未同时满足直接关联 Product Truth 与一方权威资产要求。"
            ),
            "eligible": reason_eligible,
        })
    eligible_reasons = [item for item in reason_evidence if item["eligible"]]
    eligible = bool(eligible_reasons)
    reason_ids = [item["decision_reason_id"] for item in eligible_reasons if item.get("decision_reason_id")]
    truth_refs = []
    seen_truth_ids = set()
    for reason in eligible_reasons:
        for truth in reason["product_truth_refs"]:
            if truth.get("id") in seen_truth_ids:
                continue
            seen_truth_ids.add(truth.get("id"))
            truth_refs.append(truth)
    authority = {
        "asset_status": asset_status,
        "asset_ref": asset_ref,
        "decision_reason_ids": reason_ids,
        "product_truth_refs": truth_refs,
        "reason_evidence": reason_evidence,
        "authority_rationale": (
            f"{len(eligible_reasons)} 个具体 Decision Reason 分别通过 Product Truth 与一方权威资产 Gate；"
            "可在现有相关官方资产补齐证据，或创建承载对应理由的一方权威资产。"
            if authority_required else "当前缺口没有证明必须由目标品牌一方事实源优先承接。"
        ),
    }
    blockers = []
    if not is_official:
        blockers.append("NOT_TARGET_FIRST_PARTY_CHANNEL")
    if not stable_truths:
        blockers.append("NO_STABLE_CONFIRMED_PRODUCT_TRUTH")
    if not eligible_reasons:
        blockers.append("NO_REASON_WITH_DIRECT_CONFIRMED_PRODUCT_TRUTH")
    if asset_status == "UNAVAILABLE":
        blockers.append("NO_RELEVANT_OR_REQUIRED_AUTHORITY_ASSET")
    if not authority_required:
        blockers.append("FIRST_PARTY_AUTHORITY_NEED_NOT_ESTABLISHED")
    return {
        "path": "AUTHORITATIVE_PRODUCT_TRUTH_INTERVENTION",
        "eligible": eligible,
        "reason": authority["authority_rationale"] if eligible else "；".join(blockers),
        "authority_asset_evidence": authority if is_official else None,
        "decision_reason_ids": reason_ids,
        "supporting_signal_ids": [f"product_truth:{item.get('id')}" for item in truth_refs if item.get("id")],
        "blocking_signals": blockers,
    }


def _exposure_state(channel: dict) -> dict:
    peripheral = _role(channel, "PERIPHERAL_CITATION")
    retrieval = _role(channel, "RETRIEVAL_ONLY")
    observed_runs = set(peripheral.get("observed_run_ids") or []) | set(retrieval.get("observed_run_ids") or [])
    unique_urls = int(peripheral.get("unique_url_count") or 0) + int(retrieval.get("unique_url_count") or 0)
    observations = int(peripheral.get("observation_count") or 0) + int(retrieval.get("observation_count") or 0)
    state = "PASS" if len(observed_runs) >= 2 and unique_urls >= 1 else "WEAK" if observations else "FAIL"
    signal_ids = sorted(set(_signal_ids(peripheral) + _signal_ids(retrieval)))
    return {
        "state": state,
        "peripheral_observations": int(peripheral.get("observation_count") or 0),
        "retrieval_observations": int(retrieval.get("observation_count") or 0),
        "observed_run_count": len(observed_runs),
        "unique_url_count": unique_urls,
        "supporting_signal_count": len(signal_ids),
        "supporting_signal_ids": signal_ids[:40],
    }


def _path_d(channel: dict, context: dict) -> dict:
    exposure = _exposure_state(channel)
    reason_results = context["reason_relevance"].get(channel["channel_key"], [])
    strong_reasons = [item for item in reason_results if item["state"] == "PASS"]
    weak_reasons = [item for item in reason_results if item["state"] == "WEAK"]
    relevance_state = "PASS" if strong_reasons else "WEAK" if weak_reasons else "FAIL"
    target_gap = context["channel_target_gaps"].get(channel["channel_key"], {"state": "FAIL"})
    competitor_owned = channel["channel_key"].startswith("COMPETITOR_")
    known_asset_form = KNOWN_TEST_CHANNELS.get(channel["channel_key"])
    if competitor_owned:
        fit_state = "FAIL"
        fit_reason = "竞品一方域名不是目标品牌可执行渠道。"
    elif known_asset_form and relevance_state == "PASS" and context["intervention_need"]["route"] in {"CONTENT", "EVIDENCE"}:
        fit_state = "PASS"
        fit_reason = f"该渠道已出现与当前理由相关的真实内容，可用{known_asset_form}形成低成本验证。"
    elif channel["channel_key"] == "OFFICIAL_SITE":
        fit_state = "WEAK"
        fit_reason = "官网机会应由 Path C 的一方事实 Gate 判断，不能由曝光量降级生成 TEST。"
    elif relevance_state != "PASS":
        fit_state = "WEAK"
        fit_reason = "尚未观察到足够强的当前理由相关内容，无法形成明确干预假设。"
    else:
        fit_state = "WEAK"
        fit_reason = "渠道资产形式或目标品牌可执行边界尚不清楚。"
    reason_level_evaluations = []
    for reason in reason_results:
        if competitor_owned:
            reason_fit = "FAIL"
        elif reason["state"] == "PASS" and known_asset_form:
            reason_fit = "PASS"
        elif reason["state"] == "FAIL":
            reason_fit = "FAIL"
        else:
            reason_fit = "WEAK"
        reason_level_evaluations.append({
            **reason,
            "channel_exposure": exposure["state"],
            "target_gap": target_gap.get("state"),
            "intervention_fit": reason_fit,
        })
    eligible = all(
        item == "PASS"
        for item in (exposure["state"], relevance_state, target_gap.get("state"), fit_state)
    )
    reason_ids = [item["reason_id"] for item in strong_reasons]
    why_test = (
        f"该渠道稳定进入当前 Prompt 信息环境，并对 {len(strong_reasons)} 个当前 Decision Reason 有直接词法/SourceClaim 相关信号；"
        "目标品牌尚无正式 Decision/Support 采纳，可用一个受控内容实验验证 Retrieval/Citation 提升。"
        if eligible else ""
    )
    blockers = []
    for name, state in (
        ("EXPOSURE", exposure["state"]),
        ("DECISION_REASON_RELEVANCE", relevance_state),
        ("TARGET_GAP", target_gap.get("state")),
        ("INTERVENTION_FIT", fit_state),
    ):
        if state != "PASS":
            blockers.append(f"{name}_{state}")
    signal_ids = set(exposure["supporting_signal_ids"])
    for item in strong_reasons:
        signal_ids.update(item.get("supporting_signal_ids") or [])
    return {
        "path": "RETRIEVAL_EXPOSURE_OPPORTUNITY",
        "eligible": eligible,
        "exposure": exposure,
        "decision_reason_relevance": {
            "state": relevance_state,
            "strong_reason_count": len(strong_reasons),
            "weak_reason_count": len(weak_reasons),
            "reason_results": reason_level_evaluations,
        },
        "target_gap": target_gap,
        "intervention_fit": {"state": fit_state, "reason": fit_reason},
        "decision_reason_ids": reason_ids,
        "supporting_signal_ids": sorted(signal_ids),
        "blocking_signals": blockers,
        "why_test": why_test,
        "why_not_primary": "Path D 只证明值得验证，不证明渠道已直接影响 AI 决策；PRIMARY/SECONDARY 仍需 Path A/B/C。",
    }


def _target_gap(channel: dict) -> dict:
    decision = _role(channel, "DECISION_CITATION")
    support = _role(channel, "ANSWER_SUPPORT_CITATION")
    decision_target = int((decision.get("entity_counts") or {}).get("target_brand", {}).get("observation_count") or 0)
    support_target = int((support.get("entity_counts") or {}).get("target_brand", {}).get("observation_count") or 0)
    competitor_decision = int((decision.get("entity_counts") or {}).get("competitor", {}).get("observation_count") or 0)
    if decision_target + support_target == 0:
        return {
            "state": "PASS",
            "signals": ["TARGET_BRAND_ABSENT_FROM_ELIGIBLE_DECISION_AND_SUPPORT"],
            "target_decision_observations": decision_target,
            "target_support_observations": support_target,
            "competitor_decision_observations": competitor_decision,
        }
    return {
        "state": "WEAK",
        "signals": ["TARGET_BRAND_ALREADY_HAS_ELIGIBLE_CHANNEL_EVIDENCE"],
        "target_decision_observations": decision_target,
        "target_support_observations": support_target,
        "competitor_decision_observations": competitor_decision,
    }


def _evidence_path_precedence(context: dict, evaluations: list[dict]) -> list[dict]:
    qualified: dict[str, dict] = {}
    for item in evaluations:
        paths = [item["path_a"], item["path_b"], item["path_c"]]
        eligible_paths = [path for path in paths if path["eligible"]]
        if not eligible_paths:
            continue
        path = eligible_paths[0]
        if item["path_c"]["eligible"] and context["intervention_need"].get("first_party_authority_required"):
            path = item["path_c"]
        reason_ids = (
            path.get("decision_reason_ids")
            if path["path"] == "AUTHORITATIVE_PRODUCT_TRUTH_INTERVENTION"
            else [reason.get("id") for reason in context["decision_reasons"] if reason.get("id")]
        )
        qualified[item["channel_key"]] = {
            "channel_key": item["channel_key"],
            "channel_label": item["channel_label"],
            "role": "SECONDARY",
            "rationale_path": path["path"],
            "decision_reason_ids": reason_ids,
            "supporting_signal_ids": sorted(set(path.get("supporting_signal_ids") or [])),
            "blocking_signals": [],
            "why_primary": "",
            "why_not_primary": "存在正式干预依据，但当前确定性优先路径由另一渠道承接。",
            "why_test": "",
            "authority_asset_evidence": item["path_c"].get("authority_asset_evidence") if item["path_c"]["eligible"] else None,
        }
    if not qualified:
        return []

    gap_type = context["intervention_need"].get("gap_type")
    candidates = list(qualified.values())
    official = next((item for item in candidates if item["channel_key"] == "OFFICIAL_SITE"), None)
    if official and context["intervention_need"].get("first_party_authority_required"):
        primary = official
    else:
        def decision_order(item: dict) -> tuple[int, int, str]:
            evaluation = next(row for row in evaluations if row["channel_key"] == item["channel_key"])
            decision = _role(evaluation["raw_channel"], "DECISION_CITATION")
            return (
                -int(decision.get("semantic_relation_count") or 0),
                -int(decision.get("observed_run_count") or 0),
                item["channel_key"],
            )
        primary = sorted(candidates, key=decision_order)[0]
    primary["role"] = "PRIMARY"
    primary["why_primary"] = (
        "该渠道通过明确的 evidence-backed rationale path，并在当前 intervention need 下优先承接一方事实资产。"
        if primary["channel_key"] == "OFFICIAL_SITE"
        else "该渠道通过明确的 evidence-backed rationale path，并具有最强的当前理由 Decision Evidence 覆盖。"
    )
    primary["why_not_primary"] = ""
    return sorted(candidates, key=lambda item: (0 if item["role"] == "PRIMARY" else 1, item["channel_key"]))


def resolve_channel_shadow(context: dict) -> dict:
    """Resolve one normalized context without database writes."""
    health = context.get("data_health") or "INVALID"
    if health == "INVALID":
        return {
            "resolver_version": SHADOW_VERSION,
            "strategy_opportunity_state": context.get("strategy_opportunity_state", "NONE"),
            "channel_resolution_state": "INPUT_INVALID",
            "execution_readiness": "NOT_READY",
            "proposed_intervention_mode": None,
            "active_intervention_mode": None,
            "intervention_mode": None,
            "channels": [],
            "channel_evaluations": [],
            "blocking_signals": ["DATA_HEALTH_INVALID"],
        }
    if context.get("strategy_opportunity_state") == "NONE":
        return {
            "resolver_version": SHADOW_VERSION,
            "strategy_opportunity_state": "NONE",
            "channel_resolution_state": "UNRESOLVED",
            "execution_readiness": "NOT_READY",
            "proposed_intervention_mode": None,
            "active_intervention_mode": None,
            "intervention_mode": None,
            "channels": [],
            "channel_evaluations": [],
            "blocking_signals": ["NO_VALID_STRATEGY_OPPORTUNITY"],
        }

    evaluations = []
    for channel in context.get("channels") or []:
        evaluation = {
            "channel_key": channel["channel_key"],
            "channel_label": channel.get("channel_label") or channel["channel_key"],
            "raw_channel": channel,
        }
        evaluation["path_a"] = _path_a(channel, context)
        evaluation["path_b"] = _path_b(channel, context)
        evaluation["path_c"] = _path_c(channel, context)
        evaluation["path_d"] = _path_d(channel, context)
        evaluations.append(evaluation)

    resolved_channels = _evidence_path_precedence(context, evaluations)
    resolved_keys = {item["channel_key"] for item in resolved_channels}
    has_observed_evidence_path = any(
        item["path_a"]["eligible"] or item["path_b"]["eligible"]
        for item in evaluations
    )
    for item in evaluations:
        if (
            has_observed_evidence_path
            or item["channel_key"] in resolved_keys
            or not item["path_d"]["eligible"]
        ):
            continue
        resolved_channels.append({
            "channel_key": item["channel_key"],
            "channel_label": item["channel_label"],
            "role": "TEST",
            "rationale_path": "RETRIEVAL_EXPOSURE_OPPORTUNITY",
            "decision_reason_ids": item["path_d"]["decision_reason_ids"],
            "supporting_signal_ids": item["path_d"]["supporting_signal_ids"],
            "blocking_signals": item["path_d"]["blocking_signals"],
            "why_primary": "",
            "why_not_primary": item["path_d"]["why_not_primary"],
            "why_test": item["path_d"]["why_test"],
            "exposure_signals": item["path_d"]["exposure"],
            "reason_relevance": item["path_d"]["decision_reason_relevance"],
            "target_gap": item["path_d"]["target_gap"],
            "intervention_fit": item["path_d"]["intervention_fit"],
            "test_hypothesis": {
                "channel": item["channel_key"],
                "intervention_hypothesis": item["path_d"]["why_test"],
                "success_metric": "target_channel_retrieval_rate_then_citation_rate",
                "observation_window": "沿用当前 Experiment 固定复采与最小样本规则",
            },
        })
        resolved_keys.add(item["channel_key"])

    observed = []
    for item in evaluations:
        if item["channel_key"] in resolved_keys:
            continue
        exposure = item["path_d"]["exposure"]
        if exposure["state"] == "FAIL":
            continue
        observed.append({
            "channel_key": item["channel_key"],
            "channel_label": item["channel_label"],
            "role": "OBSERVE",
            "rationale_path": "ENVIRONMENT_SIGNAL_ONLY",
            "decision_reason_ids": item["path_d"]["decision_reason_ids"],
            "supporting_signal_ids": exposure["supporting_signal_ids"],
            "blocking_signals": item["path_d"]["blocking_signals"],
            "why_primary": "",
            "why_not_primary": item["path_d"]["why_not_primary"],
            "why_test": "",
        })

    channels = resolved_channels + observed
    executable = [item for item in channels if item["role"] in EXECUTABLE_ROLES]
    resolution_state = "RESOLVED" if executable else "OBSERVE_ONLY" if observed else "UNRESOLVED"
    opportunity_confirmed = context.get("strategy_opportunity_state") == "CONFIRMED"
    step8_gates_pass = bool(context.get("step8_other_gates_pass"))
    evidence_channels = [item for item in executable if item["role"] in EVIDENCE_ROLES]
    test_channels = [item for item in executable if item["role"] == "TEST"]
    if opportunity_confirmed and step8_gates_pass and evidence_channels:
        readiness = "READY"
        proposed_intervention_mode = "CONFIRMED_CHANNEL_INTERVENTION"
        active_intervention_mode = "CONFIRMED_CHANNEL_INTERVENTION"
    elif opportunity_confirmed and step8_gates_pass and test_channels and all(item.get("test_hypothesis") for item in test_channels):
        readiness = "READY"
        proposed_intervention_mode = "CHANNEL_VALIDATION_EXPERIMENT"
        active_intervention_mode = "CHANNEL_VALIDATION_EXPERIMENT"
    else:
        readiness = "NOT_READY"
        proposed_intervention_mode = (
            "CONFIRMED_CHANNEL_INTERVENTION" if evidence_channels
            else "CHANNEL_VALIDATION_EXPERIMENT" if test_channels
            else None
        )
        active_intervention_mode = None
    return {
        "resolver_version": SHADOW_VERSION,
        "strategy_opportunity_state": context.get("strategy_opportunity_state", "NONE"),
        "channel_resolution_state": resolution_state,
        "execution_readiness": readiness,
        "proposed_intervention_mode": proposed_intervention_mode,
        "active_intervention_mode": active_intervention_mode,
        "intervention_mode": active_intervention_mode,
        "channels": channels,
        "channel_evaluations": evaluations,
        "blocking_signals": [
            *([] if opportunity_confirmed else ["STRATEGY_OPPORTUNITY_NOT_CONFIRMED"]),
            *([] if step8_gates_pass else ["STEP8_OTHER_GATES_NOT_PASS"]),
        ],
    }


def _current_candidate(db: Session, package: OptimizationEvidencePackage) -> OptimizationStrategyCandidate | None:
    candidates = (
        db.query(OptimizationStrategyCandidate)
        .filter(
            OptimizationStrategyCandidate.project_id == package.project_id,
            OptimizationStrategyCandidate.evidence_package_id == package.id,
        )
        .order_by(OptimizationStrategyCandidate.created_at.desc(), OptimizationStrategyCandidate.id.desc())
        .all()
    )
    return next(
        (
            item for item in candidates
            if infer_strategy_candidate_origin(item) == CURRENT_STEP7_CANDIDATE_ORIGIN
            and item.review_status not in {"DEFERRED", "REJECTED", "VALIDATION_FAILED"}
        ),
        None,
    )


def _opportunity_state(candidate: OptimizationStrategyCandidate | None, has_action: bool) -> str:
    if candidate is None:
        return "IDENTIFIED" if has_action else "NONE"
    if candidate.review_status in {"ACCEPTED", "ACCEPTED_WITH_EDITS"}:
        return "CONFIRMED"
    if candidate.review_status == "PENDING_REVIEW":
        return "PENDING_REVIEW"
    if candidate.review_status == "DEFERRED":
        return "SUPERSEDED"
    return "IDENTIFIED" if has_action else "NONE"


def _decision_reasons(action: dict) -> list[dict]:
    reasons: dict[str, dict] = {}
    for item in action.get("gap_items") or []:
        text = str(item.get("answer_decision_reason") or item.get("capability_label") or "").strip()
        if not text:
            continue
        reason_id = str(item.get("decision_reason_id") or item.get("gap_item_id") or text)
        reasons[reason_id] = {
            "id": reason_id,
            "text": text,
            "observed_run_ids": sorted({int(value) for value in item.get("observed_run_ids") or [] if value}),
            "product_truth_ids": sorted({int(value) for value in item.get("product_truth_ids") or [] if value}),
        }
    if not reasons:
        for reason_id in action.get("decision_reason_ids") or []:
            reasons[str(reason_id)] = {"id": str(reason_id), "text": str(reason_id), "observed_run_ids": [], "product_truth_ids": []}
    return list(reasons.values())


def _relevant_assets(action: dict) -> list[dict]:
    result = []
    seen = set()
    for item in action.get("gap_items") or []:
        asset = item.get("relevant_asset_snapshot")
        if not isinstance(asset, dict) or not asset:
            continue
        key = str(asset.get("snapshot_id") or asset.get("asset_id") or asset.get("canonical_url") or asset.get("url") or "")
        if key in seen:
            continue
        seen.add(key)
        result.append(asset)
    return result


def _truth_rows(db: Session, project_id: int, action: dict) -> list[dict]:
    ids = {
        int(value)
        for item in action.get("gap_items") or []
        for value in item.get("product_truth_ids") or []
        if value
    } | {int(value) for value in action.get("product_truth_ids") or [] if value}
    rows = db.query(TargetBrandCapabilityTruth).filter(
        TargetBrandCapabilityTruth.project_id == project_id,
        TargetBrandCapabilityTruth.id.in_(ids),
    ).all() if ids else []
    return [{
        "id": int(item.id),
        "capability_key": item.capability_key,
        "capability_label": item.capability_label,
        "status": item.product_truth_status,
        "truth_source": item.truth_source,
        "source_reference": item.source_reference,
        "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
        "note": item.note,
    } for item in rows]


def _old_channel_decision(candidate: OptimizationStrategyCandidate | None) -> dict:
    if candidate is None:
        return {"candidate_id": None, "primary": [], "secondary": [], "observe": [], "planned_channels": []}
    payload = loads(candidate.structured_payload_json, {})
    planned = payload.get("planned_channels") or []
    primary = next((item for item in planned if item.get("intervention_priority") == "PRIMARY"), {})
    return {
        "candidate_id": int(candidate.id),
        "review_status": candidate.review_status,
        "primary": [item.get("channel") for item in planned if item.get("intervention_priority") == "PRIMARY"],
        "secondary": [item.get("channel") for item in planned if item.get("intervention_priority") in {"SECONDARY", "EXPERIMENTAL"}],
        "observe": [item.get("channel") for item in planned if item.get("intervention_priority") == "OBSERVE"],
        "primary_intervention_path": payload.get("primary_intervention_path"),
        "primary_rationale_path": primary.get("intervention_type"),
        "primary_brand_asset_present": bool((primary.get("brand_asset_basis") or {}).get("has_relevant_asset_snapshot")),
        "primary_decision_citation_run_count": int(primary.get("decision_citation_run_count") or 0),
        "planned_channels": planned,
    }


def _channel_text_signals(db: Session, landscape: dict) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = defaultdict(list)
    ref_ids_by_channel: dict[str, set[int]] = defaultdict(set)
    retrieval_ids_by_channel: dict[str, set[int]] = defaultdict(set)
    doc_ids_by_channel: dict[str, set[int]] = defaultdict(set)
    for channel in landscape.get("channels") or []:
        key = channel["channel_key"]
        for role_payload in (channel.get("role_counts") or {}).values():
            sources = role_payload.get("role_source_ids") or {}
            ref_ids_by_channel[key].update(int(item) for item in sources.get("reference_source_ids", []) if item)
            retrieval_ids_by_channel[key].update(int(item) for item in sources.get("retrieval_candidate_ids", []) if item)
            doc_ids_by_channel[key].update(int(item) for item in sources.get("source_document_ids", []) if item)

    all_ref_ids = set().union(*ref_ids_by_channel.values()) if ref_ids_by_channel else set()
    all_retrieval_ids = set().union(*retrieval_ids_by_channel.values()) if retrieval_ids_by_channel else set()
    refs = db.query(ReferenceSource).filter(ReferenceSource.id.in_(all_ref_ids)).all() if all_ref_ids else []
    retrievals = db.query(RetrievalCandidate).filter(RetrievalCandidate.id.in_(all_retrieval_ids)).all() if all_retrieval_ids else []
    ref_by_id = {int(item.id): item for item in refs}
    retrieval_by_id = {int(item.id): item for item in retrievals}

    record_channels_by_hash: dict[str, set[str]] = defaultdict(set)
    runs_by_hash: dict[str, set[int]] = defaultdict(set)
    for key, ids in ref_ids_by_channel.items():
        for item_id in ids:
            item = ref_by_id.get(item_id)
            if item is None:
                continue
            identity = build_url_identity(item.url or item.canonical_url, item.canonical_url or item.url)
            url_hash = identity.canonical_url_hash
            if url_hash:
                record_channels_by_hash[url_hash].add(key)
                runs_by_hash[url_hash].add(int(item.run_id))
            result[key].append({
                "id": f"reference:{item.id}",
                "kind": "REFERENCE_TITLE",
                "text": " ".join(filter(None, [item.display_title, item.matched_title])),
                "run_ids": [int(item.run_id)],
                "url_hash": url_hash,
            })
    for key, ids in retrieval_ids_by_channel.items():
        for item_id in ids:
            item = retrieval_by_id.get(item_id)
            if item is None:
                continue
            identity = build_url_identity(item.url or item.canonical_url, item.canonical_url or item.url)
            url_hash = identity.canonical_url_hash
            if url_hash:
                record_channels_by_hash[url_hash].add(key)
                runs_by_hash[url_hash].add(int(item.run_id))
            result[key].append({
                "id": f"retrieval:{item.id}",
                "kind": "RETRIEVAL_TITLE_SNIPPET",
                "text": " ".join(filter(None, [item.title, item.snippet, item.retrieval_query])),
                "run_ids": [int(item.run_id)],
                "url_hash": url_hash,
            })

    hashes = set(record_channels_by_hash)
    docs = db.query(
        SourceDocument.id,
        SourceDocument.url,
        SourceDocument.canonical_url,
        SourceDocument.canonical_url_hash,
        SourceDocument.title,
        func.substr(SourceDocument.clean_text, 1, 12_000).label("clean_text"),
    ).filter(SourceDocument.canonical_url_hash.in_(hashes)).all() if hashes else []
    for doc in docs:
        doc_hash = doc.canonical_url_hash or build_url_identity(doc.url or doc.canonical_url).canonical_url_hash
        for key in record_channels_by_hash.get(doc_hash, set()):
            doc_ids_by_channel[key].add(int(doc.id))
            result[key].append({
                "id": f"source_document:{doc.id}",
                "kind": "SOURCE_DOCUMENT_TEXT",
                "text": " ".join(filter(None, [doc.title, (doc.clean_text or "")[:12_000]])),
                "run_ids": sorted(runs_by_hash.get(doc_hash, set())),
                "url_hash": doc_hash,
            })
    all_doc_ids = set().union(*doc_ids_by_channel.values()) if doc_ids_by_channel else set()
    claims = db.query(
        SourceClaim.id,
        SourceClaim.source_document_id,
        SourceClaim.normalized_claim,
        SourceClaim.source_span,
        SourceClaim.predicate,
        SourceClaim.object_text,
    ).filter(SourceClaim.source_document_id.in_(all_doc_ids)).all() if all_doc_ids else []
    claim_channels_by_doc = defaultdict(set)
    for key, doc_ids in doc_ids_by_channel.items():
        for doc_id in doc_ids:
            claim_channels_by_doc[doc_id].add(key)
    doc_hash_by_id = {int(item.id): item.canonical_url_hash for item in docs}
    for claim in claims:
        doc_hash = doc_hash_by_id.get(int(claim.source_document_id), "")
        for key in claim_channels_by_doc.get(int(claim.source_document_id), set()):
            result[key].append({
                "id": f"source_claim:{claim.id}",
                "kind": "SOURCE_CLAIM_DIAGNOSTIC_RELEVANCE_ONLY",
                "text": " ".join(filter(None, [claim.normalized_claim, claim.source_span, claim.predicate, claim.object_text])),
                "run_ids": sorted(runs_by_hash.get(doc_hash, set())),
                "url_hash": doc_hash,
                "formal_evidence_eligibility": "NOT_PROMOTED_BY_PATH_D",
            })
    return result


def _reason_relevance(decision_reasons: list[dict], signals_by_channel: dict[str, list[dict]]) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for channel_key, signals in signals_by_channel.items():
        reason_rows = []
        for reason in decision_reasons:
            scored = []
            for signal in signals:
                score = _lexical_relevance(reason["text"], signal.get("text") or "")
                if score <= 0:
                    continue
                scored.append((score, signal))
            scored.sort(key=lambda item: (-item[0], item[1]["id"]))
            best_score = scored[0][0] if scored else 0.0
            strong = [item for score, item in scored if score >= _STRONG_RELEVANCE]
            weak = [item for score, item in scored if _WEAK_RELEVANCE <= score < _STRONG_RELEVANCE]
            relevant_runs = {run_id for item in strong for run_id in item.get("run_ids") or []}
            relevant_urls = {item.get("url_hash") for item in strong if item.get("url_hash")}
            if best_score >= _STRONG_RELEVANCE and (len(relevant_runs) >= 2 or len(relevant_urls) >= 2):
                state = "PASS"
            elif best_score >= _WEAK_RELEVANCE:
                state = "WEAK"
            else:
                state = "FAIL"
            reason_rows.append({
                "reason_id": reason["id"],
                "reason_text": reason["text"],
                "state": state,
                "best_lexical_relevance": round(best_score, 4),
                "relevant_run_count": len(relevant_runs),
                "relevant_unique_url_count": len(relevant_urls),
                "supporting_signal_ids": [item["id"] for item in strong[:20]],
                "weak_signal_ids": [item["id"] for item in weak[:10]],
                "boundary": "仅用于 Path D 相关性诊断，不改变 Citation Role、Benchmark 或 Phase 2A eligibility。",
            })
        result[channel_key] = reason_rows
    return result


def _choose_action(rows: list[dict], candidate: OptimizationStrategyCandidate | None) -> dict | None:
    actions = [row.get("recommended_action") for row in rows if row.get("recommended_action")]
    if not actions:
        return None
    if candidate is not None:
        payload = loads(candidate.structured_payload_json, {})
        source_action_key = payload.get("source_action_key")
        matched = next((item for item in actions if item.get("action_key") == source_action_key), None)
        if matched:
            return matched
    return actions[0]


def _action_from_candidate(candidate: OptimizationStrategyCandidate | None) -> dict | None:
    if candidate is None:
        return None
    payload = loads(candidate.structured_payload_json, {})
    evidence = payload.get("evidence_summary") or {}
    gap_items = evidence.get("gap_items") or []
    if not gap_items:
        return None
    return {
        "action_key": payload.get("source_action_key"),
        "route": payload.get("proposed_direction") or "UNRESOLVED",
        "gap_type": evidence.get("gap_type") or gap_items[0].get("gap_type") or "UNKNOWN",
        "strategy_basis": payload.get("strategy_basis") or "BENCHMARK_BACKED_STRATEGY",
        "decision_reason_ids": payload.get("decision_reason_ids") or [],
        "decision_reason_event_ids": payload.get("decision_reason_event_ids") or [],
        "evidence_gap_reason": payload.get("evidence_gap_reason") or "",
        "evidence_gap_cause": payload.get("evidence_gap_cause") or "",
        "eligible_support_count": int(payload.get("eligible_support_count") or 0),
        "eligible_contradiction_ids": payload.get("eligible_contradiction_ids") or [],
        "benchmark_evidence_ids": payload.get("benchmark_evidence_ids") or [],
        "benchmark_source": payload.get("benchmark_source") or evidence.get("benchmark_source") or {},
        "citation_decision_values": payload.get("citation_decision_values") or evidence.get("citation_decision_values") or [],
        "citation_value_summary": payload.get("citation_value_summary") or evidence.get("citation_value_summary") or {},
        "channel_aggregation": payload.get("channel_aggregation") or evidence.get("channel_aggregation") or [],
        "product_truth_ids": (payload.get("product_truth_refs") or {}).get("ids") or [],
        "product_truth_status": (payload.get("product_truth_refs") or {}).get("status") or "UNKNOWN",
        "gap_items": gap_items,
    }


def build_channel_resolution_context(
    db: Session,
    project: Project,
    prompt: Prompt,
    package: OptimizationEvidencePackage,
    action: dict,
    *,
    candidate: OptimizationStrategyCandidate | None = None,
    strategy_opportunity_state: str | None = None,
    step8_other_gates_pass: bool | None = None,
) -> tuple[dict, dict]:
    """Build the normalized input shared by shadow and production resolution."""
    landscape = build_channel_evidence_landscape(db, project.id, prompt.id, package.id)
    decision_reasons = _decision_reasons(action)
    truths = _truth_rows(db, project.id, action)
    assets = _relevant_assets(action)
    product_truth_confirmed = bool(truths) and all(_truth_is_confirmed(item) for item in truths)
    confirmed_truth_ids = {int(item["id"]) for item in truths if item.get("id") and _truth_is_confirmed(item)}
    reasons_with_confirmed_truth = [
        reason
        for reason in decision_reasons
        if reason.get("product_truth_ids")
        and set(int(value) for value in reason.get("product_truth_ids") or []).issubset(confirmed_truth_ids)
    ]
    gap_type = str(action.get("gap_type") or "UNKNOWN").upper()
    first_party_required = bool(
        reasons_with_confirmed_truth
        and (
            action.get("strategy_basis") == ANSWER_DECISION_EVIDENCE_GAP
            or gap_type == "CONTENT_GAP" and assets
        )
    )
    data_health = (
        "INVALID"
        if landscape["mapping_health"]["state"] == "INVALID" or landscape["aggregation_health"]["state"] == "INVALID"
        else "WARN"
        if landscape["mapping_health"]["state"] == "WARN" or landscape["aggregation_health"]["state"] == "WARN"
        else "HEALTHY"
    )
    if step8_other_gates_pass is None:
        step8_other_gates_pass = bool(
            candidate
            and candidate.evidence_validation_status == "VALIDATED"
            and candidate.hypothesis_validation_status == "VALIDATED"
            and candidate.effective_validation_status == "VALIDATED"
        )
    context = {
        "project_id": project.id,
        "prompt_id": prompt.id,
        "evidence_package_id": int(package.id),
        "strategy_basis": action.get("strategy_basis") or "BENCHMARK_BACKED_STRATEGY",
        "strategy_opportunity_state": strategy_opportunity_state or _opportunity_state(candidate, bool(action)),
        "intervention_need": {
            "route": action.get("route") or "UNRESOLVED",
            "gap_type": gap_type,
            "gap_layers": sorted({item.get("gap_layer") for item in action.get("gap_items") or [] if item.get("gap_layer")}),
            "first_party_authority_required": first_party_required,
            "evidence_gap_cause": action.get("evidence_gap_cause") or "",
        },
        "data_health": data_health,
        "decision_reasons": decision_reasons,
        "product_truths": truths,
        "product_truth_confirmed": product_truth_confirmed,
        "benchmark_evidence_ids": sorted({
            int(value)
            for item in action.get("gap_items") or []
            for value in item.get("benchmark_evidence_ids") or []
            if value
        } | {int(value) for value in action.get("benchmark_evidence_ids") or [] if value}),
        "relevant_official_assets": assets,
        "channels": landscape.get("channels") or [],
        "reason_breakdown": landscape.get("decision_reason_breakdown") or [],
        "channel_target_gaps": {
            item["channel_key"]: _target_gap(item)
            for item in landscape.get("channels") or []
        },
        "reason_relevance": _reason_relevance(decision_reasons, _channel_text_signals(db, landscape)),
        "step8_other_gates_pass": bool(step8_other_gates_pass),
    }
    return context, landscape


def build_channel_resolution_shadow(
    db: Session,
    project_id: int,
    prompt_id: int,
    evidence_package_id: int | None = None,
) -> dict:
    project = db.get(Project, project_id)
    prompt = db.get(Prompt, prompt_id)
    if project is None or prompt is None or prompt.project_id != project_id:
        raise ValueError("PROJECT_OR_PROMPT_NOT_FOUND")
    package = _resolve_vertical_slice_package(db, project_id, prompt_id, evidence_package_id)
    candidate_ids_before = [
        int(item.id)
        for item in db.query(OptimizationStrategyCandidate).filter(
            OptimizationStrategyCandidate.project_id == project_id,
            OptimizationStrategyCandidate.evidence_package_id == package.id,
        ).order_by(OptimizationStrategyCandidate.id).all()
    ]
    candidate = _current_candidate(db, package)
    action = _action_from_candidate(candidate)
    if action is None:
        rows = _current_step7_strategy_rows_for_package(db, project, prompt, package, include_answer_binding_v1_1=True)
        action = _choose_action(rows, candidate)
    if action is None:
        action = {}
    context, landscape = build_channel_resolution_context(
        db,
        project,
        prompt,
        package,
        action,
        candidate=candidate,
    )
    decision_reasons = context["decision_reasons"]
    data_health = context["data_health"]
    result = resolve_channel_shadow(context)
    candidate_ids_after = [
        int(item.id)
        for item in db.query(OptimizationStrategyCandidate).filter(
            OptimizationStrategyCandidate.project_id == project_id,
            OptimizationStrategyCandidate.evidence_package_id == package.id,
        ).order_by(OptimizationStrategyCandidate.id).all()
    ]
    role_groups = {
        role: [item["channel_key"] for item in result["channels"] if item["role"] == role]
        for role in ("PRIMARY", "SECONDARY", "TEST", "OBSERVE")
    }
    major_keys = {
        item["channel_key"]
        for item in sorted(
            landscape.get("channels") or [],
            key=lambda row: (-int(row.get("total_observation_count") or 0), row["channel_key"]),
        )[:8]
    } | set(role_groups["PRIMARY"]) | set(role_groups["SECONDARY"]) | set(role_groups["TEST"])
    final_channel_by_key = {item["channel_key"]: item for item in result["channels"]}
    major_evaluations = [
        {
            **{key: value for key, value in item.items() if key != "raw_channel"},
            "final_shadow_role": (final_channel_by_key.get(item["channel_key"]) or {}).get("role"),
            "final_why_not_primary": (
                (final_channel_by_key.get(item["channel_key"]) or {}).get("why_not_primary")
                or item["path_d"].get("why_not_primary")
            ),
        }
        for item in result["channel_evaluations"]
        if item["channel_key"] in major_keys
    ]
    old = _old_channel_decision(candidate)
    new_primary_channel = next((item for item in result["channels"] if item["role"] == "PRIMARY"), {})
    old_fallback_signature = bool(
        old["primary"] == ["OFFICIAL_SITE"]
        and old.get("primary_decision_citation_run_count") == 0
        and not old.get("primary_brand_asset_present")
    )
    diff = {
        "primary_changed": old["primary"] != role_groups["PRIMARY"],
        "secondary_changed": old["secondary"] != role_groups["SECONDARY"],
        "old_primary": old["primary"],
        "new_primary": role_groups["PRIMARY"],
        "old_secondary": old["secondary"],
        "new_secondary": role_groups["SECONDARY"],
        "new_test": role_groups["TEST"],
        "old_primary_rationale_path": old.get("primary_rationale_path"),
        "new_primary_rationale_path": new_primary_channel.get("rationale_path"),
        "rationale_changed": old.get("primary_rationale_path") != new_primary_channel.get("rationale_path"),
        "old_fallback_signature_detected": old_fallback_signature,
        "cutover_supersede_required": old_fallback_signature,
        "cutover_supersede_reason": (
            "CHANNEL_RESOLUTION_INVALID_DUE_TO_SOURCE_MAPPING_FAILURE"
            if old_fallback_signature else None
        ),
        "diff_reason": (
            "新 Shadow 只允许 Path A/B/C 产生 PRIMARY/SECONDARY，并以 Path D 单独表达待验证渠道；不继承旧 fallback。"
        ),
    }
    return {
        "schema_version": "channel_resolution_shadow.pr3_a.v1",
        "boundary": {
            "shadow_only": True,
            "formal_resolver_changed": False,
            "strategy_candidate_mutated": False,
            "action_or_experiment_created": False,
            "phase_2a_eligibility_changed": False,
            "external_llm_calls": 0,
        },
        "project_id": project_id,
        "prompt_id": prompt_id,
        "evidence_package_id": int(package.id),
        "strategy_basis": context["strategy_basis"],
        "strategy_opportunity_state": result["strategy_opportunity_state"],
        "data_health": data_health,
        "intervention_need": context["intervention_need"],
        "decision_reasons": decision_reasons,
        "excluded_evidence_diagnostic": landscape.get("semantic_lineage_audit") or {},
        "primary": role_groups["PRIMARY"],
        "secondary": role_groups["SECONDARY"],
        "test": role_groups["TEST"],
        "observe": role_groups["OBSERVE"],
        "channel_resolution_state": result["channel_resolution_state"],
        "execution_readiness": result["execution_readiness"],
        "proposed_intervention_mode": result["proposed_intervention_mode"],
        "active_intervention_mode": result["active_intervention_mode"],
        "intervention_mode": result["intervention_mode"],
        "channels": result["channels"],
        "major_channel_evaluations": major_evaluations,
        "old_resolver_decision": old,
        "old_vs_new": diff,
        "read_only_audit": {
            "strategy_candidate_ids_before": candidate_ids_before,
            "strategy_candidate_ids_after": candidate_ids_after,
            "mutated": candidate_ids_before != candidate_ids_after,
        },
    }


def _golden_context(**overrides: Any) -> dict:
    decision_reason = {"id": "reason:1", "text": "支持自定义分享标题", "product_truth_ids": [1]}
    empty_role = {
        "observation_count": 0,
        "semantic_relation_count": 0,
        "unique_url_count": 0,
        "observed_run_ids": [],
        "role_source_ids": {},
        "entity_counts": {"target_brand": {"observation_count": 0}, "competitor": {"observation_count": 0}},
    }
    channel = {
        "channel_key": "ZHIHU",
        "channel_label": "知乎",
        "role_counts": {
            "DECISION_CITATION": dict(empty_role),
            "ANSWER_SUPPORT_CITATION": dict(empty_role),
            "PERIPHERAL_CITATION": {**empty_role, "observation_count": 4, "unique_url_count": 2, "observed_run_ids": [1, 2]},
            "RETRIEVAL_ONLY": dict(empty_role),
        },
    }
    base = {
        "strategy_basis": ANSWER_DECISION_EVIDENCE_GAP,
        "strategy_opportunity_state": "PENDING_REVIEW",
        "intervention_need": {"route": "EVIDENCE", "gap_type": "EVIDENCE_GAP", "first_party_authority_required": False},
        "data_health": "HEALTHY",
        "decision_reasons": [decision_reason],
        "product_truths": [{"id": 1, "status": "SUPPORTED", "truth_source": "MANUAL_CONFIRMED"}],
        "product_truth_confirmed": True,
        "benchmark_evidence_ids": [],
        "relevant_official_assets": [],
        "channels": [channel],
        "reason_breakdown": [],
        "channel_target_gaps": {"ZHIHU": {"state": "PASS", "signals": ["TARGET_ABSENT"]}},
        "reason_relevance": {"ZHIHU": [{
            "reason_id": "reason:1",
            "reason_text": "支持自定义分享标题",
            "state": "PASS",
            "supporting_signal_ids": ["source_claim:1"],
        }]},
        "step8_other_gates_pass": False,
    }
    base.update(overrides)
    return base


def run_channel_resolver_golden_replay() -> dict:
    """Run the PR3-A deterministic golden matrix without persistence."""
    official = _golden_context()["channels"][0].copy()
    official = {**official, "channel_key": "OFFICIAL_SITE", "channel_label": "官网"}
    decision_role = {
        "observation_count": 3,
        "semantic_relation_count": 1,
        "unique_url_count": 1,
        "observed_run_ids": [1, 2, 3],
        "role_source_ids": {"evidence_alignment_ids": [10]},
        "entity_counts": {"target_brand": {"observation_count": 0}, "competitor": {"observation_count": 3}},
    }
    strong_third_party = _golden_context()["channels"][0].copy()
    strong_third_party["role_counts"] = {**strong_third_party["role_counts"], "DECISION_CITATION": decision_role}
    reason_breakdown = [{
        "reason_text": "支持自定义分享标题",
        "channels": [{"channel_key": "ZHIHU", "role_counts": {"DECISION_CITATION": decision_role}}],
    }]
    cases = [
        ("A_BENCHMARK_OFFICIAL_PRIMARY", _golden_context(
            channels=[official, strong_third_party],
            benchmark_evidence_ids=[10],
            reason_breakdown=reason_breakdown,
            relevant_official_assets=[{"url": "https://target.example.com/features"}],
            intervention_need={"route": "CONTENT", "gap_type": "CONTENT_GAP", "first_party_authority_required": True},
            channel_target_gaps={"OFFICIAL_SITE": {"state": "PASS"}, "ZHIHU": {"state": "PASS"}},
            reason_relevance={"OFFICIAL_SITE": [], "ZHIHU": []},
        ), "PRIMARY", "OFFICIAL_SITE"),
        ("B_BENCHMARK_THIRD_PARTY_PRIMARY", _golden_context(
            channels=[strong_third_party], benchmark_evidence_ids=[10], reason_breakdown=reason_breakdown,
        ), "PRIMARY", "ZHIHU"),
        ("C_ANSWER_GAP_EVIDENCE_RESOLVED", _golden_context(
            channels=[strong_third_party], reason_breakdown=reason_breakdown,
        ), "PRIMARY", "ZHIHU"),
        ("D_ANSWER_GAP_TEST", _golden_context(), "TEST", "ZHIHU"),
        ("E_ANSWER_GAP_OBSERVE", _golden_context(
            reason_relevance={"ZHIHU": [{"reason_id": "reason:1", "reason_text": "支持自定义分享标题", "state": "WEAK", "supporting_signal_ids": []}]},
        ), "OBSERVE", "ZHIHU"),
        ("F_UNRESOLVED", _golden_context(channels=[], reason_relevance={}, channel_target_gaps={}), None, None),
        ("G_INPUT_INVALID", _golden_context(data_health="INVALID"), None, None),
        ("H_PRODUCT_TRUTH_UNKNOWN", _golden_context(
            product_truths=[{"id": 1, "status": "UNKNOWN", "truth_source": "MANUAL_CONFIRMED"}],
            product_truth_confirmed=False,
            strategy_opportunity_state="NONE",
        ), None, None),
    ]
    results = []
    for name, context, expected_role, expected_channel in cases:
        result = resolve_channel_shadow(context)
        actual = next((item for item in result["channels"] if item["role"] == expected_role), None) if expected_role else None
        passed = (
            actual is not None and actual["channel_key"] == expected_channel
            if expected_role else
            not any(item["role"] in EXECUTABLE_ROLES for item in result["channels"])
        )
        if name == "G_INPUT_INVALID":
            passed = result["channel_resolution_state"] == "INPUT_INVALID" and not result["channels"]
        if name == "H_PRODUCT_TRUTH_UNKNOWN":
            passed = result["strategy_opportunity_state"] == "NONE" and not result["channels"]
        results.append({
            "case": name,
            "passed": passed,
            "expected_role": expected_role,
            "expected_channel": expected_channel,
            "channel_resolution_state": result["channel_resolution_state"],
            "channels": [{"channel_key": item["channel_key"], "role": item["role"]} for item in result["channels"]],
        })
    return {
        "total_cases": len(results),
        "passed": sum(1 for item in results if item["passed"]),
        "failed": sum(1 for item in results if not item["passed"]),
        "cases": results,
        "external_llm_calls": 0,
    }
