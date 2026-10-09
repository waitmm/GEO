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
    SinglePromptCitationContributionResult,
    SinglePromptDiagnosisExecution,
    SinglePromptDiagnosisResult,
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
from app.modules.single_prompt_v2.source_preparation import _content_block_reason, validate_completion_for_evidence
from app.modules.single_prompt_v2.delivery_text import (
    INPUT_VERSION, audit_draft, build_sections, digest, render_draft, text_digest,
)
from .delivery_generation import GENERATION_VERSION, generate_and_check, check_submitted_draft, revalidate_generated_draft
from app.services.serialization import loads


EXECUTION_CONTRACT_VERSION = "single_prompt_execution.optimize_delivery.v2"
EXECUTION_INPUT_VALIDATION_VERSION = "single_prompt_execution_input.v3"
EXECUTION_DELIVERABLE_VERSION = "single_prompt_execution_deliverable.v3"
EXECUTION_DELIVERABLE_IMPLEMENTATION_VERSION = "single_prompt_execution_deliverable.impl.v8_scoped_input"
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
    if is_machine_authority:
        answer_result = db.query(SinglePromptDiagnosisResult).filter_by(
            diagnosis_id=strategy.diagnosis_id, result_version=strategy.diagnosis_result_version,
            output_hash=strategy.diagnosis_result_hash).one_or_none()
        answer_output = loads(answer_result.output_json, {}) if answer_result else {}
        if not answer_result or _hash(answer_output) != strategy.diagnosis_result_hash:
            raise HTTPException(409, '公开事实缺少准确的回答与事实快照版本')
        truths = _machine_public_truths(strategy_input, direction, answer_output)
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
            "answer_result_version": strategy.diagnosis_result_version,
            "answer_result_hash": strategy.diagnosis_result_hash,
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
        "brand_context": copy.deepcopy(strategy_input.get("brand_context") or {}),
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


def _machine_public_truths(qualification: dict, direction: dict, answer_output: dict) -> list[dict]:
    from .diagnosis import _truth_statement_eligibility
    qualified_ids = {str(row['object_id']) for row in qualification.get('object_qualifications') or []
        if row.get('object_type') == 'PRODUCT_TRUTH'
        and (row.get('eligibility_by_use') or {}).get('public_claim') == 'CONSUMABLE'}
    direction_ids = {str(value) for value in direction.get('truth_ids') or []}
    admitted = []
    for truth in (answer_output.get('truth_diagnosis') or {}).get('truth_snapshot') or []:
        if str(truth.get('truth_id')) not in qualified_ids & direction_ids:
            continue
        eligibility = _truth_statement_eligibility(capability_label=truth.get('capability_label') or '',
            product_truth_status=truth.get('product_truth_status') or '', source_reference=truth.get('source_reference') or '')
        if (not str(truth.get('capability_label') or '').strip()
                or truth.get('truth_source') != 'MANUAL_CONFIRMED' or eligibility['status'] != 'ELIGIBLE'):
            raise HTTPException(409, '公开事实资格与精确事实快照不一致')
        admitted.append({'product_truth_id': int(truth['truth_id']),
            'capability_key': truth.get('capability_key'), 'capability_label': truth['capability_label'],
            'product_truth_status': truth['product_truth_status'], 'truth_source': truth['truth_source'],
            'source_reference': truth['source_reference'], 'approved_aliases': [],
            'public_use_eligibility': 'CONSUMABLE', 'truth_snapshot': copy.deepcopy(truth),
            'truth_snapshot_hash': _hash(truth)})
    if {str(row['product_truth_id']) for row in admitted} != qualified_ids & direction_ids:
        raise HTTPException(409, '公开事实资格引用了快照中不存在的对象')
    return admitted


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


def _freeze_delivery_input(
    db: Session, snapshot: dict[str, Any], prior_result: SinglePromptExecutionProposalResult | None = None,
) -> dict[str, Any]:
    """Load exact immutable records once; the text compiler receives no Session."""
    dependencies = [row for row in snapshot["direction"].get("dependencies", [])
        if row.get("object_type") == "CITATION_CONTRIBUTION_SCOPE"]
    if len(dependencies) > 1:
        parts = []
        for dependency in dependencies:
            contribution = db.query(SinglePromptCitationContributionResult).filter_by(result_version=dependency["object_id"]).one_or_none()
            if not contribution:
                raise HTTPException(409, "稿件指定的引用贡献版本不存在")
            binding_ids = {b["binding_id"] for b in loads(contribution.output_json, {}).get("bindings") or []}
            part = copy.deepcopy(snapshot)
            part["direction"]["dependencies"] = [dependency]
            part["automatic_draft"]["content_blocks"] = [b for b in part["automatic_draft"].get("content_blocks", [])
                if b.get("binding_id") in binding_ids]
            parts.append(_freeze_delivery_input(db, part))
        combined = copy.deepcopy(parts[0])
        refs = [{"result_version": p["contribution_result_version"], "result_hash": p["contribution_result_hash"]} for p in parts]
        combined.update(contribution_result_version="contribution-set:" + _hash(refs)[:20],
            contribution_result_hash=_hash(refs), contribution_results=refs,
            source_manifests=[p["source_manifest"] for p in parts],
            selected_evidence=[s for p in parts for s in p["selected_evidence"]],
            historical_failures=[s for p in parts for s in p["historical_failures"]],
            strategy_direction=copy.deepcopy(snapshot["direction"]))
        return combined
    identity = snapshot["identity"]
    context = db.query(SinglePromptAnalysisContext).filter_by(
        context_id=identity["context_id"], analysis_id=identity["analysis_id"],
        project_id=identity["project_id"], prompt_id=identity["prompt_id"],
    ).one_or_none()
    if not context:
        raise HTTPException(409, detail="稿件缺少准确 Context")
    raw = loads(context.raw_output_json, {})
    if _hash(raw) != context.raw_output_hash or context.raw_output_hash != snapshot["baseline"]["raw_output_hash"]:
        raise HTTPException(409, detail="稿件原始输入 hash 不匹配")
    version = next((row["object_id"] for row in snapshot["direction"].get("dependencies", [])
                    if row.get("object_type") == "CITATION_CONTRIBUTION_SCOPE"), None)
    result = db.query(SinglePromptCitationContributionResult).filter_by(result_version=version).one_or_none()
    if not result:
        if version not in {None, "UNAVAILABLE"}:
            raise HTTPException(409, detail="稿件指定的引用贡献版本不存在")
        return _freeze_question_delivery(db, snapshot, context, raw)
    contribution = loads(result.output_json, {})
    if _hash(contribution) != result.output_hash:
        raise HTTPException(409, detail="引用贡献内容 hash 不匹配")
    inputs = contribution["input"]
    if any(inputs[key] != identity[key] for key in ("analysis_id", "context_id")) or inputs["raw_output_hash"] != context.raw_output_hash:
        raise HTTPException(409, detail="引用贡献与稿件范围不一致")
    answer = db.query(SinglePromptDiagnosisResult).filter_by(
        diagnosis_id=identity["diagnosis_id"], result_version=inputs["answer_result_version"],
    ).one_or_none()
    if not answer or answer.output_hash != inputs["answer_result_hash"] or _hash(loads(answer.output_json, {})) != answer.output_hash:
        raise HTTPException(409, detail="Answer 版本或内容 hash 不匹配")
    if answer.result_version != identity["answer_result_version"] or answer.output_hash != identity["answer_result_hash"]:
        raise HTTPException(409, detail="引用贡献不能替换策略所用的 Answer 版本")
    strategy = db.query(SinglePromptStrategyResult).filter_by(
        strategy_id=identity["strategy_id"], result_version=identity["strategy_result_version"],
    ).one_or_none()
    if not strategy or strategy.output_hash != identity["strategy_result_hash"] or _hash(loads(strategy.output_json, {})) != strategy.output_hash:
        raise HTTPException(409, detail="Strategy 版本或内容 hash 不匹配")
    _, sources, _ = validate_completion_for_evidence(
        db, allow_partial=inputs.get("input_authority") == "MACHINE_ADMISSION", **{key: inputs[key] for key in (
            "analysis_id", "context_id", "citation_manifest_id", "citation_manifest_hash",
            "completion_manifest_id", "completion_manifest_hash",
        )},
    )
    source_map = {row.snapshot_id: row for row in sources}
    units = {row["answer_unit_id"]: row for row in contribution["answer_units"]}
    bindings = {row["binding_id"]: row for row in contribution["bindings"]}
    citations = {row["citation_id"]: row for row in contribution["citations"]}
    answers = {int(row["run_id"]): row["answer_text"] for row in raw["runs"]}
    if sorted(inputs["fixed_run_ids"]) != sorted(answers):
        raise HTTPException(409, detail="引用贡献的完整 Run 范围与稿件不一致")
    selected = []
    for block in snapshot["automatic_draft"].get("content_blocks", []):
        if block.get("content_role") == "GROUNDING_REQUIRED_BRIEF" and not block.get("binding_id"):
            continue
        binding = bindings.get(block.get("binding_id"))
        if not binding or binding["processing_status"] != "DONE" or binding["evidence_relation"] not in {"SUPPORTS_FULL", "SUPPORTS_PARTIAL"}:
            raise HTTPException(409, detail="稿件依据不是合格的精确关系")
        if block.get("citation_id") != binding["citation_id"] or block.get("answer_unit_id") != binding["answer_unit_id"]:
            raise HTTPException(409, detail="内容块关系身份不匹配")
        citation = citations[binding["citation_id"]]
        source = source_map.get(binding["snapshot_id"])
        unit = units[binding["answer_unit_id"]]
        answer_text = answers.get(int(binding["run_id"]), "")
        if (not source or source.snapshot_id != citation["snapshot_id"]
                or citation["processing_status"] != "DONE"
                or source.content_hash != citation["snapshot_content_hash"]
                or source.passages_hash != citation["snapshot_passages_hash"]
                or unit["run_id"] != binding["run_id"]
                or answer_text[unit["raw_start"]:unit["raw_end"]] != unit["raw_text"]):
            raise HTTPException(409, detail="稿件回答或来源范围不匹配")
        passage = next((p for p in loads(source.passages_json, []) if p["passage_id"] == binding["passage_id"]), None)
        if not passage or binding["source_span"] not in passage["text"] or passage["text"] not in source.clean_text:
            raise HTTPException(409, detail="稿件来源片段不在固定正文中")
        if _content_block_reason(source.title, source.clean_text):
            raise HTTPException(409, detail="稿件来源被当前正文安全规则阻断")
        selected.append({
            "section_id": block["block_id"], "proposed_text": block["draft_text"],
            "binding_id": binding["binding_id"], "citation_id": binding["citation_id"],
            "answer_unit_id": unit["answer_unit_id"], "answer_unit": copy.deepcopy(unit),
            "snapshot_id": source.snapshot_id, "title": source.title, "url": source.canonical_url,
            "source_content_hash": source.content_hash, "source_artifact_hash": source.artifact_hash,
            "source_artifact_path": source.artifact_path, "source_passages_hash": source.passages_hash,
            "passage_id": passage["passage_id"], "passage_text": passage["text"],
            "passage_hash": text_digest(passage["text"]), "source_span": binding["source_span"],
            "evidence_relation": binding["evidence_relation"], "answer_anchor": binding["answer_anchor"],
            "generation_influence": binding["generation_influence"],
        })
    brand = copy.deepcopy(snapshot["brand_snapshot"])
    if _hash(brand) != snapshot["brand_snapshot_hash"]:
        raise HTTPException(409, detail="冻结品牌输入 hash 不匹配")
    # Domain matches are observations, not ownership or editing permissions.
    asset_observations = []
    configured_host = urlparse(str(brand.get('website_url') or '')).hostname
    for source in source_map.values():
        source_host = urlparse(source.canonical_url).hostname
        if configured_host and source_host and (source_host == configured_host or source_host.endswith('.' + configured_host)):
            asset_observations.append({'candidate_id': f'observed:{source.snapshot_id}',
                'url': source.canonical_url, 'title': source.title, 'snapshot_id': source.snapshot_id,
                'content_hash': source.content_hash, 'can_authorize_update': False,
                'editable_permission': 'UNVERIFIED', 'brand_ownership': 'CONFIGURED_DOMAIN_OBSERVATION'})
    if prior_result:
        prior = loads(prior_result.output_json, {})
        if _hash(prior) != prior_result.output_hash:
            raise HTTPException(409, detail="上一稿件内容 hash 不匹配")
        for candidate in (prior.get("asset_resolution") or {}).get("existing_asset_checks", []):
            source = source_map.get(candidate.get("snapshot_id"))
            if not source or source.content_hash != candidate.get("content_hash") or source.canonical_url != candidate.get("url"):
                raise HTTPException(409, detail="已有页面观察与冻结来源不匹配")
            asset_observations = [item for item in asset_observations if item['snapshot_id'] != source.snapshot_id]
            asset_observations.append({
                **copy.deepcopy(candidate), "provenance_result_version": prior_result.result_version,
                "provenance_result_hash": prior_result.output_hash,
                "can_authorize_update": False, "editable_permission": "UNVERIFIED",
                "brand_ownership": "PRIOR_RESULT_OBSERVATION_NOT_VERIFIED",
            })
            terms = {raw["prompt_text"][i:i + 2] for i in range(len(raw["prompt_text"]) - 1)}
            passages = loads(source.passages_json, [])
            ranked = sorted(passages, key=lambda p: (-sum(term in p["text"] for term in terms), p["passage_id"]))
            if ranked and any(term in ranked[0]["text"] for term in terms) and not _content_block_reason(source.title, source.clean_text):
                passage = ranked[0]
                if passage["text"] not in source.clean_text:
                    raise HTTPException(409, detail="品牌页面片段不在固定正文中")
                selected.append({
                    "section_id": f"brand-page:{source.snapshot_id}", "proposed_text": "",
                    "binding_id": None, "citation_id": next(row["citation_id"] for row in contribution["citations"] if row.get("snapshot_id") == source.snapshot_id),
                    "answer_unit_id": None, "snapshot_id": source.snapshot_id,
                    "title": source.title, "url": source.canonical_url,
                    "source_content_hash": source.content_hash, "source_artifact_hash": source.artifact_hash,
                    "source_artifact_path": source.artifact_path, "source_passages_hash": source.passages_hash,
                    "passage_id": passage["passage_id"], "passage_text": passage["text"],
                    "passage_hash": text_digest(passage["text"]), "evidence_relation": None,
                    "material_use": "ATTRIBUTED_BRAND_PAGE_OBSERVATION_NOT_TRUTH",
                    "provenance_result_version": prior_result.result_version,
                })
    events = loads(answer.output_json, {}).get("answer_diagnosis", {}).get("events", [])
    return {
        "contract_version": INPUT_VERSION, "identity": copy.deepcopy(identity),
        "brand": brand, "brand_hash": snapshot["brand_snapshot_hash"],
        "prompt_text": raw["prompt_text"], "prompt_hash": text_digest(raw["prompt_text"]),
        "prompt_configuration": copy.deepcopy((raw.get("sampling_plan") or {}).get("prompt_configuration") or {}),
        "raw_result_version": context.result_version, "raw_output_hash": context.raw_output_hash,
        "answers": [{"run_id": key, "text": text, "text_hash": text_digest(text)} for key, text in answers.items()],
        "answer_result_version": answer.result_version, "answer_result_hash": answer.output_hash,
        "answer_events": copy.deepcopy(events),
        "contribution_result_version": result.result_version, "contribution_result_hash": result.output_hash,
        "source_manifest": {key: inputs[key] for key in (
            "citation_manifest_id", "citation_manifest_hash", "completion_manifest_id", "completion_manifest_hash")},
        "selected_evidence": selected, "asset_observations": asset_observations,
        "subjects": sorted({brand["brand_name"], *(str(row.get("entity_text") or "") for row in events)} - {""}),
        "strategy_direction": copy.deepcopy(snapshot["direction"]),
        "truths": copy.deepcopy(snapshot.get("truths") or []),
        "historical_failures": _evidence_failure_audit(contribution),
        "question_topics": _question_topics(raw, snapshot["direction"].get("reason_run_ids") or []),
    }


def _question_topics(raw: dict, run_ids: list[int]) -> list[dict]:
    from .citation_contribution import build_answer_units
    topics, seen = [], set()
    for run in raw.get("runs") or []:
        if run.get("run_id") not in run_ids:
            continue
        for unit in build_answer_units(run["answer_text"], run["run_id"], []):
            text = unit["raw_text"]
            if text in seen or unit["primary_type"] == "HEADING":
                continue
            seen.add(text)
            topics.append(unit)
            if len(topics) == 8:
                return topics
    return topics


def _freeze_question_delivery(db: Session, snapshot: dict, context: SinglePromptAnalysisContext, raw: dict) -> dict:
    """A scoped research guide is not a substitute for unperformed evidence assessment."""
    from .coverage import compute_coverage
    identity = snapshot["identity"]
    answer = db.query(SinglePromptDiagnosisResult).filter_by(diagnosis_id=identity["diagnosis_id"],
        result_version=identity["answer_result_version"]).one_or_none()
    strategy = db.query(SinglePromptStrategyResult).filter_by(strategy_id=identity["strategy_id"],
        result_version=identity["strategy_result_version"]).one_or_none()
    if (not answer or answer.output_hash != identity["answer_result_hash"]
            or _hash(loads(answer.output_json, {})) != answer.output_hash
            or not strategy or strategy.output_hash != identity["strategy_result_hash"]
            or _hash(loads(strategy.output_json, {})) != strategy.output_hash):
        raise HTTPException(409, detail="问题解读稿的 Answer/Strategy 精确版本或 hash 不匹配")
    coverage = compute_coverage(raw, loads(answer.output_json, {}).get("answer_diagnosis") or {})
    run_ids = snapshot["direction"].get("reason_run_ids") or []
    if not run_ids or not set(run_ids).issubset(coverage["valid_compute_run_ids"]):
        raise HTTPException(409, detail="问题解读稿缺少已通过准入的回答范围")
    brand = copy.deepcopy(snapshot["brand_snapshot"])
    if _hash(brand) != snapshot["brand_snapshot_hash"]:
        raise HTTPException(409, detail="冻结品牌输入 hash 不匹配")
    topics = _question_topics(raw, run_ids)
    if not topics:
        raise HTTPException(409, detail="没有可定位的问题解读素材，不能创建空稿件")
    return {
        "contract_version": INPUT_VERSION, "identity": copy.deepcopy(identity),
        "brand": brand, "brand_hash": snapshot["brand_snapshot_hash"],
        "prompt_text": raw["prompt_text"], "prompt_hash": text_digest(raw["prompt_text"]),
        "prompt_configuration": copy.deepcopy((raw.get("sampling_plan") or {}).get("prompt_configuration") or {}),
        "raw_result_version": context.result_version, "raw_output_hash": context.raw_output_hash,
        "answers": [{"run_id": row["run_id"], "text": row["answer_text"], "text_hash": text_digest(row["answer_text"])}
                    for row in raw["runs"] if row["run_id"] in run_ids],
        "answer_result_version": answer.result_version, "answer_result_hash": answer.output_hash,
        "answer_events": [], "contribution_result_version": None, "contribution_result_hash": None,
        "source_manifest": {}, "selected_evidence": [], "asset_observations": [], "subjects": [brand["brand_name"]],
        "strategy_direction": copy.deepcopy(snapshot["direction"]),
        "truths": copy.deepcopy(snapshot.get("truths") or []), "historical_failures": [],
        "question_topics": topics, "content_mode": "RESEARCH_GUIDE_NOT_FACTUAL_ANSWER",
        "limitations": ["CITATION_NOT_CONSUMED", "ANSWER_TOPICS_ARE_NOT_VERIFIED_FACTS"],
    }


def _evidence_failure_audit(contribution: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    for row in contribution.get("citations") or []:
        if row.get("processing_status") != "FAILED":
            continue
        code = str(row.get("failure_code") or "ANALYSIS_FAILED")
        results.append({
            "citation_id": row.get("citation_id"),
            "source_snapshot_id": row.get("snapshot_id"),
            "source_url": row.get("canonical_url"),
            "current_state": "CURRENT_NOT_CONSUMABLE",
            "processing_status": "FAILED",
            "failure_code": code,
            "failure_detail": row.get("failure_detail"),
            "disposition": "NOT_EVALUATED_CURRENT_CONTRACT",
            "used_in_deliverable": False,
            "scope_impact": "NON_BLOCKING_FOR_SELECTED_DELIVERABLE",
            "next_action": "RE_EVALUATE_ONLY_IF_A_FUTURE_DELIVERABLE_REQUIRES_THIS_CITATION",
        })
    return results


def _compile_machine_delivery(proposal_id: str, input_snapshot: dict[str, Any]) -> dict[str, Any]:
    frozen = input_snapshot["delivery_input"]
    if frozen["contract_version"] != INPUT_VERSION or digest(frozen) != input_snapshot["delivery_input_hash"]:
        raise HTTPException(409, detail="稿件冻结输入版本或 hash 不匹配")
    direction = input_snapshot["direction"]
    brand_name = frozen["brand"]["brand_name"]
    prompt_text = frozen["prompt_text"]
    sections, findings, repairs = build_sections(frozen)
    draft = render_draft(frozen, sections)
    qa = audit_draft(frozen, draft, findings=findings, repairs=repairs)
    failures = frozen["historical_failures"]
    contribution_version = frozen["contribution_result_version"]
    asset_types, surfaces = _asset_options(direction)
    intent = (frozen.get('prompt_configuration') or {}).get('intent_type')
    public_truths = [row for row in frozen.get('truths') or [] if row.get('public_use_eligibility') == 'CONSUMABLE']
    preferred = 'FEATURE_PAGE' if public_truths and intent == 'supplier_recommendation' else 'HELP_DOC'
    recommended_asset_type = preferred if any(row['asset_type'] == preferred for row in asset_types) else (asset_types[0]['asset_type'] if asset_types else None)
    content_purpose = ('已确认能力的适用条件与选择依据' if preferred == 'FEATURE_PAGE' else
        '操作前提、步骤与异常处理' if intent == 'usage_instruction' else
        '概念解释与适用边界' if intent == 'category_awareness' else '选择标准与核对方法')
    recommended_surface = next((row["surface_key"] for row in surfaces if row["asset_type"] == recommended_asset_type), None)
    existing_asset_checks = copy.deepcopy(frozen["asset_observations"])
    output = {
        "contract_version": EXECUTION_CONTRACT_VERSION,
        "deliverable_contract_version": EXECUTION_DELIVERABLE_VERSION,
        "deliverable_implementation_version": EXECUTION_DELIVERABLE_IMPLEMENTATION_VERSION,
        "proposal_id": proposal_id,
        "input_identity": copy.deepcopy(input_snapshot["identity"]),
        "delivery_input": copy.deepcopy(frozen),
        "delivery_input_hash": digest(frozen),
        "direction": copy.deepcopy(direction),
        "strategy_channel": {
            "channel_key": direction.get("channel_key"),
            "channel_label": direction.get("channel_label"),
            "channel_role": direction.get("channel_role"),
            "immutable": True,
        },
        "asset_operation": "CONDITIONAL",
        "asset_resolution": {
            "resolver_contract": "SC-ASSET-001@1.0.0",
            "resolver_reuse": {
                "legacy_resolver": "execution_proposal_shadow.resolve_asset_operation",
                "status": "NOT_CALLED_FOR_INCOMPLETE_INVENTORY",
                "reason": "旧入口把空 ManagedAsset 列表直接解释为 CREATE_NEW；当前冻结契约要求先返回 UNKNOWN/条件方案。",
            },
            "inventory_state": "UNKNOWN",
            "existing_asset_checks": existing_asset_checks,
            "recommended_asset_type": recommended_asset_type,
            "selection_reason": f'当前问题“{prompt_text}”需要{content_purpose}；选择对应内容形式，不依据单次引用推定渠道效果。',
            "recommended_operation": "VERIFY_EXISTING_THEN_UPDATE_OR_CREATE",
            "conditions": [
                {"when": "候选页面经用户确认归属、编辑权限和内容适配均成立", "operation": "UPDATE_EXISTING", "target_candidate_id": existing_asset_checks[0]["candidate_id"] if existing_asset_checks else None},
                {"when": "完整核查后没有适配的可编辑页面", "operation": "CREATE_NEW", "asset_type": recommended_asset_type},
            ],
            "reason": "缺少 ManagedAsset 记录不等于资产不存在；先核查已观察的一方页面，再决定更新或新建。",
        },
        "channel_resolution": {
            "publication_channel_key": direction.get("channel_key") or "OWNED_SURFACE_UNRESOLVED",
            "publication_channel_label": direction.get("channel_label") or f"{brand_name}自有帮助/资讯入口（待确认）",
            "recommended_surface": recommended_surface,
            "known_website": str(frozen['brand'].get('website_url') or ''),
            "reason": (
                f"冻结资料中已有页面：{existing_asset_checks[0]['url']}。"
                f"本次内容重点是{content_purpose}；可核查该页是否适合承接，不能证明用户拥有编辑权限。"
                "这是内容承载的条件建议，不是引用效果排名，也不声称官网优于第三方渠道。"
                if existing_asset_checks else
                f"本稿针对{content_purpose}，优先考虑能维护完整说明和出处的内容位置。固定输入没有可核对的已有承载页，位置建议有条件，不推定官网最佳或用户拥有编辑权限。"
            ),
            "strategy_channel_role_changed": False,
            "upstream_channel_resolver_reused": False,
            "selection_basis": "FROZEN_STRATEGY_AND_CONTENT_PURPOSE",
            "upstream_strategy_channel": {
                "channel_key": direction.get("channel_key"),
                "channel_role": direction.get("channel_role"),
            },
        },
        "asset_type_candidates": asset_types,
        "publication_surface_candidates": surfaces,
        "package_candidates": [{"package_key": "COMPLETE_HELP_ARTICLE", "label": "完整问题解答稿", "direction_id": direction["direction_id"], "truth_ids": []}],
        "title_candidates": [{"title_id": "COMPLETE_GROUNDED_TITLE", "title": draft["title"], "truth_ids": []}],
        "public_content_candidates": draft["sections"],
        "selected_public_content": draft["sections"],
        "publication_draft": draft,
        "brand_association": {
            "brand_name": brand_name,
            "observed_fact": "固定回答正文包含目标品牌名称；名称出现不等于推荐。" if any(brand_name in row["text"] for row in frozen["answers"]) else "固定回答正文未出现目标品牌名称；不代表品牌不具备能力。",
            "action_hypothesis": f"由{brand_name}发布针对“{prompt_text}”的完整问题解答，建立品牌、场景和可核验一方资料之间的关联。",
            "validation_condition": "发布后使用新的真实 Run 观察品牌提及、推荐和准确 URL 引用；结果只作描述性比较。",
            "first_party_source": None,
            "brand_snapshot_hash": frozen["brand_hash"],
            "asset_observations": existing_asset_checks,
            "claim_boundary": "一方页面表述不等于独立验证，也不证明 AI 会采用该来源。",
        },
        "evidence_processing_audit": {
            "contribution_result_version": contribution_version,
            "selected_binding_ids": [value for row in sections for value in row.get("binding_ids") or []],
            "historical_failures": failures,
            "completed_count_excludes_failures": True,
        },
        "internal_checklist": [
            *[{"code": "SUPPLEMENTAL_CONTEXT_NOT_VERIFIED", "detail": p["text"],
               "context_version_id": (frozen.get("brand_context") or {}).get("context_version_id"),
               "source_reference": p["source_reference"], "public_claim_eligible": False}
              for p in (frozen.get("brand_context") or {}).get("passages", [])],
            {"code": "VERIFY_EXISTING_ASSET", "detail": "确认已观察的一方页面是否为当前可编辑资产，以及更适合追加模块还是另建帮助文章。"},
            {"code": "VERIFY_PUBLICATION_AUTHORITY", "detail": "确认实际账号、栏目和页面编辑权限；系统不会把已知域名等同于账号控制。"},
            {"code": "VERIFY_CURRENT_PLATFORM_RULES", "detail": "发布前核对所选平台当前规则和账号权限。"},
            {"code": "PRESERVE_EFFECT_LIMIT", "detail": "该动作是探索假设，不承诺发布后一定被引用、推荐或带来效果。"},
        ],
        "claim_usage_policy": [],
        "selection": {
            "asset_operation": "CONDITIONAL",
            "asset_type": recommended_asset_type,
            "package_key": "COMPLETE_HELP_ARTICLE",
            "publication_surface": recommended_surface,
            "publishing_account": "",
            "publishing_location": "帮助中心或资讯中心；优先核查现有相关页面",
            "account_control_status": "UNVERIFIED",
            "title": draft["title"],
            "section_order": [row["section_id"] for row in draft["sections"]],
            "execution_note": "系统已完成内容交付；发布前只需确认现有资产、实际栏目和操作权限。",
        },
        "baseline": copy.deepcopy(input_snapshot["baseline"]),
        "limitations": [*copy.deepcopy(input_snapshot.get("limitations") or []), *failures],
        "advisories": copy.deepcopy(input_snapshot.get("advisories") or []),
        "automatic_qa": qa,
        "repair_history": copy.deepcopy(qa["repairs"]),
        "validation": {},
        "boundary": copy.deepcopy(input_snapshot["boundary"]),
    }
    output["validation"] = validate_execution_output(output, input_snapshot)
    return output


def _compile_output(proposal_id: str, input_snapshot: dict[str, Any]) -> dict[str, Any]:
    if input_snapshot.get("automatic_draft"):
        return _compile_machine_delivery(proposal_id, input_snapshot)
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


def _generated_sections(receipt: dict) -> list[dict]:
    sections = []
    current = None
    for segment in receipt["segments"]:
        if segment["kind"] == "HEADING":
            current = {"section_id": segment["segment_id"], "title": segment["text"],
                "content_class": "PUBLIC_CONTENT", "purpose": "QUESTION_RESPONSE",
                "draft_text": "", "evidence_ids": [], "truth_ids": []}
            sections.append(current)
        elif segment["text"] and current is not None:
            current["draft_text"] += ("\n\n" if current["draft_text"] else "") + segment["text"]
            current["evidence_ids"] = sorted(set(current["evidence_ids"] + segment["evidence_ids"]))
    return [row for row in sections if row["draft_text"]]


def _generated_qa(output: dict, frozen: dict) -> dict:
    receipt = output["generation_receipt"]
    qa = revalidate_generated_draft(frozen, receipt)
    draft = output["publication_draft"]
    sections = _generated_sections(receipt)
    if (draft.get("body_markdown") != receipt["body_markdown"] or draft.get("content_hash") != receipt["content_hash"]
            or draft.get("title") != receipt["title"] or draft.get("sections") != sections
            or output.get("selected_public_content") != sections or output.get("public_content_candidates") != sections
            or output["selection"].get("title") != receipt["title"]
            or output["selection"].get("section_order") != [row["section_id"] for row in sections]
            or output.get("automatic_qa") != qa):
        raise ValueError("GENERATED_DELIVERY_PROJECTION_MUTATED")
    return qa


def _attach_generated_delivery(output: dict, receipt: dict, snapshot: dict) -> dict:
    revalidate_generated_draft(output["delivery_input"], receipt)
    output = copy.deepcopy(output)
    output["generation_receipt"] = copy.deepcopy(receipt)
    sections = _generated_sections(receipt)
    output["publication_draft"] = {"deliverable_type": "GROUNDED_GENERATED_ARTICLE", "title": receipt["title"],
        "body_markdown": receipt["body_markdown"], "content_hash": receipt["content_hash"], "sections": sections}
    output["public_content_candidates"] = sections
    output["selected_public_content"] = copy.deepcopy(sections)
    output["title_candidates"] = [{"title_id": "GENERATED_TITLE", "title": receipt["title"], "truth_ids": []}]
    output["selection"].update(title=receipt["title"], section_order=[row["section_id"] for row in sections])
    output["automatic_qa"] = copy.deepcopy(receipt["qa"])
    output["repair_history"] = copy.deepcopy(receipt["qa"]["repairs"])
    output["validation"] = validate_execution_output(output, snapshot)
    return output


def validate_execution_output(output: dict[str, Any], input_snapshot: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    qa = output.get("automatic_qa") or {}
    selection = output.get("selection") or {}
    direction = input_snapshot["direction"]
    complete_delivery = output.get("deliverable_contract_version") == EXECUTION_DELIVERABLE_VERSION
    if complete_delivery:
        if output.get("asset_operation") != selection.get("asset_operation"):
            errors.append("ASSET_OPERATION_SELECTION_MISMATCH")
        if selection.get("asset_operation") == "CONDITIONAL":
            errors.append("FINAL_ASSET_OPERATION_REQUIRED")
        elif selection.get("asset_operation") != "CREATE_NEW":
            errors.append("MANAGED_ASSET_REQUIRED_FOR_UPDATE")
    elif output.get("asset_operation") != "CREATE_NEW" or selection.get("asset_operation") != "CREATE_NEW":
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
        if complete_delivery:
            frozen = output.get("delivery_input") or {}
            if (
                frozen.get("contract_version") != INPUT_VERSION
                or digest(frozen) != output.get("delivery_input_hash")
                or frozen.get("identity") != input_snapshot.get("identity")
            ):
                errors.append("DELIVERY_INPUT_MISMATCH")
            else:
                if output.get("generation_receipt"):
                    try:
                        qa = _generated_qa(output, frozen)
                    except (ValueError, KeyError, TypeError):
                        qa = {"status": "NEEDS_REPAIR"}
                else:
                    qa = audit_draft(frozen, output.get("publication_draft") or {})
                if (output.get("publication_draft") or {}).get("sections") != output.get("selected_public_content"):
                    errors.append("PUBLIC_TEXT_SELECTION_MISMATCH")
        accepted_qa_statuses = {"READY", "READY_INTERNAL"} if complete_delivery else {"READY_INTERNAL"}
        if qa.get("status") not in accepted_qa_statuses:
            errors.append("AUTOMATIC_QA_NOT_READY")
    else:
        truths = input_snapshot.get("truths") or []
        errors.extend(_title_validation(
            str(selection.get("title") or ""),
            str((input_snapshot.get("brand_snapshot") or {}).get("brand_name") or "目标品牌"),
            truths,
        ))
    baseline = output.get("baseline") or {}
    if baseline != input_snapshot.get("baseline"):
        errors.append("BASELINE_MUTATION")
    if baseline.get("baseline_run_ids") != (baseline.get("run_manifest") or {}).get("valid_run_ids"):
        errors.append("BASELINE_NOT_COMPLETE_VALID_RUN_SET")
    if not machine_authority and set(direction.get("truth_ids") or []) != {
        row["product_truth_id"] for row in (input_snapshot.get("truths") or [])
    }:
        errors.append("PARTIAL_OR_UNCONFIRMED_TRUTH_IN_PUBLIC_SCOPE")
    only_business_inputs = set(errors).issubset({
        "FINAL_ASSET_OPERATION_REQUIRED", "PUBLISHING_ACCOUNT_REQUIRED",
        "PUBLISHING_LOCATION_REQUIRED", "PUBLICATION_AUTHORITY_NOT_CONFIRMED",
    })
    return {
        "status": (
            "READY_FOR_CONFIRMATION" if not errors
            else "READY_FOR_BUSINESS_INPUT" if complete_delivery and only_business_inputs
            else "NEEDS_HUMAN_SELECTION"
        ),
        "content_delivery_status": "READY" if complete_delivery and qa.get("status") == "READY" and "DELIVERY_INPUT_MISMATCH" not in errors else "INCOMPLETE",
        "publication_status": "READY" if not errors else "NEEDS_BUSINESS_CONFIRMATION",
        "errors": errors,
        "validators": {
            "strategy_channel_immutable": "PASS" if "STRATEGY_CHANNEL_MUTATION" not in errors else "FAIL",
            "asset_operation_selected": "PASS" if not {
                "ASSET_OPERATION_SELECTION_REQUIRED", "ASSET_OPERATION_SELECTION_MISMATCH",
                "FINAL_ASSET_OPERATION_REQUIRED", "MANAGED_ASSET_REQUIRED_FOR_UPDATE",
            } & set(errors) else "FAIL",
            "truth_grounding": "PASS" if "PARTIAL_OR_UNCONFIRMED_TRUTH_IN_PUBLIC_SCOPE" not in errors else "FAIL",
            "baseline_exact": "PASS" if not {"BASELINE_MUTATION", "BASELINE_NOT_COMPLETE_VALID_RUN_SET"} & set(errors) else "FAIL",
            "public_internal_separation": "PASS" if "INTERNAL_ITEM_IN_PUBLIC_CONTENT" not in errors else "FAIL",
            "actual_text_qa": "PASS" if "AUTOMATIC_QA_NOT_READY" not in errors else "FAIL",
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
    brand_context_version_id: str | None = None,
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
    if snapshot.get("automatic_draft"):
        snapshot["delivery_input"] = _freeze_delivery_input(db, snapshot)
        from .context_provider import select_context
        frozen_context = snapshot.get("brand_context") or {}
        if frozen_context.get("context_version_id") != brand_context_version_id:
            raise HTTPException(409, detail="稿件品牌资料必须与策略选定版本一致；更换资料请先形成新策略版本")
        snapshot["delivery_input"]["brand_context"] = select_context(
            db, project_id=project_id, context_version_id=brand_context_version_id,
            query=snapshot["delivery_input"]["prompt_text"],
        )
        snapshot["delivery_input_hash"] = digest(snapshot["delivery_input"])
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
    output = copy.deepcopy(loads(base.output_json, {}))
    requested_operation = str(edit.get("asset_operation") or output.get("asset_operation") or "")
    complete_delivery = output.get("deliverable_contract_version") == EXECUTION_DELIVERABLE_VERSION
    allowed_operations = {"CONDITIONAL", "CREATE_NEW"} if complete_delivery else {"CREATE_NEW"}
    if requested_operation == "UPDATE_EXISTING":
        raise HTTPException(status_code=422, detail="更新已有资产前必须先确认候选资产的归属、精确版本和编辑权限")
    if requested_operation not in allowed_operations:
        raise HTTPException(status_code=422, detail="当前资产操作不符合本方案的资产盘点边界")
    selection = output["selection"]
    editable = {
        "asset_type", "package_key", "publication_surface", "publishing_account", "publishing_location",
        "account_control_status", "title", "section_order", "execution_note", "asset_operation",
    }
    unknown = set(edit) - editable
    if unknown:
        raise HTTPException(status_code=422, detail=f"包含不可编辑字段：{', '.join(sorted(unknown))}")
    selection.update(copy.deepcopy(edit))
    selection["asset_operation"] = requested_operation
    output["asset_operation"] = requested_operation
    sections = {row["section_id"]: row for row in output["public_content_candidates"]}
    output["selected_public_content"] = [sections[value] for value in selection.get("section_order") or [] if value in sections]
    snapshot = loads(proposal.input_snapshot_json, {})
    if complete_delivery and output.get("generation_receipt"):
        if selection.get("title") != output["publication_draft"]["title"] or selection.get("section_order") != [
            row["section_id"] for row in output["publication_draft"]["sections"]
        ]:
            raise HTTPException(422, "已检查的生成稿不能未经文本复检修改标题或章节；业务信息可独立保存")
        _generated_qa(output, output["delivery_input"])
        output["repair_history"] = []
    elif complete_delivery:
        frozen = output["delivery_input"]
        output["publication_draft"] = render_draft(frozen, output["selected_public_content"], title=selection.get("title"))
        output["automatic_qa"] = audit_draft(frozen, output["publication_draft"])
        # The parent result keeps its repair evidence; this edit did not apply it again.
        output["repair_history"] = []
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


def generate_complete_execution_deliverable(
    db: Session,
    *,
    proposal_id: str,
    base_result_version: str,
    base_result_hash: str,
    reviewable_set_hash: str,
    generation_client: Any | None = None,
    generation_progress: Any | None = None,
    submitted_draft: dict | None = None,
    revision_identity: dict | None = None,
) -> tuple[SinglePromptExecutionProposalResult, bool]:
    proposal = db.query(SinglePromptExecutionProposal).filter_by(proposal_id=proposal_id).one_or_none()
    if submitted_draft is not None:
        if generation_client is None or not revision_identity or not revision_identity.get("task_id"):
            raise HTTPException(422, "正文修改必须由明确的复检任务执行")
        bound_base = db.query(SinglePromptExecutionProposalResult).filter_by(
            proposal_id=proposal_id, result_version=base_result_version, output_hash=base_result_hash,
            reviewable_set_hash=reviewable_set_hash,
        ).one_or_none()
        if not proposal or not bound_base or digest(loads(bound_base.output_json, {})) != base_result_hash:
            raise HTTPException(409, "正文修改的原稿版本或 hash 不匹配")
        # A worker may stop after committing the result but before saving its task checkpoint.
        for saved in db.query(SinglePromptExecutionProposalResult).filter_by(
            proposal_id=proposal_id, parent_result_version=base_result_version,
        ):
            previous = loads(saved.output_json, {})
            if previous.get("text_revision") == {**revision_identity, "submitted_draft_hash": digest(submitted_draft)}:
                if digest(previous) != saved.output_hash:
                    raise HTTPException(409, "正文复检结果 hash 不匹配")
                _generated_qa(previous, previous["delivery_input"])
                return saved, False
    if not proposal or proposal.active_result_version != base_result_version:
        raise HTTPException(status_code=409, detail="执行方案结果版本已变化，请重新加载")
    if not _proposal_applicability(db, proposal)["is_current_input"]:
        raise HTTPException(status_code=409, detail="执行方案输入已过期，不能生成新的完整交付")
    base = db.query(SinglePromptExecutionProposalResult).filter_by(
        proposal_id=proposal_id, result_version=base_result_version
    ).one_or_none()
    if not base or base.output_hash != base_result_hash or base.reviewable_set_hash != reviewable_set_hash:
        raise HTTPException(status_code=409, detail="执行方案交付目标已变化，请重新加载")
    base_output = loads(base.output_json, {})
    if (
        submitted_draft is None
        and
        base_output.get("deliverable_contract_version") == EXECUTION_DELIVERABLE_VERSION
        and base_output.get("deliverable_implementation_version") == EXECUTION_DELIVERABLE_IMPLEMENTATION_VERSION
        and (generation_client is None or (base_output.get("generation_receipt") or {}).get("contract_version") == GENERATION_VERSION)
    ):
        return base, False
    snapshot = loads(proposal.input_snapshot_json, {})
    if base_output.get("delivery_input"):
        frozen = base_output["delivery_input"]
        if digest(frozen) != base_output.get("delivery_input_hash"):
            raise HTTPException(409, detail="已保存稿件输入 hash 不匹配")
    else:
        frozen = _freeze_delivery_input(db, snapshot, prior_result=base)
    snapshot["delivery_input"] = copy.deepcopy(frozen)
    snapshot["delivery_input_hash"] = digest(frozen)
    output = copy.deepcopy(base_output) if submitted_draft is not None else _compile_machine_delivery(proposal_id, snapshot)
    initial_calls = int(getattr(generation_client, "external_call_count", 0))
    if generation_client is not None:
        receipt = (check_submitted_draft(frozen, submitted_draft, client=generation_client, db=db, on_stage=generation_progress)
            if submitted_draft is not None else generate_and_check(frozen, client=generation_client, db=db, on_stage=generation_progress))
        output = _attach_generated_delivery(output, receipt, snapshot)
    if submitted_draft is not None:
        output["text_revision"] = {**revision_identity, "submitted_draft_hash": digest(submitted_draft)}
    output["system_revision"] = {
        "reason": "USER_TEXT_REVISION_AND_NEW_QA" if submitted_draft is not None else "FROZEN_INPUT_GROUNDED_DELIVERY_AND_TEXT_QA",
        "base_result_version": base_result_version,
        "external_calls": max(0, int(getattr(generation_client, "external_call_count", 0)) - initial_calls),
        "source_refetches": 0,
    }
    output_hash = _hash(output)
    version_number = base.version_number + 1
    result = SinglePromptExecutionProposalResult(
        result_version=f"execution-v{version_number}:{output_hash[:16]}",
        proposal_id=proposal_id,
        version_number=version_number,
        parent_result_version=base_result_version,
        output_json=_canonical_json(output),
        output_hash=output_hash,
        reviewable_set_hash=_hash({
            "input_snapshot_hash": proposal.input_snapshot_hash,
            "deliverable_contract_version": EXECUTION_DELIVERABLE_VERSION,
            "content_hash": (output.get("publication_draft") or {}).get("content_hash"),
            "selection": output.get("selection") or {},
            "evidence_processing_audit": output.get("evidence_processing_audit") or {},
        }),
        limitations_json=_canonical_json(output.get("limitations") or []),
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
    return result, True


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
    output = loads(result.output_json, {}) if result else {}
    needs_upgrade = bool(
        proposal.input_authority_type == "MACHINE_QUALIFICATION"
        and output.get("deliverable_contract_version") != EXECUTION_DELIVERABLE_VERSION
    )
    if applicability["is_current_input"]:
        allowed_operations.append("GENERATE_DELIVERABLE" if needs_upgrade else "REVISE")
        current_validation = validate_execution_output(output, loads(proposal.input_snapshot_json, {})) if result and not needs_upgrade else {}
        if current_validation.get("status") == "READY_FOR_CONFIRMATION" and not active_confirmation:
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
        "delivery_status": {
            "needs_upgrade": needs_upgrade,
            "content_available": bool(output.get("publication_draft")),
            "next_action": "GENERATE_DELIVERABLE" if needs_upgrade else "PROVIDE_PUBLICATION_DETAILS",
        },
        "boundary": {
            "external_llm_calls": 0, "web_refetches": 0, "automatic_publication": False,
            "update_managed_enabled": False, "retest_computation": True,
        },
    }
