"""Shared EvidenceAlignment candidate builder for V1.1.

This module owns candidate membership only. It does not judge verdicts, read or
write materialization ledgers, or create EvidenceAlignment rows.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import Project, RecommendationEvent, ReferenceSource, SourceClaim, SourceDocument
from app.modules.optimization.evidence_alignment import (
    ALIGNMENT_MATERIALIZATION_CONTRACT,
    build_alignment_materialization_key,
    entity_scope_precheck,
)
from app.modules.optimization.passage_retrieval import (
    ANSWER_BINDING_REASON_SOURCE,
    EVENT_REASON_SOURCE,
    _clean_reason_text,
    _normalize_url_key,
    answer_binding_reason_inputs,
    tokenize_zh,
)
from app.modules.optimization.source_claim import SOURCE_CLAIM_MATERIALIZATION_CONTRACT, _source_claim_row_key
from app.services.serialization import loads

POLICY_A_HARD_TOPK = "POLICY_A_HARD_TOPK"
POLICY_B_THRESHOLD_WITH_CAP = "POLICY_B_THRESHOLD_WITH_CAP"
POLICY_C_TOPK_WITH_SCORE_MARGIN = "POLICY_C_TOPK_WITH_SCORE_MARGIN"
POLICY_D_TOPK_WITH_BOUNDARY_TIES = "POLICY_D_TOPK_WITH_BOUNDARY_TIES"
SELECTED_POLICY = POLICY_D_TOPK_WITH_BOUNDARY_TIES

RECALL_TOP_K = 5
RECALL_MIN_SCORE = 0.01
SCORE_TIE_EPSILON = 0.00001

ANSWER_UNIT_MATERIALIZATION_CONTRACT = "ANSWER_UNIT_SEMANTIC_V1"


def _compact(value: str) -> str:
    return " ".join((value or "").split())


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def score_bucket(score: float) -> float:
    return round(float(score or 0.0), 4)


def score_tied(left: float, right: float) -> bool:
    return abs(score_bucket(left) - score_bucket(right)) <= SCORE_TIE_EPSILON


def source_claim_semantic_hash_for_candidate(claim: SourceClaim) -> str:
    return _stable_hash({
        "contract_version": SOURCE_CLAIM_MATERIALIZATION_CONTRACT,
        "source_document_id": int(claim.source_document_id or 0),
        "passage_id": claim.passage_id or "",
        "subject_entity": _compact(claim.subject_entity or claim.subject_text or ""),
        "predicate": _compact(claim.predicate or ""),
        "object_text": _compact(claim.object_text or ""),
        "normalized_claim": _compact(claim.normalized_claim or claim.source_span or ""),
        "source_span": _compact(claim.source_span or ""),
        "claim_type": (claim.claim_type or "OTHER").upper(),
        "polarity": (claim.polarity or "NEUTRAL").upper(),
        "schema_version": claim.schema_version or "",
    })


def reason_semantic_hash_for_candidate(reason: dict) -> str:
    return _stable_hash({
        "contract_version": ANSWER_UNIT_MATERIALIZATION_CONTRACT,
        "text": _compact(reason.get("text") or ""),
        "scope": reason.get("scope") or "ENTITY_SPECIFIC",
        "entity": _compact(reason.get("entity") or ""),
        "reason_source": reason.get("reason_source") or "",
    })


def alignment_candidate_item(reason: dict, claim: SourceClaim, recall_path: str, score: float) -> dict:
    return {
        "reason": reason,
        "claim": claim,
        "recall_path": recall_path,
        "candidate_score": round(score, 4),
    }


def alignment_candidate_key(item: dict) -> str:
    return build_alignment_materialization_key(
        item["reason"]["text"],
        item["reason"]["scope"],
        item["reason"]["entity"],
        item["claim"],
        contract_version=ALIGNMENT_MATERIALIZATION_CONTRACT,
    )


def recall_level(recall_path: str | None) -> str:
    return {
        "EXPLICIT_BINDING": "L0_EXPLICIT",
        "ANSWER_CONTEXT": "L1_ANSWER_CONTEXT",
        "RUN_SCOPE": "L2_RUN_SCOPE",
        "PROMPT_SCOPE_RECALL": "L3_PROMPT_SCOPE",
    }.get(recall_path or "", "NONE")


def claim_recall_score(reason_text: str, claim: SourceClaim) -> float:
    reason_tokens = set(tokenize_zh(reason_text))
    claim_tokens = set(tokenize_zh(" ".join([
        claim.normalized_claim or "",
        claim.source_span or "",
        claim.predicate or "",
        claim.object_text or "",
    ])))
    if not reason_tokens or not claim_tokens:
        return 0.0
    return len(reason_tokens & claim_tokens) / max(len(reason_tokens), 1)


def build_alignment_reasons(
    db: Session,
    project: Project,
    prompt_id: int,
    run_ids: list[int],
    *,
    include_answer_binding_reasons: bool = True,
) -> dict[tuple[str, str, str], dict]:
    events = (
        db.query(RecommendationEvent)
        .filter(
            RecommendationEvent.project_id == project.id,
            RecommendationEvent.prompt_id == prompt_id,
            RecommendationEvent.run_id.in_(run_ids),
            RecommendationEvent.review_status.in_(["MACHINE_GROUNDED", "HUMAN_CONFIRMED"]),
        )
        .all()
    )
    unique: dict[tuple[str, str, str], dict] = {}
    for event in events:
        for item in loads(event.reasons_json, []):
            text = _clean_reason_text(item.get("normalized_reason") or "")
            if not text:
                continue
            scope = item.get("reason_scope") or "ENTITY_SPECIFIC"
            entity = event.entity_text if scope == "ENTITY_SPECIFIC" else ""
            key = (text, scope, entity)
            row = unique.setdefault(key, {
                "text": text,
                "scope": scope,
                "entity": entity,
                "reason_source": EVENT_REASON_SOURCE,
                "observations": [],
            })
            row["observations"].append({
                "run_id": event.run_id,
                "event_id": event.id,
                "reason_source": EVENT_REASON_SOURCE,
                "binding_strength": "",
            })

    binding_reasons = answer_binding_reason_inputs(db, project, prompt_id, run_ids) if include_answer_binding_reasons else []
    for item in binding_reasons:
        text = _clean_reason_text(item.get("text") or "")
        if not text:
            continue
        scope = item.get("scope") or "ENTITY_SPECIFIC"
        entity = item.get("entity") or ""
        key = (text, scope, entity)
        row = unique.setdefault(key, {
            "text": text,
            "scope": scope,
            "entity": entity,
            "reason_source": ANSWER_BINDING_REASON_SOURCE,
            "observations": [],
        })
        row["observations"].append({
            "run_id": item.get("run_id"),
            "event_id": item.get("event_id"),
            "reason_source": ANSWER_BINDING_REASON_SOURCE,
            "binding_strength": item.get("binding_strength") or "",
            "answer_unit_id": item.get("answer_unit_id"),
            "decision_binding_id": item.get("decision_binding_id"),
            "decision_role": item.get("decision_role"),
            "shadow_run_id": item.get("shadow_run_id"),
            "reason_id": item.get("reason_id"),
        })
    return unique


def citation_ids_by_run_doc(
    db: Session,
    *,
    run_ids: list[int],
    source_document_ids: set[int],
) -> dict[tuple[int, int], list[int]]:
    if not run_ids or not source_document_ids:
        return {}
    docs = db.query(SourceDocument).filter(SourceDocument.id.in_(source_document_ids)).all()
    doc_by_key: dict[str, int] = {}
    for doc in docs:
        for url in {doc.url, doc.original_url, doc.canonical_url}:
            key = _normalize_url_key(url or "")
            if key:
                doc_by_key[key] = int(doc.id)
    refs = db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(run_ids)).all()
    result: dict[tuple[int, int], list[int]] = defaultdict(list)
    for ref in refs:
        for url in {ref.canonical_url, ref.url}:
            key = _normalize_url_key(url or "")
            doc_id = doc_by_key.get(key)
            if doc_id:
                result[(int(ref.run_id), doc_id)].append(int(ref.id))
    return {key: sorted(set(ids)) for key, ids in result.items()}


def run_doc_ids_from_source_documents(
    db: Session,
    *,
    run_ids: list[int],
    source_documents: list[SourceDocument],
) -> dict[int, set[int]]:
    doc_by_key: dict[str, int] = {}
    for doc in source_documents:
        for url in {doc.url, doc.original_url, doc.canonical_url}:
            key = _normalize_url_key(url or "")
            if key:
                doc_by_key[key] = int(doc.id)
    refs = db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(run_ids)).all()
    result: dict[int, set[int]] = defaultdict(set)
    for ref in refs:
        for url in {ref.canonical_url, ref.url}:
            key = _normalize_url_key(url or "")
            doc_id = doc_by_key.get(key)
            if doc_id:
                result[int(ref.run_id)].add(doc_id)
    return result


def _boundary_tie_diagnostic(
    *,
    reason: dict,
    scored: list[tuple[float, str, SourceClaim]],
    top_k: int,
) -> tuple[dict | None, set[str]]:
    if not scored or len(scored) <= top_k:
        return None, set()
    cutoff_score = float(scored[top_k - 1][0])
    higher = [item for item in scored if score_bucket(item[0]) > score_bucket(cutoff_score)]
    tied = [item for item in scored if score_tied(item[0], cutoff_score)]
    expanded_keys = {key for score, key, _claim in scored if score_bucket(score) >= score_bucket(cutoff_score)}
    rank_start = len(higher) + 1
    rank_end = rank_start + len(tied) - 1
    return {
        "reason_text": reason.get("text", ""),
        "candidate_count_before_topk": len(scored),
        "top_k": top_k,
        "cutoff_score": score_bucket(cutoff_score),
        "boundary_tie_count": len(tied),
        "boundary_rank_start": rank_start,
        "boundary_rank_end": rank_end,
        "candidate_count_after_plain_topk": min(top_k, len(scored)),
        "candidate_count_after_tie_expansion": len(expanded_keys),
        "tie_bucket_source_claim_ids": [claim.id for _score, _key, claim in tied],
    }, expanded_keys


def tie_bucket_stats(diagnostics: list[dict]) -> dict:
    sizes = sorted(int(item.get("boundary_tie_count") or 0) for item in diagnostics)
    if not sizes:
        return {
            "reasons_with_boundary_ties": 0,
            "max_boundary_tie_bucket_size": 0,
            "p50_boundary_tie_bucket_size": 0,
            "p90_boundary_tie_bucket_size": 0,
            "coarse_score_tie_risk": False,
        }

    def percentile(percent: float) -> int:
        index = min(len(sizes) - 1, int(round((len(sizes) - 1) * percent)))
        return sizes[index]

    max_size = max(sizes)
    return {
        "reasons_with_boundary_ties": sum(1 for size in sizes if size > 1),
        "max_boundary_tie_bucket_size": max_size,
        "p50_boundary_tie_bucket_size": percentile(0.5),
        "p90_boundary_tie_bucket_size": percentile(0.9),
        "coarse_score_tie_risk": max_size > 25,
    }


def build_evidence_alignment_candidates(
    db: Session,
    *,
    project: Project,
    prompt_id: int,
    run_ids: list[int],
    claims: list[SourceClaim],
    run_doc_ids: dict[int, set[int]],
    top_k: int = RECALL_TOP_K,
    selected_policy: str = SELECTED_POLICY,
    include_answer_binding_reasons: bool = True,
) -> dict:
    recall_top_k = max(1, int(top_k or RECALL_TOP_K))
    reasons = build_alignment_reasons(
        db,
        project,
        prompt_id,
        run_ids,
        include_answer_binding_reasons=include_answer_binding_reasons,
    )
    deduped_claims: dict[tuple, SourceClaim] = {}
    for claim in sorted(claims, key=lambda row: row.id or 0):
        deduped_claims.setdefault(_source_claim_row_key(claim), claim)
    scoped_claims = list(deduped_claims.values())
    claims_by_doc: dict[int, list[SourceClaim]] = defaultdict(list)
    for claim in scoped_claims:
        claims_by_doc[int(claim.source_document_id or 0)].append(claim)
    citations = citation_ids_by_run_doc(
        db,
        run_ids=run_ids,
        source_document_ids={int(claim.source_document_id or 0) for claim in scoped_claims if claim.source_document_id},
    )

    bound_pairs: set[tuple[str, str]] = set()
    prompt_scope_pairs: set[tuple[str, str]] = set()
    hard_filtered_pairs: dict[tuple[str, str], dict] = {}
    current_candidate_items: dict[str, dict] = {}
    reason_diagnostics: dict[str, dict] = {}
    reason_run_scope_candidates: dict[tuple[str, str, str], list[SourceClaim]] = {}
    deterministic_counts = Counter()
    fallback_trigger_counts = Counter()
    l0_explicit_reason_count = 0

    for reason_key, reason in reasons.items():
        reason_hash = reason_semantic_hash_for_candidate(reason)
        binding_strengths = {
            str(obs.get("binding_strength") or "").upper()
            for obs in reason.get("observations") or []
            if obs.get("reason_source") == ANSWER_BINDING_REASON_SOURCE
        }
        binding_status = (
            "EXPLICIT"
            if {"HIGH", "MEDIUM"} & binding_strengths
            else "INFERRED_LOW"
            if binding_strengths
            else "NONE"
        )
        if binding_status == "EXPLICIT":
            l0_explicit_reason_count += 1
        observed_run_ids = {
            int(obs["run_id"])
            for obs in reason.get("observations") or []
            if obs.get("run_id")
        }
        observed_doc_ids = set()
        for run_id in observed_run_ids:
            observed_doc_ids.update(run_doc_ids.get(run_id, set()))
        l0_claims = [
            claim
            for doc_id in observed_doc_ids
            for claim in claims_by_doc.get(int(doc_id), [])
        ]
        l0_viable = 0
        for claim in l0_claims:
            pair = (reason_hash, source_claim_semantic_hash_for_candidate(claim))
            bound_pairs.add(pair)
            precheck = entity_scope_precheck(reason["scope"], reason["entity"], claim)
            if claim.subject_entity in {"", "UNKNOWN"}:
                deterministic_counts["INVALID_SUBJECT"] += 1
                continue
            if precheck == "COMPETITOR_CONTEXT":
                deterministic_counts["COMPETITOR_CONTEXT"] += 1
                continue
            if binding_status == "EXPLICIT":
                hard_filtered_pairs[pair] = alignment_candidate_item(reason, claim, "EXPLICIT_BINDING", 1.0)
            l0_viable += 1
        reason_run_scope_candidates[reason_key] = l0_claims
        reason_diagnostics[reason_hash] = {
            "binding_status": binding_status,
            "observed_run_ids": sorted(observed_run_ids),
            "observed_doc_ids": sorted(observed_doc_ids),
            "l0_viable": l0_viable,
            "has_answer_binding_observation": any(
                obs.get("reason_source") == ANSWER_BINDING_REASON_SOURCE
                for obs in reason.get("observations") or []
            ),
        }

        for claim in scoped_claims:
            prompt_scope_pairs.add((reason_hash, source_claim_semantic_hash_for_candidate(claim)))
            if claim.subject_entity in {"", "UNKNOWN"}:
                continue
            if entity_scope_precheck(reason["scope"], reason["entity"], claim) == "COMPETITOR_CONTEXT":
                continue
            current_item = alignment_candidate_item(reason, claim, "CURRENT_ALL_VIABLE_PAIRS", 1.0)
            current_candidate_items.setdefault(alignment_candidate_key(current_item), current_item)

    fallback_pairs: set[tuple[str, str]] = set()
    recall_pairs: dict[tuple[str, str], dict] = dict(hard_filtered_pairs)
    fallback_diagnostics: dict[str, dict] = {}
    all_candidate_items: dict[str, dict] = {}
    policy_b_extra_keys: set[str] = set()
    policy_c_extra_keys: set[str] = set()
    policy_d_extra_keys: set[str] = set()
    reason_recall_summaries: dict[str, dict] = {}
    l3_boundary_tie_diagnostics: list[dict] = []
    boundary_tie_by_key: dict[str, dict] = {}
    l2_attempted = 0
    l2_matched = 0
    l3_attempted = 0

    for reason_key, reason in reasons.items():
        reason_hash = reason_semantic_hash_for_candidate(reason)
        diagnostics = reason_diagnostics.get(reason_hash, {})
        if diagnostics.get("binding_status") == "EXPLICIT" and diagnostics.get("l0_viable", 0) > 0:
            reason_recall_summaries[reason_hash] = {
                "highest_recall_level_used": "L0_EXPLICIT",
                "fallback_trigger_reason": "explicit_binding_retained",
            }
            continue

        if diagnostics.get("binding_status") == "INFERRED_LOW":
            fallback_trigger_counts["binding_low"] += 1
        elif diagnostics.get("binding_status") == "NONE":
            fallback_trigger_counts["binding_missing"] += 1
        l2_attempted += 1
        l2_scored: list[tuple[float, str, SourceClaim]] = []
        l2_below_threshold = 0
        for claim in reason_run_scope_candidates.get(reason_key, []):
            pair = (reason_hash, source_claim_semantic_hash_for_candidate(claim))
            precheck = entity_scope_precheck(reason["scope"], reason["entity"], claim)
            if claim.subject_entity in {"", "UNKNOWN"}:
                deterministic_counts["INVALID_SUBJECT"] += 1
                continue
            if precheck == "COMPETITOR_CONTEXT":
                deterministic_counts["COMPETITOR_CONTEXT"] += 1
                continue
            fallback_pairs.add(pair)
            score = claim_recall_score(reason["text"], claim)
            item = alignment_candidate_item(reason, claim, "RUN_SCOPE", score)
            materialization_key = alignment_candidate_key(item)
            fallback_diagnostics[materialization_key] = {
                "recall_level": "L2_RUN_SCOPE",
                "lexical_score": round(score, 4),
                "rank_before_topk": None,
                "top_k": recall_top_k,
                "passed_score_threshold": score >= RECALL_MIN_SCORE,
            }
            if score >= RECALL_MIN_SCORE:
                l2_scored.append((score, materialization_key, claim))
            else:
                l2_below_threshold += 1
            all_candidate_items.setdefault(materialization_key, item)
        l2_scored.sort(key=lambda item: item[0], reverse=True)
        for rank, (_score, materialization_key, _claim) in enumerate(l2_scored, start=1):
            fallback_diagnostics[materialization_key]["rank_before_topk"] = rank
        if l2_scored:
            l2_matched += 1
            for score, _materialization_key, claim in l2_scored[:recall_top_k]:
                pair = (reason_hash, source_claim_semantic_hash_for_candidate(claim))
                recall_pairs[pair] = alignment_candidate_item(reason, claim, "RUN_SCOPE", score)
            reason_recall_summaries[reason_hash] = {
                "highest_recall_level_used": "L2_RUN_SCOPE",
                "fallback_trigger_reason": str(diagnostics.get("binding_status") or "NONE").lower(),
            }
            continue
        if l2_below_threshold:
            fallback_trigger_counts["below_threshold"] += 1
        else:
            fallback_trigger_counts["no_viable_candidate"] += 1

        l3_attempted += 1
        scored: list[tuple[float, str, SourceClaim]] = []
        below_threshold: list[tuple[float, str, SourceClaim]] = []
        for claim in scoped_claims:
            pair = (reason_hash, source_claim_semantic_hash_for_candidate(claim))
            precheck = entity_scope_precheck(reason["scope"], reason["entity"], claim)
            if claim.subject_entity in {"", "UNKNOWN"}:
                deterministic_counts["INVALID_SUBJECT"] += 1
                continue
            if precheck == "COMPETITOR_CONTEXT":
                deterministic_counts["COMPETITOR_CONTEXT"] += 1
                continue
            fallback_pairs.add(pair)
            score = claim_recall_score(reason["text"], claim)
            item = alignment_candidate_item(reason, claim, "PROMPT_SCOPE_RECALL", score)
            materialization_key = alignment_candidate_key(item)
            if score >= RECALL_MIN_SCORE:
                scored.append((score, materialization_key, claim))
            else:
                below_threshold.append((score, materialization_key, claim))
        scored.sort(key=lambda item: item[0], reverse=True)
        rank_cutoff_score = scored[min(recall_top_k, len(scored)) - 1][0] if scored else 0.0
        tie_diagnostic, policy_d_keys = _boundary_tie_diagnostic(reason=reason, scored=scored, top_k=recall_top_k)
        if tie_diagnostic:
            l3_boundary_tie_diagnostics.append(tie_diagnostic)
            for key in policy_d_keys:
                boundary_tie_by_key[key] = tie_diagnostic
            policy_d_extra_keys.update(policy_d_keys)
        for rank, (score, materialization_key, claim) in enumerate(scored, start=1):
            fallback_diagnostics[materialization_key] = {
                "recall_level": "L3_PROMPT_SCOPE",
                "lexical_score": round(score, 4),
                "rank_before_topk": rank,
                "top_k": recall_top_k,
                "passed_score_threshold": True,
                "rank_cutoff_score": round(rank_cutoff_score, 4),
                "score_delta_to_cutoff": round(score - rank_cutoff_score, 4),
                "number_above_threshold": len(scored),
            }
            all_candidate_items.setdefault(
                materialization_key,
                alignment_candidate_item(reason, claim, "PROMPT_SCOPE_RECALL", score),
            )
            if rank <= 25:
                policy_b_extra_keys.add(materialization_key)
            if rank <= recall_top_k or score >= max(rank_cutoff_score - 0.05, RECALL_MIN_SCORE):
                policy_c_extra_keys.add(materialization_key)
        for score, materialization_key, claim in below_threshold:
            fallback_diagnostics[materialization_key] = {
                "recall_level": "L3_PROMPT_SCOPE",
                "lexical_score": round(score, 4),
                "rank_before_topk": None,
                "top_k": recall_top_k,
                "passed_score_threshold": False,
                "rank_cutoff_score": round(rank_cutoff_score, 4),
                "score_delta_to_cutoff": round(score - rank_cutoff_score, 4),
                "number_above_threshold": len(scored),
            }
            all_candidate_items.setdefault(
                materialization_key,
                alignment_candidate_item(reason, claim, "PROMPT_SCOPE_RECALL", score),
            )
        for score, _materialization_key, claim in scored[:recall_top_k]:
            pair = (reason_hash, source_claim_semantic_hash_for_candidate(claim))
            recall_pairs[pair] = alignment_candidate_item(reason, claim, "PROMPT_SCOPE_RECALL", score)
        reason_recall_summaries[reason_hash] = {
            "highest_recall_level_used": "L3_PROMPT_SCOPE",
            "fallback_trigger_reason": "l2_below_threshold" if l2_below_threshold else "l2_no_viable_candidate",
        }

    hard_topk_items: dict[str, dict] = {}
    for item in recall_pairs.values():
        materialization_key = alignment_candidate_key(item)
        hard_topk_items.setdefault(materialization_key, item)
        all_candidate_items.setdefault(materialization_key, item)

    policy_candidate_keys = {
        POLICY_A_HARD_TOPK: set(hard_topk_items),
        POLICY_B_THRESHOLD_WITH_CAP: set(hard_topk_items) | policy_b_extra_keys,
        POLICY_C_TOPK_WITH_SCORE_MARGIN: set(hard_topk_items) | policy_c_extra_keys,
        POLICY_D_TOPK_WITH_BOUNDARY_TIES: set(hard_topk_items) | policy_d_extra_keys,
    }
    selected_keys = policy_candidate_keys.get(selected_policy, policy_candidate_keys[SELECTED_POLICY])
    selected_candidate_items = {
        key: all_candidate_items[key]
        for key in selected_keys
        if key in all_candidate_items
    }
    recall_layer_keys: dict[str, set[str]] = defaultdict(set)
    for key, item in selected_candidate_items.items():
        recall_layer_keys[recall_level(item.get("recall_path"))].add(key)

    l0_candidate_count = len(recall_layer_keys.get("L0_EXPLICIT", set()))
    if l0_candidate_count:
        l0_status = "L0_IMPLEMENTED_MATCH"
        l0_status_reason = "High/medium AnswerDecisionBinding observations produced explicit candidates that passed deterministic hard filters."
    elif l0_explicit_reason_count:
        l0_status = "L0_IMPLEMENTED_NO_MATCH"
        l0_status_reason = "Explicit AnswerDecisionBinding observations exist, but no explicit candidates survived deterministic hard filters."
    else:
        l0_status = "L0_IMPLEMENTED_NO_MATCH"
        l0_status_reason = "Current run scope has no high/medium explicit AnswerDecisionBinding observations for L0."

    l1_status = "L1_UNAVAILABLE_BY_SCHEMA"
    return {
        "builder_mode": "BINDING_AWARE_V1_1",
        "candidate_policy": selected_policy,
        "top_k": recall_top_k,
        "recall_min_score": RECALL_MIN_SCORE,
        "reasons": reasons,
        "scoped_claims": scoped_claims,
        "current_candidate_items": current_candidate_items,
        "hard_topk_candidate_items": hard_topk_items,
        "selected_candidate_items": selected_candidate_items,
        "all_candidate_items": all_candidate_items,
        "policy_candidate_keys": policy_candidate_keys,
        "reason_diagnostics": reason_diagnostics,
        "reason_recall_summaries": reason_recall_summaries,
        "fallback_diagnostics": fallback_diagnostics,
        "citation_ids_by_run_doc": citations,
        "recall_layer_keys": {key: set(value) for key, value in recall_layer_keys.items()},
        "deterministic_counts": dict(deterministic_counts),
        "fallback_trigger_counts": dict(fallback_trigger_counts),
        "bound_pairs_count": len(bound_pairs),
        "fallback_pairs_count": len(fallback_pairs),
        "prompt_scope_pairs_count": len(prompt_scope_pairs),
        "l0_status": l0_status,
        "l0_status_reason": l0_status_reason,
        "l0_explicit_reason_count": l0_explicit_reason_count,
        "l1_status": l1_status,
        "l1_status_reason": (
            "AnswerUnit rows expose normalized unit text and binding ids, but the current schema does not "
            "store reliable sentence/paragraph-level citation co-location for recall."
        ),
        "l2_status": (
            "L2_IMPLEMENTED_NO_TRIGGER"
            if l2_attempted == 0
            else "L2_IMPLEMENTED_MATCH"
            if l2_matched > 0
            else "L2_IMPLEMENTED_NO_MATCH"
        ),
        "l2_attempted_reason_count": l2_attempted,
        "l2_matched_reason_count": l2_matched,
        "l3_attempted_reason_count": l3_attempted,
        "boundary_tie_diagnostics": l3_boundary_tie_diagnostics,
        "boundary_tie_by_key": boundary_tie_by_key,
        "boundary_tie_stats": tie_bucket_stats(l3_boundary_tie_diagnostics),
        "deduped_source_claims": len(claims) - len(scoped_claims),
    }
