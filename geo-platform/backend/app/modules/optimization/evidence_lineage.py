"""EvidenceAlignment formal V1 lineage eligibility.

This module is intentionally small and deterministic. It does not score
evidence; it only decides whether an EvidenceAlignment can be consumed by the
formal single-Prompt V1 decision chain.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import (
    AnswerDecisionBinding,
    AnswerUnit,
    BrowserMonitorRun,
    EvidenceAlignment,
    RecommendationEvent,
    ReferenceSource,
    SourceClaim,
    SourceDocument,
)
from app.modules.optimization.passage_retrieval import (
    ANSWER_BINDING_REASON_SOURCE,
    FORMAL_V1_1_INPUT_VERSION,
)
from app.services.serialization import loads
from app.services.url_identity import canonicalize_url

LEGACY_INELIGIBLE_RELATIONS = {"RELATED"}


@dataclass(frozen=True)
class EvidenceLineageEligibility:
    eligible_for_v1: bool
    ineligibility_reasons: list[str]
    run_id: int | None = None
    answer_unit_id: int | None = None
    decision_binding_id: int | None = None
    recommendation_event_id: int | None = None
    source_document_id: int | None = None
    source_claim_id: int | None = None
    reference_source_id: int | None = None

    def as_dict(self) -> dict:
        return {
            "eligible_for_v1": self.eligible_for_v1,
            "ineligibility_reasons": self.ineligibility_reasons,
            "run_id": self.run_id,
            "answer_unit_id": self.answer_unit_id,
            "decision_binding_id": self.decision_binding_id,
            "recommendation_event_id": self.recommendation_event_id,
            "source_document_id": self.source_document_id,
            "source_claim_id": self.source_claim_id,
            "reference_source_id": self.reference_source_id,
        }


def evaluate_evidence_alignment_v1_eligibility(
    db: Session,
    alignment: EvidenceAlignment,
    *,
    allowed_run_ids: set[int] | None = None,
    include_answer_binding_v1_1: bool = False,
) -> EvidenceLineageEligibility:
    """Return formal V1 eligibility for one EvidenceAlignment.

    SourceDocument and SourceClaim are document-level facts and may be reused
    across Runs. The Run lineage is established by the current Run's
    ReferenceSource pointing to the SourceDocument, plus AnswerUnit /
    AnswerDecisionBinding / RecommendationEvent consistency.
    """

    reasons: list[str] = []
    payload = loads(alignment.machine_payload_json, {})
    run_id = int(alignment.run_id or 0) or None
    answer_unit_id = _optional_int(payload.get("answer_unit_id"))
    decision_binding_id = _optional_int(payload.get("decision_binding_id"))

    if not run_id:
        reasons.append("MISSING_RUN_LINEAGE")
    elif allowed_run_ids is not None and run_id not in allowed_run_ids:
        reasons.append("RUN_NOT_IN_CURRENT_PACKAGE")

    if (alignment.relation or "").upper() in LEGACY_INELIGIBLE_RELATIONS:
        reasons.append("LEGACY_RELATION_ONLY")

    is_v1_1 = _is_answer_binding_v1_1_payload(payload)
    if is_v1_1 and not include_answer_binding_v1_1:
        reasons.append("ANSWER_BINDING_V1_1_DISABLED")
    if not is_v1_1:
        reasons.append("LEGACY_RELATION_ONLY")

    run = db.get(BrowserMonitorRun, run_id) if run_id else None
    if not run:
        reasons.append("MISSING_RUN_LINEAGE")
    else:
        if run.project_id != alignment.project_id or run.prompt_id != alignment.prompt_id:
            reasons.append("RUN_MISMATCH")

    event = db.get(RecommendationEvent, alignment.recommendation_event_id) if alignment.recommendation_event_id else None
    if not event:
        reasons.append("MISSING_RECOMMENDATION_EVENT")
    else:
        if event.project_id != alignment.project_id or event.prompt_id != alignment.prompt_id:
            reasons.append("RUN_MISMATCH")
        if run_id and event.run_id != run_id:
            reasons.append("RUN_MISMATCH")

    unit = db.get(AnswerUnit, answer_unit_id) if answer_unit_id else None
    if not unit:
        reasons.append("MISSING_ANSWER_UNIT")
    else:
        if unit.project_id != alignment.project_id or unit.prompt_id != alignment.prompt_id:
            reasons.append("RUN_MISMATCH")
        if run_id and unit.run_id != run_id:
            reasons.append("RUN_MISMATCH")

    binding = db.get(AnswerDecisionBinding, decision_binding_id) if decision_binding_id else None
    if not binding:
        reasons.append("MISSING_DECISION_BINDING")
    else:
        if binding.project_id != alignment.project_id or binding.prompt_id != alignment.prompt_id:
            reasons.append("RUN_MISMATCH")
        if run_id and binding.run_id != run_id:
            reasons.append("RUN_MISMATCH")
        if event and binding.recommendation_event_id != event.id:
            reasons.append("RUN_MISMATCH")
        if unit and binding.answer_unit_id != unit.id:
            reasons.append("RUN_MISMATCH")

    doc = db.get(SourceDocument, alignment.source_document_id) if alignment.source_document_id else None
    if not doc:
        reasons.append("SOURCE_DOCUMENT_MISMATCH")

    claim = db.get(SourceClaim, alignment.source_claim_id) if alignment.source_claim_id else None
    if not claim:
        reasons.append("SOURCE_DOCUMENT_MISMATCH")
    else:
        if claim.project_id != alignment.project_id:
            reasons.append("SOURCE_DOCUMENT_MISMATCH")
        if doc and claim.source_document_id != doc.id:
            reasons.append("SOURCE_DOCUMENT_MISMATCH")

    reference_source_id = None
    if run_id and doc:
        reference_source_id = _reference_source_id_for_run_document(db, run_id, doc)
        if not reference_source_id:
            reasons.append("SOURCE_NOT_REFERENCED_IN_RUN")

    return EvidenceLineageEligibility(
        eligible_for_v1=not reasons,
        ineligibility_reasons=sorted(set(reasons)),
        run_id=run_id,
        answer_unit_id=answer_unit_id,
        decision_binding_id=decision_binding_id,
        recommendation_event_id=alignment.recommendation_event_id,
        source_document_id=alignment.source_document_id,
        source_claim_id=alignment.source_claim_id,
        reference_source_id=reference_source_id,
    )


def eligible_evidence_alignments_for_v1(
    db: Session,
    alignments: list[EvidenceAlignment],
    *,
    allowed_run_ids: set[int] | None = None,
    include_answer_binding_v1_1: bool = False,
) -> tuple[list[EvidenceAlignment], dict[int, EvidenceLineageEligibility]]:
    eligibility_by_id: dict[int, EvidenceLineageEligibility] = {}
    eligible: list[EvidenceAlignment] = []
    for alignment in alignments:
        result = evaluate_evidence_alignment_v1_eligibility(
            db,
            alignment,
            allowed_run_ids=allowed_run_ids,
            include_answer_binding_v1_1=include_answer_binding_v1_1,
        )
        eligibility_by_id[alignment.id] = result
        if result.eligible_for_v1:
            eligible.append(alignment)
    return eligible, eligibility_by_id


def _is_answer_binding_v1_1_payload(payload: dict) -> bool:
    return (
        payload.get("reason_source") == ANSWER_BINDING_REASON_SOURCE
        or payload.get("formal_input_version") == FORMAL_V1_1_INPUT_VERSION
    )


def _reference_source_id_for_run_document(db: Session, run_id: int, doc: SourceDocument) -> int | None:
    doc_url_keys = {
        key
        for key in (_normalize_url_key(doc.url), _normalize_url_key(doc.original_url), _normalize_url_key(doc.canonical_url))
        if key
    }
    refs = db.query(ReferenceSource).filter(ReferenceSource.run_id == run_id).all()
    for ref in refs:
        ref_url_keys = {
            key
            for key in (_normalize_url_key(ref.url), _normalize_url_key(ref.canonical_url))
            if key
        }
        if doc_url_keys and ref_url_keys and doc_url_keys.intersection(ref_url_keys):
            return ref.id

    # URL is the normal relationship. Domain + title is only a fallback for
    # captured citations that have no resolvable URL.
    if doc_url_keys:
        return None
    doc_title = (doc.title or "").strip()
    doc_domain = (doc.domain or "").strip().lower()
    if not doc_title or not doc_domain:
        return None
    for ref in refs:
        ref_title = (ref.display_title or ref.matched_title or "").strip()
        if ref_title == doc_title and (ref.domain or "").strip().lower() == doc_domain:
            return ref.id
    return None


def _normalize_url_key(url: str | None) -> str:
    return canonicalize_url(str(url or ""))


def _optional_int(value: object) -> int | None:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return None
    return parsed or None
