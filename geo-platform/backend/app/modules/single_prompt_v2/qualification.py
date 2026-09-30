from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    Prompt,
    SinglePromptCitationContributionExecution,
    SinglePromptCitationContributionResult,
)
from app.modules.single_prompt_v2.strategy import build_strategy_input_projection
from app.services.serialization import loads


QUALIFICATION_CONTRACT_VERSION = "single_prompt_v2.qualification_projection.v1"
AUTOMATIC_STRATEGY_VERSION = "single_prompt_v2.automatic_strategy_direction.v1"
AUTOMATIC_EXECUTION_DRAFT_VERSION = "single_prompt_v2.automatic_execution_draft.v1"

_POSITIVE_TRUTH_STATUSES = {"SUPPORTED", "TRUE"}
_CURRENT_CONTRIBUTION_STATUSES = {
    "READY_FOR_CALIBRATION",
    "CALIBRATION_COMPLETED",
    "REVIEW_COMPLETED",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _use_eligibility(**overrides: str) -> dict[str, str]:
    result = {
        "diagnosis": "NOT_CONSUMABLE",
        "strategy_direction": "NOT_CONSUMABLE",
        "execution_draft": "NOT_CONSUMABLE",
        "public_claim": "NOT_CONSUMABLE",
        "publication": "NOT_CONSUMABLE",
    }
    result.update(overrides)
    return result


def _truth_provenance(row: dict[str, Any]) -> str:
    source = str(row.get("truth_source") or "")
    if source in {
        "OFFICIAL_SOURCE_ATTESTED",
        "THIRD_PARTY_SOURCE_ATTESTED",
        "FIRST_PARTY_ASSERTED",
        "OPERATIONALLY_VERIFIED",
        "MACHINE_INFERRED",
    }:
        return source
    if source == "MANUAL_CONFIRMED":
        return "FIRST_PARTY_ASSERTED"
    return "MACHINE_INFERRED"


def _load_current_contribution_scope(
    db: Session,
    *,
    analysis_id: str,
    context_id: str,
) -> dict[str, Any]:
    rows = (
        db.query(SinglePromptCitationContributionExecution)
        .filter(
            SinglePromptCitationContributionExecution.analysis_id == analysis_id,
            SinglePromptCitationContributionExecution.context_id == context_id,
            SinglePromptCitationContributionExecution.status.in_(_CURRENT_CONTRIBUTION_STATUSES),
            SinglePromptCitationContributionExecution.active_result_version != "",
        )
        .order_by(SinglePromptCitationContributionExecution.contribution_id.asc())
        .all()
    )
    if not rows:
        return {
            "status": "UNAVAILABLE",
            "run_ids": [],
            "scope_limitations": ["CITATION_CONTRIBUTION_NOT_AVAILABLE"],
            "result": None,
        }
    if len(rows) != 1:
        return {
            "status": "AMBIGUOUS",
            "run_ids": sorted({int(row.selected_run_id) for row in rows}),
            "scope_limitations": ["MULTIPLE_CURRENT_CITATION_CONTRIBUTIONS_REQUIRE_EXPLICIT_SELECTION"],
            "result": None,
        }
    execution = rows[0]
    result = (
        db.query(SinglePromptCitationContributionResult)
        .filter(
            SinglePromptCitationContributionResult.contribution_id == execution.contribution_id,
            SinglePromptCitationContributionResult.result_version == execution.active_result_version,
        )
        .one_or_none()
    )
    if not result:
        return {
            "status": "INVALID_BINDING",
            "run_ids": [int(execution.selected_run_id)],
            "scope_limitations": ["CITATION_CONTRIBUTION_RESULT_BINDING_MISSING"],
            "result": None,
        }
    output = loads(result.output_json, {})
    if (
        str((output.get("input") or {}).get("analysis_id") or "") != analysis_id
        or str((output.get("input") or {}).get("context_id") or "") != context_id
        or int(output.get("selected_run_id") or 0) != int(execution.selected_run_id)
    ):
        return {
            "status": "INVALID_BINDING",
            "run_ids": [int(execution.selected_run_id)],
            "scope_limitations": ["CITATION_CONTRIBUTION_INPUT_IDENTITY_MISMATCH"],
            "result": None,
        }
    return {
        "status": "PARTIAL_SCOPE",
        "run_ids": [int(execution.selected_run_id)],
        "scope_limitations": ["CITATION_CONTRIBUTION_RUN_1_ONLY"],
        "result": {
            "contribution_id": execution.contribution_id,
            "result_version": result.result_version,
            "result_hash": result.output_hash,
            "contract_version": execution.contract_version,
            "processing": {
                "done": sum(1 for row in output.get("citations") or [] if row.get("processing_status") == "DONE"),
                "failed": sum(1 for row in output.get("citations") or [] if row.get("processing_status") == "FAILED"),
                "binding_count": len(output.get("bindings") or []),
                "evaluation_count": len(output.get("evaluations") or []),
            },
            "answer_anchor": "UNPROVEN",
            "generation_influence": "UNAVAILABLE",
            "answer_units": copy.deepcopy(output.get("answer_units") or []),
            "bindings": copy.deepcopy(output.get("bindings") or []),
        },
    }


def _confirmed_truths(projection: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        int(row["truth_id"]): row
        for row in projection.get("truth_snapshot") or []
        if row.get("truth_id") is not None
        and row.get("product_truth_status") in _POSITIVE_TRUTH_STATUSES
        and row.get("truth_source") == "MANUAL_CONFIRMED"
    }


def _direction_candidates(projection: dict[str, Any]) -> list[dict[str, Any]]:
    reasons = {str(row.get("reason_id")): row for row in projection.get("reasons") or []}
    truths = _confirmed_truths(projection)
    candidates = []
    for coverage in projection.get("reason_capability_coverage") or []:
        reason_id = str(coverage.get("reason_id") or "")
        reason = reasons.get(reason_id)
        truth_ids = sorted({int(value) for value in coverage.get("truth_ids") or [] if int(value) in truths})
        if (
            not reason
            or not reason.get("fact_consumption_eligible")
            or coverage.get("fact_consumption_eligible") is not True
            or coverage.get("effective_relation") != "FULLY_COVERS"
            or not truth_ids
        ):
            continue
        candidates.append({
            "reason": reason,
            "coverage": coverage,
            "truth_ids": truth_ids,
            "truths": [truths[value] for value in truth_ids],
        })
    return sorted(
        candidates,
        key=lambda item: (-len(item["truth_ids"]), int(item["reason"].get("run_id") or 0), item["reason"]["reason_id"]),
    )


def _truth_dependency(direction_id: str, row: dict[str, Any]) -> list[dict[str, Any]]:
    truth_id = int(row["truth_id"])
    statement = row.get("statement_eligibility") or {}
    public_ready = statement.get("status") == "ELIGIBLE"
    provenance = _truth_provenance(row)
    return [
        {
            "dependency_id": f"dep:{direction_id}:truth:{truth_id}:applicability",
            "object_id": str(truth_id),
            "object_type": "PRODUCT_TRUTH",
            "dependency_role": "SUPPORTING",
            "required_for": ["STRATEGY_DIRECTION", "EXECUTION_DRAFT"],
            "state": "SATISFIED",
            "eligibility": "CONSUMABLE",
            "provenance": provenance,
            "reason_codes": [],
        },
        {
            "dependency_id": f"dep:{direction_id}:truth:{truth_id}:public-claim",
            "object_id": str(truth_id),
            "object_type": "PRODUCT_TRUTH",
            "dependency_role": "BLOCKING",
            "required_for": ["PUBLIC_CLAIM", "PUBLICATION"],
            "state": "SATISFIED" if public_ready else "UNSATISFIED",
            "eligibility": "CONSUMABLE" if public_ready else "VERIFY_FIRST",
            "provenance": provenance,
            "reason_codes": copy.deepcopy(statement.get("issues") or []),
        },
    ]


def _build_execution_draft(
    *,
    direction: dict[str, Any],
    brand_name: str,
    truths: list[dict[str, Any]],
) -> dict[str, Any]:
    direction_id = direction["strategy_id"]
    claims = []
    for row in truths:
        truth_id = int(row["truth_id"])
        statement = row.get("statement_eligibility") or {}
        public_ready = statement.get("status") == "ELIGIBLE"
        claims.append({
            "claim_id": f"claim:{direction_id}:truth:{truth_id}",
            "text": str(row.get("capability_label") or "").strip(),
            "truth_id": truth_id,
            "truth_provenance": _truth_provenance(row),
            "conditions": [],
            "scope": "TARGET_BRAND_ONLY",
            "claim_eligibility": "READY" if public_ready else "VERIFY_FIRST",
            "public_claim_eligibility": "CONSUMABLE" if public_ready else "NOT_CONSUMABLE",
            "limiting_dependencies": [] if public_ready else [f"dep:{direction_id}:truth:{truth_id}:public-claim"],
            "reason_codes": copy.deepcopy(statement.get("issues") or []),
        })
    public_ready_claims = [row for row in claims if row["public_claim_eligibility"] == "CONSUMABLE"]
    sections = [
        {
            "section_id": f"section:{direction_id}:scenario",
            "title": "场景与用户问题",
            "purpose": "说明抖音跳转微信场景及当前回答中的选择依据",
            "section_eligibility": "DRAFT_ALLOWED",
            "public_claim_eligibility": "NOT_CONSUMABLE",
            "claim_ids": [],
            "limiting_dependencies": [],
        },
        {
            "section_id": f"section:{direction_id}:capabilities",
            "title": "目标品牌能力说明",
            "purpose": "按原子能力组织目标品牌可核对的事实表达",
            "section_eligibility": "READY" if public_ready_claims else "DRAFT_ALLOWED",
            "public_claim_eligibility": "CONSUMABLE" if len(public_ready_claims) == len(claims) else "NOT_CONSUMABLE",
            "claim_ids": [row["claim_id"] for row in claims],
            "limiting_dependencies": sorted({value for row in claims for value in row["limiting_dependencies"]}),
        },
        {
            "section_id": f"section:{direction_id}:boundaries",
            "title": "适用条件与事实边界",
            "purpose": "显式保留未证明的发布渠道、引用采用和能力来源限制",
            "section_eligibility": "READY",
            "public_claim_eligibility": "CONSUMABLE",
            "claim_ids": [],
            "limiting_dependencies": [],
        },
    ]
    title = f"{brand_name}抖音跳转微信能力说明"
    if not public_ready_claims:
        title = f"{title}（内部草案，待补公开依据）"
    return {
        "contract_version": AUTOMATIC_EXECUTION_DRAFT_VERSION,
        "draft_id": f"draft-{_hash({'direction_id': direction_id, 'claims': claims})[:20]}",
        "direction_id": direction_id,
        "title": title,
        "goal": direction["intervention_goal"],
        "asset_role": "TARGET_CAPABILITY_FACT_ANCHOR",
        "asset_operation": "CONDITIONAL",
        "asset_type_candidates": ["PRODUCT_PAGE", "FEATURE_PAGE", "HELP_DOC"],
        "channel_candidate": {
            "status": "NOT_SELECTED",
            "channel_key": None,
            "channel_role": None,
            "eligibility": "OBSERVE_ONLY",
            "reason": "当前方向由目标品牌场景理由和第一方能力确认成立；现有 Run 1 Citation 范围不足以选择 9-Run 发布渠道。",
        },
        "sections": sections,
        "claims": claims,
        "required_truth_ids": [int(row["truth_id"]) for row in truths],
        "required_evidence_ids": [],
        "eligibility_by_use": copy.deepcopy(direction["eligibility_by_use"]),
        "limiting_dependencies": copy.deepcopy(direction["limiting_dependencies"]),
        "internal_checklist": [
            "为拟公开的每项目标品牌能力补充官方页面或其他可核对来源",
            "用户选择实际资产类型和发布位置后再进入外部行动批准",
            "不得把 Run 1 Citation Contribution 表述为 9-Run 引用机制结论",
        ],
        "boundary": {
            "internal_draft_only": True,
            "external_action_authorized": False,
            "public_claims_ready": bool(claims and len(public_ready_claims) == len(claims)),
            "publication_eligibility": (
                "ELIGIBLE_PENDING_BUSINESS_APPROVAL"
                if claims and len(public_ready_claims) == len(claims)
                else "VERIFY_FIRST"
            ),
            "asset_operation_decision": "USER_SELECTION_REQUIRED",
        },
    }


def _build_exploratory_direction_and_draft(
    *,
    projection: dict[str, Any],
    contribution_scope: dict[str, Any],
    prompt_text: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    run_ids = sorted(int(value) for value in projection.get("analyzable_run_ids") or [])
    contribution = contribution_scope.get("result") or {}
    units = {str(row.get("answer_unit_id")): row for row in contribution.get("answer_units") or []}
    supported = []
    seen_units: set[str] = set()
    for binding in contribution.get("bindings") or []:
        if binding.get("processing_status") != "DONE" or binding.get("evidence_relation") not in {
            "SUPPORTS_FULL", "SUPPORTS_PARTIAL",
        }:
            continue
        unit_id = str(binding.get("answer_unit_id") or "")
        unit = units.get(unit_id)
        if not unit or unit_id in seen_units:
            continue
        seen_units.add(unit_id)
        supported.append({
            "answer_unit_id": unit_id,
            "raw_text": str(unit.get("raw_text") or ""),
            "context_heading": str(unit.get("context_heading") or ""),
            "primary_type": str(unit.get("primary_type") or ""),
            "binding_id": str(binding.get("binding_id") or ""),
            "citation_id": str(binding.get("citation_id") or ""),
            "source_key": str(binding.get("source_key") or ""),
            "evidence_relation": str(binding.get("evidence_relation") or ""),
        })
        if len(supported) >= 5:
            break
    direction_id = f"strategy-machine-{_hash({'prompt': prompt_text, 'runs': run_ids, 'mode': 'exploratory'})[:20]}"
    contribution_exact = bool(run_ids and run_ids == sorted(int(value) for value in contribution_scope.get("run_ids") or []))
    dependency_state = "SATISFIED" if supported and contribution_exact else "LIMITED"
    dependency = {
        "dependency_id": f"dep:{direction_id}:citation-contribution",
        "object_id": str(contribution.get("result_version") or "UNAVAILABLE"),
        "object_type": "CITATION_CONTRIBUTION_SCOPE",
        "dependency_role": "SUPPORTING",
        "required_for": ["EXECUTION_DRAFT"],
        "state": dependency_state,
        "eligibility": "CONSUMABLE" if dependency_state == "SATISFIED" else "OBSERVE_ONLY",
        "provenance": "MACHINE_RESULT",
        "reason_codes": [] if dependency_state == "SATISFIED" else ["SOURCE_GROUNDING_INCOMPLETE"],
    }
    direction = {
        "contract_version": AUTOMATIC_STRATEGY_VERSION,
        "direction_id": direction_id,
        "strategy_id": direction_id,
        "direction_type": "DISCOVERY",
        "level": "ACTIONABLE",
        "mechanism_gap": "TARGET_BRAND_NOT_PRESENT_IN_OBSERVED_ANSWER",
        "intervention_goal": f"围绕“{prompt_text}”形成一份可核验的问题解答资产，让目标品牌有机会进入后续答案候选。",
        "reason_id": None,
        "reason_ids": [],
        "reason_text": "",
        "reason_run_ids": run_ids,
        "truth_ids": [],
        "evidence_relation_ids": [row["binding_id"] for row in supported if row["binding_id"]],
        "dependencies": [dependency],
        "eligibility_by_use": _use_eligibility(
            diagnosis="CONSUMABLE",
            strategy_direction="CONSUMABLE",
            execution_draft="CONSUMABLE",
            public_claim="NOT_CONSUMABLE",
            publication="VERIFY_FIRST",
        ),
        "strategy_direction_eligibility": "CONSUMABLE",
        "execution_draft_eligibility": "CONSUMABLE",
        "public_claim_eligibility": "NOT_CONSUMABLE",
        "limiting_dependencies": [dependency["dependency_id"]] if dependency_state != "SATISFIED" else [],
        "scope_limitations": [
            "OBSERVED_ABSENCE_IS_NOT_CAPABILITY_ABSENCE",
            "NO_TARGET_BRAND_PUBLIC_CLAIM_AUTHORIZED",
            "GENERATION_INFLUENCE_UNAVAILABLE",
        ],
        "reasoning_trace": [
            {"step": "ANSWER_SCOPE", "run_ids": run_ids, "result": "TARGET_BRAND_NOT_OBSERVED"},
            {"step": "CITATION_SCOPE", "run_ids": contribution_scope.get("run_ids") or [], "result": dependency_state},
            {"step": "PUBLIC_CLAIM", "result": "NOT_CONSUMABLE_WITHOUT_PRODUCT_TRUTH"},
        ],
    }
    blocks = [{
        "block_id": f"block:{direction_id}:{index + 1}",
        "heading": row["context_heading"] or f"核心问题 {index + 1}",
        "draft_text": row["raw_text"],
        "content_role": "SOURCE_GROUNDED_REFERENCE_BLOCK",
        "answer_unit_id": row["answer_unit_id"],
        "binding_id": row["binding_id"],
        "citation_id": row["citation_id"],
        "evidence_relation": row["evidence_relation"],
        "publication_eligibility": "VERIFY_FIRST",
    } for index, row in enumerate(supported)]
    if not blocks:
        blocks = [{
            "block_id": f"block:{direction_id}:scope",
            "heading": "用户问题与适用场景",
            "draft_text": f"解释“{prompt_text}”的主要使用场景、前置条件、可行路径和风险边界。",
            "content_role": "GROUNDING_REQUIRED_BRIEF",
            "answer_unit_id": None,
            "binding_id": None,
            "citation_id": None,
            "evidence_relation": "NOT_EVALUATED",
            "publication_eligibility": "VERIFY_FIRST",
        }]
    draft = {
        "contract_version": AUTOMATIC_EXECUTION_DRAFT_VERSION,
        "draft_id": f"draft-{_hash({'direction_id': direction_id, 'blocks': blocks})[:20]}",
        "direction_id": direction_id,
        "title": f"{prompt_text}：场景、方法与注意事项",
        "goal": direction["intervention_goal"],
        "asset_role": "DISCOVERY_CONTENT",
        "asset_operation": "CONDITIONAL",
        "asset_type_candidates": ["PRODUCT_PAGE", "HELP_DOC", "ARTICLE"],
        "channel_candidate": {
            "status": "USER_SELECTION_REQUIRED",
            "channel_key": None,
            "channel_role": None,
            "eligibility": "VERIFY_FIRST",
            "reason": "当前没有已验证的 ManagedAsset 和发布位置，不能推断 CREATE_NEW、UPDATE 或渠道角色。",
        },
        "content_blocks": blocks,
        "claims": [],
        "required_truth_ids": [],
        "required_evidence_ids": [row["binding_id"] for row in supported if row["binding_id"]],
        "eligibility_by_use": copy.deepcopy(direction["eligibility_by_use"]),
        "limiting_dependencies": copy.deepcopy(direction["limiting_dependencies"]),
        "internal_checklist": [
            "选择实际资产操作、资产类型与发布位置",
            "如需写入目标品牌能力，先使用可消费 Product Truth；当前稿件不得自行补写品牌能力",
            "发布前对引用事实、条件和时效做最终核验",
        ],
        "qa": {
            "status": "READY_INTERNAL",
            "checks": {
                "target_brand_claims_without_truth": "PASS",
                "source_grounding": "PASS" if supported else "VERIFY_FIRST",
                "asset_operation_inference": "PASS",
                "external_action_authorized": "NO",
            },
            "blocking_for_publication": ["ASSET_DECISION_REQUIRED", "BUSINESS_CONFIRMATION_REQUIRED"],
        },
        "boundary": {
            "internal_draft_only": True,
            "external_action_authorized": False,
            "public_claims_ready": False,
            "publication_eligibility": "VERIFY_FIRST",
        },
    }
    return direction, draft


def evaluate_qualification_projection(
    projection: dict[str, Any],
    contribution_scope: dict[str, Any],
    prompt_text: str = "",
) -> dict[str, Any]:
    run_ids = sorted(int(value) for value in projection.get("analyzable_run_ids") or [])
    candidates = _direction_candidates(projection)
    object_qualifications: list[dict[str, Any]] = []
    directions: list[dict[str, Any]] = []
    drafts: list[dict[str, Any]] = []

    if candidates:
        candidate = candidates[0]
        reason = candidate["reason"]
        truths = candidate["truths"]
        direction_id = f"strategy-machine-{_hash({'reason_id': reason['reason_id'], 'truth_ids': candidate['truth_ids']})[:20]}"
        dependencies = [{
            "dependency_id": f"dep:{direction_id}:reason:{reason['reason_id']}",
            "object_id": reason["reason_id"],
            "object_type": "ANSWER_REASON",
            "dependency_role": "BLOCKING",
            "required_for": ["STRATEGY_DIRECTION", "EXECUTION_DRAFT"],
            "state": "SATISFIED",
            "eligibility": "CONSUMABLE",
            "provenance": "MACHINE_GROUNDED",
            "reason_codes": [],
        }]
        for truth in truths:
            dependencies.extend(_truth_dependency(direction_id, truth))
        dependencies.append({
            "dependency_id": f"dep:{direction_id}:citation-scope",
            "object_id": str((contribution_scope.get("result") or {}).get("result_version") or "UNAVAILABLE"),
            "object_type": "CITATION_CONTRIBUTION_SCOPE",
            "dependency_role": "ENRICHING",
            "required_for": ["STRATEGY_DIRECTION"],
            "state": "LIMITED",
            "eligibility": "OBSERVE_ONLY",
            "provenance": "MACHINE_RESULT",
            "reason_codes": copy.deepcopy(contribution_scope.get("scope_limitations") or []),
        })
        public_blockers = [
            row["dependency_id"]
            for row in dependencies
            if "PUBLIC_CLAIM" in row["required_for"] and row["state"] != "SATISFIED"
        ]
        observed_run_ids = [int(reason["run_id"])] if reason.get("run_id") is not None else []
        direction = {
            "contract_version": AUTOMATIC_STRATEGY_VERSION,
            "direction_id": direction_id,
            "strategy_id": direction_id,
            "direction_type": "MECHANISM",
            "level": "ACTIONABLE",
            "mechanism_gap": "TARGET_CAPABILITY_ASSOCIATION_UNDERREPRESENTED",
            "intervention_goal": "将已确认的抖音跳转微信能力整理为可核验、可引用的场景化事实表达。",
            "reason_id": reason["reason_id"],
            "reason_ids": [reason["reason_id"]],
            "reason_text": reason.get("grounded_text") or "",
            "reason_run_ids": observed_run_ids,
            "truth_ids": candidate["truth_ids"],
            "evidence_relation_ids": [],
            "dependencies": dependencies,
            "eligibility_by_use": _use_eligibility(
                diagnosis="CONSUMABLE",
                strategy_direction="CONSUMABLE",
                execution_draft="CONSUMABLE",
                public_claim="VERIFY_FIRST" if public_blockers else "CONSUMABLE",
                publication="NOT_CONSUMABLE" if public_blockers else "VERIFY_FIRST",
            ),
            "strategy_direction_eligibility": "CONSUMABLE",
            "execution_draft_eligibility": "CONSUMABLE",
            "public_claim_eligibility": "VERIFY_FIRST" if public_blockers else "CONSUMABLE",
            "limiting_dependencies": public_blockers,
            "scope_limitations": [
                f"ANSWER_ANALYSIS_RUNS_{len(run_ids)}",
                *copy.deepcopy(contribution_scope.get("scope_limitations") or []),
                "CITATION_CONTRIBUTION_DOES_NOT_COVER_DIRECTION_REASON_RUN",
            ],
            "reasoning_trace": [
                {"step": "ANSWER_REASON", "object_id": reason["reason_id"], "result": "MACHINE_GROUNDED"},
                {"step": "TARGET_APPLICABILITY", "object_ids": [str(value) for value in candidate["truth_ids"]], "result": "FULLY_COVERS_FOR_STRATEGY"},
                {"step": "PUBLIC_CLAIM", "object_ids": [str(value) for value in candidate["truth_ids"]], "result": "VERIFY_FIRST" if public_blockers else "CONSUMABLE"},
                {"step": "CITATION_SCOPE", "run_ids": contribution_scope.get("run_ids") or [], "result": "LIMITED_NOT_GLOBAL"},
            ],
        }
        directions.append(direction)
        brand_name = str((projection.get("brand_snapshot") or {}).get("brand_name") or "目标品牌")
        drafts.append(_build_execution_draft(direction=direction, brand_name=brand_name, truths=truths))

        object_qualifications.append({
            "object_id": reason["reason_id"],
            "object_type": "ANSWER_REASON",
            "quality_state": "MACHINE_GROUNDED",
            "eligibility_by_use": _use_eligibility(
                diagnosis="CONSUMABLE",
                strategy_direction="CONSUMABLE",
                execution_draft="CONSUMABLE",
                public_claim="NOT_CONSUMABLE",
            ),
            "provenance": {"source": "ANSWER_SEMANTIC", "run_id": reason.get("run_id"), "event_id": reason.get("event_id")},
            "scope": {"run_ids": observed_run_ids},
            "scope_limitation": [],
            "reason_codes": [],
        })
        for truth in truths:
            statement = truth.get("statement_eligibility") or {}
            public_ready = statement.get("status") == "ELIGIBLE"
            object_qualifications.append({
                "object_id": str(truth["truth_id"]),
                "object_type": "PRODUCT_TRUTH",
                "quality_state": _truth_provenance(truth),
                "eligibility_by_use": _use_eligibility(
                    diagnosis="CONSUMABLE",
                    strategy_direction="CONSUMABLE",
                    execution_draft="CONSUMABLE",
                    public_claim="CONSUMABLE" if public_ready else "VERIFY_FIRST",
                    publication="VERIFY_FIRST" if public_ready else "NOT_CONSUMABLE",
                ),
                "provenance": {"source": _truth_provenance(truth), "truth_source": truth.get("truth_source")},
                "scope": {"brand_id": truth.get("brand_id"), "target_brand_only": True},
                "scope_limitation": [] if public_ready else copy.deepcopy(statement.get("issues") or []),
                "reason_codes": copy.deepcopy(statement.get("issues") or []),
            })
    elif run_ids:
        direction, draft = _build_exploratory_direction_and_draft(
            projection=projection,
            contribution_scope=contribution_scope,
            prompt_text=prompt_text or "当前问题",
        )
        directions.append(direction)
        drafts.append(draft)

    result = {
        "contract_version": QUALIFICATION_CONTRACT_VERSION,
        "input_identity": copy.deepcopy(projection["identity"]),
        "input_projection_hash": projection["input_snapshot_hash"],
        "analysis_scope": {
            "run_ids": run_ids,
            "label": f"Answer analysis: Runs {min(run_ids)}-{max(run_ids)}" if run_ids else "Answer analysis: unavailable",
        },
        "evidence_scope": {
            "run_ids": copy.deepcopy(contribution_scope.get("run_ids") or []),
            "label": (
                f"Citation Contribution: Run {contribution_scope['run_ids'][0]} only"
                if len(contribution_scope.get("run_ids") or []) == 1
                else "Citation Contribution: unavailable or ambiguous"
            ),
            "status": contribution_scope.get("status"),
            "result": copy.deepcopy(contribution_scope.get("result")),
        },
        "scope_limitations": copy.deepcopy(contribution_scope.get("scope_limitations") or []),
        "object_qualifications": object_qualifications,
        "directions": directions,
        "execution_drafts": drafts,
        "final_plan": {
            "analysis_completed": bool(run_ids),
            "machine_direction_count": len(directions),
            "execution_draft_count": len(drafts),
            "execution_ready_count": sum(
                1 for row in drafts if row["boundary"]["public_claims_ready"]
            ),
            "draftable_verify_first_count": sum(
                1 for row in drafts if not row["boundary"]["public_claims_ready"]
            ),
            "human_review_global_blocker": False,
            "external_action_authorized": False,
        },
        "boundary": {
            "read_only": True,
            "database_writes": 0,
            "external_llm_calls": 0,
            "diagnosis_review_required_for_computation": False,
            "business_approval_required_for_external_action": True,
        },
    }
    result["projection_hash"] = _hash(result)
    return result


def build_qualification_projection(
    db: Session,
    *,
    analysis_id: str,
    diagnosis_id: str,
    result_version: str,
    project_id: int,
    prompt_id: int,
) -> dict[str, Any]:
    projection = build_strategy_input_projection(
        db,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        result_version=result_version,
        project_id=project_id,
        prompt_id=prompt_id,
    )
    if not projection.get("is_active_result"):
        raise HTTPException(status_code=409, detail="资格投影只读取当前精确 DiagnosisResultVersion，不自动替换为 latest")
    contribution_scope = _load_current_contribution_scope(
        db,
        analysis_id=analysis_id,
        context_id=str(projection["identity"]["context_id"]),
    )
    prompt = db.get(Prompt, prompt_id)
    return evaluate_qualification_projection(
        projection,
        contribution_scope,
        str(prompt.prompt_text if prompt else "当前问题"),
    )
