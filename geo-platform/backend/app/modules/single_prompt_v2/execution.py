from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    SinglePromptAnalysis,
    SinglePromptAnalysisContext,
    SinglePromptDiagnosisExecution,
    SinglePromptExecutionConfirmation,
    SinglePromptExecutionProposal,
    SinglePromptExecutionProposalResult,
    SinglePromptPublicationRecord,
    SinglePromptStrategyExecution,
    SinglePromptStrategyResult,
    SinglePromptStrategyReview,
)
from app.modules.optimization.execution_proposal_shadow import (
    FORMAL_METRIC_CALCULATORS,
    build_claim_usage_policy,
)
from app.modules.single_prompt_v2.strategy import _strategy_applicability, strategy_review_snapshot
from app.services.serialization import loads


EXECUTION_CONTRACT_VERSION = "single_prompt_execution.v2_fourth_slice"
EXECUTION_INPUT_VALIDATION_VERSION = "single_prompt_execution_input.v1"
PUBLICATION_CONFORMANCE_VERSION = "single_prompt_publication_conformance.v1"

VALID_RUN_STATUSES = {"success", "partial_success"}
FOUNDATION_ASSET_TYPES = ["PRODUCT_PAGE", "FEATURE_PAGE", "HELP_DOC"]
FOUNDATION_SURFACES = {
    "OWNED_PRODUCT_PAGE": "PRODUCT_PAGE",
    "OWNED_FEATURE_PAGE": "FEATURE_PAGE",
    "OWNED_HELP_CENTER": "HELP_DOC",
}
CHANNEL_ASSET_TYPES = {
    "BILIBILI": ["VIDEO"],
    "DOUYIN": ["VIDEO"],
    "BAIJIAHAO": ["ARTICLE"],
    "CSDN": ["ARTICLE"],
    "JIANSHU": ["ARTICLE"],
    "JUEJIN": ["ARTICLE"],
    "SOHU": ["ARTICLE"],
    "TENCENT": ["ARTICLE"],
    "WECHAT": ["ARTICLE"],
    "XIAOHONGSHU": ["ARTICLE"],
    "ZHIHU": ["ARTICLE"],
}
GENERIC_TITLE_WORDS = {
    "能力说明", "产品说明", "功能说明", "使用说明", "使用指南", "产品介绍", "功能介绍", "常见问题",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _iso(value: datetime | None) -> str | None:
    return f"{value.isoformat()}Z" if value else None


def _baseline_snapshot(
    analysis: SinglePromptAnalysis,
    context: SinglePromptAnalysisContext,
) -> dict[str, Any]:
    raw = loads(context.raw_output_json, {})
    run_scope = loads(context.run_scope_json, {})
    runs = raw.get("runs") or []
    sampling_plan = raw.get("sampling_plan") or loads(analysis.sampling_plan_json, {})
    if not isinstance(runs, list) or not runs:
        raise HTTPException(status_code=409, detail="冻结 AnalysisContext 缺少 Run 明细，不能生成执行方案")
    valid = [
        row for row in runs
        if row.get("status") in VALID_RUN_STATUSES and str(row.get("answer_text") or "").strip()
    ]
    failed = [row for row in runs if row not in valid]
    baseline_run_ids = [int(row["run_id"]) for row in valid if row.get("run_id") is not None]
    if not baseline_run_ids or len(baseline_run_ids) != context.valid_run_count:
        raise HTTPException(status_code=409, detail="冻结 AnalysisContext 的有效 Run 清单与计数不一致")
    if (
        _hash(raw) != context.raw_output_hash
        or _hash(sampling_plan) != analysis.sampling_plan_hash
        or not isinstance(run_scope, dict)
        or _hash(run_scope) != context.run_scope_hash
    ):
        raise HTTPException(status_code=409, detail="冻结 AnalysisContext 或采样计划 Hash 不匹配")
    scoped_run_ids = [int(value) for value in run_scope.get("run_ids") or []]
    raw_run_ids = [int(row["run_id"]) for row in runs if row.get("run_id") is not None]
    if scoped_run_ids != raw_run_ids or int(run_scope.get("planned_run_count") or 0) != len(runs):
        raise HTTPException(status_code=409, detail="冻结 Run Scope 与原始 Run manifest 不一致")
    reference_count = sum(len(row.get("references") or []) for row in runs)
    retrieval_count = sum(len(row.get("retrieval_candidates") or []) for row in runs)
    independent_unknown = all(
        (row.get("environment") or {}).get("sampling_mode") in {None, "", "UNKNOWN"}
        for row in runs
    )
    warnings = []
    if independent_unknown:
        warnings.append("INDEPENDENT_SESSION_PROOF_UNAVAILABLE")
    if reference_count and retrieval_count == 0:
        warnings.append("RETRIEVAL_OBSERVATION_UNAVAILABLE")
    return {
        "analysis_id": context.analysis_id,
        "context_id": context.context_id,
        "raw_result_version": context.result_version,
        "raw_output_hash": context.raw_output_hash,
        "run_scope_hash": context.run_scope_hash,
        "sampling_plan_hash": analysis.sampling_plan_hash,
        "sampling_configuration": sampling_plan,
        "baseline_run_ids": baseline_run_ids,
        "run_manifest": {
            "planned": [{"run_id": row.get("run_id"), "status": row.get("status")} for row in runs],
            "valid_run_ids": baseline_run_ids,
            "failed": [
                {"run_id": row.get("run_id"), "status": row.get("status"), "error": row.get("error")}
                for row in failed
            ],
            "planned_count": int(sampling_plan.get("sample_count") or len(runs)),
            "valid_count": len(valid),
            "failed_count": len(failed),
        },
        "collector_capability_snapshot": {
            "reference_observation": "AVAILABLE" if reference_count else "NO_REFERENCE_OBSERVED",
            "retrieval_observation": "UNAVAILABLE" if reference_count and retrieval_count == 0 else "AVAILABLE",
            "independent_session_proof": "UNAVAILABLE" if independent_unknown else "OBSERVED",
            "warnings": warnings,
        },
        "metric_definition_versions": {
            key: spec["calculator"] for key, spec in FORMAL_METRIC_CALCULATORS.items()
        },
        "measurement_status": "BASELINE_INPUT_FROZEN_NOT_COMPARED",
    }


def _confirmed_truths(strategy_input: dict[str, Any], direction: dict[str, Any]) -> list[dict[str, Any]]:
    allowed_ids = {int(value) for value in direction.get("truth_ids") or []}
    fully_covered = {
        int(row["truth_id"])
        for row in strategy_input.get("truth_relationships") or []
        if row.get("truth_id") is not None
        and row.get("effective_relation") == "FULLY_COVERS"
        and str(row.get("reason_id")) in set(direction.get("reason_ids") or [])
    }
    return [
        {
            "product_truth_id": int(row["truth_id"]),
            "capability_key": row.get("capability_key"),
            "capability_label": str(row.get("capability_label") or "").strip(),
            "product_truth_status": row.get("product_truth_status"),
            "truth_source": row.get("truth_source"),
            "approved_aliases": [],
        }
        for row in strategy_input.get("truth_snapshot") or []
        if row.get("truth_id") is not None
        and int(row["truth_id"]) in allowed_ids & fully_covered
        and row.get("product_truth_status") in {"TRUE", "SUPPORTED"}
        and row.get("truth_source") == "MANUAL_CONFIRMED"
        and (row.get("statement_eligibility") or {}).get("status") == "ELIGIBLE"
        and str(row.get("capability_label") or "").strip()
    ]


def _strategy_input_for_execution(
    db: Session,
    *,
    strategy_id: str,
    strategy_result_version: str,
    project_id: int,
    prompt_id: int,
    direction_id: str,
) -> dict[str, Any]:
    strategy = db.query(SinglePromptStrategyExecution).filter(
        SinglePromptStrategyExecution.strategy_id == strategy_id
    ).one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="V2 策略不存在")
    if strategy.project_id != project_id or strategy.prompt_id != prompt_id:
        raise HTTPException(status_code=409, detail="策略身份与当前 Project/Prompt 不匹配")
    if strategy.active_result_version != strategy_result_version:
        raise HTTPException(status_code=409, detail="策略结果版本已变化，请重新加载精确版本")
    result = db.query(SinglePromptStrategyResult).filter(
        SinglePromptStrategyResult.strategy_id == strategy_id,
        SinglePromptStrategyResult.result_version == strategy_result_version,
    ).one_or_none()
    review = db.query(SinglePromptStrategyReview).filter(
        SinglePromptStrategyReview.strategy_id == strategy_id,
        SinglePromptStrategyReview.result_version == strategy_result_version,
    ).one_or_none()
    is_machine_authority = strategy.input_authority_type == "MACHINE_QUALIFICATION"
    if not result or (not is_machine_authority and (not review or review.decision != "ACCEPTED")):
        raise HTTPException(status_code=409, detail="当前精确策略版本没有有效的机器资格或人工确认")
    applicability = _strategy_applicability(db, strategy)
    if not applicability["is_current_input"]:
        raise HTTPException(status_code=409, detail="策略输入已过期，不能授权新的执行方案")
    output = loads(result.output_json, {})
    direction = next((row for row in output.get("directions") or [] if row.get("direction_id") == direction_id), None)
    if not direction or direction.get("level") != "ACTIONABLE":
        raise HTTPException(status_code=409, detail="所选方向不属于当前已确认策略的合格方向")
    strategy_input = loads(strategy.input_snapshot_json, {})
    analysis = db.query(SinglePromptAnalysis).filter(
        SinglePromptAnalysis.analysis_id == strategy.analysis_id
    ).one_or_none()
    context = db.query(SinglePromptAnalysisContext).filter(
        SinglePromptAnalysisContext.context_id == strategy.context_id,
        SinglePromptAnalysisContext.analysis_id == strategy.analysis_id,
    ).one_or_none()
    diagnosis = db.query(SinglePromptDiagnosisExecution).filter(
        SinglePromptDiagnosisExecution.diagnosis_id == strategy.diagnosis_id
    ).one_or_none()
    if not analysis or not context or not diagnosis:
        raise HTTPException(status_code=409, detail="策略引用的冻结 V2 输入不完整")
    review_snapshot = strategy_review_snapshot(review) if review else {}
    baseline = _baseline_snapshot(analysis, context)
    truths = _confirmed_truths(strategy_input, direction) if not is_machine_authority else []
    if not is_machine_authority and (
        not truths
        or {row["product_truth_id"] for row in truths} != {int(value) for value in direction.get("truth_ids") or []}
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PUBLIC_CLAIM_EVIDENCE_REQUIRED",
                "detail": "策略方向可以基于已确认能力成立，但生成公开内容前必须补充目标品牌依据并确认可写范围。",
            },
        )
    return {
        "identity": {
            "analysis_id": strategy.analysis_id,
            "context_id": strategy.context_id,
            "diagnosis_id": strategy.diagnosis_id,
            "project_id": strategy.project_id,
            "prompt_id": strategy.prompt_id,
            "strategy_id": strategy.strategy_id,
            "strategy_result_version": result.result_version,
            "strategy_result_hash": result.output_hash,
            "strategy_review_id": review.review_id if review else None,
            "strategy_review_snapshot_hash": _hash(review_snapshot) if review else "",
            "input_authority_type": strategy.input_authority_type,
            "input_authority_id": strategy.input_authority_id,
            "input_authority_hash": strategy.input_authority_hash,
            "strategy_input_snapshot_hash": strategy.input_snapshot_hash,
        },
        "strategy_review_snapshot": review_snapshot,
        "automatic_draft": next(
            (
                copy.deepcopy(row)
                for row in output.get("execution_drafts") or []
                if row.get("direction_id") == direction_id
            ),
            None,
        ),
        "direction": copy.deepcopy(direction),
        "themes": [
            copy.deepcopy(row) for row in output.get("themes") or []
            if set(row.get("reason_ids") or []) & set(direction.get("reason_ids") or [])
        ],
        "truths": truths,
        "reasons": [
            copy.deepcopy(row) for row in strategy_input.get("reasons") or []
            if row.get("reason_id") in set(direction.get("reason_ids") or [])
        ],
        "truth_relationships": [
            copy.deepcopy(row) for row in strategy_input.get("truth_relationships") or []
            if str(row.get("reason_id")) in set(direction.get("reason_ids") or [])
        ],
        "effective_evidence_eligibility": copy.deepcopy(output.get("effective_evidence_eligibility") or {}),
        "limitations": copy.deepcopy(output.get("limitations") or []),
        "advisories": copy.deepcopy(output.get("advisories") or []),
        "brand_snapshot": loads(diagnosis.brand_snapshot_json, {}),
        "brand_snapshot_hash": diagnosis.brand_snapshot_hash,
        "baseline": baseline,
        "boundary": {
            "asset_operation": "CONDITIONAL" if is_machine_authority else "CREATE_NEW",
            "update_managed_enabled": False,
            "external_llm_calls": 0,
            "web_refetches": 0,
            "automatic_publication": False,
            "retest_computation": False,
        },
    }


def _asset_options(direction: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    if direction["direction_type"] in {"FOUNDATION", "MECHANISM", "DISCOVERY"}:
        assets = [
            {"asset_type": value, "label": {"PRODUCT_PAGE": "产品页", "FEATURE_PAGE": "功能页", "HELP_DOC": "帮助文档"}[value]}
            for value in FOUNDATION_ASSET_TYPES
        ]
        surfaces = [
            {"surface_key": key, "label": {"OWNED_PRODUCT_PAGE": "官网产品页", "OWNED_FEATURE_PAGE": "官网功能页", "OWNED_HELP_CENTER": "帮助中心"}[key], "asset_type": value}
            for key, value in FOUNDATION_SURFACES.items()
        ]
        return assets, surfaces
    channel = str(direction.get("channel_key") or "")
    assets = [{"asset_type": value, "label": "视频" if value == "VIDEO" else "文章"} for value in CHANNEL_ASSET_TYPES.get(channel, [])]
    surfaces = [{"surface_key": "CHANNEL_ACCOUNT", "label": f"{direction.get('channel_label') or channel}账号/栏目", "asset_type": assets[0]["asset_type"]}] if assets else []
    return assets, surfaces


def _reason_adapter(row: dict[str, Any], truth_ids: list[int]) -> dict[str, Any]:
    return {
        "reason_id": row.get("reason_id"),
        "original_reason": row.get("grounded_text") or "",
        "qualifier": [],
        "product_truth_ids": truth_ids,
    }


def _compile_output(proposal_id: str, input_snapshot: dict[str, Any]) -> dict[str, Any]:
    automatic_draft = input_snapshot.get("automatic_draft") or {}
    if automatic_draft:
        direction = input_snapshot["direction"]
        asset_types, surfaces = _asset_options(direction)
        blocks = []
        for index, row in enumerate(automatic_draft.get("content_blocks") or automatic_draft.get("sections") or []):
            block_id = str(row.get("block_id") or row.get("section_id") or f"section:{proposal_id}:{index + 1}")
            blocks.append({
                "section_id": block_id,
                "content_class": "PUBLIC_CONTENT",
                "purpose": str(row.get("content_role") or row.get("purpose") or "GROUNDED_CONTENT"),
                "title": str(row.get("heading") or row.get("title") or f"内容 {index + 1}"),
                "draft_text": str(row.get("draft_text") or ""),
                "truth_ids": [],
                "reason_ids": [],
                "theme_ids": [],
                "allowed_claim_ids": [],
                "answer_unit_id": row.get("answer_unit_id"),
                "binding_id": row.get("binding_id"),
                "citation_id": row.get("citation_id"),
                "evidence_relation": row.get("evidence_relation"),
            })
        title = str(automatic_draft.get("title") or "执行内容草稿")
        output = {
            "contract_version": EXECUTION_CONTRACT_VERSION,
            "proposal_id": proposal_id,
            "input_identity": copy.deepcopy(input_snapshot["identity"]),
            "direction": copy.deepcopy(direction),
            "strategy_channel": {
                "channel_key": direction.get("channel_key"),
                "channel_label": direction.get("channel_label"),
                "channel_role": direction.get("channel_role"),
                "immutable": True,
            },
            "asset_operation": "CONDITIONAL",
            "asset_type_candidates": asset_types,
            "publication_surface_candidates": surfaces,
            "package_candidates": [{"package_key": "MACHINE_DRAFT", "label": "当前机器资格草稿", "direction_id": direction["direction_id"], "truth_ids": []}],
            "title_candidates": [{"title_id": "MACHINE_GROUNDED_TITLE", "title": title, "truth_ids": []}],
            "public_content_candidates": blocks,
            "internal_checklist": copy.deepcopy(automatic_draft.get("internal_checklist") or []),
            "claim_usage_policy": [],
            "selection": {
                "asset_operation": "CONDITIONAL",
                "asset_type": None,
                "package_key": "MACHINE_DRAFT",
                "publication_surface": None,
                "publishing_account": "",
                "publishing_location": "",
                "account_control_status": "UNVERIFIED",
                "title": title,
                "section_order": [row["section_id"] for row in blocks],
                "execution_note": "",
            },
            "selected_public_content": blocks,
            "baseline": copy.deepcopy(input_snapshot["baseline"]),
            "limitations": copy.deepcopy(input_snapshot.get("limitations") or []),
            "advisories": copy.deepcopy(input_snapshot.get("advisories") or []),
            "automatic_qa": copy.deepcopy(automatic_draft.get("qa") or {}),
            "validation": {},
            "boundary": copy.deepcopy(input_snapshot["boundary"]),
        }
        output["validation"] = validate_execution_output(output, input_snapshot)
        return output
    direction = input_snapshot["direction"]
    truths = input_snapshot["truths"]
    truth_ids = [row["product_truth_id"] for row in truths]
    brand = str((input_snapshot.get("brand_snapshot") or {}).get("brand_name") or "目标品牌")
    reasons = [_reason_adapter(row, truth_ids) for row in input_snapshot.get("reasons") or []]
    claim_policy = build_claim_usage_policy(brand, truths, reasons)
    allowed_claims = [row for row in claim_policy if row.get("policy") == "TARGET_ASSERTION_ALLOWED"]
    asset_types, surfaces = _asset_options(direction)
    if not asset_types or not surfaces:
        raise HTTPException(status_code=409, detail="所选渠道没有已批准的确定性资产类型规则")
    suffix = "能力说明" if direction["direction_type"] == "FOUNDATION" else "使用说明"
    default_title = f"{brand}：{'、'.join(row['capability_label'] for row in truths)}{suffix}"
    sections = [{
        "section_id": f"section:{proposal_id}:summary",
        "content_class": "PUBLIC_CONTENT",
        "purpose": "DIRECT_ANSWER",
        "title": "能力概览",
        "truth_ids": truth_ids,
        "reason_ids": [],
        "theme_ids": [row.get("theme_id") for row in input_snapshot.get("themes") or [] if row.get("theme_id")],
        "allowed_claim_ids": [row["claim_id"] for row in allowed_claims],
    }]
    sections.extend({
        "section_id": f"section:{proposal_id}:truth:{truth['product_truth_id']}",
        "content_class": "PUBLIC_CONTENT",
        "purpose": "PRODUCT_TRUTH",
        "title": truth["capability_label"],
        "truth_ids": [truth["product_truth_id"]],
        "reason_ids": [],
        "theme_ids": [],
        "allowed_claim_ids": [
            row["claim_id"] for row in allowed_claims
            if row.get("product_truth_id") == truth["product_truth_id"]
        ],
    } for truth in truths)
    partial_items = [
        {"code": "PARTIAL_TRUTH_RELATION_NOT_PUBLISHABLE", "relationship_id": row.get("relationship_id"), "reason_id": row.get("reason_id")}
        for row in input_snapshot.get("truth_relationships") or []
        if row.get("effective_relation") == "PARTIALLY_COVERS"
    ]
    checklist = [
        {"code": "VERIFY_PUBLICATION_AUTHORITY", "detail": "确认发布账号和位置确由目标品牌控制；用户报告不等于系统验证。"},
        {"code": "PRESERVE_MEASUREMENT_LIMITS", "detail": "保留固定 Baseline 与当前采集能力限制，不把不可测写成零。"},
        *partial_items,
        *[{"code": str(row.get("code") or "LIMITATION"), "detail": row} for row in input_snapshot.get("limitations") or []],
        *[{"code": str(row.get("code") or "ADVISORY"), "detail": row} for row in input_snapshot.get("advisories") or []],
    ]
    if direction.get("hypothesis"):
        checklist.append({"code": "CHANNEL_TEST_HYPOTHESIS", "detail": direction["hypothesis"]})
    selected_asset = asset_types[0]["asset_type"] if len(asset_types) == 1 else None
    selected_surface = surfaces[0]["surface_key"] if len(surfaces) == 1 else None
    output = {
        "contract_version": EXECUTION_CONTRACT_VERSION,
        "proposal_id": proposal_id,
        "input_identity": copy.deepcopy(input_snapshot["identity"]),
        "direction": copy.deepcopy(direction),
        "strategy_channel": {
            "channel_key": direction.get("channel_key"),
            "channel_label": direction.get("channel_label"),
            "channel_role": direction.get("channel_role"),
            "immutable": True,
        },
        "asset_operation": "CREATE_NEW",
        "asset_type_candidates": asset_types,
        "publication_surface_candidates": surfaces,
        "package_candidates": [{"package_key": "FULL_DIRECTION_SCOPE", "label": "完整承接已确认方向", "direction_id": direction["direction_id"], "truth_ids": truth_ids}],
        "title_candidates": [{"title_id": "EXACT_TRUTH_TITLE", "title": default_title, "truth_ids": truth_ids}],
        "public_content_candidates": sections,
        "internal_checklist": checklist,
        "claim_usage_policy": claim_policy,
        "selection": {
            "asset_operation": "CREATE_NEW",
            "asset_type": selected_asset,
            "package_key": "FULL_DIRECTION_SCOPE",
            "publication_surface": selected_surface,
            "publishing_account": "",
            "publishing_location": "",
            "account_control_status": "UNVERIFIED",
            "title": default_title,
            "section_order": [row["section_id"] for row in sections],
            "execution_note": "",
        },
        "selected_public_content": sections,
        "baseline": copy.deepcopy(input_snapshot["baseline"]),
        "limitations": copy.deepcopy(input_snapshot.get("limitations") or []),
        "advisories": copy.deepcopy(input_snapshot.get("advisories") or []),
        "validation": {},
        "boundary": copy.deepcopy(input_snapshot["boundary"]),
    }
    output["validation"] = validate_execution_output(output, input_snapshot)
    return output


def _title_validation(title: str, brand: str, truths: list[dict[str, Any]]) -> list[str]:
    errors = []
    if not title.strip():
        return ["TITLE_REQUIRED"]
    allowed_phrases = [brand, *(row["capability_label"] for row in truths), *GENERIC_TITLE_WORDS]
    remainder = title
    for phrase in sorted(allowed_phrases, key=len, reverse=True):
        remainder = remainder.replace(phrase, "")
    remainder = re.sub(r"[\s:：,，、。.!！?？()（）\-_/|]+", "", remainder)
    if remainder:
        errors.append("TITLE_CONTAINS_UNAPPROVED_WORDING")
    if not all(row["capability_label"] in title for row in truths):
        errors.append("TITLE_DROPS_CONFIRMED_SCOPE")
    return errors


def validate_execution_output(output: dict[str, Any], input_snapshot: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    selection = output.get("selection") or {}
    direction = input_snapshot["direction"]
    if output.get("asset_operation") != "CREATE_NEW" or selection.get("asset_operation") != "CREATE_NEW":
        errors.append("ASSET_OPERATION_SELECTION_REQUIRED")
    if output.get("strategy_channel") != {
        "channel_key": direction.get("channel_key"),
        "channel_label": direction.get("channel_label"),
        "channel_role": direction.get("channel_role"),
        "immutable": True,
    }:
        errors.append("STRATEGY_CHANNEL_MUTATION")
    allowed_types = {row["asset_type"] for row in output.get("asset_type_candidates") or []}
    if selection.get("asset_type") not in allowed_types:
        errors.append("ASSET_TYPE_SELECTION_REQUIRED")
    surfaces = {row["surface_key"]: row for row in output.get("publication_surface_candidates") or []}
    surface = surfaces.get(selection.get("publication_surface"))
    if not surface:
        errors.append("PUBLICATION_SURFACE_SELECTION_REQUIRED")
    elif surface["asset_type"] != selection.get("asset_type"):
        errors.append("PUBLICATION_SURFACE_ASSET_TYPE_MISMATCH")
    if not str(selection.get("publishing_account") or "").strip():
        errors.append("PUBLISHING_ACCOUNT_REQUIRED")
    if not str(selection.get("publishing_location") or "").strip():
        errors.append("PUBLISHING_LOCATION_REQUIRED")
    if selection.get("account_control_status") != "USER_REPORTED_CONTROL":
        errors.append("PUBLICATION_AUTHORITY_NOT_CONFIRMED")
    allowed_packages = {row.get("package_key") for row in output.get("package_candidates") or []}
    if selection.get("package_key") not in allowed_packages:
        errors.append("INVALID_PACKAGE_SELECTION")
    candidate_sections = {row["section_id"]: row for row in output.get("public_content_candidates") or []}
    order = selection.get("section_order") or []
    if not order or len(order) != len(set(order)) or not set(order).issubset(candidate_sections):
        errors.append("INVALID_PUBLIC_SECTION_SELECTION")
    machine_authority = (input_snapshot.get("identity") or {}).get("input_authority_type") == "MACHINE_QUALIFICATION"
    if not machine_authority and not any(candidate_sections.get(value, {}).get("purpose") == "PRODUCT_TRUTH" for value in order):
        errors.append("PRODUCT_TRUTH_SECTION_REQUIRED")
    if any(candidate_sections.get(value, {}).get("content_class") != "PUBLIC_CONTENT" for value in order):
        errors.append("INTERNAL_ITEM_IN_PUBLIC_CONTENT")
    if machine_authority:
        if str(selection.get("title") or "") not in {
            str(row.get("title") or "") for row in output.get("title_candidates") or []
        }:
            errors.append("TITLE_CONTAINS_UNAPPROVED_WORDING")
        qa = output.get("automatic_qa") or {}
        if qa.get("status") != "READY_INTERNAL":
            errors.append("AUTOMATIC_QA_NOT_READY")
    else:
        errors.extend(_title_validation(
            str(selection.get("title") or ""),
            str((input_snapshot.get("brand_snapshot") or {}).get("brand_name") or "目标品牌"),
            input_snapshot["truths"],
        ))
    baseline = output.get("baseline") or {}
    if baseline != input_snapshot.get("baseline"):
        errors.append("BASELINE_MUTATION")
    if baseline.get("baseline_run_ids") != (baseline.get("run_manifest") or {}).get("valid_run_ids"):
        errors.append("BASELINE_NOT_COMPLETE_VALID_RUN_SET")
    if not machine_authority and set(direction.get("truth_ids") or []) != {row["product_truth_id"] for row in input_snapshot["truths"]}:
        errors.append("PARTIAL_OR_UNCONFIRMED_TRUTH_IN_PUBLIC_SCOPE")
    return {
        "status": "READY_FOR_CONFIRMATION" if not errors else "NEEDS_HUMAN_SELECTION",
        "errors": errors,
        "validators": {
            "strategy_channel_immutable": "PASS" if "STRATEGY_CHANNEL_MUTATION" not in errors else "FAIL",
            "asset_operation_selected": "PASS" if "ASSET_OPERATION_SELECTION_REQUIRED" not in errors else "FAIL",
            "truth_grounding": "PASS" if "PARTIAL_OR_UNCONFIRMED_TRUTH_IN_PUBLIC_SCOPE" not in errors else "FAIL",
            "baseline_exact": "PASS" if not {"BASELINE_MUTATION", "BASELINE_NOT_COMPLETE_VALID_RUN_SET"} & set(errors) else "FAIL",
            "public_internal_separation": "PASS" if "INTERNAL_ITEM_IN_PUBLIC_CONTENT" not in errors else "FAIL",
        },
    }


def create_execution_proposal(
    db: Session,
    *,
    strategy_id: str,
    strategy_result_version: str,
    project_id: int,
    prompt_id: int,
    direction_id: str,
    idempotency_key: str,
    strategy_result_hash: str,
    strategy_review_id: str | None,
    strategy_review_snapshot_hash: str,
    input_authority_type: str = "HUMAN_REVIEW",
    input_authority_id: str = "",
    input_authority_hash: str = "",
) -> tuple[SinglePromptExecutionProposal, SinglePromptExecutionProposalResult, bool]:
    snapshot = _strategy_input_for_execution(
        db, strategy_id=strategy_id, strategy_result_version=strategy_result_version,
        project_id=project_id, prompt_id=prompt_id, direction_id=direction_id,
    )
    current = snapshot["identity"]
    expected_authority = {
        "input_authority_type": current.get("input_authority_type") or "HUMAN_REVIEW",
        "input_authority_id": current.get("input_authority_id") or "",
        "input_authority_hash": current.get("input_authority_hash") or "",
    }
    submitted_authority = {
        "input_authority_type": input_authority_type,
        "input_authority_id": input_authority_id,
        "input_authority_hash": input_authority_hash,
    }
    if strategy_result_hash != current["strategy_result_hash"] or (
        input_authority_type == "MACHINE_QUALIFICATION" and submitted_authority != expected_authority
    ) or (
        input_authority_type == "HUMAN_REVIEW"
        and (
            strategy_review_id != current["strategy_review_id"]
            or strategy_review_snapshot_hash != current["strategy_review_snapshot_hash"]
        )
    ):
        raise HTTPException(status_code=409, detail="策略结果或审核快照已变化，请重新加载")
    snapshot["input_snapshot_hash"] = _hash(snapshot)
    fingerprint = _hash({
        "identity": current,
        "direction_id": direction_id,
        "input_snapshot_hash": snapshot["input_snapshot_hash"],
        "contract_version": EXECUTION_CONTRACT_VERSION,
    })
    existing = db.query(SinglePromptExecutionProposal).filter(
        SinglePromptExecutionProposal.strategy_id == strategy_id,
        SinglePromptExecutionProposal.idempotency_key == idempotency_key,
    ).one_or_none()
    if existing:
        if existing.input_fingerprint != fingerprint:
            raise HTTPException(status_code=409, detail="幂等键已用于不同执行方案输入")
        result = db.query(SinglePromptExecutionProposalResult).filter(
            SinglePromptExecutionProposalResult.result_version == existing.active_result_version
        ).one()
        return existing, result, False
    proposal_id = f"execution-proposal-{uuid4()}"
    output = _compile_output(proposal_id, snapshot)
    output_hash = _hash(output)
    reviewable_set_hash = _hash({
        "direction_id": direction_id,
        "asset_types": [row["asset_type"] for row in output["asset_type_candidates"]],
        "surfaces": [row["surface_key"] for row in output["publication_surface_candidates"]],
        "public_section_ids": [row["section_id"] for row in output["public_content_candidates"]],
        "input_snapshot_hash": snapshot["input_snapshot_hash"],
    })
    result = SinglePromptExecutionProposalResult(
        result_version=f"execution-v1:{output_hash[:16]}", proposal_id=proposal_id,
        version_number=1, output_json=_canonical_json(output), output_hash=output_hash,
        reviewable_set_hash=reviewable_set_hash,
        limitations_json=_canonical_json(output.get("limitations") or []),
    )
    proposal = SinglePromptExecutionProposal(
        proposal_id=proposal_id, strategy_id=strategy_id,
        analysis_id=current["analysis_id"], context_id=current["context_id"],
        diagnosis_id=current["diagnosis_id"], project_id=project_id, prompt_id=prompt_id,
        direction_id=direction_id, idempotency_key=idempotency_key, input_fingerprint=fingerprint,
        strategy_result_version=strategy_result_version, strategy_result_hash=strategy_result_hash,
        strategy_review_id=strategy_review_id, strategy_review_snapshot_hash=strategy_review_snapshot_hash,
        input_authority_type=input_authority_type,
        input_authority_id=input_authority_id,
        input_authority_hash=input_authority_hash,
        validation_contract_version=EXECUTION_INPUT_VALIDATION_VERSION,
        input_snapshot_json=_canonical_json(snapshot), input_snapshot_hash=snapshot["input_snapshot_hash"],
        status=output["validation"]["status"], active_result_version=result.result_version,
    )
    db.add_all([proposal, result])
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = db.query(SinglePromptExecutionProposal).filter(
            SinglePromptExecutionProposal.strategy_id == strategy_id,
            SinglePromptExecutionProposal.idempotency_key == idempotency_key,
        ).one_or_none()
        if concurrent and concurrent.input_fingerprint == fingerprint:
            return concurrent, db.query(SinglePromptExecutionProposalResult).filter_by(result_version=concurrent.active_result_version).one(), False
        raise
    return proposal, result, True


def _proposal_applicability(db: Session, proposal: SinglePromptExecutionProposal) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    strategy = db.query(SinglePromptStrategyExecution).filter_by(strategy_id=proposal.strategy_id).one_or_none()
    checks["strategy_exists"] = bool(strategy)
    checks["strategy_result_is_active"] = bool(strategy and strategy.active_result_version == proposal.strategy_result_version)
    checks["strategy_input_is_current"] = bool(strategy and _strategy_applicability(db, strategy)["is_current_input"])
    result = db.query(SinglePromptStrategyResult).filter_by(result_version=proposal.strategy_result_version).one_or_none()
    checks["strategy_result_hash_matches"] = bool(result and result.output_hash == proposal.strategy_result_hash)
    if proposal.input_authority_type == "MACHINE_QUALIFICATION":
        checks["machine_authority_matches"] = bool(
            strategy
            and strategy.input_authority_type == "MACHINE_QUALIFICATION"
            and strategy.input_authority_id == proposal.input_authority_id
            and strategy.input_authority_hash == proposal.input_authority_hash
        )
    else:
        review = db.query(SinglePromptStrategyReview).filter_by(review_id=proposal.strategy_review_id).one_or_none()
        checks["strategy_review_accepted"] = bool(review and review.decision == "ACCEPTED")
        checks["strategy_review_snapshot_matches"] = bool(
            review and _hash(strategy_review_snapshot(review)) == proposal.strategy_review_snapshot_hash
        )
    return {"is_current_input": all(checks.values()), "checks": checks}


def revise_execution_proposal(
    db: Session,
    *,
    proposal_id: str,
    base_result_version: str,
    base_result_hash: str,
    reviewable_set_hash: str,
    editor: str,
    edit: dict[str, Any],
) -> SinglePromptExecutionProposalResult:
    proposal = db.query(SinglePromptExecutionProposal).filter_by(proposal_id=proposal_id).one_or_none()
    if not proposal or proposal.active_result_version != base_result_version:
        raise HTTPException(status_code=409, detail="执行方案结果版本已变化，请重新加载")
    if not _proposal_applicability(db, proposal)["is_current_input"]:
        raise HTTPException(status_code=409, detail="执行方案输入已过期，不能授权新的执行")
    base = db.query(SinglePromptExecutionProposalResult).filter_by(
        proposal_id=proposal_id, result_version=base_result_version
    ).one_or_none()
    if not base or base.output_hash != base_result_hash or base.reviewable_set_hash != reviewable_set_hash:
        raise HTTPException(status_code=409, detail="执行方案编辑目标已变化，请重新加载")
    if str(edit.get("asset_operation") or "") != "CREATE_NEW":
        raise HTTPException(status_code=422, detail="当前 V2 未启用 UPDATE；执行方案不能自动降级成其他操作")
    output = copy.deepcopy(loads(base.output_json, {}))
    selection = output["selection"]
    editable = {
        "asset_type", "package_key", "publication_surface", "publishing_account", "publishing_location",
        "account_control_status", "title", "section_order", "execution_note", "asset_operation",
    }
    unknown = set(edit) - editable
    if unknown:
        raise HTTPException(status_code=422, detail=f"包含不可编辑字段：{', '.join(sorted(unknown))}")
    selection.update(copy.deepcopy(edit))
    selection["asset_operation"] = "CREATE_NEW"
    output["asset_operation"] = "CREATE_NEW"
    sections = {row["section_id"]: row for row in output["public_content_candidates"]}
    output["selected_public_content"] = [sections[value] for value in selection.get("section_order") or [] if value in sections]
    snapshot = loads(proposal.input_snapshot_json, {})
    output["validation"] = validate_execution_output(output, snapshot)
    output["human_revision"] = {
        "editor": editor,
        "edited_fields": sorted(edit),
        "base_result_version": base_result_version,
    }
    output_hash = _hash(output)
    version_number = base.version_number + 1
    result = SinglePromptExecutionProposalResult(
        result_version=f"execution-v{version_number}:{output_hash[:16]}", proposal_id=proposal_id,
        version_number=version_number, parent_result_version=base_result_version,
        output_json=_canonical_json(output), output_hash=output_hash,
        reviewable_set_hash=_hash({
            "input_snapshot_hash": proposal.input_snapshot_hash,
            "selection": selection,
            "selected_section_ids": selection.get("section_order") or [],
        }),
        limitations_json=base.limitations_json,
    )
    db.add(result)
    db.flush()
    changed = db.execute(
        update(SinglePromptExecutionProposal)
        .where(
            SinglePromptExecutionProposal.proposal_id == proposal_id,
            SinglePromptExecutionProposal.active_result_version == base_result_version,
        )
        .values(active_result_version=result.result_version, status=output["validation"]["status"])
    )
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="执行方案结果版本已变化，请重新加载")
    db.commit()
    db.refresh(result)
    return result


def confirm_execution_proposal(
    db: Session,
    *,
    proposal_id: str,
    result_version: str,
    result_hash: str,
    reviewable_set_hash: str,
    idempotency_key: str,
    confirmer: str,
    note: str,
) -> tuple[SinglePromptExecutionConfirmation, bool]:
    proposal = db.query(SinglePromptExecutionProposal).filter_by(proposal_id=proposal_id).one_or_none()
    if not proposal or proposal.active_result_version != result_version:
        raise HTTPException(status_code=409, detail="执行方案结果版本已变化，请重新加载")
    if not _proposal_applicability(db, proposal)["is_current_input"]:
        raise HTTPException(status_code=409, detail="执行方案输入已过期，不能授权新的执行")
    result = db.query(SinglePromptExecutionProposalResult).filter_by(
        proposal_id=proposal_id, result_version=result_version
    ).one_or_none()
    if not result or result.output_hash != result_hash or result.reviewable_set_hash != reviewable_set_hash:
        raise HTTPException(status_code=409, detail="执行确认目标已变化，请重新加载")
    output = loads(result.output_json, {})
    validation = validate_execution_output(output, loads(proposal.input_snapshot_json, {}))
    if validation["status"] != "READY_FOR_CONFIRMATION":
        raise HTTPException(status_code=409, detail={"code": "EXECUTION_PROPOSAL_NOT_READY", "validation": validation})
    existing = db.query(SinglePromptExecutionConfirmation).filter_by(
        proposal_id=proposal_id, idempotency_key=idempotency_key
    ).one_or_none()
    if existing:
        if existing.result_version != result_version or existing.result_hash != result_hash:
            raise HTTPException(status_code=409, detail="幂等键已用于不同执行确认")
        return existing, False
    confirmed_snapshot = {
        "proposal_id": proposal_id,
        "result_version": result_version,
        "result_hash": result_hash,
        "reviewable_set_hash": reviewable_set_hash,
        "input_snapshot_hash": proposal.input_snapshot_hash,
        "strategy_result_version": proposal.strategy_result_version,
        "strategy_review_id": proposal.strategy_review_id,
        "direction_id": proposal.direction_id,
        "selection": output["selection"],
        "public_content": output["selected_public_content"],
        "baseline": output["baseline"],
        "limitations": output.get("limitations") or [],
        "advisories": output.get("advisories") or [],
        "publication_status": "NOT_REPORTED",
    }
    snapshot_hash = _hash(confirmed_snapshot)
    confirmation = SinglePromptExecutionConfirmation(
        confirmation_id=f"execution-confirmation-{uuid4()}", proposal_id=proposal_id,
        result_version=result_version, result_hash=result_hash, reviewable_set_hash=reviewable_set_hash,
        input_snapshot_hash=proposal.input_snapshot_hash, idempotency_key=idempotency_key,
        confirmation_snapshot_json=_canonical_json(confirmed_snapshot), confirmation_snapshot_hash=snapshot_hash,
        confirmer=confirmer, note=note,
    )
    db.add(confirmation)
    proposal.status = "CONFIRMED_PENDING_PUBLICATION"
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = db.query(SinglePromptExecutionConfirmation).filter_by(
            proposal_id=proposal_id, idempotency_key=idempotency_key
        ).one_or_none()
        if concurrent and concurrent.result_version == result_version:
            return concurrent, False
        raise
    db.refresh(confirmation)
    return confirmation, True


def _assess_publication_conformance(report: dict[str, Any], confirmed: dict[str, Any]) -> dict[str, Any]:
    selection = confirmed["selection"]
    checked: list[str] = []
    mismatches: list[str] = []
    unknown: list[str] = []
    expected_channel = (confirmed.get("strategy_channel") or {}).get("channel_key")
    actual_channel = str(report.get("actual_channel") or "").upper()
    if expected_channel:
        checked.append("channel")
        if actual_channel != expected_channel:
            mismatches.append("CHANNEL_OUTSIDE_CONFIRMED_SCOPE")
    checked.extend(["publishing_account", "publishing_location"])
    if report.get("actual_account") != selection.get("publishing_account"):
        mismatches.append("ACCOUNT_DIFFERS_FROM_CONFIRMATION")
    if report.get("actual_location") != selection.get("publishing_location"):
        mismatches.append("LOCATION_DIFFERS_FROM_CONFIRMATION")
    content_version = str(report.get("actual_content_version") or "").strip()
    content_excerpt = str(report.get("actual_content_excerpt") or "").strip()
    actual_title = str(report.get("actual_title") or "").strip()
    actual_sections = report.get("actual_section_ids")
    actual_claims = report.get("actual_claim_ids")
    expected_sections = selection.get("section_order") or []
    expected_claims = sorted({
        claim_id for row in confirmed.get("public_content") or [] for claim_id in row.get("allowed_claim_ids") or []
    })
    if content_version:
        checked.append("content_version")
        if content_version != confirmed["result_version"]:
            mismatches.append("CONTENT_VERSION_DIFFERS_FROM_CONFIRMATION")
    elif actual_title and isinstance(actual_sections, list) and isinstance(actual_claims, list):
        checked.extend(["title", "sections", "claims"])
        if actual_title != selection.get("title"):
            unknown.append("TITLE_VARIATION_REQUIRES_RULE_VALIDATION")
        if not set(actual_sections).issubset(set(expected_sections)):
            mismatches.append("UNKNOWN_PUBLIC_SECTION")
        if not set(actual_claims).issubset(set(expected_claims)):
            mismatches.append("UNCONFIRMED_PUBLIC_CLAIM")
    else:
        unknown.append("ACTUAL_CONTENT_NOT_PROVIDED")
    if content_excerpt:
        checked.append("content_excerpt")
        unknown.append("ACTUAL_CONTENT_EXCERPT_NOT_FULLY_VALIDATED")
    if mismatches:
        status = "OUTSIDE_CONFIRMED_SCOPE"
    elif unknown:
        status = "NOT_EVALUABLE"
    elif content_version == confirmed["result_version"] and report.get("actual_account") == selection.get("publishing_account") and report.get("actual_location") == selection.get("publishing_location"):
        status = "MATCHED"
    else:
        status = "VALIDATED_VARIATION"
    return {
        "contract_version": PUBLICATION_CONFORMANCE_VERSION,
        "conformance": status,
        "checked_fields": checked,
        "mismatches": mismatches,
        "not_evaluable": unknown,
        "system_verified_online": False,
    }


def record_publication(
    db: Session,
    *,
    confirmation_id: str,
    proposal_id: str,
    idempotency_key: str,
    prior_publication_id: str | None,
    recorder: str,
    report: dict[str, Any],
) -> tuple[SinglePromptPublicationRecord, bool]:
    confirmation = db.query(SinglePromptExecutionConfirmation).filter_by(
        confirmation_id=confirmation_id
    ).one_or_none()
    if not confirmation:
        raise HTTPException(status_code=409, detail="没有精确 ExecutionConfirmation，不能登记为已确认方案的执行")
    if confirmation.proposal_id != proposal_id:
        raise HTTPException(status_code=409, detail="ExecutionConfirmation 不属于当前执行方案")
    if str(report.get("publication_status") or "USER_REPORTED") != "USER_REPORTED":
        raise HTTPException(status_code=422, detail="本轮发布登记只能是 USER_REPORTED")
    url = str(report.get("actual_url") or "").strip()
    parsed = urlparse(url)
    if not url or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=422, detail="实际发布 URL 必须是有效的 http/https 地址")
    if not str(report.get("published_at") or "").strip():
        raise HTTPException(status_code=422, detail="请提供实际发布时间")
    existing = db.query(SinglePromptPublicationRecord).filter_by(
        confirmation_id=confirmation_id, idempotency_key=idempotency_key
    ).one_or_none()
    report_hash = _hash(report)
    if existing:
        if existing.report_hash != report_hash:
            raise HTTPException(status_code=409, detail="幂等键已用于不同发布报告")
        return existing, False
    revision_number = 1
    if prior_publication_id:
        prior = db.query(SinglePromptPublicationRecord).filter_by(publication_id=prior_publication_id).one_or_none()
        if not prior or prior.confirmation_id != confirmation_id:
            raise HTTPException(status_code=409, detail="发布修订引用的历史记录不属于当前确认")
        if db.query(SinglePromptPublicationRecord).filter_by(prior_publication_id=prior_publication_id).first():
            raise HTTPException(status_code=409, detail="该发布记录已有后继修订，请基于最新记录提交")
        revision_number = prior.revision_number + 1
    confirmed = loads(confirmation.confirmation_snapshot_json, {})
    proposal = db.query(SinglePromptExecutionProposal).filter_by(proposal_id=confirmation.proposal_id).one()
    proposal_result = db.query(SinglePromptExecutionProposalResult).filter_by(result_version=confirmation.result_version).one()
    proposal_output = loads(proposal_result.output_json, {})
    confirmed["strategy_channel"] = proposal_output.get("strategy_channel") or {}
    conformance = _assess_publication_conformance(report, confirmed)
    publication = SinglePromptPublicationRecord(
        publication_id=f"publication-{uuid4()}", confirmation_id=confirmation_id,
        proposal_id=confirmation.proposal_id, prior_publication_id=prior_publication_id,
        revision_number=revision_number, idempotency_key=idempotency_key,
        publication_status="USER_REPORTED", conformance=conformance["conformance"],
        report_json=_canonical_json(report), report_hash=report_hash,
        conformance_json=_canonical_json(conformance), recorder=recorder,
    )
    db.add(publication)
    proposal.status = "PUBLICATION_REPORTED"
    db.commit()
    db.refresh(publication)
    return publication, True


def get_execution_proposal_status(
    db: Session,
    *,
    proposal_id: str,
    strategy_id: str,
    project_id: int,
    prompt_id: int,
) -> dict[str, Any]:
    proposal = db.query(SinglePromptExecutionProposal).filter_by(
        proposal_id=proposal_id, strategy_id=strategy_id
    ).one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="V2 执行方案不存在")
    if proposal.project_id != project_id or proposal.prompt_id != prompt_id:
        raise HTTPException(status_code=409, detail="执行方案身份与当前 Project/Prompt 不匹配")
    result = db.query(SinglePromptExecutionProposalResult).filter_by(
        result_version=proposal.active_result_version
    ).one_or_none()
    confirmations = db.query(SinglePromptExecutionConfirmation).filter_by(
        proposal_id=proposal_id
    ).order_by(SinglePromptExecutionConfirmation.created_at).all()
    confirmation_ids = [row.confirmation_id for row in confirmations]
    publications = db.query(SinglePromptPublicationRecord).filter(
        SinglePromptPublicationRecord.confirmation_id.in_(confirmation_ids)
    ).order_by(SinglePromptPublicationRecord.created_at).all() if confirmation_ids else []
    applicability = _proposal_applicability(db, proposal)
    active_confirmation = next((row for row in confirmations if row.result_version == proposal.active_result_version), None)
    allowed_operations = ["VIEW"]
    if applicability["is_current_input"]:
        allowed_operations.append("REVISE")
        if result and (loads(result.output_json, {}).get("validation") or {}).get("status") == "READY_FOR_CONFIRMATION" and not active_confirmation:
            allowed_operations.append("CONFIRM")
    if confirmations:
        allowed_operations.append("RECORD_PUBLICATION")
    return {
        "proposal": {
            "proposal_id": proposal.proposal_id, "strategy_id": proposal.strategy_id,
            "analysis_id": proposal.analysis_id, "context_id": proposal.context_id,
            "diagnosis_id": proposal.diagnosis_id, "project_id": proposal.project_id,
            "prompt_id": proposal.prompt_id, "direction_id": proposal.direction_id,
            "strategy_result_version": proposal.strategy_result_version,
            "strategy_result_hash": proposal.strategy_result_hash,
            "strategy_review_id": proposal.strategy_review_id,
            "strategy_review_snapshot_hash": proposal.strategy_review_snapshot_hash,
            "input_authority_type": proposal.input_authority_type,
            "input_authority_id": proposal.input_authority_id,
            "input_authority_hash": proposal.input_authority_hash,
            "input_snapshot_hash": proposal.input_snapshot_hash,
            "status": proposal.status,
        },
        "result": {
            "result_version": result.result_version, "version_number": result.version_number,
            "parent_result_version": result.parent_result_version, "output_hash": result.output_hash,
            "reviewable_set_hash": result.reviewable_set_hash, "output": loads(result.output_json, {}),
            "created_at": _iso(result.created_at),
        } if result else None,
        "confirmations": [{
            "confirmation_id": row.confirmation_id, "result_version": row.result_version,
            "confirmation_snapshot_hash": row.confirmation_snapshot_hash,
            "confirmer": row.confirmer, "note": row.note, "created_at": _iso(row.created_at),
        } for row in confirmations],
        "publications": [{
            "publication_id": row.publication_id, "confirmation_id": row.confirmation_id,
            "prior_publication_id": row.prior_publication_id, "revision_number": row.revision_number,
            "publication_status": row.publication_status, "conformance": row.conformance,
            "report_hash": row.report_hash,
            "report": loads(row.report_json, {}), "conformance_detail": loads(row.conformance_json, {}),
            "recorder": row.recorder, "created_at": _iso(row.created_at),
        } for row in publications],
        "applicability": applicability,
        "allowed_operations": allowed_operations,
        "boundary": {
            "external_llm_calls": 0, "web_refetches": 0, "automatic_publication": False,
            "update_managed_enabled": False, "retest_computation": True,
        },
    }
