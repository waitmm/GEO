"""Deterministic SC-GRADED-DELIVERY-001 plan and result projections.

This module never reads the database or calls a provider.  Callers must finish
their existing identity/integrity checks before creating a plan.
"""
from __future__ import annotations

import copy
from typing import Any

from .delivery_text import digest


PLAN_CONTRACT_VERSION = "single_prompt_v2.delivery_qualification_plan.v1"
RESULT_CONTRACT_VERSION = "single_prompt_v2.delivery_qualification_result.v1"
QUALIFICATION_CONTRACT_VERSION = "SC-GRADED-DELIVERY-001@1.0.0"

L1 = "L1_FULLY_GROUNDED"
L2 = "L2_PARTIALLY_GROUNDED"
L3 = "L3_ACTIONABLE_WITHOUT_FACT_CLAIMS"
L4 = "L4_RECOVERY_PACKAGE"
_LEVEL_ORDER = {L1: 1, L2: 2, L3: 3, L4: 4}


def _sealed(value: dict[str, Any], *, prefix: str) -> dict[str, Any]:
    payload = copy.deepcopy(value)
    value_hash = digest(payload)
    return {
        **payload,
        f"{prefix}_version": f"{prefix}-v1:{value_hash[:16]}",
        f"{prefix}_hash": value_hash,
    }


def validate_seal(value: dict[str, Any], *, prefix: str) -> None:
    payload = copy.deepcopy(value)
    version = payload.pop(f"{prefix}_version", None)
    value_hash = payload.pop(f"{prefix}_hash", None)
    expected = digest(payload)
    if value_hash != expected or version != f"{prefix}-v1:{expected[:16]}":
        raise ValueError(f"{prefix.upper()}_HASH_MISMATCH")


def build_plan(
    *,
    task_id: str,
    task_input_hash: str,
    analysis_id: str,
    context_id: str,
    project_id: int,
    prompt_id: int,
    fixed_run_ids: list[int],
    proposal_id: str,
    proposal_result_version: str,
    proposal_result_hash: str,
    strategy_id: str,
    strategy_result_version: str,
    strategy_result_hash: str,
    direction: dict[str, Any],
    delivery_input: dict[str, Any],
    evidence_binding_ids: list[str],
) -> dict[str, Any]:
    """Create an immutable pre-request plan after existing hard gates pass."""
    selected = [
        row for row in delivery_input.get("selected_evidence") or []
        if row.get("material_use") != "ATTRIBUTED_BRAND_PAGE_OBSERVATION_NOT_TRUTH"
    ]
    evidence_ids = [str(row.get("section_id") or "") for row in selected]
    truth_ids = [
        str(row.get("product_truth_id") or "")
        for row in delivery_input.get("truths") or []
        if row.get("public_use_eligibility") == "CONSUMABLE"
    ]
    limitations = [
        str(value) for value in (
            list(direction.get("scope_limitations") or [])
            + list(delivery_input.get("limitations") or [])
        ) if value
    ]
    has_fact_material = bool(evidence_ids or truth_ids)
    if not has_fact_material:
        level = L3
        evidence_qualification = (
            "SOURCE_UNAVAILABLE"
            if any("SOURCE" in value or "CITATION" in value for value in limitations)
            else "EVALUATED_NO_SUPPORT"
        )
        delivery_type = "RESEARCH_BRIEF"
        allowed = ["INSTRUCTION"]
        public_claim = "NOT_CONSUMABLE"
        publication = "VERIFY_FIRST"
    else:
        partial = bool(limitations or direction.get("limiting_dependencies"))
        level = L2 if partial else L1
        evidence_qualification = (
            "PARTIALLY_GROUNDED_FOR_SELECTED_BLOCKS"
            if partial else "FULLY_GROUNDED_FOR_SELECTED_BLOCKS"
        )
        delivery_type = "BOUNDED_DRAFT" if partial else "GROUNDED_DRAFT"
        allowed = ["INSTRUCTION", "SOURCE_STATEMENT", "TARGET_STATEMENT"]
        public_claim = "VERIFY_FIRST" if partial else "CONSUMABLE"
        publication = "VERIFY_FIRST" if partial else "ELIGIBLE_PENDING_BUSINESS_APPROVAL"

    qualification = _sealed({
        "contract_version": QUALIFICATION_CONTRACT_VERSION,
        "task_id": task_id,
        "task_input_hash": task_input_hash,
        "analysis_id": analysis_id,
        "context_id": context_id,
        "project_id": project_id,
        "prompt_id": prompt_id,
        "fixed_run_ids": sorted(int(value) for value in fixed_run_ids),
        "fixed_run_scope_hash": digest(sorted(int(value) for value in fixed_run_ids)),
        "strategy_id": strategy_id,
        "strategy_result_version": strategy_result_version,
        "strategy_result_hash": strategy_result_hash,
        "direction_id": str(direction.get("direction_id") or direction.get("strategy_id") or ""),
        "proposal_id": proposal_id,
        "proposal_result_version": proposal_result_version,
        "proposal_result_hash": proposal_result_hash,
        "diagnosis_result_version": (delivery_input.get("identity") or {}).get("answer_result_version"),
        "diagnosis_result_hash": (delivery_input.get("identity") or {}).get("answer_result_hash"),
        "contribution_partition_hash": digest(delivery_input.get("contribution_results") or [{
            "result_version": delivery_input.get("contribution_result_version"),
            "result_hash": delivery_input.get("contribution_result_hash"),
        }]),
        "truth_partition_hash": digest(delivery_input.get("truths") or []),
        "block_allowlist_hash": digest({
            "evidence_ids": evidence_ids,
            "binding_ids": evidence_binding_ids,
            "truth_ids": truth_ids,
        }),
    }, prefix="qualification")
    plan_payload = {
        "contract_version": PLAN_CONTRACT_VERSION,
        "plan_id": f"delivery-plan:{qualification['qualification_hash'][:20]}",
        "qualification": qualification,
        "planned_delivery_level": level,
        "product_outcome": "NONE",
        "delivery_type": delivery_type,
        "evidence_qualification": evidence_qualification,
        "public_claim_eligibility": public_claim,
        "publication_eligibility": publication,
        "allowed_block_kinds": allowed,
        "evidence_allowlist": evidence_ids,
        "binding_allowlist": list(evidence_binding_ids),
        "truth_allowlist": truth_ids,
        "limitations": sorted(set(limitations)),
    }
    return _sealed(plan_payload, prefix="plan")


def build_result(plan: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    """Admit the actual QA'd text at the planned level or a legal lower level."""
    blocks = [block for block in receipt.get("segments") or []
              if block.get("kind") != "HEADING" and str(block.get("text") or "").strip()]
    qa_ready = (receipt.get("qa") or {}).get("status") == "READY"
    allowed = set(plan.get("allowed_block_kinds") or [])
    evidence = set(plan.get("evidence_allowlist") or []) | {
        f"truth:{value}" for value in plan.get("truth_allowlist") or []
    }
    valid = qa_ready and bool(str(receipt.get("body_markdown") or "").strip())
    valid = valid and all(block.get("kind") in allowed for block in blocks)
    valid = valid and all(set(block.get("evidence_ids") or []).issubset(evidence) for block in blocks)
    planned = str(plan["planned_delivery_level"])
    if planned == L3:
        valid = valid and all(block.get("kind") == "INSTRUCTION" and not block.get("evidence_ids") for block in blocks)
    factual = any(block.get("kind") != "INSTRUCTION" for block in blocks)
    admitted = planned if valid and (planned == L3 or factual) else L3 if valid else "REJECTED"
    delivery_type = plan["delivery_type"] if admitted == planned else "INSTRUCTION_ONLY_DRAFT" if admitted == L3 else None
    payload = {
        "contract_version": RESULT_CONTRACT_VERSION,
        "result_id": f"delivery-result:{plan['plan_hash'][:20]}:{digest(receipt.get('content_hash'))[:12]}",
        "plan_id": plan["plan_id"],
        "plan_version": plan["plan_version"],
        "plan_hash": plan["plan_hash"],
        "qualification_version": plan["qualification"]["qualification_version"],
        "qualification_hash": plan["qualification"]["qualification_hash"],
        "direction_id": plan["qualification"].get("direction_id"),
        "admitted_delivery_level": admitted,
        "delivery_type": delivery_type,
        "qa_status": (receipt.get("qa") or {}).get("status"),
        "content_hash": receipt.get("content_hash"),
        "product_outcome": "CONTENT_DELIVERED" if admitted != "REJECTED" else "NONE",
        "public_claim_eligibility": plan["public_claim_eligibility"] if admitted != L3 else "NOT_CONSUMABLE",
        "publication_eligibility": plan["publication_eligibility"] if admitted != L3 else "VERIFY_FIRST",
    }
    return _sealed(payload, prefix="result")


def build_l4_recovery(*, task_id: str, task_input_hash: str, analysis_id: str, context_id: str,
                      project_id: int, prompt_id: int, fixed_run_ids: list[int], raw_output_hash: str,
                      missing_objects: list[str], reasons: list[str], recovery_actions: list[str]) -> tuple[dict, dict]:
    """Build the sole zero-provider-call, no-direction L4 plan/result pair."""
    qualification = _sealed({
        "contract_version": QUALIFICATION_CONTRACT_VERSION,
        "task_id": task_id, "task_input_hash": task_input_hash,
        "analysis_id": analysis_id, "context_id": context_id,
        "project_id": project_id, "prompt_id": prompt_id,
        "fixed_run_ids": sorted(fixed_run_ids), "fixed_run_scope_hash": digest(sorted(fixed_run_ids)),
        "raw_output_hash": raw_output_hash, "direction_id": None, "proposal_id": None,
    }, prefix="qualification")
    plan = _sealed({
        "contract_version": PLAN_CONTRACT_VERSION,
        "plan_id": f"delivery-plan:{qualification['qualification_hash'][:20]}",
        "qualification": qualification,
        "planned_delivery_level": L4, "product_outcome": "NONE",
        "delivery_type": "RECOVERY_ACTIONS", "evidence_qualification": "INPUT_UNAVAILABLE",
        "public_claim_eligibility": "NOT_CONSUMABLE", "publication_eligibility": "NOT_CONSUMABLE",
        "allowed_block_kinds": [], "evidence_allowlist": [], "binding_allowlist": [], "truth_allowlist": [],
    }, prefix="plan")
    result = _sealed({
        "contract_version": RESULT_CONTRACT_VERSION,
        "result_id": f"delivery-result:{plan['plan_hash'][:20]}:recovery",
        "plan_id": plan["plan_id"], "plan_version": plan["plan_version"], "plan_hash": plan["plan_hash"],
        "qualification_version": qualification["qualification_version"],
        "qualification_hash": qualification["qualification_hash"],
        "direction_id": None,
        "admitted_delivery_level": L4, "delivery_type": "RECOVERY_ACTIONS",
        "qa_status": "NOT_APPLICABLE", "product_outcome": "RECOVERY_REQUIRED",
        "public_claim_eligibility": "NOT_CONSUMABLE", "publication_eligibility": "NOT_CONSUMABLE",
        "missing_objects": sorted(set(missing_objects)), "reasons": list(reasons),
        "recovery_actions": list(recovery_actions),
        "reentry_conditions": ["创建绑定同一 Project/Prompt 的新固定 Analysis，并取得至少一个可消费 Answer Run。"],
        "downstream_content_delivery_dependency_satisfied": False,
        "external_model_calls": 0,
    }, prefix="result")
    return plan, result


def aggregate_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    admitted = [row for row in results if row.get("admitted_delivery_level") in _LEVEL_ORDER]
    if not admitted:
        return {"product_outcome": "NONE", "highest_level": None, "lowest_level": None,
                "all_directions_l1": False, "direction_results": []}
    levels = [str(row["admitted_delivery_level"]) for row in admitted]
    return {
        "product_outcome": (
            "RECOVERY_REQUIRED" if all(row.get("product_outcome") == "RECOVERY_REQUIRED" for row in admitted)
            else "CONTENT_DELIVERED" if all(row.get("product_outcome") == "CONTENT_DELIVERED" for row in admitted)
            else "NONE"
        ),
        "highest_level": min(levels, key=_LEVEL_ORDER.get),
        "lowest_level": max(levels, key=_LEVEL_ORDER.get),
        "all_directions_l1": bool(levels) and all(level == L1 for level in levels),
        "direction_results": [{
            "direction_id": row.get("direction_id"),
            "plan_id": row.get("plan_id"), "plan_version": row.get("plan_version"), "plan_hash": row.get("plan_hash"),
            "result_id": row.get("result_id"), "result_version": row.get("result_version"), "result_hash": row.get("result_hash"),
            "admitted_delivery_level": row.get("admitted_delivery_level"), "product_outcome": row.get("product_outcome"),
        } for row in admitted],
    }
