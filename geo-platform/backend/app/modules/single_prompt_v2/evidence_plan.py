"""Deterministic same-run Evidence candidate planning for V2."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.modules.optimization.evidence_alignment_candidates import (
    POLICY_D_TOPK_WITH_BOUNDARY_TIES,
    RECALL_MIN_SCORE,
    RECALL_TOP_K,
    score_tied,
)
from app.modules.optimization.passage_retrieval import RETRIEVAL_VERSION, retrieve_passages_for_reason


EVIDENCE_PLAN_POLICY_VERSION = "single_prompt_v2.evidence_plan.v1_same_run_boundary_ties"
EVIDENCE_BASE_TARGET = RECALL_TOP_K
EVIDENCE_TOTAL_CAP_PER_REASON = 12
EVIDENCE_FALLBACK_REPLACEMENTS_PER_REASON = 3


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _candidate_row(passage: dict[str, Any], rank: int, tier: str) -> dict[str, Any]:
    return {
        "passage_id": str(passage.get("passage_id") or ""),
        "source_snapshot_id": str(passage.get("snapshot_id") or ""),
        "source_key": str(passage.get("source_key") or ""),
        "rank": rank,
        "score": float(passage.get("bm25_score") or 0.0),
        "tier": tier,
    }


def build_evidence_candidate_plan(
    reasons: list[dict[str, Any]],
    passages: list[dict[str, Any]],
    observed_source_keys_by_run: dict[int, set[str]],
    explicit_source_keys_by_reason: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    by_id = {str(row.get("passage_id") or ""): row for row in passages}
    reason_plans: list[dict[str, Any]] = []
    for reason in sorted(reasons, key=lambda row: (int(row.get("run_id") or 0), str(row.get("reason_id") or ""))):
        reason_id = str(reason.get("reason_id") or "")
        run_id = int(reason.get("run_id") or 0)
        source_keys = observed_source_keys_by_run.get(run_id, set())
        explicit_source_keys = (explicit_source_keys_by_reason or {}).get(reason_id, set())
        run_passages = [row for row in passages if row.get("source_key") in source_keys]
        ranked = retrieve_passages_for_reason(
            str(reason.get("effective_grounded_text") or reason.get("reason_span") or ""),
            run_passages,
            top_k=max(len(run_passages), 1),
        )
        ranked.sort(key=lambda row: (
            0 if row.get("source_key") in explicit_source_keys else 1,
            -float(row.get("bm25_score") or 0.0),
            str(row.get("source_key") or ""),
            str(row.get("passage_id") or ""),
        ))
        # Preserve relevance order while ensuring different sources receive an
        # early candidate before additional passages from the same source.
        best_by_source: list[dict[str, Any]] = []
        remaining: list[dict[str, Any]] = []
        seen_sources: set[str] = set()
        for row in ranked:
            source_key = str(row.get("source_key") or row.get("snapshot_id") or "")
            if source_key not in seen_sources:
                seen_sources.add(source_key)
                best_by_source.append(row)
            else:
                remaining.append(row)
        diversified = best_by_source + remaining
        eligible = [row for row in diversified if float(row.get("bm25_score") or 0.0) >= RECALL_MIN_SCORE]
        if not source_keys:
            status, stop_reason = "NO_ELIGIBLE_SOURCE", "NO_SOURCE_OBSERVED_IN_REASON_RUN"
            base_rows: list[dict[str, Any]] = []
            fallback_rows: list[dict[str, Any]] = []
        elif not eligible:
            status, stop_reason = "NO_VIABLE_CANDIDATE", "NO_CANDIDATE_ABOVE_MIN_SCORE"
            base_rows, fallback_rows = [], []
        else:
            cutoff_index = min(EVIDENCE_BASE_TARGET, len(eligible)) - 1
            cutoff = float(eligible[cutoff_index].get("bm25_score") or 0.0)
            base_raw = [row for row in eligible if score_tied(float(row.get("bm25_score") or 0.0), cutoff) or float(row.get("bm25_score") or 0.0) > cutoff]
            base_raw = base_raw[:EVIDENCE_TOTAL_CAP_PER_REASON]
            base_ids = {str(row.get("passage_id") or "") for row in base_raw}
            fallback_raw = [row for row in eligible if str(row.get("passage_id") or "") not in base_ids]
            fallback_raw = fallback_raw[: max(EVIDENCE_TOTAL_CAP_PER_REASON - len(base_raw), 0)]
            base_rows = [_candidate_row(row, eligible.index(row) + 1, "BASE") for row in base_raw]
            fallback_rows = [_candidate_row(row, eligible.index(row) + 1, "FALLBACK") for row in fallback_raw]
            status = "PLANNED"
            stop_reason = "TOTAL_CAP_REACHED" if len(eligible) > len(base_rows) + len(fallback_rows) else "CANDIDATE_POOL_EXHAUSTED"
        pool_identity = [
            {
                "passage_id": str(row.get("passage_id") or ""),
                "source_snapshot_id": str(row.get("snapshot_id") or ""),
                "score": float(row.get("bm25_score") or 0.0),
            }
            for row in eligible
        ]
        reason_plans.append({
            "reason_id": reason_id,
            "run_id": run_id,
            "status": status,
            "observed_source_count": len(source_keys),
            "explicit_anchor_source_keys": sorted(explicit_source_keys),
            "candidate_pool_count": len(eligible),
            "candidate_pool_hash": _hash(pool_identity),
            "base_candidates": base_rows,
            "fallback_queue": fallback_rows,
            "fallback_replacement_cap": EVIDENCE_FALLBACK_REPLACEMENTS_PER_REASON,
            "stop_reason": stop_reason,
            "policy": POLICY_D_TOPK_WITH_BOUNDARY_TIES,
            "policy_version": EVIDENCE_PLAN_POLICY_VERSION,
            "retrieval_version": RETRIEVAL_VERSION,
        })
    payload = {
        "policy_version": EVIDENCE_PLAN_POLICY_VERSION,
        "reason_plans": reason_plans,
    }
    plan_hash = _hash(payload)
    return {
        "plan_id": f"evidence-plan-{plan_hash[:20]}",
        "plan_hash": plan_hash,
        "status": "FROZEN",
        "policy_version": EVIDENCE_PLAN_POLICY_VERSION,
        "base_target": EVIDENCE_BASE_TARGET,
        "total_cap_per_reason": EVIDENCE_TOTAL_CAP_PER_REASON,
        "reason_plans": reason_plans,
        "passages_by_id": by_id,
        "execution_complete": False,
    }
