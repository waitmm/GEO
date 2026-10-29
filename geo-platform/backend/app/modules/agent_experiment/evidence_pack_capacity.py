"""Offline-only Evidence Pack capacity projection.

This module deliberately does not execute a model or merge model outputs.  It
answers the narrower, auditable question: can every frozen Run/Citation/Source
identity be assigned to deterministic sub-packs that individually fit the
current single-request budget?

Turning those sub-packs into multiple model calls and combining their GEO
diagnosis/strategy/draft is a semantic change and is not authorized here.
"""

from __future__ import annotations

import json
from typing import Any

from app.modules.single_prompt_v2.delivery_text import digest

from .evidence_pack import (
    DEFAULT_TEXT_BUDGET,
    EvidencePackCapacityError,
    _citation_occurrences,
    build_evidence_pack,
    render_evidence_pack_prompt,
)


CAPACITY_PLAN_CONTRACT = "geo.evidence-pack.capacity-plan.shadow.v1"
DEFAULT_MAX_OUTPUT_TOKENS = 16_384
DEFAULT_TASK_TOKEN_CAP = 300_000


def model_input_characters(payload: dict[str, Any]) -> int:
    """Return the exact JSON character count used by the current transport."""
    return len(json.dumps(payload, ensure_ascii=False))


def responses_text_budget_projection(
    payload: dict[str, Any], *, max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
) -> dict[str, int]:
    """Mirror the production Responses text request-guard reservation."""
    body = {
        "model": "deepseek-flash",
        "instructions": render_evidence_pack_prompt(),
        "input": json.dumps(payload, ensure_ascii=False),
        "temperature": 0.0,
        "max_output_tokens": max_output_tokens,
        "reasoning": {"effort": "none"},
    }
    request_body_utf8_bytes = len(json.dumps(body, ensure_ascii=False).encode("utf-8"))
    input_token_upper_bound = request_body_utf8_bytes + 4_096
    return {
        "request_body_utf8_bytes": request_body_utf8_bytes,
        "input_token_upper_bound": input_token_upper_bound,
        "max_output_tokens": max_output_tokens,
        "total_token_reservation": input_token_upper_bound + max_output_tokens,
    }


def _run_id(value: Any) -> str:
    return str(value)


def _scope_for_runs(scope: dict[str, Any], run_ids: list[str]) -> dict[str, Any]:
    """Create an in-memory projection; never claim it is a new frozen scope."""
    selected = set(run_ids)
    projected = dict(scope)
    projected["runs"] = [
        row for row in scope.get("runs") or []
        if _run_id(row.get("run_id")) in selected
    ]

    manifest = scope.get("citation_manifest")
    if isinstance(manifest, dict) and isinstance(manifest.get("payload"), dict):
        payload = dict(manifest["payload"])
        payload["occurrences"] = [
            row for row in manifest["payload"].get("occurrences") or []
            if _run_id(row.get("run_id")) in selected
        ]
        projected["citation_manifest"] = {**manifest, "payload": payload}

    cited_urls = {
        str(row.get("canonical_url") or "")
        for row in _citation_occurrences(projected)
    }
    cited_urls.discard("")
    projected["source_snapshots"] = [
        row for row in projected.get("source_snapshots") or []
        if str(row.get("canonical_url") or "") in cited_urls
    ]
    selected_source_keys = {
        str(row.get("source_key") or "")
        for row in projected["source_snapshots"]
        if row.get("source_key")
    }
    projected["source_dispositions"] = [
        row for row in projected.get("source_dispositions") or []
        if str(row.get("source_key") or "") in selected_source_keys
    ]
    return projected


def _try_batch(
    scope: dict[str, Any], run_ids: list[str], *, text_budget: int,
    max_output_tokens: int, task_token_cap: int,
) -> tuple[bool, dict[str, Any]]:
    projected = _scope_for_runs(scope, run_ids)
    try:
        pack = build_evidence_pack(projected, text_budget=text_budget)
    except EvidencePackCapacityError as exc:
        return False, {"reason": str(exc)}

    coverage = pack["coverage"]
    actual_characters = model_input_characters(pack)
    request_budget = responses_text_budget_projection(
        pack, max_output_tokens=max_output_tokens,
    )
    if coverage["citation_evidence_omitted"]:
        return False, {
            "reason": "CITATION_CATALOG_OMITTED",
            "omitted": coverage["citation_evidence_omitted"],
            "actual_model_input_characters": actual_characters,
        }
    if coverage["source_passage_omitted"]:
        return False, {
            "reason": "SOURCE_PASSAGE_OMITTED",
            "omitted": coverage["source_passage_omitted"],
            "actual_model_input_characters": actual_characters,
        }
    if actual_characters > text_budget:
        return False, {
            "reason": "SERIALIZED_MODEL_INPUT_EXCEEDS_BUDGET",
            "actual_model_input_characters": actual_characters,
            "text_budget": text_budget,
        }
    if request_budget["total_token_reservation"] > task_token_cap:
        return False, {
            "reason": "SINGLE_BATCH_TOKEN_RESERVATION_EXCEEDS_TASK_CAP",
            **request_budget,
            "task_token_cap": task_token_cap,
        }
    occurrences = _citation_occurrences(projected)
    return True, {
        "pack": pack,
        "projected_scope": projected,
        "actual_model_input_characters": actual_characters,
        "request_budget": request_budget,
        "citation_occurrence_ids": [
            str(row["citation_occurrence_id"]) for row in occurrences
        ],
        "source_snapshot_ids": [
            str(row.get("snapshot_id")) for row in projected.get("source_snapshots") or []
        ],
    }


def plan_evidence_pack_batches(
    scope: dict[str, Any], *, text_budget: int = DEFAULT_TEXT_BUDGET,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    task_token_cap: int = DEFAULT_TASK_TOKEN_CAP,
) -> dict[str, Any]:
    """Plan deterministic full-coverage sub-packs without executing them.

    A READY plan proves only input partition feasibility.  It does not authorize
    multi-call execution or claim that independently generated prose can be
    merged without a dedicated semantic contract.
    """
    runs = sorted(scope.get("runs") or [], key=lambda row: int(row.get("run_id", 0)))
    ordered_ids = [_run_id(row.get("run_id")) for row in runs]
    scope_hash = digest(scope)
    all_occurrences = _citation_occurrences(scope)
    expected_citations = {
        str(row["citation_occurrence_id"]) for row in all_occurrences
    }
    all_snapshots = {
        str(row.get("snapshot_id")) for row in scope.get("source_snapshots") or []
    }
    cited_urls = {
        str(row.get("canonical_url") or "") for row in all_occurrences
        if row.get("canonical_url")
    }
    unassigned_snapshots = sorted(
        str(row.get("snapshot_id"))
        for row in scope.get("source_snapshots") or []
        if not row.get("canonical_url")
        or str(row.get("canonical_url")) not in cited_urls
    )

    batches: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    cursor = 0
    covered_citations: set[str] = set()
    covered_snapshots: set[str] = set()
    while cursor < len(ordered_ids):
        low, high = 1, len(ordered_ids) - cursor
        best_count = 0
        best: dict[str, Any] | None = None
        last_failure: dict[str, Any] = {}
        while low <= high:
            count = (low + high) // 2
            candidate_ids = ordered_ids[cursor:cursor + count]
            fits, details = _try_batch(
                scope, candidate_ids, text_budget=text_budget,
                max_output_tokens=max_output_tokens, task_token_cap=task_token_cap,
            )
            if fits:
                best_count, best = count, details
                low = count + 1
            else:
                last_failure = details
                high = count - 1
        if not best_count or best is None:
            run_id = ordered_ids[cursor]
            fits, details = _try_batch(
                scope, [run_id], text_budget=text_budget,
                max_output_tokens=max_output_tokens, task_token_cap=task_token_cap,
            )
            assert not fits
            blocked.append({"run_id": run_id, **(details or last_failure)})
            cursor += 1
            continue

        batch_run_ids = ordered_ids[cursor:cursor + best_count]
        pack = best["pack"]
        citation_ids = best["citation_occurrence_ids"]
        snapshot_ids = best["source_snapshot_ids"]
        covered_citations.update(citation_ids)
        covered_snapshots.update(snapshot_ids)
        batch_number = len(batches) + 1
        batch_identity = {
            "frozen_scope_hash": scope_hash,
            "batch_number": batch_number,
            "run_ids": batch_run_ids,
            "citation_occurrence_ids": citation_ids,
            "source_snapshot_ids": snapshot_ids,
            "evidence_pack_hash": pack["evidence_pack_hash"],
        }
        batches.append({
            **batch_identity,
            "batch_hash": digest(batch_identity),
            "actual_model_input_characters": best["actual_model_input_characters"],
            **best["request_budget"],
            "logical_evidence_characters": pack["coverage"]["estimated_text_characters"],
            "unique_citation_catalog_entries": pack["coverage"]["citation_evidence_total"],
            "citation_occurrence_count": pack["coverage"]["citation_occurrence_count"],
            "source_passage_count": pack["coverage"]["source_passage_total"],
        })
        cursor += best_count

    missing_runs = sorted(set(ordered_ids) - {
        run_id for batch in batches for run_id in batch["run_ids"]
    } - {row["run_id"] for row in blocked}, key=int)
    missing_citations = sorted(expected_citations - covered_citations)
    missing_snapshots = sorted(all_snapshots - covered_snapshots)
    partition_status = "READY" if not (
        blocked or missing_runs or missing_citations or missing_snapshots or unassigned_snapshots
    ) else "REVIEW_REQUIRED"
    aggregate_token_reservation = sum(
        int(row["total_token_reservation"]) for row in batches
    )
    aggregate_budget_status = (
        "WITHIN_TASK_CAP" if aggregate_token_reservation <= task_token_cap
        else "AGGREGATE_TASK_TOKEN_RESERVATION_EXCEEDS_CAP"
    )
    status = (
        "READY" if partition_status == "READY" and aggregate_budget_status == "WITHIN_TASK_CAP"
        else "REVIEW_REQUIRED"
    )
    plan = {
        "contract_version": CAPACITY_PLAN_CONTRACT,
        "mode": "SHADOW_ONLY_NO_MODEL_EXECUTION_NO_RESULT_MERGE",
        "status": status,
        "frozen_scope_hash": scope_hash,
        "text_budget": text_budget,
        "max_output_tokens_per_batch": max_output_tokens,
        "task_token_cap": task_token_cap,
        "partition_status": partition_status,
        "aggregate_budget_status": aggregate_budget_status,
        "aggregate_input_token_upper_bound": sum(
            int(row["input_token_upper_bound"]) for row in batches
        ),
        "aggregate_output_token_reservation": sum(
            int(row["max_output_tokens"]) for row in batches
        ),
        "aggregate_total_token_reservation": aggregate_token_reservation,
        "batch_count": len(batches),
        "batches": batches,
        "blocked_runs": blocked,
        "coverage": {
            "run_total": len(ordered_ids),
            "run_planned": sum(len(row["run_ids"]) for row in batches),
            "citation_occurrence_total": len(expected_citations),
            "citation_occurrence_covered": len(covered_citations),
            "source_snapshot_total": len(all_snapshots),
            "source_snapshot_covered": len(covered_snapshots),
            "missing_run_ids": missing_runs,
            "missing_citation_occurrence_ids": missing_citations,
            "missing_source_snapshot_ids": missing_snapshots,
            "unassigned_source_snapshot_ids": unassigned_snapshots,
        },
        "cutover_blocker": (
            "SEMANTIC_CONTRACT_REVIEW_REQUIRED:MULTI_BATCH_RESULT_MERGE"
        ),
    }
    plan["plan_hash"] = digest(plan)
    return plan
