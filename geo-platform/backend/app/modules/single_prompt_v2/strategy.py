from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    SinglePromptAnalysisContext,
    SinglePromptDiagnosisExecution,
    SinglePromptDiagnosisResult,
    SinglePromptDiagnosisReview,
    SinglePromptPreparedSourceSnapshot,
    SinglePromptSourceSnapshot,
    SinglePromptStrategyExecution,
    SinglePromptStrategyResult,
    SinglePromptStrategyReview,
)
from app.modules.optimization.service import _infer_platform_from_domain, source_platform_label
from app.modules.optimization.strategy_synthesis_shadow import (
    _deterministic_theme_title,
    _greedy_theme_groups,
    _mechanism_tags,
    _qualifiers,
    _reason_pair_constraint,
    _scenario_tags,
)
from app.modules.single_prompt_v2.diagnosis import (
    answer_semantic_eligibility,
    current_evidence_eligibility,
    current_truth_relation_eligibility,
)
from app.modules.single_prompt_v2.llm_safety import assess_normalized_projection
from app.services.serialization import loads


STRATEGY_CONTRACT_VERSION = "single_prompt_strategy.v2_third_slice"
STRATEGY_INPUT_VALIDATION_VERSION = "single_prompt_strategy_input.v4_capability_publication_split"
CHANNEL_EVIDENCE_ADAPTER_VERSION = "single_prompt_channel_evidence.v1"
FOUNDATION_RESOLUTION_VERSION = "single_prompt_foundation.v1"
CHANNEL_RESOLUTION_VERSION = "single_prompt_channel_resolution.v1"
THEME_SYNTHESIS_VERSION = "single_prompt_theme_synthesis.v1"

_POSITIVE_SPEECH_ACTS = {"RECOMMEND", "INCLUDE_AS_OPTION", "PRAISE"}
_POSITIVE_TRUTH_STATUSES = {"SUPPORTED", "TRUE"}
_PLATFORM_LABELS = {
    "BAIJIAHAO": "百家号",
    "BILIBILI": "B站",
    "CSDN": "CSDN",
    "DOUYIN": "抖音",
    "JIANSHU": "简书",
    "JUEJIN": "掘金",
    "SINA": "新浪",
    "SOHU": "搜狐",
    "TENCENT": "腾讯",
    "WECHAT": "微信",
    "XIAOHONGSHU": "小红书",
    "ZHIHU": "知乎",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _iso(value: datetime | None) -> str | None:
    return f"{value.isoformat()}Z" if value else None


def _review_snapshot(review: SinglePromptDiagnosisReview) -> dict[str, Any]:
    return {
        "review_id": review.review_id,
        "diagnosis_id": review.diagnosis_id,
        "result_version": review.result_version,
        "result_hash": review.result_hash,
        "reviewable_set_hash": review.reviewable_set_hash,
        "prior_review_id": review.prior_review_id,
        "decision": review.decision,
        "decisions": loads(review.decisions_json, []),
    }


def strategy_review_snapshot(review: SinglePromptStrategyReview) -> dict[str, Any]:
    return {
        "review_id": review.review_id,
        "strategy_id": review.strategy_id,
        "result_version": review.result_version,
        "result_hash": review.result_hash,
        "reviewable_set_hash": review.reviewable_set_hash,
        "decision": review.decision,
        "reviewer": review.reviewer,
        "note": review.note,
    }


def _source_channel(snapshot: dict[str, Any]) -> dict[str, Any]:
    observations = snapshot.get("reference_observations") or []
    domain = next((str(row.get("domain") or "").lower() for row in observations if row.get("domain")), "")
    if not domain:
        domain = (urlparse(str(snapshot.get("canonical_url") or "")).hostname or "").lower()
    source_role = str(snapshot.get("source_role") or "")
    if source_role == "TARGET_FIRST_PARTY":
        return {"channel_key": "OFFICIAL_SITE", "channel_label": "官网", "recognized_execution_channel": False}
    inferred = _infer_platform_from_domain(domain)
    platform = str(inferred.get("inferred_platform") or "UNKNOWN").upper()
    if platform != "UNKNOWN":
        return {
            "channel_key": platform,
            "channel_label": _PLATFORM_LABELS.get(platform, source_platform_label(platform.lower())),
            "recognized_execution_channel": True,
        }
    safe_domain = re.sub(r"[^A-Z0-9]+", "_", domain.upper()).strip("_")
    return {
        "channel_key": f"WEB_{safe_domain}" if safe_domain else "UNKNOWN",
        "channel_label": domain or "未知来源",
        "recognized_execution_channel": False,
    }


def _reason_rows(
    output: dict[str, Any],
    context: SinglePromptAnalysisContext,
    review: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    raw = loads(context.raw_output_json, {})
    run_answers = {
        int(row.get("run_id")): str(row.get("answer_text") or "")
        for row in raw.get("runs") or []
        if row.get("run_id") is not None
    }
    review_decisions = {
        str(row.get("event_id")): str(row.get("decision"))
        for row in (review or {}).get("decisions") or []
        if row.get("scope") == "ANSWER_SEMANTIC_EVENT" and row.get("event_id")
    }
    result: list[dict[str, Any]] = []
    for event in (output.get("answer_diagnosis") or {}).get("events") or []:
        event_act = str(event.get("effective_speech_act") or event.get("machine_speech_act") or "")
        event_id = str(event.get("event_id") or "")
        event_status = str(event.get("semantic_validation_status") or "VERIFIED_CONSERVATIVE")
        event_eligible = event.get("fact_consumption_eligible") is not False
        if event_status == "SEMANTIC_REVIEW_REQUIRED":
            event_eligible = (
                review_decisions.get(event_id) == "CONFIRM_INCLUDE_AS_OPTION"
                or (
                    event.get("fact_consumption_eligible") is True
                    and event.get("review_status") == "HUMAN_CONFIRMED_INCLUDE_AS_OPTION"
                    and bool(event.get("review_id"))
                )
            )
        run_id = int(event.get("run_id") or 0)
        for reason in event.get("reasons") or []:
            grounded = str(reason.get("effective_grounded_text") or reason.get("reason_span") or "").strip()
            normalized = str(reason.get("normalized_reason") or grounded).strip()
            projection = assess_normalized_projection(normalized, grounded)
            explicit_eligibility = reason.get("fact_consumption_eligible")
            eligible = explicit_eligibility is True or (
                explicit_eligibility is None
                and projection["fact_consumption_eligible"]
                and bool(grounded)
                and grounded in run_answers.get(run_id, "")
            )
            result.append({
                "reason_id": str(reason.get("reason_id") or ""),
                "event_id": event_id,
                "run_id": run_id,
                "entity_text": str(event.get("entity_text") or ""),
                "effective_speech_act": event_act,
                "grounded_text": grounded,
                "normalized_display_text": normalized,
                "fact_consumption_eligible": event_eligible and eligible and event_act in _POSITIVE_SPEECH_ACTS,
                "event_review_decision": review_decisions.get(event_id),
                "local_revalidation": projection,
            })
    return [row for row in result if row["reason_id"]]


def build_strategy_input_projection(
    db: Session,
    *,
    analysis_id: str,
    diagnosis_id: str,
    result_version: str,
    project_id: int,
    prompt_id: int,
) -> dict[str, Any]:
    execution = db.query(SinglePromptDiagnosisExecution).filter(
        SinglePromptDiagnosisExecution.diagnosis_id == diagnosis_id,
        SinglePromptDiagnosisExecution.analysis_id == analysis_id,
    ).one_or_none()
    if not execution:
        raise HTTPException(status_code=404, detail="诊断执行不存在")
    if execution.project_id != project_id or execution.prompt_id != prompt_id:
        raise HTTPException(status_code=409, detail="诊断身份与当前 Project/Prompt 不匹配")
    result = db.query(SinglePromptDiagnosisResult).filter(
        SinglePromptDiagnosisResult.diagnosis_id == diagnosis_id,
        SinglePromptDiagnosisResult.result_version == result_version,
    ).one_or_none()
    if not result:
        raise HTTPException(status_code=404, detail="诊断结果版本不存在")
    context = db.query(SinglePromptAnalysisContext).filter(
        SinglePromptAnalysisContext.context_id == execution.context_id,
        SinglePromptAnalysisContext.analysis_id == analysis_id,
    ).one_or_none()
    if not context or context.raw_output_hash != execution.raw_output_hash:
        raise HTTPException(status_code=409, detail="冻结的 AnalysisContext 与诊断输入不一致")
    review = db.query(SinglePromptDiagnosisReview).filter(
        SinglePromptDiagnosisReview.result_version == result_version,
        SinglePromptDiagnosisReview.diagnosis_id == diagnosis_id,
    ).one_or_none()
    output = loads(result.output_json, {})
    result_scope = str(output.get("result_scope") or "")
    prepared_snapshot_ids = list((output.get("input") or {}).get("source_snapshot_ids") or [])
    if prepared_snapshot_ids:
        snapshots = (
            db.query(SinglePromptPreparedSourceSnapshot)
            .filter(SinglePromptPreparedSourceSnapshot.snapshot_id.in_(prepared_snapshot_ids))
            .order_by(SinglePromptPreparedSourceSnapshot.source_key)
            .all()
        )
        if {row.snapshot_id for row in snapshots} != set(prepared_snapshot_ids):
            raise HTTPException(
                status_code=409,
                detail={"code": "STRATEGY_SOURCE_SNAPSHOT_BINDING_MISMATCH"},
            )
    elif result_scope == "ANSWER_ONLY":
        snapshots = []
    elif result_scope == "ANSWER_AND_EVIDENCE":
        raise HTTPException(
            status_code=409,
            detail={"code": "EVIDENCE_SOURCE_SNAPSHOT_BINDING_MISSING"},
        )
    else:
        snapshots = (
            db.query(SinglePromptSourceSnapshot)
            .filter(SinglePromptSourceSnapshot.diagnosis_id == diagnosis_id)
            .order_by(SinglePromptSourceSnapshot.source_key)
            .all()
        )
    answer_eligibility = answer_semantic_eligibility(output)
    limitations = loads(result.limitations_json, [])
    advisories, evidence_eligibility = current_evidence_eligibility(
        snapshots,
        historical_content_ready=int(loads(result.stats_json, {}).get("content_ready") or 0),
        historical_output=output,
    )
    source_rows = []
    output_snapshots = {
        str(row.get("snapshot_id")): row
        for row in (output.get("source_diagnosis") or {}).get("snapshots") or []
    }
    for row in snapshots:
        frozen = output_snapshots.get(row.snapshot_id, {})
        source = {
            "snapshot_id": row.snapshot_id,
            "source_key": row.source_key,
            "canonical_url": row.canonical_url,
            "title": row.title,
            "content_hash": row.content_hash,
            "passages_hash": row.passages_hash,
            "fetch_status": row.fetch_status,
            "reference_observations": loads(row.reference_observations_json, []),
            "source_role": frozen.get("source_role"),
        }
        source["channel"] = _source_channel(source)
        source_rows.append(source)
    review_payload = _review_snapshot(review) if review else None
    reasons = _reason_rows(output, context, review_payload)
    truth_relation_eligibility = current_truth_relation_eligibility(output)
    run_scope = loads(context.run_scope_json, {})
    analyzable_run_ids = sorted({
        int(value) for value in (run_scope.get("run_ids") if isinstance(run_scope, dict) else run_scope or [])
        if value is not None
    })
    input_snapshot = {
        "contract_version": STRATEGY_INPUT_VALIDATION_VERSION,
        "identity": {
            "analysis_id": analysis_id,
            "context_id": execution.context_id,
            "diagnosis_id": diagnosis_id,
            "project_id": project_id,
            "prompt_id": prompt_id,
            "diagnosis_result_version": result.result_version,
            "diagnosis_result_hash": result.output_hash,
            "reviewable_set_hash": result.reviewable_set_hash,
            "raw_output_hash": execution.raw_output_hash,
            "diagnosis_contract_config_hash": execution.contract_config_hash,
        },
        "diagnosis_review": review_payload,
        "answer_semantic_eligibility": answer_eligibility,
        "review_snapshot_hash": _hash(review_payload) if review_payload else None,
        "analyzable_run_ids": analyzable_run_ids,
        "reasons": reasons,
        "truth_snapshot": (output.get("truth_diagnosis") or {}).get("truth_snapshot") or [],
        "truth_relationships": truth_relation_eligibility["effective_relationships"],
        "reason_capability_coverage": copy.deepcopy(
            (output.get("truth_diagnosis") or {}).get("reason_capability_coverage") or []
        ),
        "external_capability_signals": copy.deepcopy(
            (output.get("truth_diagnosis") or {}).get("external_capability_signals") or []
        ),
        "truth_relation_eligibility": truth_relation_eligibility,
        "evidence_relations": (output.get("evidence_diagnosis") or {}).get("source_relations") or [],
        "source_claim_jobs": (output.get("evidence_diagnosis") or {}).get("source_claim_jobs") or [],
        "source_snapshots": source_rows,
        "foundation_assessment": output.get("foundation_assessment") or {},
        "effective_evidence_eligibility": copy.deepcopy(evidence_eligibility),
        "limitations": copy.deepcopy(limitations),
        "advisories": copy.deepcopy(advisories),
        "validation_versions": {
            "strategy_input": STRATEGY_INPUT_VALIDATION_VERSION,
            "source_content": evidence_eligibility.get("contract_version"),
            "truth_relation": truth_relation_eligibility.get("contract_version"),
            "diagnosis": output.get("contract_version"),
            "diagnosis_config_hash": execution.contract_config_hash,
        },
    }
    input_snapshot["consumed_object_ids"] = {
        "event_ids": sorted({row["event_id"] for row in reasons if row["event_id"]}),
        "reason_ids": sorted({row["reason_id"] for row in reasons}),
        "truth_ids": sorted(str(row.get("truth_id")) for row in input_snapshot["truth_snapshot"] if row.get("truth_id") is not None),
        "truth_relationship_ids": sorted(str(row.get("relationship_id")) for row in input_snapshot["truth_relationships"] if row.get("relationship_id")),
        "external_capability_signal_ids": sorted(
            str(row.get("signal_id"))
            for row in input_snapshot["external_capability_signals"]
            if row.get("signal_id")
        ),
        "evidence_relation_ids": sorted(str(row.get("relation_id")) for row in input_snapshot["evidence_relations"] if row.get("relation_id")),
        "source_snapshot_ids": sorted(row["snapshot_id"] for row in source_rows),
    }
    input_snapshot["input_snapshot_hash"] = _hash(input_snapshot)
    input_snapshot["is_active_result"] = execution.active_result_version == result_version
    return input_snapshot


def _confirmed_capabilities(projection: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        int(row["truth_id"]): row
        for row in projection.get("truth_snapshot") or []
        if row.get("truth_id") is not None
        and row.get("product_truth_status") in _POSITIVE_TRUTH_STATUSES
        and row.get("truth_source") == "MANUAL_CONFIRMED"
    }


def _publishable_truths(projection: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        truth_id: row
        for truth_id, row in _confirmed_capabilities(projection).items()
        if (row.get("statement_eligibility") or {}).get("status") == "ELIGIBLE"
    }


def _truths_by_reason(projection: dict[str, Any]) -> dict[str, list[int]]:
    confirmed = _confirmed_capabilities(projection)
    result: dict[str, list[int]] = defaultdict(list)
    for row in projection.get("truth_relationships") or []:
        truth_id = row.get("truth_id")
        if (
            truth_id is not None
            and int(truth_id) in confirmed
            and row.get("effective_relation") == "FULLY_COVERS"
        ):
            result[str(row.get("reason_id"))].append(int(truth_id))
    for signal in projection.get("external_capability_signals") or []:
        if signal.get("fact_consumption_eligible") is not True:
            continue
        if signal.get("signal_context") == "CO_RECOMMENDED_WITH_TARGET":
            continue
        for match in signal.get("target_truth_matches") or []:
            truth_id = match.get("truth_id")
            if (
                truth_id is not None
                and int(truth_id) in confirmed
                and match.get("applicability") == "ELIGIBLE"
            ):
                result[str(signal.get("reason_id"))].append(int(truth_id))
    for coverage in projection.get("reason_capability_coverage") or []:
        if (
            coverage.get("fact_consumption_eligible") is True
            and coverage.get("effective_relation") == "FULLY_COVERS"
        ):
            result[str(coverage.get("reason_id"))].extend(
                int(value)
                for value in coverage.get("truth_ids") or []
                if int(value) in confirmed
            )
    return {key: sorted(set(values)) for key, values in result.items()}


def _direction_id(kind: str, key: str, reason_ids: list[str]) -> str:
    return f"dir-{_hash({'kind': kind, 'key': key, 'reason_ids': sorted(reason_ids)})[:20]}"


def _resolve_foundation(projection: dict[str, Any], reason_truths: dict[str, list[int]]) -> tuple[dict, list[dict]]:
    confirmed = _confirmed_capabilities(projection)
    assessment = projection.get("foundation_assessment") or {}
    assessment_truth_ids = {int(value) for value in assessment.get("truth_ids") or [] if value is not None}
    supported_truth_ids = {value for values in reason_truths.values() for value in values}
    evidence_ids = [str(value) for value in assessment.get("evidence_ids") or [] if value]
    valid_assessment = bool(
        assessment.get("assessment_id")
        and evidence_ids
        and assessment_truth_ids
        and assessment_truth_ids.issubset(confirmed)
        and assessment_truth_ids.issubset(supported_truth_ids)
    )
    directions: list[dict] = []
    if assessment.get("state") == "CONFIRMED_MISSING" and valid_assessment:
        state = "REQUIRED"
        reason_ids = sorted(key for key, values in reason_truths.items() if set(values) & assessment_truth_ids)
        directions.append({
            "direction_id": _direction_id("FOUNDATION", str(assessment["assessment_id"]), reason_ids),
            "direction_type": "FOUNDATION",
            "channel_key": None,
            "channel_label": None,
            "channel_role": None,
            "level": "ACTIONABLE",
            "reason_ids": reason_ids,
            "truth_ids": sorted(assessment_truth_ids),
            "evidence_relation_ids": [],
            "basis_ids": [str(assessment["assessment_id"]), *evidence_ids],
            "rationale": "已确认的目标品牌事实存在明确权威事实资产缺口；本方向只表达基础承载需求，不选择官网渠道或具体资产。",
            "hypothesis": None,
            "effect_status": "NOT_PROVEN",
        })
    elif assessment.get("state") == "CONFIRMED_PRESENT" and valid_assessment:
        state = "NOT_REQUIRED"
    else:
        state = "UNKNOWN"
    return {
        "state": state,
        "assessment_id": assessment.get("assessment_id"),
        "basis_ids": ([str(assessment.get("assessment_id")), *evidence_ids] if valid_assessment else []),
        "reason": (
            "已确认存在权威事实资产缺口。" if state == "REQUIRED"
            else "已确认当前事实承载基础不构成缺口。" if state == "NOT_REQUIRED"
            else "当前冻结诊断没有同时证明目标品牌事实和权威事实资产缺口。"
        ),
    }, directions


def _resolve_channels(projection: dict[str, Any], reason_truths: dict[str, list[int]]) -> tuple[list[dict], list[dict]]:
    reasons = {row["reason_id"]: row for row in projection.get("reasons") or []}
    eligible_source_ids = set((projection.get("effective_evidence_eligibility") or {}).get("eligible_snapshot_ids") or [])
    eligible_relation_ids = set((projection.get("effective_evidence_eligibility") or {}).get("effective_evidence_relation_ids") or [])
    sources = {row["snapshot_id"]: row for row in projection.get("source_snapshots") or []}
    grouped: dict[str, dict] = {}
    for source in sources.values():
        channel = source["channel"]
        entry = grouped.setdefault(channel["channel_key"], {
            **channel,
            "source_snapshot_ids": [],
            "observed_reason_ids": set(),
            "decision_reason_ids": set(),
            "test_reason_ids": set(),
            "evidence_relation_ids": set(),
            "blocking_signals": set(),
        })
        entry["source_snapshot_ids"].append(source["snapshot_id"])
    for relation in projection.get("evidence_relations") or []:
        source_id = str(relation.get("source_snapshot_id") or "")
        reason_id = str(relation.get("reason_id") or "")
        source = sources.get(source_id)
        if not source:
            continue
        entry = grouped[source["channel"]["channel_key"]]
        entry["observed_reason_ids"].add(reason_id)
        if source_id not in eligible_source_ids or str(relation.get("relation_id")) not in eligible_relation_ids:
            entry["blocking_signals"].add("CURRENT_EVIDENCE_NOT_ELIGIBLE")
            continue
        if not reasons.get(reason_id, {}).get("fact_consumption_eligible"):
            entry["blocking_signals"].add("REASON_NOT_FACT_CONSUMABLE")
            continue
        if not reason_truths.get(reason_id):
            entry["blocking_signals"].add("TARGET_BRAND_TRUTH_UNRESOLVED")
            continue
        if relation.get("alignment_evaluation") != "EVALUATED":
            entry["blocking_signals"].add("EVIDENCE_RELATION_NOT_EVALUATED")
            continue
        if relation.get("effective_relation") != "SOURCE_SUPPORTS_REASON":
            entry["blocking_signals"].add("NO_ELIGIBLE_SOURCE_SUPPORT")
            continue
        entry["evidence_relation_ids"].add(str(relation.get("relation_id")))
        if relation.get("anchor_binding") == "EXPLICIT":
            entry["decision_reason_ids"].add(reason_id)
        elif entry["recognized_execution_channel"]:
            entry["test_reason_ids"].add(reason_id)
            entry["blocking_signals"].add("REFERENCE_ANCHOR_UNPROVEN_FOR_DECISION_CITATION")
        else:
            entry["blocking_signals"].add("CHANNEL_EXECUTION_FIT_UNPROVEN")

    assessments: list[dict] = []
    directions: list[dict] = []
    for key in sorted(grouped):
        entry = grouped[key]
        decision_reason_ids = sorted(entry.pop("decision_reason_ids"))
        test_reason_ids = sorted(entry.pop("test_reason_ids"))
        observed_reason_ids = sorted(entry.pop("observed_reason_ids"))
        relation_ids = sorted(entry.pop("evidence_relation_ids"))
        blockers = sorted(entry.pop("blocking_signals"))
        if decision_reason_ids and entry["recognized_execution_channel"]:
            role, level, selected_reasons = "PRIMARY", "ACTIONABLE", decision_reason_ids
            rationale = "该渠道存在当前 Reason 的可消费来源支持和明确回答锚点，且目标品牌事实完整承接对应 Reason。"
        elif test_reason_ids:
            role, level, selected_reasons = "TEST", "ACTIONABLE", test_reason_ids
            rationale = "该渠道存在可消费的 Reason 支持环境，但回答锚点未证明；仅形成可验证渠道假设，不宣称渠道有效。"
        elif observed_reason_ids:
            role, selected_reasons = "OBSERVE", []
            if {"CURRENT_EVIDENCE_NOT_ELIGIBLE", "EVIDENCE_RELATION_NOT_EVALUATED"} & set(blockers):
                level = "BLOCKED"
                rationale = "关键正文或证据关系当前不可消费/未评估，不能把来源出现转成渠道方向。"
            elif {"TARGET_BRAND_TRUTH_UNRESOLVED", "REASON_NOT_FACT_CONSUMABLE"} & set(blockers):
                level = "VERIFY_FIRST"
                rationale = "渠道环境与 Reason 有关联，但目标适用事实或 Reason 语义仍需先核实。"
            else:
                level = "OBSERVE"
                rationale = "当前只有来源出现或不完整证据信号，尚不满足干预资格。"
        else:
            role, level, selected_reasons = "OBSERVE", "OBSERVE", []
            rationale = "当前只有渠道环境观测，无法绑定到可消费 Reason。"
        assessment = {
            **entry,
            "channel_role": role,
            "level": level,
            "reason_ids": selected_reasons,
            "observed_reason_ids": observed_reason_ids,
            "evidence_relation_ids": relation_ids,
            "blocking_signals": blockers,
            "gate_checks": {
                "reason_relevance": bool(relation_ids),
                "target_applicability": bool(selected_reasons and all(reason_truths.get(value) for value in selected_reasons)),
                "execution_fit": bool(entry["recognized_execution_channel"]),
                "verifiability": bool(entry["recognized_execution_channel"] and selected_reasons and relation_ids),
            },
            "rationale": rationale,
        }
        assessments.append(assessment)
        if level == "ACTIONABLE":
            truth_ids = sorted({value for reason_id in selected_reasons for value in reason_truths.get(reason_id, [])})
            directions.append({
                "direction_id": _direction_id("CHANNEL", key, selected_reasons),
                "direction_type": "CHANNEL",
                "channel_key": key,
                "channel_label": entry["channel_label"],
                "channel_role": role,
                "level": "ACTIONABLE",
                "reason_ids": selected_reasons,
                "truth_ids": truth_ids,
                "evidence_relation_ids": relation_ids,
                "basis_ids": relation_ids,
                "gate_checks": copy.deepcopy(assessment["gate_checks"]),
                "rationale": rationale,
                "hypothesis": f"在{entry['channel_label']}验证目标品牌已确认事实是否能够进入后续回答的引用或推荐观察。",
                "effect_status": "NOT_PROVEN",
            })
    return assessments, directions


def _build_themes(projection: dict[str, Any], reason_ids: list[str], reason_truths: dict[str, list[int]]) -> list[dict]:
    reason_map = {row["reason_id"]: row for row in projection.get("reasons") or []}
    truth_map = _confirmed_capabilities(projection)
    objects = []
    for reason_id in sorted(set(reason_ids)):
        row = reason_map.get(reason_id)
        if not row:
            continue
        truth_ids = reason_truths.get(reason_id, [])
        family = " / ".join(
            str(truth_map[value].get("capability_label") or truth_map[value].get("capability_key") or "")
            for value in truth_ids if value in truth_map
        ) or row["grounded_text"]
        objects.append({
            "reason_id": reason_id,
            "original_reason": row["grounded_text"],
            "capability_family": family,
            "scenario": _scenario_tags(row["grounded_text"]),
            "qualifier": _qualifiers(row["grounded_text"]),
            "intervention_mechanisms": _mechanism_tags(row["grounded_text"], "EVIDENCE_GAP"),
            "required_asset_type": "STRATEGY_DIRECTION",
            "observed_run_ids": [row["run_id"]] if row["run_id"] else [],
            "product_truth_ids": truth_ids,
        })
    allowed_pairs = []
    for index, left in enumerate(objects):
        for right in objects[index + 1:]:
            if _reason_pair_constraint(left, right)["allowed"]:
                allowed_pairs.append([left["reason_id"], right["reason_id"]])
    groups = _greedy_theme_groups([row["reason_id"] for row in objects], allowed_pairs)
    by_id = {row["reason_id"]: row for row in objects}
    all_runs = projection.get("analyzable_run_ids") or sorted({
        row["run_id"] for row in projection.get("reasons") or [] if row["run_id"]
    })
    themes = []
    for group in groups:
        members = [by_id[value] for value in group]
        run_ids = sorted({run_id for row in members for run_id in row["observed_run_ids"]})
        title = _deterministic_theme_title(members)
        themes.append({
            "theme_id": f"theme-{_hash(sorted(group))[:20]}",
            "title": title,
            "reason_ids": sorted(group),
            "observed_run_ids": run_ids,
            "coverage": {"numerator": len(run_ids), "denominator": len(all_runs), "rule": "MEMBER_REASON_RUN_ID_UNION"},
            "provenance_ids": sorted(group),
        })
    return themes


def evaluate_strategy_readiness(projection: dict[str, Any]) -> dict[str, Any]:
    reason_truths = _truths_by_reason(projection)
    foundation, foundation_directions = _resolve_foundation(projection, reason_truths)
    channel_assessments, channel_directions = _resolve_channels(projection, reason_truths)
    directions = foundation_directions + channel_directions
    needs_human = len(directions) > 1
    for index, direction in enumerate(directions):
        direction["priority_order"] = None if needs_human else index + 1
        direction["priority_basis"] = "HUMAN_REQUIRED_SAME_LEVEL" if needs_human else "ONLY_ELIGIBLE_DIRECTION"
    reason_ids = sorted({reason_id for row in directions for reason_id in row["reason_ids"]})
    actionable_themes = _build_themes(projection, reason_ids, reason_truths)
    observable_reason_ids = [
        row["reason_id"] for row in projection.get("reasons") or []
        if row.get("fact_consumption_eligible")
    ]
    observed_themes = _build_themes(projection, observable_reason_ids, reason_truths)
    verification_items: list[dict] = []
    if not projection.get("diagnosis_review"):
        verification_items.append({"code": "DIAGNOSIS_REVIEW_REQUIRED", "detail": "完成当前诊断结果版本的审核。"})
    if (projection.get("answer_semantic_eligibility") or {}).get("no_consumable_answer_semantic_result"):
        verification_items.append({
            "code": "NO_CONSUMABLE_ANSWER_SEMANTIC_RESULT",
            "detail": "回答语义没有通过当前准入契约的结果；不能通过审核将失败升级为策略输入。",
        })
    confirmed_capabilities = _confirmed_capabilities(projection)
    publishable_truths = _publishable_truths(projection)
    if not confirmed_capabilities:
        verification_items.append({"code": "TARGET_BRAND_TRUTH_UNRESOLVED", "detail": "补充并确认目标品牌自己的能力事实；空事实不表示能力为假。"})
    elif len(publishable_truths) < len(confirmed_capabilities):
        verification_items.append({
            "code": "PUBLIC_CLAIM_EVIDENCE_PENDING",
            "detail": "能力已可用于策略适用性判断；进入公开内容前仍需补充目标品牌依据并确认可写范围。",
        })
    missing_capability_labels = sorted({
        str(item.get("capability_label") or "")
        for coverage in projection.get("reason_capability_coverage") or []
        if coverage.get("fact_consumption_eligible") is True
        and coverage.get("effective_relation") != "FULLY_COVERS"
        for item in coverage.get("missing_capabilities") or []
        if item.get("capability_label")
    })
    if confirmed_capabilities and missing_capability_labels:
        verification_items.append({
            "code": "TARGET_CAPABILITY_CONFIRMATION_INCOMPLETE",
            "detail": f"仍有答案理由未被完整承接；待确认能力：{'、'.join(missing_capability_labels)}。",
        })
    if any(not row.get("fact_consumption_eligible") for row in projection.get("reasons") or []):
        verification_items.append({"code": "REASON_SEMANTIC_REVIEW_REQUIRED", "detail": "存在不能按当前安全契约消费的 Reason。"})
    if any(row.get("alignment_evaluation") != "EVALUATED" for row in projection.get("evidence_relations") or []):
        verification_items.append({"code": "EVIDENCE_RELATION_NOT_EVALUATED", "detail": "部分引用关系尚未完成 SourceClaim/Alignment 判断。"})
    if any(row.get("anchor_binding") == "UNPROVEN" for row in projection.get("evidence_relations") or []):
        verification_items.append({"code": "REFERENCE_ANCHOR_UNPROVEN", "detail": "来源支持不能冒充本次回答采用该来源作为推荐依据。"})
    if foundation["state"] == "UNKNOWN":
        verification_items.append({"code": "FOUNDATION_REQUIREMENT_UNKNOWN", "detail": "当前输入未明确证明权威事实资产是否存在缺口。"})
    if (projection.get("effective_evidence_eligibility") or {}).get("content_blocked_current"):
        verification_items.append({"code": "CONTENT_BLOCKED", "detail": "验证/拦截页已从策略证据消费范围排除。"})
    review_valid = bool(
        projection.get("diagnosis_review")
        and projection["diagnosis_review"].get("decision") == "REVIEW_COMPLETED"
        and projection["diagnosis_review"].get("result_hash") == projection["identity"]["diagnosis_result_hash"]
        and projection["diagnosis_review"].get("reviewable_set_hash") == projection["identity"]["reviewable_set_hash"]
    )
    no_answer_semantic = bool(
        (projection.get("answer_semantic_eligibility") or {}).get("no_consumable_answer_semantic_result")
    )
    if no_answer_semantic:
        classification = "A"
        blocker = {
            "code": "NO_CONSUMABLE_ANSWER_SEMANTIC_RESULT",
            "detail": "当前 DiagnosisResultVersion 没有可消费的回答语义结果，不能审核升级或创建策略。",
        }
    elif not review_valid:
        classification = "A"
        blocker = {"code": "DIAGNOSIS_REVIEW_REQUIRED", "detail": "当前精确 DiagnosisResultVersion 尚无有效审核，不能创建正式策略候选。"}
    elif not directions:
        classification = "B"
        blocker = {"code": "NO_ELIGIBLE_STRATEGY_DIRECTION", "detail": "诊断已审核，但当前没有同时通过事实、关系和干预依据 Gate 的方向。"}
    else:
        classification = "C"
        blocker = None
    blocked_directions = []
    if foundation["state"] == "UNKNOWN":
        blocked_directions.append({"direction_type": "FOUNDATION", "level": "VERIFY_FIRST", "reason": foundation["reason"]})
    blocked_directions.extend({
        "direction_type": "CHANNEL",
        "channel_key": row["channel_key"],
        "channel_label": row["channel_label"],
        "level": row["level"],
        "reason": row["rationale"],
        "blocking_signals": row["blocking_signals"],
    } for row in channel_assessments if row["level"] != "ACTIONABLE")
    return {
        "contract_version": STRATEGY_CONTRACT_VERSION,
        "classification": classification,
        "can_create_strategy": classification == "C",
        "blocker": blocker,
        "legal_next_steps": (
            ["CREATE_NEW_DIAGNOSIS_AFTER_CONTRACT_FIX"] if no_answer_semantic
            else ["COMPLETE_DIAGNOSIS_REVIEW"] if classification == "A"
            else ["RESOLVE_LISTED_VERIFICATION_ITEMS"] if classification == "B"
            else ["CREATE_STRATEGY_CANDIDATE"]
        ),
        "input_identity": copy.deepcopy(projection["identity"]),
        "input_projection_hash": projection["input_snapshot_hash"],
        "review_id": (projection.get("diagnosis_review") or {}).get("review_id"),
        "review_snapshot_hash": projection.get("review_snapshot_hash"),
        "validation_contract_version": STRATEGY_INPUT_VALIDATION_VERSION,
        "current_observation": {
            "reason_count": len(projection.get("reasons") or []),
            "fact_consumable_reason_count": len(observable_reason_ids),
            "source_count": len(projection.get("source_snapshots") or []),
            "effective_evidence_relation_count": len((projection.get("effective_evidence_eligibility") or {}).get("effective_evidence_relation_ids") or []),
            "confirmed_capability_count": len(confirmed_capabilities),
            "public_claim_eligible_count": len(publishable_truths),
        },
        "foundation": foundation,
        "channel_assessments": channel_assessments,
        "observed_themes": observed_themes,
        "actionable_themes": actionable_themes,
        "qualified_directions": directions,
        "qualified_direction_count": len(directions),
        "blocked_directions": blocked_directions,
        "verification_items": verification_items,
        "needs_human_prioritization": needs_human,
        "limitations": copy.deepcopy(projection.get("limitations") or []),
        "advisories": copy.deepcopy(projection.get("advisories") or []),
        "effective_evidence_eligibility": copy.deepcopy(projection.get("effective_evidence_eligibility") or {}),
        "boundary": {
            "foundation_selects_channel": False,
            "primary_required": False,
            "test_is_proven_effect": False,
            "external_llm_calls": 0,
            "execution_proposal_created": False,
            "action_created": False,
            "experiment_created": False,
        },
    }


def build_strategy_readiness(db: Session, **scope: Any) -> dict[str, Any]:
    return evaluate_strategy_readiness(build_strategy_input_projection(db, **scope))


def _candidate_output(strategy_id: str, projection: dict, readiness: dict) -> dict:
    direction_ids = [row["direction_id"] for row in readiness["qualified_directions"]]
    return {
        "contract_version": STRATEGY_CONTRACT_VERSION,
        "strategy_id": strategy_id,
        "input_identity": readiness["input_identity"],
        "input_projection_hash": projection["input_snapshot_hash"],
        "review_id": readiness["review_id"],
        "review_snapshot_hash": readiness["review_snapshot_hash"],
        "validation_contract_version": STRATEGY_INPUT_VALIDATION_VERSION,
        "current_observation": readiness["current_observation"],
        "themes": readiness["actionable_themes"],
        "directions": copy.deepcopy(readiness["qualified_directions"]),
        "foundation": readiness["foundation"],
        "needs_human_prioritization": readiness["needs_human_prioritization"],
        "unresolved": {
            "blocked_directions": readiness["blocked_directions"],
            "verification_items": readiness["verification_items"],
        },
        "limitations": copy.deepcopy(readiness["limitations"]),
        "advisories": copy.deepcopy(readiness["advisories"]),
        "effective_evidence_eligibility": copy.deepcopy(readiness["effective_evidence_eligibility"]),
        "provenance": {
            "direction_ids": direction_ids,
            "consumed_object_ids": copy.deepcopy(projection["consumed_object_ids"]),
            "effective_evidence_relation_ids": copy.deepcopy(
                (projection.get("effective_evidence_eligibility") or {}).get("effective_evidence_relation_ids") or []
            ),
        },
        "boundary": copy.deepcopy(readiness["boundary"]),
    }


def _validate_candidate_output(output: dict[str, Any], projection: dict[str, Any]) -> None:
    """Keep persisted strategy structure inside the exact frozen V2 input set."""
    consumed = projection.get("consumed_object_ids") or {}
    allowed_reason_ids = set(consumed.get("reason_ids") or [])
    allowed_truth_ids = set(consumed.get("truth_ids") or [])
    allowed_relation_ids = set(
        (projection.get("effective_evidence_eligibility") or {}).get("effective_evidence_relation_ids") or []
    )
    for direction in output.get("directions") or []:
        direction_type = direction.get("direction_type")
        if direction_type not in {"FOUNDATION", "CHANNEL"}:
            raise HTTPException(status_code=422, detail="策略输出包含未知方向类型")
        if not set(direction.get("reason_ids") or []).issubset(allowed_reason_ids):
            raise HTTPException(status_code=422, detail="策略输出引用了冻结输入以外的 Reason")
        if not {str(value) for value in direction.get("truth_ids") or []}.issubset(allowed_truth_ids):
            raise HTTPException(status_code=422, detail="策略输出引用了冻结输入以外的 Product Truth")
        if not set(direction.get("evidence_relation_ids") or []).issubset(allowed_relation_ids):
            raise HTTPException(status_code=422, detail="策略输出引用了当前不可消费的证据关系")
        if direction_type == "FOUNDATION" and any(
            direction.get(field) is not None for field in ("channel_key", "channel_label", "channel_role")
        ):
            raise HTTPException(status_code=422, detail="Foundation 方向不得选择渠道或渠道 Role")
        if direction_type == "CHANNEL" and direction.get("channel_role") not in {"PRIMARY", "TEST"}:
            raise HTTPException(status_code=422, detail="正式渠道方向只能使用已通过 Gate 的 PRIMARY 或 TEST")
        if direction.get("level") != "ACTIONABLE":
            raise HTTPException(status_code=422, detail="正式策略候选只能保存 ACTIONABLE 方向")
    for theme in output.get("themes") or []:
        if not set(theme.get("reason_ids") or []).issubset(allowed_reason_ids):
            raise HTTPException(status_code=422, detail="策略主题引用了冻结输入以外的 Reason")


def create_strategy_candidate(
    db: Session,
    *,
    analysis_id: str,
    diagnosis_id: str,
    result_version: str,
    project_id: int,
    prompt_id: int,
    idempotency_key: str,
    diagnosis_result_hash: str,
    reviewable_set_hash: str,
    review_id: str,
    review_snapshot_hash: str,
    input_projection_hash: str,
) -> tuple[SinglePromptStrategyExecution, SinglePromptStrategyResult, bool]:
    projection = build_strategy_input_projection(
        db,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        result_version=result_version,
        project_id=project_id,
        prompt_id=prompt_id,
    )
    identity = projection["identity"]
    submitted = {
        "diagnosis_result_hash": diagnosis_result_hash,
        "reviewable_set_hash": reviewable_set_hash,
        "review_id": review_id,
        "review_snapshot_hash": review_snapshot_hash,
        "input_projection_hash": input_projection_hash,
    }
    current = {
        "diagnosis_result_hash": identity["diagnosis_result_hash"],
        "reviewable_set_hash": identity["reviewable_set_hash"],
        "review_id": (projection.get("diagnosis_review") or {}).get("review_id"),
        "review_snapshot_hash": projection.get("review_snapshot_hash"),
        "input_projection_hash": projection["input_snapshot_hash"],
    }
    readiness = evaluate_strategy_readiness(projection)
    if not readiness["can_create_strategy"]:
        raise HTTPException(status_code=409, detail={"code": readiness["blocker"]["code"], "readiness": readiness})
    if submitted != current or not projection.get("is_active_result"):
        raise HTTPException(status_code=409, detail="策略输入版本已变化，请重新加载精确诊断、审核和安全投影")
    input_fingerprint = _hash({
        "identity": identity,
        "review_snapshot_hash": review_snapshot_hash,
        "input_projection_hash": input_projection_hash,
        "strategy_contract_version": STRATEGY_CONTRACT_VERSION,
    })
    existing = db.query(SinglePromptStrategyExecution).filter(
        SinglePromptStrategyExecution.diagnosis_id == diagnosis_id,
        SinglePromptStrategyExecution.idempotency_key == idempotency_key,
    ).one_or_none()
    if existing:
        if existing.input_fingerprint != input_fingerprint:
            raise HTTPException(status_code=409, detail="幂等键已用于不同策略输入")
        result = db.query(SinglePromptStrategyResult).filter(
            SinglePromptStrategyResult.strategy_id == existing.strategy_id,
            SinglePromptStrategyResult.result_version == existing.active_result_version,
        ).one()
        return existing, result, False

    strategy_id = f"strategy-{uuid4()}"
    output = _candidate_output(strategy_id, projection, readiness)
    _validate_candidate_output(output, projection)
    output_hash = _hash(output)
    reviewable_set = {
        "theme_ids": sorted(row["theme_id"] for row in output["themes"]),
        "direction_ids": sorted(row["direction_id"] for row in output["directions"]),
        "input_projection_hash": projection["input_snapshot_hash"],
    }
    result = SinglePromptStrategyResult(
        result_version=f"strategy-v1:{output_hash[:16]}",
        strategy_id=strategy_id,
        version_number=1,
        parent_result_version=None,
        output_json=_canonical_json(output),
        output_hash=output_hash,
        reviewable_set_hash=_hash(reviewable_set),
        limitations_json=_canonical_json(output["limitations"]),
    )
    execution = SinglePromptStrategyExecution(
        strategy_id=strategy_id,
        analysis_id=analysis_id,
        context_id=identity["context_id"],
        diagnosis_id=diagnosis_id,
        project_id=project_id,
        prompt_id=prompt_id,
        idempotency_key=idempotency_key,
        input_fingerprint=input_fingerprint,
        diagnosis_result_version=result_version,
        diagnosis_result_hash=diagnosis_result_hash,
        diagnosis_review_id=review_id,
        review_snapshot_hash=review_snapshot_hash,
        validation_contract_version=STRATEGY_INPUT_VALIDATION_VERSION,
        input_snapshot_json=_canonical_json(projection),
        input_snapshot_hash=projection["input_snapshot_hash"],
        status="READY_FOR_REVIEW",
        active_result_version=result.result_version,
    )
    db.add_all([execution, result])
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = db.query(SinglePromptStrategyExecution).filter(
            SinglePromptStrategyExecution.diagnosis_id == diagnosis_id,
            SinglePromptStrategyExecution.idempotency_key == idempotency_key,
        ).one_or_none()
        if concurrent and concurrent.input_fingerprint == input_fingerprint:
            concurrent_result = db.query(SinglePromptStrategyResult).filter(
                SinglePromptStrategyResult.result_version == concurrent.active_result_version
            ).one()
            return concurrent, concurrent_result, False
        raise
    db.refresh(execution)
    db.refresh(result)
    return execution, result, True


def _strategy_applicability(db: Session, execution: SinglePromptStrategyExecution) -> dict[str, Any]:
    projection = build_strategy_input_projection(
        db,
        analysis_id=execution.analysis_id,
        diagnosis_id=execution.diagnosis_id,
        result_version=execution.diagnosis_result_version,
        project_id=execution.project_id,
        prompt_id=execution.prompt_id,
    )
    review = projection.get("diagnosis_review") or {}
    checks = {
        "diagnosis_result_is_active": bool(projection.get("is_active_result")),
        "diagnosis_result_hash_matches": projection["identity"]["diagnosis_result_hash"] == execution.diagnosis_result_hash,
        "diagnosis_review_matches": review.get("review_id") == execution.diagnosis_review_id,
        "review_snapshot_hash_matches": projection.get("review_snapshot_hash") == execution.review_snapshot_hash,
        "validation_contract_matches": execution.validation_contract_version == STRATEGY_INPUT_VALIDATION_VERSION,
        "input_snapshot_hash_matches": projection.get("input_snapshot_hash") == execution.input_snapshot_hash,
    }
    return {"is_current_input": all(checks.values()), "checks": checks}


def get_strategy_status(
    db: Session,
    *,
    strategy_id: str,
    analysis_id: str,
    diagnosis_id: str,
    project_id: int,
    prompt_id: int,
) -> dict[str, Any]:
    execution = db.query(SinglePromptStrategyExecution).filter(
        SinglePromptStrategyExecution.strategy_id == strategy_id,
        SinglePromptStrategyExecution.analysis_id == analysis_id,
        SinglePromptStrategyExecution.diagnosis_id == diagnosis_id,
    ).one_or_none()
    if not execution:
        raise HTTPException(status_code=404, detail="策略执行不存在")
    if execution.project_id != project_id or execution.prompt_id != prompt_id:
        raise HTTPException(status_code=409, detail="策略身份与当前 Project/Prompt 不匹配")
    result = db.query(SinglePromptStrategyResult).filter(
        SinglePromptStrategyResult.strategy_id == strategy_id,
        SinglePromptStrategyResult.result_version == execution.active_result_version,
    ).one_or_none()
    review = db.query(SinglePromptStrategyReview).filter(
        SinglePromptStrategyReview.result_version == execution.active_result_version
    ).one_or_none()
    applicability = _strategy_applicability(db, execution)
    return {
        "strategy": {
            "strategy_id": execution.strategy_id,
            "analysis_id": execution.analysis_id,
            "context_id": execution.context_id,
            "diagnosis_id": execution.diagnosis_id,
            "project_id": execution.project_id,
            "prompt_id": execution.prompt_id,
            "input_fingerprint": execution.input_fingerprint,
            "diagnosis_result_version": execution.diagnosis_result_version,
            "diagnosis_result_hash": execution.diagnosis_result_hash,
            "diagnosis_review_id": execution.diagnosis_review_id,
            "review_snapshot_hash": execution.review_snapshot_hash,
            "validation_contract_version": execution.validation_contract_version,
            "input_snapshot_hash": execution.input_snapshot_hash,
            "status": execution.status,
        },
        "result": {
            "result_version": result.result_version,
            "version_number": result.version_number,
            "parent_result_version": result.parent_result_version,
            "output_hash": result.output_hash,
            "reviewable_set_hash": result.reviewable_set_hash,
            "output": loads(result.output_json, {}),
            "limitations": loads(result.limitations_json, []),
            "created_at": _iso(result.created_at),
        } if result else None,
        "review": {
            "review_id": review.review_id,
            "review_snapshot_hash": _hash(strategy_review_snapshot(review)),
            "decision": review.decision,
            "reviewer": review.reviewer,
            "note": review.note,
            "result_version": review.result_version,
            "created_at": _iso(review.created_at),
        } if review else None,
        "applicability": applicability,
        "allowed_operations": ["VIEW"] if review or not applicability["is_current_input"] else ["VIEW", "REVISE", "REVIEW"],
        "created_at": _iso(execution.created_at),
    }


def revise_strategy_priority(
    db: Session,
    *,
    strategy_id: str,
    base_result_version: str,
    base_result_hash: str,
    reviewable_set_hash: str,
    ordered_direction_ids: list[str],
    editor: str,
    reason: str,
) -> SinglePromptStrategyResult:
    execution = db.query(SinglePromptStrategyExecution).filter(
        SinglePromptStrategyExecution.strategy_id == strategy_id
    ).one_or_none()
    if not execution or execution.active_result_version != base_result_version:
        raise HTTPException(status_code=409, detail="策略结果版本已变化，请重新加载")
    if not _strategy_applicability(db, execution)["is_current_input"]:
        raise HTTPException(status_code=409, detail="策略输入已过期；旧候选保留历史，但不能继续修改")
    base = db.query(SinglePromptStrategyResult).filter(
        SinglePromptStrategyResult.strategy_id == strategy_id,
        SinglePromptStrategyResult.result_version == base_result_version,
    ).one_or_none()
    if not base or base.output_hash != base_result_hash or base.reviewable_set_hash != reviewable_set_hash:
        raise HTTPException(status_code=409, detail="策略审核目标集合已变化，请重新加载")
    if db.query(SinglePromptStrategyReview).filter(SinglePromptStrategyReview.result_version == base_result_version).first():
        raise HTTPException(status_code=409, detail="已审核策略结果不可修改")
    output = copy.deepcopy(loads(base.output_json, {}))
    current_ids = [str(row.get("direction_id")) for row in output.get("directions") or []]
    if len(set(ordered_direction_ids)) != len(ordered_direction_ids) or set(ordered_direction_ids) != set(current_ids):
        raise HTTPException(status_code=422, detail="人工优先级必须且只能覆盖当前全部合格方向")
    order = {value: index + 1 for index, value in enumerate(ordered_direction_ids)}
    for row in output["directions"]:
        row["priority_order"] = order[row["direction_id"]]
        row["priority_basis"] = "HUMAN_PRIORITIZATION"
    output["needs_human_prioritization"] = False
    output["human_revision"] = {
        "type": "DIRECTION_PRIORITY",
        "editor": editor,
        "reason": reason,
        "ordered_direction_ids": ordered_direction_ids,
    }
    output_hash = _hash(output)
    version_number = base.version_number + 1
    result = SinglePromptStrategyResult(
        result_version=f"strategy-v{version_number}:{output_hash[:16]}",
        strategy_id=strategy_id,
        version_number=version_number,
        parent_result_version=base.result_version,
        output_json=_canonical_json(output),
        output_hash=output_hash,
        reviewable_set_hash=_hash({
            "theme_ids": sorted(row["theme_id"] for row in output["themes"]),
            "direction_ids": sorted(current_ids),
            "input_projection_hash": output["input_projection_hash"],
            "ordered_direction_ids": ordered_direction_ids,
        }),
        limitations_json=base.limitations_json,
    )
    db.add(result)
    db.flush()
    changed = db.execute(
        update(SinglePromptStrategyExecution)
        .where(
            SinglePromptStrategyExecution.strategy_id == strategy_id,
            SinglePromptStrategyExecution.active_result_version == base_result_version,
        )
        .values(active_result_version=result.result_version, status="READY_FOR_REVIEW")
    )
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="策略结果版本已变化，请重新加载")
    db.commit()
    db.refresh(result)
    return result


def complete_strategy_review(
    db: Session,
    *,
    strategy_id: str,
    result_version: str,
    result_hash: str,
    reviewable_set_hash: str,
    decision: str,
    reviewer: str,
    note: str,
) -> SinglePromptStrategyReview:
    if decision not in {"ACCEPTED", "REJECTED"}:
        raise HTTPException(status_code=422, detail="策略审核结论必须为 ACCEPTED 或 REJECTED")
    execution = db.query(SinglePromptStrategyExecution).filter(
        SinglePromptStrategyExecution.strategy_id == strategy_id
    ).one_or_none()
    if not execution or execution.active_result_version != result_version:
        raise HTTPException(status_code=409, detail="策略结果版本已变化，请重新加载")
    if not _strategy_applicability(db, execution)["is_current_input"]:
        raise HTTPException(status_code=409, detail="策略输入已过期；旧候选保留历史，但不能继续审核")
    result = db.query(SinglePromptStrategyResult).filter(
        SinglePromptStrategyResult.strategy_id == strategy_id,
        SinglePromptStrategyResult.result_version == result_version,
    ).one_or_none()
    if not result or result.output_hash != result_hash or result.reviewable_set_hash != reviewable_set_hash:
        raise HTTPException(status_code=409, detail="策略审核目标集合已变化，请重新加载")
    if decision == "ACCEPTED" and loads(result.output_json, {}).get("needs_human_prioritization"):
        raise HTTPException(status_code=409, detail="同层策略方向尚未完成人工优先级选择")
    if db.query(SinglePromptStrategyReview).filter(SinglePromptStrategyReview.result_version == result_version).first():
        raise HTTPException(status_code=409, detail="该策略结果已经完成审核")
    review = SinglePromptStrategyReview(
        review_id=f"strategy-review-{uuid4()}",
        strategy_id=strategy_id,
        result_version=result_version,
        result_hash=result_hash,
        reviewable_set_hash=reviewable_set_hash,
        decision=decision,
        reviewer=reviewer,
        note=note,
    )
    db.add(review)
    execution.status = decision
    db.commit()
    db.refresh(review)
    return review
