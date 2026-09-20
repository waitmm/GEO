"""Read-only planner for V1.1 incremental materialization.

The planner does not execute LLM calls, fetch pages, mutate workflow state, or
create downstream business objects. It only explains how much expensive work is
already reusable for the current Prompt Run scope.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    AnswerDecisionBinding,
    AnswerUnit,
    BrowserMonitorRun,
    DecisionGapDiagnosis,
    EvidenceAlignment,
    EvidenceAlignmentMaterialization,
    LLMCallCache as LLMCallCacheRow,
    OptimizationEvidencePackage,
    OptimizationStrategyCandidate,
    Project,
    RecommendationEvent,
    RecommendationIntelligenceSnapshot,
    ReferenceSource,
    SourceClaim,
    SourceClaimMaterialization,
    SourceDocument,
    SourceQuality,
)
from app.modules.optimization.evidence_alignment import (
    ALIGNMENT_MATERIALIZATION_CONTRACT,
    ALIGNMENT_PROMPT_VERSION,
    ALIGNMENT_SCHEMA_VERSION,
    ALIGNMENT_SYSTEM,
    alignment_llm_input_hash,
    alignment_source_claim_semantic_hash,
    build_alignment_materialization_key,
    entity_scope_precheck,
    resolve_alignment_materialization_compatibility,
)
from app.modules.optimization.evidence_alignment_candidates import (
    POLICY_A_HARD_TOPK,
    POLICY_B_THRESHOLD_WITH_CAP,
    POLICY_C_TOPK_WITH_SCORE_MARGIN,
    POLICY_D_TOPK_WITH_BOUNDARY_TIES,
    SELECTED_POLICY,
    alignment_candidate_item,
    alignment_candidate_key,
    build_evidence_alignment_candidates,
    claim_recall_score,
    recall_level,
    reason_semantic_hash_for_candidate,
    source_claim_semantic_hash_for_candidate,
)
from app.modules.optimization.evidence_lineage import eligible_evidence_alignments_for_v1
from app.modules.optimization.passage_retrieval import (
    ANSWER_BINDING_REASON_SOURCE,
    EVENT_REASON_SOURCE,
    FORMAL_V1_1_INPUT_VERSION,
    _cited_document_ids_for_runs,
    _clean_reason_text,
    _normalize_url_key,
    _split_document_passages,
    answer_binding_reason_inputs,
    tokenize_zh,
)
from app.modules.optimization.source_claim import (
    SOURCE_CLAIM_MATERIALIZATION_CONTRACT,
    SOURCE_CLAIM_PROMPT_VERSION,
    SOURCE_CLAIM_SCHEMA_VERSION,
    SOURCE_CLAIM_SYSTEM,
    _legacy_source_claim_rows_are_backfillable,
    _source_claim_row_key,
    build_source_claim_materialization_key,
    normalize_source_claim_extraction_input,
    resolve_source_claim_materialization_compatibility,
    source_claim_llm_input_hash,
    source_claim_passage_content_hash,
)
from app.modules.optimization.source_qualification import derive_content_status
from app.services.serialization import loads


ANSWER_UNIT_MATERIALIZATION_CONTRACT = "ANSWER_UNIT_SEMANTIC_V1"
PLANNER_VERSION = "incremental_materialization_planner.v1"

MATERIALIZATION_STATUSES = [
    "HIT",
    "MISSING",
    "IN_PROGRESS",
    "STALE_CONTENT",
    "STALE_SCHEMA",
    "STALE_MODEL",
    "STALE_PROMPT",
    "STALE_SOURCE_SNAPSHOT",
    "FAILED_RETRYABLE",
    "FAILED_FINAL",
    "INVALID",
]

_SOURCE_SNAPSHOT_STALE_AFTER = timedelta(days=30)
_RECALL_TOP_K = 10
_RECALL_MIN_SCORE = 0.01
_SCORE_TIE_EPSILON = 0.00001


def _compact(value: str) -> str:
    return " ".join((value or "").split())


def _stable_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _score_bucket(score: float) -> float:
    return round(float(score or 0.0), 4)


def _score_tied(left: float, right: float) -> bool:
    return abs(_score_bucket(left) - _score_bucket(right)) <= _SCORE_TIE_EPSILON


def _llm_input_hash(system_prompt: str, user_payload: dict, prompt_version: str, schema_version: str) -> str:
    raw = json.dumps(
        {"system": system_prompt, "payload": user_payload, "pv": prompt_version, "sv": schema_version},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _latest_prompt_evidence_package(
    db: Session,
    project_id: int,
    prompt_id: int,
) -> OptimizationEvidencePackage | None:
    return (
        db.query(OptimizationEvidencePackage)
        .filter(
            OptimizationEvidencePackage.project_id == project_id,
            OptimizationEvidencePackage.prompt_id == prompt_id,
            OptimizationEvidencePackage.status == "active",
        )
        .order_by(OptimizationEvidencePackage.version.desc(), OptimizationEvidencePackage.id.desc())
        .first()
    )


def _current_run_scope(
    db: Session,
    project_id: int,
    prompt_id: int,
    explicit_run_ids: list[int] | None = None,
) -> tuple[list[int], str, OptimizationEvidencePackage | None]:
    if explicit_run_ids:
        return sorted({int(run_id) for run_id in explicit_run_ids}), "EXPLICIT_RUN_IDS", None

    package = _latest_prompt_evidence_package(db, project_id, prompt_id)
    if package is not None:
        package_run_ids = sorted({int(run_id) for run_id in loads(package.source_run_ids_json, []) if run_id})
        if package_run_ids:
            return package_run_ids, "ACTIVE_EVIDENCE_PACKAGE", package

    rows = (
        db.query(BrowserMonitorRun.id)
        .filter(
            BrowserMonitorRun.project_id == project_id,
            BrowserMonitorRun.prompt_id == prompt_id,
            BrowserMonitorRun.status.in_(["success", "partial_success"]),
        )
        .order_by(BrowserMonitorRun.id.asc())
        .all()
    )
    return [int(row[0]) for row in rows], "PROMPT_SUCCESSFUL_RUNS", package


def _cache_hit_count(
    db: Session,
    *,
    provider: str,
    model: str,
    prompt_version: str,
    schema_version: str,
    input_hashes: set[str],
) -> int:
    if not input_hashes:
        return 0
    hashes = list(input_hashes)
    hit_count = 0
    for start in range(0, len(hashes), 500):
        chunk = hashes[start:start + 500]
        hit_count += (
            db.query(LLMCallCacheRow.input_hash)
            .filter(
                LLMCallCacheRow.provider == provider,
                LLMCallCacheRow.model == model,
                LLMCallCacheRow.prompt_version == prompt_version,
                LLMCallCacheRow.schema_version == schema_version,
                LLMCallCacheRow.input_hash.in_(chunk),
            )
            .distinct()
            .count()
        )
    return hit_count


def _source_claim_llm_hash(passage_text: str) -> str:
    return _llm_input_hash(
        SOURCE_CLAIM_SYSTEM,
        {"passage": passage_text},
        SOURCE_CLAIM_PROMPT_VERSION,
        SOURCE_CLAIM_SCHEMA_VERSION,
    )


def _alignment_llm_hash(reason_text: str, claim_text: str) -> str:
    return _llm_input_hash(
        ALIGNMENT_SYSTEM,
        {"reason": reason_text, "source_claim": claim_text},
        ALIGNMENT_PROMPT_VERSION,
        ALIGNMENT_SCHEMA_VERSION,
    )


def _source_claim_semantic_hash(claim: SourceClaim) -> str:
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


def _answer_unit_semantic_hash(unit: AnswerUnit, binding_events: list[RecommendationEvent]) -> str:
    payload = loads(unit.machine_payload_json, {})
    event_entities = sorted({_compact(event.entity_text or "") for event in binding_events if event.entity_text})
    speech_acts = sorted({_compact(event.speech_act or "") for event in binding_events if event.speech_act})
    return _stable_hash({
        "contract_version": ANSWER_UNIT_MATERIALIZATION_CONTRACT,
        "semantic_schema_version": unit.extraction_version or "",
        "resolved_entity": _compact(unit.entity_hint or "") or event_entities,
        "semantic_type": unit.semantic_type or "",
        "proposition": _compact(unit.unit_text_normalized or unit.unit_text_original or ""),
        "source_span": _compact(unit.source_span or ""),
        "speech_acts": speech_acts,
        "predicate": payload.get("predicate") or "",
        "object": payload.get("object") or "",
        "capability": payload.get("capability") or payload.get("capability_key") or "",
        "attribute": payload.get("attribute") or payload.get("qualifier") or "",
        "polarity": payload.get("polarity") or "",
        "negation": payload.get("negation") or payload.get("is_negated") or False,
        "epistemic_status": payload.get("epistemic_status") or "",
    })


def _reason_semantic_hash(reason: dict) -> str:
    return _stable_hash({
        "contract_version": ANSWER_UNIT_MATERIALIZATION_CONTRACT,
        "text": _compact(reason.get("text") or ""),
        "scope": reason.get("scope") or "ENTITY_SPECIFIC",
        "entity": _compact(reason.get("entity") or ""),
        "reason_source": reason.get("reason_source") or "",
    })


def _build_alignment_reasons(
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
        })
    return unique


def _claim_recall_score(reason_text: str, claim: SourceClaim) -> float:
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


def _document_plan(
    db: Session,
    run_ids: list[int],
) -> tuple[dict, list[SourceDocument], dict[int, set[int]], dict[str, int]]:
    references = db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(run_ids)).all()
    docs = db.query(SourceDocument).all()
    doc_by_key: dict[str, SourceDocument] = {}
    for doc in docs:
        for url in {doc.url, doc.original_url, doc.canonical_url}:
            key = _normalize_url_key(url or "")
            if key:
                doc_by_key[key] = doc

    unique_ref_keys = {
        _normalize_url_key(ref.canonical_url or ref.url or "")
        for ref in references
        if _normalize_url_key(ref.canonical_url or ref.url or "")
    }
    matched_docs = {doc_by_key[key].id: doc_by_key[key] for key in unique_ref_keys if key in doc_by_key}
    missing_url_keys = sorted(key for key in unique_ref_keys if key not in doc_by_key)

    docs_by_id = {doc.id: doc for doc in docs}
    cited_doc_ids = _cited_document_ids_for_runs(db, run_ids, docs)
    required_docs = [docs_by_id[doc_id] for doc_id in sorted(cited_doc_ids) if doc_id in docs_by_id]

    run_doc_ids: dict[int, set[int]] = defaultdict(set)
    for ref in references:
        for url in {ref.canonical_url, ref.url}:
            key = _normalize_url_key(url or "")
            if key in doc_by_key:
                run_doc_ids[int(ref.run_id)].add(int(doc_by_key[key].id))

    quality_by_doc_id: dict[int, SourceQuality] = {}
    for quality in db.query(SourceQuality).order_by(SourceQuality.id.desc()).all():
        quality_by_doc_id.setdefault(quality.source_document_id, quality)

    state_counts = Counter()
    now = datetime.utcnow()
    for doc in required_docs:
        content = derive_content_status(doc, quality_by_doc_id.get(doc.id))
        if content.get("content_status") != "CONTENT_VALID":
            state_counts["MISSING" if content.get("content_status") == "CONTENT_PENDING" else "INVALID"] += 1
        elif doc.fetch_time and now - doc.fetch_time > _SOURCE_SNAPSHOT_STALE_AFTER:
            state_counts["STALE_SOURCE_SNAPSHOT"] += 1
        else:
            state_counts["HIT"] += 1

    return {
        "observed_citation_records": len(references),
        "unique_canonical_urls": len(unique_ref_keys),
        "required_documents": len(required_docs),
        "source_document_hit": len(matched_docs),
        "missing_source_documents": len(missing_url_keys),
        "state_counts": dict(state_counts),
        "missing_url_sample": missing_url_keys[:5],
    }, required_docs, run_doc_ids, {key: doc.id for key, doc in doc_by_key.items()}


def _passage_plan(required_docs: list[SourceDocument]) -> tuple[dict, list[dict]]:
    state_counts = Counter()
    passages: list[dict] = []
    for doc in required_docs:
        doc_passages = _split_document_passages(doc)
        if doc_passages:
            state_counts["HIT"] += len(doc_passages)
            passages.extend(doc_passages)
        elif (doc.clean_text or "").strip():
            state_counts["MISSING"] += 1
        else:
            state_counts["INVALID"] += 1
    return {
        "required": len(passages),
        "hit": state_counts.get("HIT", 0),
        "missing": state_counts.get("MISSING", 0),
        "stale": 0,
        "state_counts": dict(state_counts),
        "storage_mode": "DERIVED_FROM_SOURCE_DOCUMENT",
    }, passages


def _source_claim_plan(db: Session, project: Project, passages: list[dict]) -> tuple[dict, list[SourceClaim]]:
    settings = get_settings()
    doc_ids = {int(passage["doc_id"]) for passage in passages if passage.get("doc_id")}
    source_claim_rows = (
        db.query(SourceClaim)
        .filter(
            SourceClaim.project_id == project.id,
            SourceClaim.source_document_id.in_(doc_ids),
        )
        .all()
        if doc_ids else []
    )
    valid_claims = [row for row in source_claim_rows if row.review_status == "MACHINE_GROUNDED"]
    claims_by_passage: dict[tuple[int, str], list[SourceClaim]] = defaultdict(list)
    for claim in valid_claims:
        claims_by_passage[(int(claim.source_document_id or 0), claim.passage_id or "")].append(claim)
    all_claims_by_passage: dict[tuple[int, str], list[SourceClaim]] = defaultdict(list)
    for claim in source_claim_rows:
        all_claims_by_passage[(int(claim.source_document_id or 0), claim.passage_id or "")].append(claim)

    state_counts = Counter()
    passage_state_counts = Counter()
    materialization_jobs: dict[str, list[dict]] = defaultdict(list)
    source_claim_hashes: set[str] = set()
    empty_content_count = 0
    for passage in passages:
        extraction_input = normalize_source_claim_extraction_input(passage.get("text") or "")
        if not extraction_input:
            empty_content_count += 1
            continue
        materialization_key = build_source_claim_materialization_key(extraction_input)
        materialization_jobs[materialization_key].append({
            **passage,
            "text": extraction_input,
            "passage_content_hash": source_claim_passage_content_hash(extraction_input),
        })
        input_hash = source_claim_llm_input_hash(extraction_input)
        source_claim_hashes.add(input_hash)

    materializations = {
        row.materialization_key: row
        for row in db.query(SourceClaimMaterialization)
        .filter(SourceClaimMaterialization.materialization_key.in_(list(materialization_jobs.keys())))
        .all()
    } if materialization_jobs else {}

    materialization_hit_count = 0
    zero_claim_hit_count = 0
    legacy_reuse_count = 0
    stale_count = 0
    incompatible_count = 0
    in_progress_count = 0
    failed_retryable_count = 0
    failed_final_count = 0
    missing_materialization_hashes: set[str] = set()

    for materialization_key, group in materialization_jobs.items():
        compatibility = resolve_source_claim_materialization_compatibility(materializations.get(materialization_key))
        group_size = len(group)
        if compatibility == "COMPATIBLE":
            materialization_hit_count += 1
            state_counts["HIT"] += 1
            passage_state_counts["HIT"] += group_size
            if int(materializations[materialization_key].claim_count or 0) == 0:
                zero_claim_hit_count += 1
            continue

        representative = group[0]
        passage_key = (int(representative["doc_id"]), representative["passage_id"])
        doc = db.get(SourceDocument, representative["doc_id"])
        legacy_rows = all_claims_by_passage.get(passage_key, [])
        if compatibility == "MISSING" and doc and _legacy_source_claim_rows_are_backfillable(legacy_rows, doc):
            legacy_reuse_count += 1
            state_counts["LEGACY_REUSABLE"] += 1
            passage_state_counts["HIT"] += group_size
            continue

        if compatibility == "STALE_SCHEMA":
            stale_count += 1
            state_counts["STALE_SCHEMA"] += 1
            passage_state_counts["STALE_SCHEMA"] += group_size
        elif compatibility == "IN_PROGRESS":
            in_progress_count += 1
            state_counts["IN_PROGRESS"] += 1
            passage_state_counts["IN_PROGRESS"] += group_size
        elif compatibility == "FAILED_RETRYABLE":
            failed_retryable_count += 1
            state_counts["FAILED_RETRYABLE"] += 1
            passage_state_counts["FAILED_RETRYABLE"] += group_size
        elif compatibility == "FAILED_FINAL":
            failed_final_count += 1
            state_counts["FAILED_FINAL"] += 1
            passage_state_counts["FAILED_FINAL"] += group_size
        elif compatibility == "MISSING":
            state_counts["MISSING"] += 1
            passage_state_counts["MISSING"] += group_size
        else:
            incompatible_count += 1
            state_counts["INCOMPATIBLE"] += 1
            passage_state_counts["INCOMPATIBLE"] += group_size
        if compatibility in {"MISSING", "FAILED_RETRYABLE"}:
            missing_materialization_hashes.add(source_claim_llm_input_hash(representative.get("text") or ""))

    llm_cache_hits = _cache_hit_count(
        db,
        provider="deepseek",
        model=settings.deepseek_model,
        prompt_version=SOURCE_CLAIM_PROMPT_VERSION,
        schema_version=SOURCE_CLAIM_SCHEMA_VERSION,
        input_hashes=source_claim_hashes,
    )
    missing_llm_cache_hits = _cache_hit_count(
        db,
        provider="deepseek",
        model=settings.deepseek_model,
        prompt_version=SOURCE_CLAIM_PROMPT_VERSION,
        schema_version=SOURCE_CLAIM_SCHEMA_VERSION,
        input_hashes=missing_materialization_hashes,
    )
    duplicate_claim_rows = len(source_claim_rows) - len({_source_claim_row_key(row) for row in source_claim_rows})
    unique_extraction_inputs = len(materialization_jobs)
    lookup_first_llm_required = max(len(missing_materialization_hashes) - missing_llm_cache_hits, 0)
    object_conservation_total = (
        materialization_hit_count
        + legacy_reuse_count
        + state_counts.get("MISSING", 0)
        + stale_count
        + in_progress_count
        + failed_retryable_count
        + failed_final_count
        + incompatible_count
    )
    missing_total = state_counts.get("MISSING", 0) + failed_retryable_count
    missing_no_external_llm_breakdown = {
        "llm_call_cache_hit": missing_llm_cache_hits,
        "invalid_input": 0,
        "empty_content": 0,
        "deduped_elsewhere": 0,
    }
    missing_conservation_total = (
        lookup_first_llm_required
        + sum(missing_no_external_llm_breakdown.values())
    )
    source_claim_dedupe_ratio = (
        1 - (unique_extraction_inputs / len(passages))
        if passages else 0.0
    )
    source_claim_cache_hit_rate = (
        (materialization_hit_count + legacy_reuse_count) / unique_extraction_inputs
        if unique_extraction_inputs else 1.0
    )
    return {
        "required_passage_rows": len(passages),
        "unique_extraction_inputs": unique_extraction_inputs,
        "required_semantic_passages": len(passages),
        "hit": passage_state_counts.get("HIT", 0),
        "missing": passage_state_counts.get("MISSING", 0),
        "stale": stale_count,
        "in_progress": in_progress_count,
        "invalid": failed_final_count,
        "state_counts": dict(state_counts),
        "passage_state_counts": dict(passage_state_counts),
        "object_conservation": {
            "required_unique_inputs": unique_extraction_inputs,
            "materialization_hit": materialization_hit_count,
            "legacy_reuse": legacy_reuse_count,
            "missing": state_counts.get("MISSING", 0),
            "stale": stale_count,
            "in_progress": in_progress_count,
            "failed_retryable": failed_retryable_count,
            "failed_final": failed_final_count,
            "incompatible": incompatible_count,
            "counted_total": object_conservation_total,
            "is_balanced": object_conservation_total == unique_extraction_inputs,
        },
        "existing_source_claim_rows": len(source_claim_rows),
        "valid_source_claim_rows": len(valid_claims),
        "duplicate_source_claim_rows": duplicate_claim_rows,
        "empty_content_count": empty_content_count,
        "llm_call_cache_hit": llm_cache_hits,
        "missing_unique_llm_inputs": len(missing_materialization_hashes),
        "missing_llm_call_cache_hit": missing_llm_cache_hits,
        "missing_no_external_llm_breakdown": missing_no_external_llm_breakdown,
        "missing_conservation": {
            "missing_total": missing_total,
            "missing_llm_required": lookup_first_llm_required,
            "explained_no_external_llm_total": sum(missing_no_external_llm_breakdown.values()),
            "counted_total": missing_conservation_total,
            "is_balanced": missing_conservation_total == missing_total,
        },
        "llm_input_contract": {
            "system_prompt_version": SOURCE_CLAIM_PROMPT_VERSION,
            "schema_version": SOURCE_CLAIM_SCHEMA_VERSION,
            "user_payload_fields": ["passage"],
            "semantic_input_normalization": "strip",
            "materialization_key_fields": [
                "contract_version",
                "passage_content_hash",
            ],
            "post_processing_fields": [
                "source_document.url",
                "source_document.domain",
            ],
            "post_processing_note": (
                "Document URL/domain are used after extraction for ownership "
                "and referential-subject normalization; they are not part of "
                "the SourceClaim LLM user payload."
            ),
        },
        "current_implementation_llm_required": max(len(source_claim_hashes) - llm_cache_hits, 0),
        "lookup_first_llm_required": lookup_first_llm_required,
        "materialization_hit_count": materialization_hit_count,
        "zero_claim_hit_count": zero_claim_hit_count,
        "legacy_reuse_count": legacy_reuse_count,
        "stale_count": stale_count,
        "missing_count": state_counts.get("MISSING", 0),
        "incompatible_count": incompatible_count,
        "failed_retryable_count": failed_retryable_count,
        "failed_final_count": failed_final_count,
        "actual_source_claim_llm_calls": lookup_first_llm_required,
        "source_claim_dedupe_ratio": round(source_claim_dedupe_ratio, 6),
        "source_claim_cache_hit_rate": round(source_claim_cache_hit_rate, 6),
        "materialization_contract": SOURCE_CLAIM_MATERIALIZATION_CONTRACT,
    }, valid_claims


def _answer_unit_plan(
    db: Session,
    project_id: int,
    prompt_id: int,
    run_ids: list[int],
) -> dict:
    units = (
        db.query(AnswerUnit)
        .filter(
            AnswerUnit.project_id == project_id,
            AnswerUnit.prompt_id == prompt_id,
            AnswerUnit.run_id.in_(run_ids),
        )
        .all()
    )
    bindings = (
        db.query(AnswerDecisionBinding)
        .filter(
            AnswerDecisionBinding.project_id == project_id,
            AnswerDecisionBinding.prompt_id == prompt_id,
            AnswerDecisionBinding.run_id.in_(run_ids),
        )
        .all()
    )
    event_ids = {binding.recommendation_event_id for binding in bindings if binding.recommendation_event_id}
    events = {
        event.id: event
        for event in db.query(RecommendationEvent).filter(RecommendationEvent.id.in_(event_ids)).all()
    } if event_ids else {}
    events_by_unit: dict[int, list[RecommendationEvent]] = defaultdict(list)
    for binding in bindings:
        event = events.get(binding.recommendation_event_id)
        if event:
            events_by_unit[int(binding.answer_unit_id)].append(event)
    semantic_hashes = {_answer_unit_semantic_hash(unit, events_by_unit.get(unit.id, [])) for unit in units}
    return {
        "raw_observations": len(units),
        "semantic_objects": len(semantic_hashes),
        "hit": len(semantic_hashes),
        "missing": 0,
        "stale": 0,
        "binding_rows": len(bindings),
        "materialization_contract": ANSWER_UNIT_MATERIALIZATION_CONTRACT,
    }


def _existing_alignment_semantic_keys(db: Session, project_id: int, prompt_id: int) -> set[tuple[str, str]]:
    rows = (
        db.query(EvidenceAlignment, SourceClaim)
        .join(SourceClaim, SourceClaim.id == EvidenceAlignment.source_claim_id)
        .filter(
            EvidenceAlignment.project_id == project_id,
            EvidenceAlignment.prompt_id == prompt_id,
        )
        .all()
    )
    keys: set[tuple[str, str]] = set()
    for alignment, claim in rows:
        payload = loads(alignment.machine_payload_json, {})
        reason_key = payload.get("semantic_reason_key") or alignment.recommendation_reason_id or ""
        if not reason_key:
            continue
        keys.add((
            _stable_hash({
                "contract_version": ANSWER_UNIT_MATERIALIZATION_CONTRACT,
                "reason_key": _compact(reason_key),
            }),
            _source_claim_semantic_hash(claim),
        ))
    return keys


def _alignment_materialization_key_for_item(item: dict) -> str:
    return build_alignment_materialization_key(
        item["reason"]["text"],
        item["reason"]["scope"],
        item["reason"]["entity"],
        item["claim"],
    )


def _alignment_shadow_item(reason: dict, claim: SourceClaim, recall_path: str, score: float) -> dict:
    return {
        "reason": reason,
        "claim": claim,
        "recall_path": recall_path,
        "candidate_score": round(score, 4),
    }


def _candidate_key_for_alignment(alignment: EvidenceAlignment, claim: SourceClaim) -> str:
    payload = loads(alignment.machine_payload_json, {})
    semantic_key = payload.get("semantic_reason_key") or alignment.recommendation_reason_id or ""
    parts = semantic_key.split("|")
    if len(parts) >= 3 and parts[0]:
        return build_alignment_materialization_key(parts[0], parts[1], parts[2], claim)
    return build_alignment_materialization_key(semantic_key, "ENTITY_SPECIFIC", "", claim)


def _recall_level(recall_path: str | None) -> str:
    return {
        "EXPLICIT_BINDING": "L0_EXPLICIT",
        "ANSWER_CONTEXT": "L1_ANSWER_CONTEXT",
        "RUN_SCOPE": "L2_RUN_SCOPE",
        "PROMPT_SCOPE_RECALL": "L3_PROMPT_SCOPE",
    }.get(recall_path or "", "NONE")


def _boundary_tie_diagnostic(
    *,
    reason: dict,
    scored: list[tuple[float, str, SourceClaim]],
    top_k: int,
) -> tuple[dict | None, set[str]]:
    if not scored or len(scored) <= top_k:
        return None, set()
    cutoff_score = float(scored[top_k - 1][0])
    higher = [item for item in scored if _score_bucket(item[0]) > _score_bucket(cutoff_score)]
    tied = [item for item in scored if _score_tied(item[0], cutoff_score)]
    expanded_keys = {key for score, key, _claim in scored if _score_bucket(score) >= _score_bucket(cutoff_score)}
    rank_start = len(higher) + 1
    rank_end = rank_start + len(tied) - 1
    return {
        "reason_text": reason.get("text", ""),
        "candidate_count_before_topk": len(scored),
        "top_k": top_k,
        "cutoff_score": _score_bucket(cutoff_score),
        "boundary_tie_count": len(tied),
        "boundary_rank_start": rank_start,
        "boundary_rank_end": rank_end,
        "candidate_count_after_plain_topk": min(top_k, len(scored)),
        "candidate_count_after_tie_expansion": len(expanded_keys),
        "tie_bucket_source_claim_ids": [claim.id for _score, _key, claim in tied],
    }, expanded_keys


def _tie_bucket_stats(diagnostics: list[dict]) -> dict:
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


def _event_support_level(event: RecommendationEvent | None) -> str:
    if not event:
        return "FACT_ONLY"
    speech_act = (event.speech_act or "").upper()
    strength = (event.recommendation_strength or "").upper()
    polarity = (event.polarity or "").upper()
    if speech_act == "RECOMMEND":
        return "RECOMMENDATION_REASON"
    if speech_act in {"INCLUDE_AS_OPTION", "COMPARE"} or strength in {"MODERATE", "STRONG"} or polarity == "POSITIVE":
        return "CANDIDATE_OR_EVALUATION"
    return "FACT_ONLY"


def _event_support_rank(level: str) -> int:
    return {
        "NONE": 0,
        "FACT_ONLY": 1,
        "CANDIDATE_OR_EVALUATION": 2,
        "RECOMMENDATION_REASON": 3,
    }.get((level or "NONE").upper(), 0)


def _shadow_benchmark_tier(content_status: str, relevance: str, decision_support: str) -> str:
    if content_status != "CONTENT_VALID":
        return "NOT_EVALUABLE"
    if relevance == "DIRECT" and decision_support in {"RECOMMENDATION_REASON", "CANDIDATE_OR_EVALUATION"}:
        return "PRIMARY_BENCHMARK"
    if (relevance == "DIRECT" and decision_support == "FACT_ONLY") or (
        relevance == "PARTIAL" and decision_support in {"RECOMMENDATION_REASON", "CANDIDATE_OR_EVALUATION"}
    ):
        return "SECONDARY_BENCHMARK"
    return "REFERENCE_ONLY"


def _existing_alignment_rows_by_key(
    db: Session,
    *,
    project_id: int,
    prompt_id: int,
) -> dict[str, list[tuple[EvidenceAlignment, SourceClaim]]]:
    rows = (
        db.query(EvidenceAlignment, SourceClaim)
        .join(SourceClaim, SourceClaim.id == EvidenceAlignment.source_claim_id)
        .filter(
            EvidenceAlignment.project_id == project_id,
            EvidenceAlignment.prompt_id == prompt_id,
            EvidenceAlignment.prompt_version == ALIGNMENT_PROMPT_VERSION,
            EvidenceAlignment.schema_version == ALIGNMENT_SCHEMA_VERSION,
        )
        .all()
    )
    grouped: dict[str, list[tuple[EvidenceAlignment, SourceClaim]]] = defaultdict(list)
    for alignment, claim in rows:
        key = _candidate_key_for_alignment(alignment, claim)
        if key:
            grouped[key].append((alignment, claim))
    return grouped


def _evidence_relation_summary(
    *,
    candidate_keys: set[str],
    candidate_items: dict[str, dict],
    existing_rows_by_key: dict[str, list[tuple[EvidenceAlignment, SourceClaim]]],
) -> dict:
    relation_counts = Counter()
    relation_row_counts = Counter()
    supported_reasons: set[str] = set()
    contradicted_reasons: set[str] = set()
    reason_texts = {
        (candidate_items.get(key) or {}).get("reason", {}).get("text", "")
        for key in candidate_keys
    }
    reason_texts.discard("")
    for key in candidate_keys:
        item = candidate_items.get(key) or {}
        reason_text = (item.get("reason") or {}).get("text", "")
        key_relations = {((alignment.relation or "NONE").upper()) for alignment, _claim in existing_rows_by_key.get(key, [])}
        for relation in key_relations:
            relation_counts[relation] += 1
            if relation == "SUPPORTS" and reason_text:
                supported_reasons.add(reason_text)
            if relation == "CONTRADICTS" and reason_text:
                contradicted_reasons.add(reason_text)
        for alignment, _claim in existing_rows_by_key.get(key, []):
            relation_row_counts[(alignment.relation or "NONE").upper()] += 1
    unsupported_reasons = reason_texts - supported_reasons - contradicted_reasons
    return {
        "candidate_keys": len(candidate_keys),
        "SUPPORTS_semantic_relations": relation_counts.get("SUPPORTS", 0),
        "CONTRADICTS_semantic_relations": relation_counts.get("CONTRADICTS", 0),
        "SUPPORTS_rows": relation_row_counts.get("SUPPORTS", 0),
        "CONTRADICTS_rows": relation_row_counts.get("CONTRADICTS", 0),
        "supported_reason_count": len(supported_reasons),
        "unsupported_reason_count": len(unsupported_reasons),
        "contradicted_reason_count": len(contradicted_reasons),
        "relation_counts": dict(relation_counts),
        "relation_row_counts": dict(relation_row_counts),
    }


def _benchmark_summary_for_keys(
    db: Session,
    *,
    project_id: int,
    prompt_id: int,
    run_ids: list[int],
    candidate_keys: set[str],
    existing_rows_by_key: dict[str, list[tuple[EvidenceAlignment, SourceClaim]]],
) -> dict:
    alignments = [
        alignment
        for key in candidate_keys
        for alignment, _claim in existing_rows_by_key.get(key, [])
        if (alignment.review_status or "").upper() in {"MACHINE_GROUNDED", "HUMAN_CONFIRMED"}
    ]
    eligible_alignments, eligibility_by_id = eligible_evidence_alignments_for_v1(
        db,
        alignments,
        allowed_run_ids={int(run_id) for run_id in run_ids if run_id},
        include_answer_binding_v1_1=True,
    )
    event_ids = {alignment.recommendation_event_id for alignment in eligible_alignments if alignment.recommendation_event_id}
    events = db.query(RecommendationEvent).filter(RecommendationEvent.id.in_(event_ids)).all() if event_ids else []
    event_by_id = {event.id: event for event in events}
    doc_ids = {alignment.source_document_id for alignment in eligible_alignments if alignment.source_document_id}
    docs = db.query(SourceDocument).filter(SourceDocument.id.in_(doc_ids)).all() if doc_ids else []
    quality_rows = (
        db.query(SourceQuality)
        .filter(SourceQuality.source_document_id.in_(doc_ids))
        .order_by(SourceQuality.source_document_id.asc(), SourceQuality.id.desc())
        .all()
    ) if doc_ids else []
    quality_by_doc_id: dict[int, SourceQuality] = {}
    for quality in quality_rows:
        quality_by_doc_id.setdefault(int(quality.source_document_id), quality)
    doc_by_id = {doc.id: doc for doc in docs}
    grouped: dict[int, list[EvidenceAlignment]] = defaultdict(list)
    for alignment in eligible_alignments:
        grouped[int(alignment.source_document_id)].append(alignment)

    tier_counts = Counter()
    support_docs = 0
    contradiction_docs = 0
    for doc_id, doc_alignments in grouped.items():
        doc = doc_by_id.get(doc_id)
        content_status = derive_content_status(doc, quality_by_doc_id.get(doc_id)).get("content_status") if doc else "CONTENT_PENDING"
        supports = [alignment for alignment in doc_alignments if (alignment.relation or "").upper() == "SUPPORTS"]
        contradictions = [alignment for alignment in doc_alignments if (alignment.relation or "").upper() == "CONTRADICTS"]
        relevance = "TANGENTIAL"
        support_level = "NONE"
        if supports:
            support_docs += 1
            relevance = "DIRECT"
            for alignment in supports:
                candidate_level = _event_support_level(event_by_id.get(alignment.recommendation_event_id))
                if _event_support_rank(candidate_level) > _event_support_rank(support_level):
                    support_level = candidate_level
                if (alignment.scope_relation or "").upper() == "PASS_MARKET":
                    relevance = "PARTIAL"
        if contradictions:
            contradiction_docs += 1
        tier_counts[_shadow_benchmark_tier(str(content_status), relevance, support_level)] += 1

    ineligible_counts = Counter()
    for eligibility in eligibility_by_id.values():
        if eligibility.eligible_for_v1:
            continue
        for reason in eligibility.ineligibility_reasons:
            ineligible_counts[reason] += 1
    return {
        "eligible_alignment_rows": len(eligible_alignments),
        "source_documents_with_eligible_evidence": len(grouped),
        "source_documents_with_support": support_docs,
        "source_documents_with_contradiction": contradiction_docs,
        "primary_benchmark_count": tier_counts.get("PRIMARY_BENCHMARK", 0),
        "secondary_benchmark_count": tier_counts.get("SECONDARY_BENCHMARK", 0),
        "reference_only_count": tier_counts.get("REFERENCE_ONLY", 0),
        "not_evaluable_count": tier_counts.get("NOT_EVALUABLE", 0),
        "tier_counts": dict(tier_counts),
        "ineligible_alignment_counts": dict(ineligible_counts),
    }


def _latest_decision_snapshot(db: Session, project_id: int, prompt_id: int) -> RecommendationIntelligenceSnapshot | None:
    return (
        db.query(RecommendationIntelligenceSnapshot)
        .filter(
            RecommendationIntelligenceSnapshot.project_id == project_id,
            RecommendationIntelligenceSnapshot.prompt_id == prompt_id,
            RecommendationIntelligenceSnapshot.status == "active",
        )
        .order_by(RecommendationIntelligenceSnapshot.created_at.desc(), RecommendationIntelligenceSnapshot.id.desc())
        .first()
    )


def _current_gap_summary(db: Session, project_id: int, prompt_id: int) -> dict:
    snapshot = _latest_decision_snapshot(db, project_id, prompt_id)
    if not snapshot:
        return {"snapshot_id": None, "gap_count": 0, "dominant_gap": None, "gap_types": [], "capability_gaps": []}
    gap_rows = (
        db.query(DecisionGapDiagnosis)
        .filter(DecisionGapDiagnosis.snapshot_id == snapshot.id)
        .order_by(DecisionGapDiagnosis.id)
        .all()
    )
    if gap_rows:
        gaps = [
            {
                "gap_type": row.gap_type,
                "severity": row.severity,
                "metric_name": row.metric_name,
                "metric_value": row.metric_value,
                "diagnosis_text": row.diagnosis_text,
            }
            for row in gap_rows
        ]
    else:
        gaps = loads(snapshot.gap_diagnosis_json, [])
    gap_types = [gap.get("gap_type", "UNKNOWN") for gap in gaps]
    return {
        "snapshot_id": snapshot.id,
        "gap_count": len(gaps),
        "dominant_gap": gap_types[0] if gap_types else None,
        "gap_types": gap_types,
        "capability_gaps": [
            gap.get("gap_type", "UNKNOWN")
            for gap in gaps
            if "CAPABILITY" in str(gap.get("gap_type", "")).upper()
        ],
    }


def _current_strategy_summary(db: Session, project_id: int, package_id: int | None) -> dict:
    if not package_id:
        return {"candidate_exists": False, "candidate_id": None}
    candidate = (
        db.query(OptimizationStrategyCandidate)
        .filter(
            OptimizationStrategyCandidate.project_id == project_id,
            OptimizationStrategyCandidate.evidence_package_id == package_id,
        )
        .order_by(OptimizationStrategyCandidate.generated_at.desc(), OptimizationStrategyCandidate.id.desc())
        .first()
    )
    if not candidate:
        return {"candidate_exists": False, "candidate_id": None}
    payload = loads(candidate.structured_payload_json, {})
    effective = loads(candidate.effective_payload_json, {})
    return {
        "candidate_exists": True,
        "candidate_id": candidate.id,
        "strategy_type": candidate.intervention_type or payload.get("intervention_type") or "",
        "priority_capability": payload.get("decision_market", {}).get("gap_type") or payload.get("primary_gap_type") or "",
        "planned_channel": candidate.target_platform or effective.get("target_platform") or payload.get("target_platform") or "",
        "resolver_output": payload.get("channel_role") or payload.get("target_platform") or "",
        "state": candidate.review_status,
        "generation_status": candidate.generation_status,
    }


def _shadow_downstream_diff(
    db: Session,
    *,
    project: Project,
    prompt_id: int,
    run_ids: list[int],
    package: OptimizationEvidencePackage | None,
    current_candidate_keys: set[str],
    proposed_candidate_keys: set[str],
    current_candidate_items: dict[str, dict],
    proposed_candidate_items: dict[str, dict],
    removed_classification_counts: dict[str, int],
) -> dict:
    existing_rows_by_key = _existing_alignment_rows_by_key(db, project_id=project.id, prompt_id=prompt_id)
    current_items = {**proposed_candidate_items, **current_candidate_items}
    proposed_items = {**current_candidate_items, **proposed_candidate_items}
    current_evidence = _evidence_relation_summary(
        candidate_keys=current_candidate_keys,
        candidate_items=current_items,
        existing_rows_by_key=existing_rows_by_key,
    )
    proposed_evidence = _evidence_relation_summary(
        candidate_keys=proposed_candidate_keys,
        candidate_items=proposed_items,
        existing_rows_by_key=existing_rows_by_key,
    )
    current_benchmark = _benchmark_summary_for_keys(
        db,
        project_id=project.id,
        prompt_id=prompt_id,
        run_ids=run_ids,
        candidate_keys=current_candidate_keys,
        existing_rows_by_key=existing_rows_by_key,
    )
    proposed_benchmark = _benchmark_summary_for_keys(
        db,
        project_id=project.id,
        prompt_id=prompt_id,
        run_ids=run_ids,
        candidate_keys=proposed_candidate_keys,
        existing_rows_by_key=existing_rows_by_key,
    )
    benchmark_core_fields = [
        "eligible_alignment_rows",
        "source_documents_with_eligible_evidence",
        "source_documents_with_support",
        "source_documents_with_contradiction",
        "primary_benchmark_count",
        "secondary_benchmark_count",
        "reference_only_count",
        "not_evaluable_count",
        "tier_counts",
    ]
    benchmark_changed = any(
        current_benchmark.get(field) != proposed_benchmark.get(field)
        for field in benchmark_core_fields
    )
    current_gap = _current_gap_summary(db, project.id, prompt_id)
    current_strategy = _current_strategy_summary(db, project.id, package.id if package else None)

    removed_total = sum(int(value or 0) for value in removed_classification_counts.values())
    causes = [key for key, value in sorted(removed_classification_counts.items()) if value]
    if not causes and current_candidate_keys != proposed_candidate_keys:
        causes = ["NO_EXISTING_SUPPORT_OR_CONTRADICTION_REMOVED"]
    semantic_diff_requires_decision = bool(
        removed_classification_counts.get("LEGACY_UNPROVEN_CROSS_PRODUCT", 0)
        or removed_classification_counts.get("LEGACY_ALIGNMENT_FALSE_POSITIVE", 0)
        or removed_classification_counts.get("LEGACY_SCOPE_ARTIFACT", 0)
    )
    evidence_changed = current_evidence != proposed_evidence
    return {
        "policy_scope": "selected_shadow_policy",
        "Evidence": {
            "changed": evidence_changed,
            "current_official": current_evidence,
            "proposed_shadow": proposed_evidence,
            "diff_caused_by": causes,
            "removed_classification_counts": removed_classification_counts,
        },
        "Benchmark": {
            "changed": benchmark_changed,
            "core_fields_compared": benchmark_core_fields,
            "current_official": current_benchmark,
            "proposed_shadow": proposed_benchmark,
            "diff_caused_by": causes if benchmark_changed else [],
        },
        "Gap": {
            "changed": False,
            "current_official": current_gap,
            "proposed_shadow": {
                **current_gap,
                "status": "NOT_RECOMPUTED_READ_ONLY",
                "input_evidence_changed": evidence_changed,
                "input_benchmark_changed": benchmark_changed,
            },
            "diff_caused_by": [],
        },
        "Strategy": {
            "changed": False,
            "current_official": current_strategy,
            "proposed_shadow": {
                **current_strategy,
                "status": "NOT_RECOMPUTED_READ_ONLY",
                "input_evidence_changed": evidence_changed,
                "input_benchmark_changed": benchmark_changed,
            },
            "diff_caused_by": [],
        },
        "removed_existing_support_or_contradict_count": removed_total,
        "semantic_diff_requires_separate_decision": semantic_diff_requires_decision and benchmark_changed,
    }


def _citation_ids_by_run_doc(
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


def _final_exclusion_reason(
    *,
    item: dict,
    proposed_keys: set[str],
    fallback_trace: dict | None,
    hard_filter_result: str,
    same_run_observed_source: bool,
    binding_status: str,
    top_k: int,
) -> str:
    if item["materialization_key"] in proposed_keys:
        return "RETAINED"
    if hard_filter_result in {"INVALID_SUBJECT", "COMPETITOR_CONTEXT"}:
        return "ENTITY_HARD_FILTER"
    if not item.get("in_current_prompt_scope", True):
        return "SOURCE_SCOPE_FILTER"
    if fallback_trace:
        score = float(fallback_trace.get("lexical_score") or 0.0)
        rank = fallback_trace.get("rank_before_topk")
        if score < _RECALL_MIN_SCORE:
            return "BELOW_SCORE_THRESHOLD"
        if rank and int(rank) > int(top_k):
            return "TOPK_TRUNCATION"
        return "OTHER_EXPLICIT"
    if binding_status == "EXPLICIT" and not same_run_observed_source:
        return "BINDING_MISS"
    if not same_run_observed_source:
        return "RUN_SCOPE_MISS"
    return "OTHER_EXPLICIT"


def _proposed_fix_layer(final_exclusion_reason: str, trace: dict) -> str:
    if final_exclusion_reason == "TOPK_TRUNCATION":
        return "TopK application layer correction"
    if final_exclusion_reason == "BELOW_SCORE_THRESHOLD":
        if trace.get("same_run_observed_source") is True:
            return "L2 Run-scope fallback or Score/Threshold correction"
        return "L1 Answer-context expansion or Score/Threshold correction"
    if final_exclusion_reason in {"BINDING_MISS", "ANSWER_CONTEXT_MISS"}:
        return "L1 Answer-context expansion"
    if final_exclusion_reason == "RUN_SCOPE_MISS":
        return "L2 Run-scope fallback"
    if final_exclusion_reason == "PROMPT_SCOPE_MISS":
        return "L3 Prompt-scope fallback"
    if final_exclusion_reason == "ENTITY_HARD_FILTER":
        return "Hard Filter correction"
    if final_exclusion_reason == "STRUCTURAL_LOCALITY_FILTER":
        return "Structural locality filter"
    return "Manual diagnosis before C2-B cutover"


def _claim_source_context_excerpt(claim: SourceClaim | None, document: SourceDocument | None) -> str:
    if not claim or not document:
        return ""
    blocks = loads(document.content_blocks_json, [])
    block_index = None
    passage_id = claim.passage_id or ""
    if ":b" in passage_id:
        try:
            block_index = int(passage_id.rsplit(":b", 1)[1])
        except ValueError:
            block_index = None
    if block_index is not None:
        selected = []
        for block in blocks:
            current_index = block.get("block_index")
            if current_index in {block_index - 1, block_index, block_index + 1}:
                text = _compact(block.get("text") or "")
                if text:
                    selected.append(text)
        if selected:
            return " ".join(selected)[:1000]
    return _compact(claim.source_span or claim.normalized_claim or document.clean_text or "")[:1000]


def _source_context_alignment_audit(
    *,
    reason_text: str,
    claim: SourceClaim | None,
    document: SourceDocument | None,
    original_verdict: str,
    original_review_status: str,
) -> dict:
    context = _claim_source_context_excerpt(claim, document)
    normalized_context = _compact(" ".join([
        claim.normalized_claim if claim else "",
        claim.source_span if claim else "",
        context,
    ]))
    audit_decision = "HUMAN_REVIEW_REQUIRED"
    audit_reason = "No deterministic source-context audit rule applies to this reason/claim pair."
    if "自动生成" in reason_text:
        has_generate = "生成" in normalized_context
        has_auto_generate = "自动生成" in normalized_context or ("系统" in normalized_context and has_generate)
        has_encrypted_link = "加密" in normalized_context and ("链接" in normalized_context or "短链" in normalized_context)
        if has_auto_generate and has_encrypted_link:
            audit_decision = "TRUE_POSITIVE_RECALL_LOSS"
            audit_reason = (
                "Source context explicitly states the system automatically generates encrypted jump links, "
                "so it supports the 'automatic encrypted short link generation' capability."
            )
        else:
            audit_decision = "LEGACY_ALIGNMENT_FALSE_POSITIVE"
            audit_reason = (
                "Source context supports encrypted-link anti-risk effects but does not prove automatic generation."
            )
    return {
        "original_verdict": original_verdict,
        "original_review_status": original_review_status,
        "new_audit_decision": audit_decision,
        "audit_reason": audit_reason,
        "source_context_excerpt": context,
    }


def _recall_loss_classification(trace: dict) -> str:
    if trace["hard_filter_result"] != "PASS" or not trace["in_current_prompt_scope"]:
        return "LEGACY_SCOPE_ARTIFACT"
    source_context_audit = trace.get("source_context_audit") or {}
    if source_context_audit.get("new_audit_decision") in {
        "TRUE_POSITIVE_RECALL_LOSS",
        "LEGACY_ALIGNMENT_FALSE_POSITIVE",
    }:
        return source_context_audit["new_audit_decision"]
    relation = trace["alignment_verdict"]
    if relation not in {"SUPPORTS", "CONTRADICTS"}:
        return "LEGACY_ALIGNMENT_FALSE_POSITIVE"
    if trace["alignment_review_status_counts"].get("HUMAN_CONFIRMED", 0) > 0:
        return "TRUE_POSITIVE_RECALL_LOSS"
    if not trace.get("citation_anchor_available") and trace.get("same_answer_context") == "unavailable":
        return "LEGACY_UNPROVEN_CROSS_PRODUCT"
    return "HUMAN_REVIEW_REQUIRED"


def _old_only_alignment_verdict_audit(
    db: Session,
    *,
    project_id: int,
    prompt_id: int,
    old_only_keys: set[str],
    current_candidate_items: dict[str, dict],
    proposed_candidate_items: dict[str, dict],
    reason_diagnostics: dict[str, dict],
    reason_recall_summaries: dict[str, dict],
    fallback_diagnostics: dict[str, dict],
    citation_ids_by_run_doc: dict[tuple[int, int], list[int]],
    top_k: int,
) -> dict:
    if not old_only_keys:
        return {
            "existing_verdict_row_counts": {},
            "supports_contradicts_row_count": 0,
            "supports_contradicts_count": 0,
            "supports_contradicts": [],
            "reason_clusters": [],
            "classification_counts": {},
            "exclusion_reason_counts": {},
        }

    current_keys = set(current_candidate_items)
    proposed_keys = set(proposed_candidate_items)
    rows = (
        db.query(EvidenceAlignment, SourceClaim, SourceDocument)
        .join(SourceClaim, SourceClaim.id == EvidenceAlignment.source_claim_id)
        .join(SourceDocument, SourceDocument.id == EvidenceAlignment.source_document_id)
        .filter(
            EvidenceAlignment.project_id == project_id,
            EvidenceAlignment.prompt_id == prompt_id,
            EvidenceAlignment.prompt_version == ALIGNMENT_PROMPT_VERSION,
            EvidenceAlignment.schema_version == ALIGNMENT_SCHEMA_VERSION,
        )
        .all()
    )
    verdict_counts = Counter()
    critical_by_pair: dict[tuple[str, str], dict] = {}
    supports_contradicts_row_count = 0
    existing_by_key_relation: dict[tuple[str, str], list[EvidenceAlignment]] = defaultdict(list)
    existing_verdicts_by_key: dict[str, Counter] = defaultdict(Counter)
    for alignment, claim, document in rows:
        reason_parts = loads(alignment.machine_payload_json, {}).get("semantic_reason_key", "").split("|")
        if len(reason_parts) < 3 or not reason_parts[0]:
            continue
        materialization_key = _candidate_key_for_alignment(alignment, claim)
        relation = (alignment.relation or "NONE").upper()
        if materialization_key in current_keys or materialization_key in proposed_keys:
            existing_verdicts_by_key[materialization_key][relation] += 1
        if materialization_key not in old_only_keys:
            continue
        verdict_counts[relation] += 1
        existing_by_key_relation[(materialization_key, relation)].append(alignment)
        if relation not in {"SUPPORTS", "CONTRADICTS"}:
            continue
        supports_contradicts_row_count += 1
        dedupe_key = (materialization_key, relation)
        item = critical_by_pair.setdefault(dedupe_key, {
            "materialization_key": materialization_key,
            "relation": relation,
            "alignment_ids": [],
            "row_count": 0,
            "review_status_counts": Counter(),
            "sample_alignment_id": alignment.id,
            "source_claim_id": claim.id,
            "source_document_id": document.id,
            "source_url": document.canonical_url or document.url or "",
            "review_status": alignment.review_status,
            "reason_text": reason_parts[0],
            "reason_scope": reason_parts[1] or "ENTITY_SPECIFIC",
            "reason_entity": reason_parts[2] or "",
            "source_claim": _compact(claim.normalized_claim or claim.source_span or ""),
        })
        item["alignment_ids"].append(alignment.id)
        item["row_count"] += 1
        item["review_status_counts"][alignment.review_status or ""] += 1
    critical = list(critical_by_pair.values())
    classification_counts = Counter()
    exclusion_reason_counts = Counter()
    for item in critical:
        materialization_key = item["materialization_key"]
        current_item = current_candidate_items.get(materialization_key)
        claim = current_item["claim"] if current_item else None
        document = db.get(SourceDocument, int(item["source_document_id"] or 0)) if item.get("source_document_id") else None
        reason = current_item["reason"] if current_item else {
            "text": item["reason_text"],
            "scope": item["reason_scope"],
            "entity": item["reason_entity"],
            "observations": [],
        }
        reason_hash = _reason_semantic_hash(reason)
        diagnostics = reason_diagnostics.get(reason_hash, {})
        recall_summary = reason_recall_summaries.get(reason_hash, {})
        observed_run_ids = sorted({
            int(row.run_id)
            for row in existing_by_key_relation.get((materialization_key, item["relation"]), [])
            if row.run_id
        })
        citation_ids = sorted({
            citation_id
            for run_id in observed_run_ids
            for citation_id in citation_ids_by_run_doc.get((run_id, int(item["source_document_id"] or 0)), [])
        })
        hard_filter_result = "PASS"
        hard_filter_reason = ""
        if not claim or claim.subject_entity in {"", "UNKNOWN"}:
            hard_filter_result = "INVALID_SUBJECT"
            hard_filter_reason = "SourceClaim subject_entity is missing or UNKNOWN."
        elif entity_scope_precheck(reason["scope"], reason["entity"], claim) == "COMPETITOR_CONTEXT":
            hard_filter_result = "COMPETITOR_CONTEXT"
            hard_filter_reason = "Reason entity and SourceClaim subject are different entity-specific contexts."
        fallback = fallback_diagnostics.get(materialization_key, {})
        same_run_observed_source = bool(citation_ids)
        explicitly_bound_to_answer_unit = bool(
            diagnostics.get("has_answer_binding_observation")
            and any(int(doc_id) == int(item["source_document_id"] or 0) for doc_id in diagnostics.get("observed_doc_ids", []))
        )
        answer_context_available = bool(diagnostics.get("has_answer_binding_observation"))
        same_answer_context: bool | str = (
            bool(explicitly_bound_to_answer_unit and same_run_observed_source)
            if answer_context_available
            else "unavailable"
        )
        trace = {
            "reason_semantic_key": "|".join([
                item["reason_text"],
                item["reason_scope"],
                item["reason_entity"],
            ]),
            "reason_text": item["reason_text"],
            "source_claim_id": item["source_claim_id"],
            "source_claim_semantic_key": alignment_source_claim_semantic_hash(claim) if claim else "unavailable",
            "source_claim_text": item["source_claim"],
            "alignment_verdict": item["relation"],
            "alignment_human_review_status": (
                "HUMAN_CONFIRMED"
                if item["review_status_counts"].get("HUMAN_CONFIRMED", 0) > 0
                else "HUMAN_REJECTED"
                if item["review_status_counts"].get("HUMAN_REJECTED", 0) > 0
                else "NO_HUMAN_REVIEW"
            ),
            "alignment_review_status_counts": dict(item["review_status_counts"]),
            "source_claim_human_review_status": claim.review_status if claim else "unavailable",
            "source_document_id": item["source_document_id"],
            "citation_ids": citation_ids,
            "observed_run_ids": observed_run_ids,
            "current_candidate_membership_source": "production_all_viable_pairs.v1",
            "binding_status": diagnostics.get("binding_status", "NONE"),
            "explicitly_bound_to_answer_unit": explicitly_bound_to_answer_unit,
            "same_answer_context": same_answer_context,
            "same_run_observed_source": same_run_observed_source,
            "in_current_prompt_scope": materialization_key in current_keys,
            "citation_anchor_available": bool(citation_ids),
            "structural_passage_distance": "unavailable",
            "section_relation": "unavailable",
            "hard_filter_result": hard_filter_result,
            "hard_filter_reason": hard_filter_reason or "passed deterministic entity/scope precheck",
            "lexical_score": fallback.get("lexical_score", _claim_recall_score(reason["text"], claim) if claim else 0.0),
            "BM25_score": "unavailable",
            "semantic_score": "unavailable",
            "combined_candidate_score": fallback.get("lexical_score", _claim_recall_score(reason["text"], claim) if claim else 0.0),
            "rank_before_topk": fallback.get("rank_before_topk", "unavailable"),
            "rank_cutoff_score": fallback.get("rank_cutoff_score", "unavailable"),
            "score_delta_to_cutoff": fallback.get("score_delta_to_cutoff", "unavailable"),
            "number_above_threshold": fallback.get("number_above_threshold", "unavailable"),
            "top_k": top_k,
            "proposed_recall_level": _recall_level(proposed_candidate_items.get(materialization_key, {}).get("recall_path")),
            "highest_recall_level_used": recall_summary.get("highest_recall_level_used", "NONE"),
            "fallback_trigger_reason": recall_summary.get("fallback_trigger_reason", "OTHER_EXPLICIT"),
        }
        trace["source_context_audit"] = _source_context_alignment_audit(
            reason_text=item["reason_text"],
            claim=claim,
            document=document,
            original_verdict=item["relation"],
            original_review_status=trace["alignment_human_review_status"],
        )
        trace["final_exclusion_reason"] = _final_exclusion_reason(
            item={**trace, "materialization_key": materialization_key},
            proposed_keys=proposed_keys,
            fallback_trace=fallback,
            hard_filter_result=hard_filter_result,
            same_run_observed_source=same_run_observed_source,
            binding_status=str(trace["binding_status"] or "NONE"),
            top_k=top_k,
        )
        trace["diagnosis_classification"] = _recall_loss_classification(trace)
        trace["proposed_fix_layer"] = _proposed_fix_layer(trace["final_exclusion_reason"], trace)
        classification_counts[trace["diagnosis_classification"]] += 1
        exclusion_reason_counts[trace["final_exclusion_reason"]] += 1
        item["alignment_ids"] = sorted(item["alignment_ids"])
        item["review_status_counts"] = dict(item["review_status_counts"])
        item["recall_trace"] = trace
    critical.sort(key=lambda item: (item["relation"], item["reason_text"], item["source_claim_id"] or 0))
    critical_reason_texts = {item["reason_text"] for item in critical}
    reason_clusters = []
    for reason_text in sorted(critical_reason_texts):
        current_for_reason = {
            key
            for key, item in current_candidate_items.items()
            if item["reason"]["text"] == reason_text
        }
        proposed_for_reason = {
            key
            for key, item in proposed_candidate_items.items()
            if item["reason"]["text"] == reason_text
        }
        critical_for_reason = [item for item in critical if item["reason_text"] == reason_text]
        current_verdict_rows = Counter()
        proposed_verdict_rows = Counter()
        for key in current_for_reason:
            current_verdict_rows.update(existing_verdicts_by_key.get(key, {}))
        for key in proposed_for_reason:
            proposed_verdict_rows.update(existing_verdicts_by_key.get(key, {}))
        reason_clusters.append({
            "reason_text": reason_text,
            "current_candidate_count": len(current_for_reason),
            "proposed_candidate_count": len(proposed_for_reason),
            "current_SUPPORTS": current_verdict_rows.get("SUPPORTS", 0),
            "current_CONTRADICTS": current_verdict_rows.get("CONTRADICTS", 0),
            "proposed_retained_SUPPORTS": proposed_verdict_rows.get("SUPPORTS", 0),
            "proposed_retained_CONTRADICTS": proposed_verdict_rows.get("CONTRADICTS", 0),
            "critical_old_only_count": len(critical_for_reason),
        })
    return {
        "existing_verdict_row_counts": dict(verdict_counts),
        "supports_contradicts_row_count": supports_contradicts_row_count,
        "supports_contradicts_count": len(critical),
        "supports_contradicts": critical,
        "reason_clusters": reason_clusters,
        "classification_counts": dict(classification_counts),
        "exclusion_reason_counts": dict(exclusion_reason_counts),
    }


def _alignment_plan(
    db: Session,
    project: Project,
    prompt_id: int,
    run_ids: list[int],
    claims: list[SourceClaim],
    run_doc_ids: dict[int, set[int]],
    package: OptimizationEvidencePackage | None = None,
    top_k: int = _RECALL_TOP_K,
) -> dict:
    settings = get_settings()
    candidate_build = build_evidence_alignment_candidates(
        db,
        project=project,
        prompt_id=prompt_id,
        run_ids=run_ids,
        claims=claims,
        run_doc_ids=run_doc_ids,
        top_k=top_k,
        selected_policy=SELECTED_POLICY,
    )
    recall_top_k = candidate_build["top_k"]
    reasons = candidate_build["reasons"]
    scoped_claims = candidate_build["scoped_claims"]
    current_candidate_items = candidate_build["current_candidate_items"]
    hard_topk_candidate_items = candidate_build["hard_topk_candidate_items"]
    all_shadow_candidate_items = candidate_build["all_candidate_items"]
    policy_candidate_keys = candidate_build["policy_candidate_keys"]
    alignment_jobs = candidate_build["selected_candidate_items"]
    reason_diagnostics = candidate_build["reason_diagnostics"]
    reason_recall_summaries = candidate_build["reason_recall_summaries"]
    fallback_diagnostics = candidate_build["fallback_diagnostics"]
    citation_ids_by_run_doc = candidate_build["citation_ids_by_run_doc"]
    recall_layer_keys = candidate_build["recall_layer_keys"]
    deterministic_counts = Counter(candidate_build["deterministic_counts"])
    fallback_trigger_counts = Counter(candidate_build["fallback_trigger_counts"])
    l3_boundary_tie_diagnostics = candidate_build["boundary_tie_diagnostics"]
    boundary_tie_by_key = candidate_build["boundary_tie_by_key"]
    tie_stats = candidate_build["boundary_tie_stats"]
    l0_status = candidate_build["l0_status"]
    l0_status_reason = candidate_build["l0_status_reason"]
    l0_explicit_reason_count = candidate_build["l0_explicit_reason_count"]
    l1_status = candidate_build["l1_status"]
    l1_status_reason = candidate_build["l1_status_reason"]
    l2_attempted = candidate_build["l2_attempted_reason_count"]
    l2_matched = candidate_build["l2_matched_reason_count"]
    l3_attempted = candidate_build["l3_attempted_reason_count"]
    current_candidate_keys = set(current_candidate_items)
    hard_topk_candidate_keys = set(hard_topk_candidate_items)
    proposed_candidate_keys = set(alignment_jobs)
    shared_candidate_keys = current_candidate_keys & proposed_candidate_keys
    old_only_candidate_keys = current_candidate_keys - proposed_candidate_keys
    new_only_candidate_keys = proposed_candidate_keys - current_candidate_keys
    base_old_only_audit = _old_only_alignment_verdict_audit(
        db,
        project_id=project.id,
        prompt_id=prompt_id,
        old_only_keys=current_candidate_keys - hard_topk_candidate_keys,
        current_candidate_items=current_candidate_items,
        proposed_candidate_items=hard_topk_candidate_items,
        reason_diagnostics=reason_diagnostics,
        reason_recall_summaries=reason_recall_summaries,
        fallback_diagnostics=fallback_diagnostics,
        citation_ids_by_run_doc=citation_ids_by_run_doc,
        top_k=recall_top_k,
    )
    base_true_positive_recall_loss_keys = {
        item["materialization_key"]
        for item in base_old_only_audit["supports_contradicts"]
        if item.get("recall_trace", {}).get("diagnosis_classification") == "TRUE_POSITIVE_RECALL_LOSS"
    }
    selected_shadow_policy = "Policy D"
    selected_policy_key = SELECTED_POLICY
    old_only_audit = _old_only_alignment_verdict_audit(
        db,
        project_id=project.id,
        prompt_id=prompt_id,
        old_only_keys=old_only_candidate_keys,
        current_candidate_items=current_candidate_items,
        proposed_candidate_items=alignment_jobs,
        reason_diagnostics=reason_diagnostics,
        reason_recall_summaries=reason_recall_summaries,
        fallback_diagnostics=fallback_diagnostics,
        citation_ids_by_run_doc=citation_ids_by_run_doc,
        top_k=recall_top_k,
    )

    materializations = {
        row.materialization_key: row
        for row in db.query(EvidenceAlignmentMaterialization)
        .filter(EvidenceAlignmentMaterialization.materialization_key.in_(list(alignment_jobs.keys())))
        .all()
    } if alignment_jobs else {}

    legacy_alignment_keys: set[str] = set()
    existing_alignment_rows = (
        db.query(EvidenceAlignment, SourceClaim)
        .join(SourceClaim, SourceClaim.id == EvidenceAlignment.source_claim_id)
        .filter(
            EvidenceAlignment.project_id == project.id,
            EvidenceAlignment.prompt_id == prompt_id,
            EvidenceAlignment.prompt_version == ALIGNMENT_PROMPT_VERSION,
            EvidenceAlignment.schema_version == ALIGNMENT_SCHEMA_VERSION,
        )
        .all()
    )
    for alignment, claim in existing_alignment_rows:
        payload = loads(alignment.machine_payload_json, {})
        semantic_key = payload.get("semantic_reason_key") or ""
        parts = semantic_key.split("|")
        if len(parts) < 3 or not parts[0]:
            continue
        legacy_alignment_keys.add(_candidate_key_for_alignment(alignment, claim))

    true_positive_recall_loss_keys = {
        item["materialization_key"]
        for item in old_only_audit["supports_contradicts"]
        if item.get("recall_trace", {}).get("diagnosis_classification") == "TRUE_POSITIVE_RECALL_LOSS"
    }

    def _policy_external_llm_estimate(candidate_keys: set[str]) -> int:
        if not candidate_keys:
            return 0
        policy_materializations = {
            row.materialization_key: row
            for row in db.query(EvidenceAlignmentMaterialization)
            .filter(EvidenceAlignmentMaterialization.materialization_key.in_(list(candidate_keys)))
            .all()
        }
        missing_hashes: set[str] = set()
        for key in candidate_keys:
            item = all_shadow_candidate_items.get(key) or current_candidate_items.get(key)
            if not item:
                continue
            compatibility = resolve_alignment_materialization_compatibility(policy_materializations.get(key))
            if compatibility == "COMPATIBLE":
                continue
            if compatibility == "MISSING" and key in legacy_alignment_keys:
                continue
            if compatibility in {
                "MISSING",
                "FAILED_RETRYABLE",
                "STALE_SCHEMA",
                "STALE_MODEL",
                "STALE_PROMPT",
                "INCOMPATIBLE",
            }:
                missing_hashes.add(alignment_llm_input_hash(item["reason"]["text"], item["claim"].normalized_claim))
        cache_hits = _cache_hit_count(
            db,
            provider="deepseek",
            model=settings.deepseek_model,
            prompt_version=ALIGNMENT_PROMPT_VERSION,
            schema_version=ALIGNMENT_SCHEMA_VERSION,
            input_hashes=missing_hashes,
        )
        return max(len(missing_hashes) - cache_hits, 0)

    classification_by_key = {
        item["materialization_key"]: item.get("recall_trace", {}).get("diagnosis_classification", "HUMAN_REVIEW_REQUIRED")
        for item in base_old_only_audit["supports_contradicts"]
    }

    def _policy_simulation(candidate_keys: set[str], description: str) -> dict:
        critical_recall_loss = len(base_true_positive_recall_loss_keys - candidate_keys)
        external_llm = _policy_external_llm_estimate(candidate_keys)
        return {
            "description": description,
            "candidate_count": len(candidate_keys),
            "critical_recall_loss": critical_recall_loss,
            "TRUE_POSITIVE_RECALL_LOSS": critical_recall_loss,
            "LEGACY_UNPROVEN_CROSS_PRODUCT_retained": sum(
                1
                for key, classification in classification_by_key.items()
                if classification == "LEGACY_UNPROVEN_CROSS_PRODUCT" and key in candidate_keys
            ),
            "estimated_external_llm_required": external_llm,
            "external_llm_estimate": external_llm,
        }

    policy_simulations = {
        "Policy A": _policy_simulation(
            policy_candidate_keys["POLICY_A_HARD_TOPK"],
            "Hard TopK = 5",
        ),
        "Policy B": _policy_simulation(
            policy_candidate_keys["POLICY_B_THRESHOLD_WITH_CAP"],
            "Keep all fallback candidates above threshold with max cap=25 per triggered reason",
        ),
        "Policy C": _policy_simulation(
            policy_candidate_keys["POLICY_C_TOPK_WITH_SCORE_MARGIN"],
            "TopK plus score margin 0.05 around the Kth candidate",
        ),
        "Policy D": _policy_simulation(
            policy_candidate_keys["POLICY_D_TOPK_WITH_BOUNDARY_TIES"],
            "TopK plus all candidates in the Kth score tie bucket",
        ),
    }

    state_counts = Counter()
    materialization_hit_count = 0
    legacy_reuse_count = 0
    stale_count = 0
    in_progress_count = 0
    failed_retryable_count = 0
    failed_final_count = 0
    incompatible_count = 0
    missing_llm_hashes: set[str] = set()
    all_alignment_llm_hashes = {
        alignment_llm_input_hash(item["reason"]["text"], item["claim"].normalized_claim)
        for item in alignment_jobs.values()
    }
    for materialization_key, item in alignment_jobs.items():
        compatibility = resolve_alignment_materialization_compatibility(materializations.get(materialization_key))
        if compatibility == "COMPATIBLE":
            materialization_hit_count += 1
            state_counts["HIT"] += 1
            continue
        if compatibility == "MISSING" and materialization_key in legacy_alignment_keys:
            legacy_reuse_count += 1
            state_counts["LEGACY_REUSABLE"] += 1
            continue
        if compatibility == "STALE_SCHEMA":
            stale_count += 1
            state_counts["STALE_SCHEMA"] += 1
        elif compatibility == "IN_PROGRESS":
            in_progress_count += 1
            state_counts["IN_PROGRESS"] += 1
        elif compatibility == "FAILED_RETRYABLE":
            failed_retryable_count += 1
            state_counts["FAILED_RETRYABLE"] += 1
        elif compatibility == "FAILED_FINAL":
            failed_final_count += 1
            state_counts["FAILED_FINAL"] += 1
        elif compatibility == "MISSING":
            state_counts["MISSING"] += 1
        else:
            incompatible_count += 1
            state_counts["INCOMPATIBLE"] += 1
        if compatibility in {"MISSING", "FAILED_RETRYABLE"}:
            missing_llm_hashes.add(alignment_llm_input_hash(item["reason"]["text"], item["claim"].normalized_claim))

    llm_cache_hits = _cache_hit_count(
        db,
        provider="deepseek",
        model=settings.deepseek_model,
        prompt_version=ALIGNMENT_PROMPT_VERSION,
        schema_version=ALIGNMENT_SCHEMA_VERSION,
        input_hashes=all_alignment_llm_hashes,
    )
    missing_llm_cache_hits = _cache_hit_count(
        db,
        provider="deepseek",
        model=settings.deepseek_model,
        prompt_version=ALIGNMENT_PROMPT_VERSION,
        schema_version=ALIGNMENT_SCHEMA_VERSION,
        input_hashes=missing_llm_hashes,
    )
    unique_alignment_inputs = len(alignment_jobs)
    lookup_first_llm_required = max(len(missing_llm_hashes) - missing_llm_cache_hits, 0)
    cache_hit_pairs = materialization_hit_count + legacy_reuse_count + missing_llm_cache_hits
    missing_pairs = lookup_first_llm_required
    existing_alignment_hits = legacy_reuse_count
    naive_pairs = len(reasons) * len(scoped_claims)
    current_implementation_llm_hashes = {
        _alignment_llm_hash(reason["text"], claim.normalized_claim)
        for reason in reasons.values()
        for claim in scoped_claims
        if claim.subject_entity not in {"", "UNKNOWN"}
        and entity_scope_precheck(reason["scope"], reason["entity"], claim) != "COMPETITOR_CONTEXT"
    }
    current_llm_cache_hits = _cache_hit_count(
        db,
        provider="deepseek",
        model=settings.deepseek_model,
        prompt_version=ALIGNMENT_PROMPT_VERSION,
        schema_version=ALIGNMENT_SCHEMA_VERSION,
        input_hashes=current_implementation_llm_hashes,
    )
    object_conservation_total = (
        materialization_hit_count
        + legacy_reuse_count
        + state_counts.get("MISSING", 0)
        + stale_count
        + in_progress_count
        + failed_retryable_count
        + failed_final_count
        + incompatible_count
    )
    missing_total = state_counts.get("MISSING", 0) + failed_retryable_count
    missing_no_external_llm_breakdown = {
        "llm_call_cache_hit": missing_llm_cache_hits,
        "invalid_input": 0,
        "empty_content": 0,
        "deduped_elsewhere": 0,
    }
    missing_conservation_total = lookup_first_llm_required + sum(missing_no_external_llm_breakdown.values())
    recall_path_counts = Counter(item["recall_path"] for item in alignment_jobs.values())
    critical_boundary_tie_details = []
    for item in base_old_only_audit["supports_contradicts"]:
        key = item["materialization_key"]
        if key not in base_true_positive_recall_loss_keys:
            continue
        boundary = boundary_tie_by_key.get(key)
        fallback = fallback_diagnostics.get(key, {})
        critical_boundary_tie_details.append({
            "materialization_key": key,
            "reason_text": item.get("reason_text", ""),
            "source_claim_id": item.get("source_claim_id"),
            "rank": fallback.get("rank_before_topk", "unavailable"),
            "score": fallback.get("lexical_score", "unavailable"),
            "tie_bucket_size": boundary.get("boundary_tie_count") if boundary else "unavailable",
            "tie_bucket_rank_range": (
                [boundary.get("boundary_rank_start"), boundary.get("boundary_rank_end")]
                if boundary
                else "unavailable"
            ),
            "cutoff_score": boundary.get("cutoff_score") if boundary else fallback.get("rank_cutoff_score", "unavailable"),
        })
    l0_change_explanation = {
        "previous_recall_path_semantics": (
            "Earlier C2-A diagnostics used a broader run-local binding bucket that counted many same-run candidates as L0-like candidates."
        ),
        "current_recall_path_semantics": (
            "C2-A.2/A.3 uses strict ladder ownership: L0 only includes high/medium explicit AnswerDecisionBinding pairs; "
            "binding-low or binding-missing reasons short-circuit into L2 run-scope recall before L3 prompt-scope recall."
        ),
        "reason_for_L0_change": "SHADOW_LOGIC_CHANGED_AS_DESIGNED",
    }
    downstream_diff = _shadow_downstream_diff(
        db,
        project=project,
        prompt_id=prompt_id,
        run_ids=run_ids,
        package=package,
        current_candidate_keys=current_candidate_keys,
        proposed_candidate_keys=proposed_candidate_keys,
        current_candidate_items=current_candidate_items,
        proposed_candidate_items=alignment_jobs,
        removed_classification_counts=old_only_audit["classification_counts"],
    )
    critical_old_only_explained = old_only_audit["supports_contradicts_count"] == sum(
        old_only_audit["classification_counts"].values()
    )
    has_human_review_required = bool(old_only_audit["classification_counts"].get("HUMAN_REVIEW_REQUIRED", 0))
    downstream_benchmark_changed = bool(downstream_diff["Benchmark"]["changed"])
    downstream_gap_changed = bool(downstream_diff["Gap"]["changed"])
    downstream_strategy_changed = bool(downstream_diff["Strategy"]["changed"])
    gate_blocker = None
    if true_positive_recall_loss_keys:
        gate_blocker = "TRUE_POSITIVE_RECALL_LOSS"
    elif tie_stats["coarse_score_tie_risk"]:
        gate_blocker = "COARSE_SCORE_TIE_RISK"
    elif not critical_old_only_explained or has_human_review_required:
        gate_blocker = "UNEXPLAINED_CRITICAL_OLD_ONLY"
    elif downstream_benchmark_changed and downstream_diff["semantic_diff_requires_separate_decision"]:
        gate_blocker = "LEGACY_WEAK_RELATIONS_CURRENTLY_AFFECT_DOWNSTREAM"
    elif downstream_gap_changed or downstream_strategy_changed:
        gate_blocker = "DOWNSTREAM_SHADOW_DIFF"
    c2_cutover_ready = gate_blocker is None
    return {
        "reason_observations": sum(len(reason.get("observations") or []) for reason in reasons.values()),
        "semantic_reasons": len(reasons),
        "source_claim_candidates": len(scoped_claims),
        "duplicate_source_claim_candidates": len(claims) - len(scoped_claims),
        "naive_pairs": naive_pairs,
        "bound_pairs": candidate_build["bound_pairs_count"],
        "fallback_pairs": candidate_build["fallback_pairs_count"],
        "after_hard_filter": candidate_build["bound_pairs_count"] + candidate_build["fallback_pairs_count"],
        "after_recall": len(alignment_jobs),
        "unique_alignment_inputs": unique_alignment_inputs,
        "alignment_materialization_dedupe_ratio": round(
            1 - (unique_alignment_inputs / len(alignment_jobs)),
            6,
        ) if alignment_jobs else 0.0,
        "cache_hit_pairs": cache_hit_pairs,
        "existing_alignment_hit_pairs": existing_alignment_hits,
        "llm_call_cache_hit_pairs": llm_cache_hits,
        "missing_llm_call_cache_hit": missing_llm_cache_hits,
        "missing_pairs": missing_pairs,
        "actual_llm_required": missing_pairs,
        "lookup_first_llm_required": lookup_first_llm_required,
        "materialization_hit_count": materialization_hit_count,
        "legacy_reuse_count": legacy_reuse_count,
        "stale_count": stale_count,
        "missing_count": state_counts.get("MISSING", 0),
        "in_progress_count": in_progress_count,
        "failed_retryable_count": failed_retryable_count,
        "failed_final_count": failed_final_count,
        "incompatible_count": incompatible_count,
        "state_counts": dict(state_counts),
        "object_conservation": {
            "required_unique_inputs": unique_alignment_inputs,
            "materialization_hit": materialization_hit_count,
            "legacy_reuse": legacy_reuse_count,
            "missing": state_counts.get("MISSING", 0),
            "stale": stale_count,
            "in_progress": in_progress_count,
            "failed_retryable": failed_retryable_count,
            "failed_final": failed_final_count,
            "incompatible": incompatible_count,
            "counted_total": object_conservation_total,
            "is_balanced": object_conservation_total == unique_alignment_inputs,
        },
        "missing_no_external_llm_breakdown": missing_no_external_llm_breakdown,
        "missing_conservation": {
            "missing_total": missing_total,
            "missing_llm_required": lookup_first_llm_required,
            "explained_no_external_llm_total": sum(missing_no_external_llm_breakdown.values()),
            "counted_total": missing_conservation_total,
            "is_balanced": missing_conservation_total == missing_total,
        },
        "llm_input_contract": {
            "system_prompt_version": ALIGNMENT_PROMPT_VERSION,
            "schema_version": ALIGNMENT_SCHEMA_VERSION,
            "user_payload_fields": ["reason", "source_claim"],
            "semantic_input_normalization": "compact_whitespace",
            "materialization_key_fields": [
                "contract_version",
                "answer_unit_semantic_hash",
                "source_claim_semantic_hash",
            ],
            "excluded_fields": [
                "run_id",
                "evidence_package_id",
                "strategy_candidate_id",
                "answer_unit_row_id",
                "source_claim_row_id",
                "prompt_intent_embedding",
            ],
        },
        "current_implementation": {
            "candidate_pairs_before_recall": naive_pairs,
            "llm_cache_hit_pairs": current_llm_cache_hits,
            "external_llm_required_without_alignment_recall": max(
                len(current_implementation_llm_hashes) - current_llm_cache_hits,
                0,
            ),
        },
        "candidate_builder_shadow": {
            "mode": "PRODUCTION_CUTOVER" if settings.use_binding_aware_alignment_candidates_v1_1 else "SHADOW_ONLY",
            "current_builder": (
                "binding_aware_candidate_builder.v1"
                if settings.use_binding_aware_alignment_candidates_v1_1
                else "production_all_viable_pairs.v1"
            ),
            "proposed_builder": "binding_aware_candidate_builder.v1",
            "cutover_enabled": settings.use_binding_aware_alignment_candidates_v1_1,
            "legacy_candidate_builder_rollback_available": True,
            "identity": "ALIGNMENT_V1 materialization_key",
            "selected_shadow_policy": selected_shadow_policy,
            "selected_shadow_policy_key": selected_policy_key,
            "current_candidate_keys": len(current_candidate_keys),
            "proposed_candidate_keys": len(proposed_candidate_keys),
            "proposed_candidate_key_hash": _stable_hash(sorted(proposed_candidate_keys)),
            "shared_candidate_keys": len(shared_candidate_keys),
            "old_only_candidate_keys": len(old_only_candidate_keys),
            "new_only_candidate_keys": len(new_only_candidate_keys),
            "policy_candidate_keys": {
                "Policy A": len(policy_candidate_keys["POLICY_A_HARD_TOPK"]),
                "Policy B": len(policy_candidate_keys["POLICY_B_THRESHOLD_WITH_CAP"]),
                "Policy C": len(policy_candidate_keys["POLICY_C_TOPK_WITH_SCORE_MARGIN"]),
                "Policy D": len(policy_candidate_keys["POLICY_D_TOPK_WITH_BOUNDARY_TIES"]),
            },
            "base_hard_topk_candidate_keys": len(policy_candidate_keys["POLICY_A_HARD_TOPK"]),
            "old_only_existing_verdict_counts": old_only_audit["existing_verdict_row_counts"],
            "old_only_existing_verdict_row_counts": old_only_audit["existing_verdict_row_counts"],
            "old_only_supports_contradicts_row_count": old_only_audit["supports_contradicts_row_count"],
            "old_only_supports_contradicts_count": old_only_audit["supports_contradicts_count"],
            "old_only_supports_contradicts": old_only_audit["supports_contradicts"],
            "old_only_supports_contradicts_grain": "unique semantic materialization_key + relation; each item includes all matching row-level alignment_ids",
            "critical_reason_clusters": old_only_audit["reason_clusters"],
            "critical_classification_counts": old_only_audit["classification_counts"],
            "critical_exclusion_reason_counts": old_only_audit["exclusion_reason_counts"],
            "true_positive_recall_loss_count": len(true_positive_recall_loss_keys),
            "base_hard_topk_true_positive_recall_loss_count": len(base_true_positive_recall_loss_keys),
            "policy_simulations": policy_simulations,
            "boundary_tie_diagnostics": l3_boundary_tie_diagnostics,
            "boundary_tie_stats": tie_stats,
            "critical_boundary_tie_details": critical_boundary_tie_details,
            "recall_layer_comparison": {
                layer: {
                    "candidates": len(recall_layer_keys.get(layer, set())),
                    "shared": len(recall_layer_keys.get(layer, set()) & current_candidate_keys),
                    "old_only_recovered": 0,
                    "new_only": len(recall_layer_keys.get(layer, set()) - current_candidate_keys),
                }
                for layer in ["L0_EXPLICIT", "L1_ANSWER_CONTEXT", "L2_RUN_SCOPE", "L3_PROMPT_SCOPE"]
            },
            "l0_status": l0_status,
            "l0_status_reason": l0_status_reason,
            "l0_explicit_reason_count": l0_explicit_reason_count,
            "l0_semantics_change_explanation": l0_change_explanation,
            "l1_status": l1_status,
            "l1_status_reason": l1_status_reason,
            "l2_status": (
                candidate_build["l2_status"]
            ),
            "l2_attempted_reason_count": l2_attempted,
            "l2_matched_reason_count": l2_matched,
            "l3_attempted_reason_count": l3_attempted,
            "fallback_trigger_counts": dict(fallback_trigger_counts),
            "topk_application": {
                "L0_EXPLICIT_topk_applied": False,
                "L1_ANSWER_CONTEXT_topk_applied": False,
                "L2_RUN_SCOPE_topk_applied": True,
                "L3_PROMPT_SCOPE_topk_applied": True,
            },
            "shadow_downstream_diff": downstream_diff,
            "old_only_requires_review_before_cutover": bool(true_positive_recall_loss_keys or has_human_review_required),
            "c2b_cutover_gate": {
                "true_positive_recall_loss_clear": len(true_positive_recall_loss_keys) == 0,
                "critical_old_only_explained": critical_old_only_explained,
                "l2_shadow_verified": l2_matched > 0 or l2_attempted == 0,
                "l1_status_acceptable": l1_status in {"L1_IMPLEMENTED_NO_MATCH", "L1_UNAVAILABLE_BY_SCHEMA"},
                "l0_status_acceptable": l0_status in {"L0_IMPLEMENTED_MATCH", "L0_IMPLEMENTED_NO_MATCH"},
                "no_full_library_fallback": True,
                "boundary_tie_policy_verified": policy_simulations["Policy D"]["TRUE_POSITIVE_RECALL_LOSS"] == 0,
                "coarse_score_tie_risk": tie_stats["coarse_score_tie_risk"],
                "benchmark_unchanged": not downstream_benchmark_changed,
                "gap_unchanged": not downstream_gap_changed,
                "strategy_unchanged": not downstream_strategy_changed,
                "semantic_diff_requires_separate_decision": downstream_diff["semantic_diff_requires_separate_decision"],
                "c2_cutover_ready": c2_cutover_ready,
                "blocker": gate_blocker,
                "cutover_allowed": settings.use_binding_aware_alignment_candidates_v1_1,
            },
        },
        "deterministic_filter_counts": dict(deterministic_counts),
        "recall_path_counts": dict(recall_path_counts),
        "recall_top_k": recall_top_k,
        "recall_min_score": _RECALL_MIN_SCORE,
        "materialization_contract": ALIGNMENT_MATERIALIZATION_CONTRACT,
    }


def build_incremental_materialization_plan(
    db: Session,
    project: Project,
    prompt_id: int,
    *,
    run_ids: list[int] | None = None,
    top_k: int = 5,
) -> dict:
    started = datetime.utcnow()
    scoped_run_ids, scope_source, package = _current_run_scope(db, project.id, prompt_id, run_ids)
    document_plan, required_docs, run_doc_ids, _ = _document_plan(db, scoped_run_ids)
    passage_plan, passages = _passage_plan(required_docs)
    source_claim_plan, valid_claims = _source_claim_plan(db, project, passages)
    answer_unit_plan = _answer_unit_plan(db, project.id, prompt_id, scoped_run_ids)
    alignment_plan = _alignment_plan(db, project, prompt_id, scoped_run_ids, valid_claims, run_doc_ids, package=package, top_k=top_k)

    source_claim_reuse_rate = (
        source_claim_plan["hit"] / source_claim_plan["required_semantic_passages"]
        if source_claim_plan["required_semantic_passages"] else 1.0
    )
    alignment_reuse_rate = (
        alignment_plan["cache_hit_pairs"] / alignment_plan["unique_alignment_inputs"]
        if alignment_plan["unique_alignment_inputs"] else 1.0
    )
    llm_amplification_ratio = (
        alignment_plan["actual_llm_required"] / alignment_plan["naive_pairs"]
        if alignment_plan["naive_pairs"] else 0.0
    )
    current_source_claim_llm = source_claim_plan["current_implementation_llm_required"]
    current_alignment_llm = alignment_plan["current_implementation"]["external_llm_required_without_alignment_recall"]
    planned_source_claim_llm = source_claim_plan["lookup_first_llm_required"]
    planned_alignment_llm = alignment_plan["actual_llm_required"]
    primary_bottleneck = (
        "EVIDENCE_ALIGNMENT"
        if current_alignment_llm >= current_source_claim_llm
        else "SOURCE_CLAIM"
    )
    planner_duration_ms = int((datetime.utcnow() - started).total_seconds() * 1000)
    return {
        "status": "OK",
        "planner_version": PLANNER_VERSION,
        "read_only": True,
        "project_id": project.id,
        "prompt_id": prompt_id,
        "run_scope": {
            "source": scope_source,
            "run_count": len(scoped_run_ids),
            "run_ids": scoped_run_ids,
            "evidence_package_id": package.id if package else None,
            "evidence_package_version": package.version if package else None,
        },
        "materialization_contracts": {
            "answer_unit": ANSWER_UNIT_MATERIALIZATION_CONTRACT,
            "source_claim": SOURCE_CLAIM_MATERIALIZATION_CONTRACT,
            "alignment": ALIGNMENT_MATERIALIZATION_CONTRACT,
            "formal_input": FORMAL_V1_1_INPUT_VERSION,
        },
        "state_machine": MATERIALIZATION_STATUSES,
        "answer_units": answer_unit_plan,
        "source_documents": document_plan,
        "passages": passage_plan,
        "source_claims": source_claim_plan,
        "evidence_alignment": alignment_plan,
        "reuse": {
            "semantic_reuse_rate": round(
                answer_unit_plan["semantic_objects"] / answer_unit_plan["raw_observations"],
                4,
            ) if answer_unit_plan["raw_observations"] else 1.0,
            "source_claim_reuse_rate": round(source_claim_reuse_rate, 4),
            "alignment_reuse_rate": round(alignment_reuse_rate, 4),
            "llm_amplification_ratio": round(llm_amplification_ratio, 6),
        },
        "amplification": {
            "primary_bottleneck": primary_bottleneck,
            "run_to_answer_unit_observation_factor": round(
                answer_unit_plan["raw_observations"] / len(scoped_run_ids),
                4,
            ) if scoped_run_ids else 0.0,
            "answer_unit_semantic_reuse_factor": round(
                answer_unit_plan["raw_observations"] / answer_unit_plan["semantic_objects"],
                4,
            ) if answer_unit_plan["semantic_objects"] else 0.0,
            "document_to_passage_factor": round(
                source_claim_plan["required_semantic_passages"] / document_plan["required_documents"],
                4,
            ) if document_plan["required_documents"] else 0.0,
            "alignment_pair_factor": round(
                alignment_plan["naive_pairs"] / alignment_plan["semantic_reasons"],
                4,
            ) if alignment_plan["semantic_reasons"] else 0.0,
            "alignment_recall_cropping_ratio": round(
                alignment_plan["after_recall"] / alignment_plan["naive_pairs"],
                4,
            ) if alignment_plan["naive_pairs"] else 0.0,
            "current_external_llm_required_without_incrementalization": (
                current_source_claim_llm + current_alignment_llm
            ),
            "planned_external_llm_required_after_lookup_and_recall": (
                planned_source_claim_llm + planned_alignment_llm
            ),
            "planned_external_llm_reduction": max(
                (current_source_claim_llm + current_alignment_llm)
                - (planned_source_claim_llm + planned_alignment_llm),
                0,
            ),
        },
        "performance_log": {
            "planner_duration_ms": planner_duration_ms,
            "source_claim_cache_hit_rate": round(source_claim_reuse_rate, 4),
            "alignment_cache_hit_rate": round(alignment_reuse_rate, 4),
            "naive_alignment_pairs": alignment_plan["naive_pairs"],
            "candidate_alignment_pairs": alignment_plan["after_recall"],
            "actual_alignment_llm_calls": alignment_plan["actual_llm_required"],
            "fallback_recall_rate": round(
                alignment_plan["recall_path_counts"].get("PROMPT_SCOPE_RECALL", 0) / alignment_plan["after_recall"],
                4,
            ) if alignment_plan["after_recall"] else 0.0,
            "explicit_binding_recall_rate": round(
                alignment_plan["recall_path_counts"].get("EXPLICIT_BINDING", 0) / alignment_plan["after_recall"],
                4,
            ) if alignment_plan["after_recall"] else 0.0,
            "run_scope_fallback_rate": 0.0,
            "prompt_scope_fallback_rate": round(
                alignment_plan["recall_path_counts"].get("PROMPT_SCOPE_RECALL", 0) / alignment_plan["after_recall"],
                4,
            ) if alignment_plan["after_recall"] else 0.0,
            "materialization_wait_count": 0,
            "singleflight_dedup_count": 0,
            "llm_token_usage": None,
            "llm_call_count": (
                planned_source_claim_llm
                + planned_alignment_llm
            ),
            "llm_duration": None,
        },
        "notes": [
            "Materialization planner is read-only and does not execute SourceClaim or EvidenceAlignment generation.",
            "EvidenceAlignment after_recall is a deterministic planner estimate; Phase C1 rewires verdict materialization only, not recall execution.",
            "Cache reuse may share semantic verdicts, but Prompt/Run/Evidence Package scope must still be rebound per current context.",
        ],
    }
