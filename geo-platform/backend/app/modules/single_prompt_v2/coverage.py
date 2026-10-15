"""Read-only completeness projections for the fixed V2 analysis scope."""

from __future__ import annotations

import hashlib
from typing import Any


COVERAGE_PROJECTION_VERSION = "single_prompt_v2.coverage.v1"

_ADMITTED_STATUSES = {
    "DONE",
    "DONE_ZERO_EVENTS",
    "DONE_WITH_FAILURES",
    "DONE_WITH_REVIEW_REQUIRED",
    "SEMANTIC_REVIEW_REQUIRED",
}


def _answer_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _run_rows(raw_output: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in raw_output.get("runs") or [] if row.get("run_id") is not None]


def _has_available_input(row: dict[str, Any]) -> bool:
    if not str(row.get("answer_text") or "").strip():
        return False
    status = str(row.get("status") or "").strip().lower()
    return not status or status in {"success", "partial_success"}


def input_scope_coverage(raw_output: dict[str, Any]) -> dict[str, Any]:
    rows = _run_rows(raw_output)
    expected = sorted(int(row["run_id"]) for row in rows)
    bound = sorted(
        int(row["run_id"])
        for row in rows
        if _has_available_input(row)
    )
    unavailable = sorted(set(expected) - set(bound))
    hashes = {
        str(int(row["run_id"])): _answer_hash(str(row.get("answer_text") or ""))
        for row in rows
        if _has_available_input(row)
    }
    limitations = {
        str(int(row["run_id"])): sorted({
            str(value)
            for value in (
                row.get("limitations")
                or (row.get("environment") or {}).get("limitations")
                or []
            )
            if value
        })
        for row in rows
    }
    return {
        "contract_version": COVERAGE_PROJECTION_VERSION,
        "expected_run_ids": expected,
        "bound_run_ids": bound,
        "missing_run_ids": unavailable,
        "input_unavailable_run_ids": unavailable,
        "input_unavailable_count": len(unavailable),
        "readable_answer_count": len(bound),
        "expected_run_count": len(expected),
        "answer_sha256_by_run": hashes,
        "quality_limitations_by_run": limitations,
        "scope_complete": not unavailable and bool(expected),
        "boundary": "INPUT_SCOPE_ONLY_NOT_COMPUTE_COMPLETION",
    }


def _jobs_by_run(raw_output: dict[str, Any], answer_diagnosis: dict[str, Any]) -> dict[int, dict[str, Any]]:
    by_hash = {
        str(job.get("answer_hash") or ""): job
        for job in answer_diagnosis.get("answer_jobs") or []
        if job.get("answer_hash")
    }
    result: dict[int, dict[str, Any]] = {}
    available_runs = [run for run in _run_rows(raw_output) if _has_available_input(run)]
    available_run_ids = {int(run["run_id"]) for run in available_runs}
    for run in available_runs:
        run_id = int(run["run_id"])
        answer = str(run.get("answer_text") or "")
        job = by_hash.get(_answer_hash(answer))
        if job:
            result[run_id] = job
    if not by_hash:
        projected_runs = {
            int(row.get("run_id"))
            for row in [
                *(answer_diagnosis.get("events") or []),
                *(answer_diagnosis.get("market_criteria") or []),
            ]
            if row.get("run_id") is not None and int(row["run_id"]) in available_run_ids
        }
        failed_runs = {
            int(row.get("run_id"))
            for row in answer_diagnosis.get("failures") or []
            if row.get("run_id") is not None and int(row["run_id"]) in available_run_ids
        }
        for run_id in projected_runs:
            result[run_id] = {"status": "DONE", "result_source": "LEGACY_PROJECTED_OBJECT"}
        for run_id in failed_runs - projected_runs:
            result[run_id] = {"status": "FAILED_LEGACY_RECORDED", "result_source": "LEGACY_FAILURE"}
    return result


def _is_cache_only_miss(job: dict[str, Any]) -> bool:
    source = str(job.get("result_source") or "")
    error = str(job.get("error") or "")
    return (
        source == "CACHE_MISS_EXTERNAL_NOT_AUTHORIZED"
        or "仅允许兼容缓存" in error
        or "没有可消费缓存" in error
    )


def compute_coverage(raw_output: dict[str, Any], answer_diagnosis: dict[str, Any]) -> dict[str, Any]:
    input_scope = input_scope_coverage(raw_output)
    jobs = _jobs_by_run(raw_output, answer_diagnosis)
    groups: dict[str, list[int]] = {
        "input_unavailable_run_ids": [],
        "success_with_events_run_ids": [],
        "success_zero_events_run_ids": [],
        "actual_failure_run_ids": [],
        "pending_compute_run_ids": [],
        "pending_external_authorization_run_ids": [],
        "running_run_ids": [],
        "invalid_cache_run_ids": [],
    }
    for run_id in input_scope["expected_run_ids"]:
        if run_id in input_scope["input_unavailable_run_ids"]:
            groups["input_unavailable_run_ids"].append(run_id)
            continue
        job = jobs.get(run_id)
        if not job:
            groups["pending_compute_run_ids"].append(run_id)
            continue
        status = str(job.get("status") or "")
        if status in _ADMITTED_STATUSES:
            target = "success_zero_events_run_ids" if status == "DONE_ZERO_EVENTS" else "success_with_events_run_ids"
            groups[target].append(run_id)
        elif status in {"RUNNING", "ADMITTED_PENDING_PROJECTION"}:
            groups["running_run_ids"].append(run_id)
        elif _is_cache_only_miss(job):
            groups["pending_external_authorization_run_ids"].append(run_id)
        elif status == "CACHE_REJECTED_BY_V2_VALIDATION":
            groups["invalid_cache_run_ids"].append(run_id)
            groups["pending_external_authorization_run_ids"].append(run_id)
        elif status.startswith("PENDING_EXTERNAL"):
            groups["pending_external_authorization_run_ids"].append(run_id)
        elif status.startswith("PENDING") or status == "NOT_STARTED":
            groups["pending_compute_run_ids"].append(run_id)
        else:
            groups["actual_failure_run_ids"].append(run_id)
    valid = sorted(groups["success_with_events_run_ids"] + groups["success_zero_events_run_ids"])
    terminal = sorted(valid + groups["actual_failure_run_ids"])
    expected_count = len(input_scope["expected_run_ids"])
    return {
        "contract_version": COVERAGE_PROJECTION_VERSION,
        "expected_run_ids": input_scope["expected_run_ids"],
        **groups,
        "valid_compute_run_ids": valid,
        "valid_compute_count": len(valid),
        "expected_run_count": expected_count,
        "input_unavailable_count": len(groups["input_unavailable_run_ids"]),
        "terminal_execution_run_ids": terminal,
        "terminal_execution_count": len(terminal),
        "all_runs_validly_understood": bool(expected_count) and len(valid) == expected_count,
        "all_runs_have_terminal_disposition": bool(expected_count) and len(terminal) == expected_count,
        "boundary": "FAILURE_IS_NOT_ZERO_AND_PENDING_IS_NOT_FAILURE",
    }


def review_coverage(
    raw_output: dict[str, Any],
    answer_diagnosis: dict[str, Any],
    review: dict[str, Any] | None,
) -> dict[str, Any]:
    compute = compute_coverage(raw_output, answer_diagnosis)
    admitted = set(compute["valid_compute_run_ids"])
    pending_events = [
        str(row.get("event_id"))
        for row in answer_diagnosis.get("events") or []
        if row.get("event_id") and row.get("semantic_validation_status") == "SEMANTIC_REVIEW_REQUIRED"
    ]
    decisions = {
        str(row.get("event_id")): str(row.get("decision"))
        for row in (review or {}).get("decisions") or []
        if row.get("scope") == "ANSWER_SEMANTIC_EVENT" and row.get("event_id")
    }
    exact_review = bool(review and review.get("decision") == "REVIEW_COMPLETED")
    reviewed_runs = sorted(admitted) if exact_review and all(event_id in decisions for event_id in pending_events) else []
    reuse = answer_diagnosis.get("review_reuse_provenance") or {}
    prefilled_event_ids = sorted(str(row.get("event_id")) for row in reuse.get("events") or [] if row.get("event_id"))
    prefilled_run_ids = sorted({int(value) for value in reuse.get("run_ids") or []})
    return {
        "contract_version": COVERAGE_PROJECTION_VERSION,
        "expected_run_ids": compute["expected_run_ids"],
        "valid_compute_run_ids": compute["valid_compute_run_ids"],
        "reviewed_run_ids": reviewed_runs,
        "unreviewed_valid_run_ids": sorted(admitted - set(reviewed_runs)),
        "pending_review_event_ids": sorted(pending_events),
        "reviewed_pending_event_ids": sorted(set(pending_events) & set(decisions)),
        "prefilled_event_ids": prefilled_event_ids,
        "prefilled_run_ids": prefilled_run_ids,
        "reviewed_run_count": len(reviewed_runs),
        "expected_run_count": len(compute["expected_run_ids"]),
        "exact_result_review_present": exact_review,
        "full_scope_review_complete": (
            exact_review
            and compute["all_runs_validly_understood"]
            and set(reviewed_runs) == set(compute["expected_run_ids"])
        ),
        "boundary": "PREFILL_IS_PROVENANCE_NOT_REVIEW_AUTHORITY",
    }


def evidence_plan_coverage(evidence_diagnosis: dict[str, Any]) -> dict[str, Any]:
    plan = evidence_diagnosis.get("candidate_plan") or {}
    reason_plans = plan.get("reason_plans") or []
    relations = evidence_diagnosis.get("source_relations") or []
    jobs = evidence_diagnosis.get("source_claim_jobs") or []
    if not reason_plans:
        reason_ids = sorted({str(row.get("reason_id")) for row in relations if row.get("reason_id")})
        recalled = sorted({str(row.get("reason_id")) for row in relations if row.get("candidate_recall") == "RECALLED"})
        return {
            "contract_version": COVERAGE_PROJECTION_VERSION,
            "plan_status": "LEGACY_PLAN_METADATA_INCOMPLETE" if reason_ids else "NOT_PLANNED",
            "plan_id": None,
            "plan_hash": None,
            "eligible_reason_ids": reason_ids,
            "planned_reason_ids": recalled,
            "unplanned_reason_ids": sorted(set(reason_ids) - set(recalled)),
            "base_candidate_count": sum(row.get("candidate_recall") == "RECALLED" for row in relations),
            "fallback_candidate_count": 0,
            "evaluated_relation_count": sum(row.get("alignment_evaluation") == "EVALUATED" for row in relations),
            "technical_failure_count": sum(str(row.get("status") or "").startswith("FAILED") for row in jobs),
            "not_evaluated_relation_count": sum(row.get("alignment_evaluation") != "EVALUATED" for row in relations),
            "execution_complete": False,
            "boundary": "LEGACY_RECALL_IS_NOT_A_FROZEN_COMPLETE_PLAN",
        }
    eligible = sorted(str(row.get("reason_id")) for row in reason_plans)
    planned = sorted(str(row.get("reason_id")) for row in reason_plans if row.get("status") == "PLANNED")
    return {
        "contract_version": COVERAGE_PROJECTION_VERSION,
        "plan_status": plan.get("status"),
        "plan_id": plan.get("plan_id"),
        "plan_hash": plan.get("plan_hash"),
        "policy_version": plan.get("policy_version"),
        "eligible_reason_ids": eligible,
        "planned_reason_ids": planned,
        "unplanned_reason_ids": sorted(set(eligible) - set(planned)),
        "base_candidate_count": sum(len(row.get("base_candidates") or []) for row in reason_plans),
        "fallback_candidate_count": sum(len(row.get("fallback_queue") or []) for row in reason_plans),
        "evaluated_relation_count": sum(row.get("alignment_evaluation") == "EVALUATED" for row in relations),
        "technical_failure_count": sum(str(row.get("status") or "").startswith("FAILED") for row in jobs),
        "partial_rejection_count": sum(int(row.get("rejected_claim_count") or 0) for row in jobs),
        "not_evaluated_relation_count": sum(row.get("alignment_evaluation") != "EVALUATED" for row in relations),
        "execution_complete": bool(plan.get("execution_complete")),
        "boundary": "PLAN_FROZEN_IS_NOT_EXECUTION_COMPLETE",
    }


def diagnosis_coverage_projections(
    raw_output: dict[str, Any],
    output: dict[str, Any],
    review: dict[str, Any] | None,
) -> dict[str, Any]:
    answer = output.get("answer_diagnosis") or {}
    compute = compute_coverage(raw_output, answer)
    reviewed = review_coverage(raw_output, answer, review)
    evidence = evidence_plan_coverage(output.get("evidence_diagnosis") or {})
    return {
        "input_scope_coverage": input_scope_coverage(raw_output),
        "compute_coverage": compute,
        "review_coverage": reviewed,
        "evidence_plan_coverage": evidence,
        "strategy_dependency_coverage": {
            "contract_version": COVERAGE_PROJECTION_VERSION,
            "global_nine_run_conclusion_eligible": bool(
                compute["all_runs_validly_understood"] and reviewed["full_scope_review_complete"]
            ),
            "reason_level_direction_evaluation_required": True,
            "boundary": "LOCAL_DIRECTION_ELIGIBILITY_DOES_NOT_AUTHORIZE_FULL_SCOPE_CONCLUSIONS",
        },
    }
