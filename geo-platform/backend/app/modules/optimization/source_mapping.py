from __future__ import annotations

from collections import defaultdict
from enum import StrEnum
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.models import OptimizationEvidencePackage, ReferenceSource, RetrievalCandidate, SourceDocument
from app.services.serialization import loads
from app.services.url_identity import (
    CANONICALIZATION_VERSION,
    UrlIdentity,
    build_url_identity,
)


class SourceMappingOutcome(StrEnum):
    MAPPED_EXACT = "MAPPED_EXACT"
    MAPPED_CANONICAL = "MAPPED_CANONICAL"
    MAPPED_COMPATIBLE_VERSION = "MAPPED_COMPATIBLE_VERSION"
    MAPPED_REDIRECT = "MAPPED_REDIRECT"
    UNMAPPED_NO_SOURCE = "UNMAPPED_NO_SOURCE"
    UNMAPPED_INVALID_URL = "UNMAPPED_INVALID_URL"
    UNMAPPED_VERSION_INCOMPATIBLE = "UNMAPPED_VERSION_INCOMPATIBLE"


class DataHealthState(StrEnum):
    HEALTHY = "HEALTHY"
    WARN = "WARN"
    INVALID = "INVALID"


_MAPPED_OUTCOMES = {
    SourceMappingOutcome.MAPPED_EXACT,
    SourceMappingOutcome.MAPPED_CANONICAL,
    SourceMappingOutcome.MAPPED_COMPATIBLE_VERSION,
    SourceMappingOutcome.MAPPED_REDIRECT,
}


def _record_identity(record: ReferenceSource | RetrievalCandidate) -> UrlIdentity:
    raw_url = (record.url or "").strip()
    identity = build_url_identity(raw_url, record.canonical_url or raw_url)
    if not identity.valid and raw_url:
        identity = build_url_identity(raw_url)
    return identity


def _document_identity(doc: SourceDocument) -> UrlIdentity:
    raw_url = (doc.original_url or doc.url or "").strip()
    identity = build_url_identity(raw_url, doc.canonical_url or doc.url or raw_url)
    if not identity.valid and raw_url:
        identity = build_url_identity(raw_url)
    return identity


def _locator_key(value: str) -> tuple[str, str] | None:
    identity = build_url_identity(value)
    if not identity.valid:
        return None
    parsed = urlparse(identity.canonical_url)
    return parsed.netloc, parsed.path or "/"


def _document_indexes(docs: list[SourceDocument]) -> dict:
    same_version_hash: dict[str, list[SourceDocument]] = defaultdict(list)
    raw: dict[str, list[SourceDocument]] = defaultdict(list)
    current_canonical: dict[str, list[SourceDocument]] = defaultdict(list)
    old_version_locator: dict[tuple[str, str], list[SourceDocument]] = defaultdict(list)
    identities: dict[int, UrlIdentity] = {}

    for doc in docs:
        identity = _document_identity(doc)
        identities[int(doc.id)] = identity
        if (
            doc.canonicalization_version == CANONICALIZATION_VERSION
            and doc.canonical_url_hash
        ):
            same_version_hash[doc.canonical_url_hash].append(doc)
        for value in {doc.original_url, doc.url}:
            if value and value.strip():
                raw[value.strip()].append(doc)
        for value in {doc.original_url, doc.url, doc.canonical_url}:
            candidate = build_url_identity(value or "")
            if candidate.valid:
                current_canonical[candidate.canonical_url].append(doc)
                if doc.canonicalization_version != CANONICALIZATION_VERSION:
                    locator = _locator_key(value or "")
                    if locator:
                        old_version_locator[locator].append(doc)

    return {
        "same_version_hash": same_version_hash,
        "raw": raw,
        "current_canonical": current_canonical,
        "old_version_locator": old_version_locator,
        "identities": identities,
    }


def _unique_records(records: list[ReferenceSource | RetrievalCandidate]) -> list[ReferenceSource | RetrievalCandidate]:
    result = []
    seen = set()
    for record in records:
        # Coverage conserves the observed URL set. Canonical identities may
        # intentionally collapse multiple observed variants onto one document.
        key = (record.url or record.canonical_url or "").strip()
        if not key:
            key = f"invalid-record:{record.id}"
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result


def _match_record(record, indexes: dict) -> dict:
    identity = _record_identity(record)
    display_url = (record.canonical_url or record.url or "").strip()
    base = {
        "source_record_id": int(record.id),
        "raw_url": (record.url or "").strip(),
        "canonical_url": identity.canonical_url,
        "canonical_url_hash": identity.canonical_url_hash,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "source_document_ids": [],
        "retryability": "NONE",
        "requires_manual_review": False,
        "reason": "",
    }
    if not identity.valid:
        return {
            **base,
            "outcome": SourceMappingOutcome.UNMAPPED_INVALID_URL.value,
            "retryability": "MANUAL_REVIEW",
            "requires_manual_review": True,
            "reason": identity.invalid_reason or "INVALID_URL",
        }

    if (
        record.canonicalization_version == CANONICALIZATION_VERSION
        and record.canonical_url_hash
    ):
        docs = indexes["same_version_hash"].get(record.canonical_url_hash, [])
        if docs:
            return {
                **base,
                "outcome": SourceMappingOutcome.MAPPED_CANONICAL.value,
                "source_document_ids": sorted({int(doc.id) for doc in docs}),
                "reason": "SAME_VERSION_CANONICAL_HASH",
            }

    exact_docs = []
    for value in {(record.url or "").strip(), (record.canonical_url or "").strip()}:
        if value:
            exact_docs.extend(indexes["raw"].get(value, []))
    if exact_docs:
        return {
            **base,
            "outcome": SourceMappingOutcome.MAPPED_EXACT.value,
            "source_document_ids": sorted({int(doc.id) for doc in exact_docs}),
            "reason": "RAW_URL_EXACT",
        }

    compatible_docs = indexes["current_canonical"].get(identity.canonical_url, [])
    if compatible_docs:
        versions = {
            doc.canonicalization_version or "LEGACY_UNVERSIONED"
            for doc in compatible_docs
        }
        compatible = (
            record.canonicalization_version != CANONICALIZATION_VERSION
            or any(version != CANONICALIZATION_VERSION for version in versions)
        )
        return {
            **base,
            "outcome": (
                SourceMappingOutcome.MAPPED_COMPATIBLE_VERSION.value
                if compatible
                else SourceMappingOutcome.MAPPED_CANONICAL.value
            ),
            "source_document_ids": sorted({int(doc.id) for doc in compatible_docs}),
            "reason": "CURRENT_RULE_RECANONICALIZATION" if compatible else "CURRENT_CANONICAL_MATCH",
        }

    locator = _locator_key(display_url)
    incompatible_docs = indexes["old_version_locator"].get(locator, []) if locator else []
    if incompatible_docs:
        return {
            **base,
            "outcome": SourceMappingOutcome.UNMAPPED_VERSION_INCOMPATIBLE.value,
            "retryability": "RECANONICALIZE",
            "reason": "LEGACY_VERSION_LOCATOR_MATCH_BUT_CURRENT_IDENTITY_DIFFERS",
        }

    return {
        **base,
        "outcome": SourceMappingOutcome.UNMAPPED_NO_SOURCE.value,
        "retryability": "AUTO_RETRY",
        "reason": "NO_SOURCE_DOCUMENT_IDENTITY_MATCH",
    }


def build_source_mapping_report(
    db: Session,
    references: list[ReferenceSource],
    retrievals: list[RetrievalCandidate] | None = None,
) -> dict:
    """Map only current-scope source records and report explicit URL conservation."""
    docs = db.query(SourceDocument).all()
    indexes = _document_indexes(docs)
    unique_references = _unique_records(references)
    outcomes = [_match_record(record, indexes) for record in unique_references]
    retrieval_outcomes = [
        _match_record(record, indexes)
        for record in _unique_records(retrievals or [])
    ]

    by_outcome = {outcome.value: 0 for outcome in SourceMappingOutcome}
    mapped_document_ids: set[int] = set()
    for outcome in outcomes:
        by_outcome[outcome["outcome"]] += 1
        mapped_document_ids.update(outcome["source_document_ids"])
    for outcome in retrieval_outcomes:
        mapped_document_ids.update(outcome["source_document_ids"])

    mapped_unique_urls = sum(by_outcome[outcome.value] for outcome in _MAPPED_OUTCOMES)
    total_unique_urls = len(outcomes)
    unmapped_unique_urls = total_unique_urls - mapped_unique_urls
    reasons = []
    if total_unique_urls > 0 and mapped_unique_urls == 0:
        reasons.append("REFERENCE_URLS_PRESENT_BUT_NONE_MAPPED")
    if len(references) > 0 and not mapped_document_ids:
        reasons.append("CITATIONS_PRESENT_BUT_NO_AGGREGATION_INPUT_DOCUMENTS")
    if reasons:
        health = DataHealthState.INVALID
    elif unmapped_unique_urls > 0:
        health = DataHealthState.WARN
    else:
        health = DataHealthState.HEALTHY

    return {
        "canonicalization_version": CANONICALIZATION_VERSION,
        "source_document_ids": sorted(mapped_document_ids),
        "aggregation_input_documents": len(mapped_document_ids),
        "total_reference_records": len(references),
        "total_unique_reference_urls": total_unique_urls,
        "mapped_unique_urls": mapped_unique_urls,
        "unmapped_unique_urls": unmapped_unique_urls,
        "mapping_coverage": (mapped_unique_urls / total_unique_urls) if total_unique_urls else 1.0,
        "by_outcome": by_outcome,
        "requires_manual_review_urls": [
            outcome["raw_url"] or outcome["canonical_url"]
            for outcome in outcomes
            if outcome["requires_manual_review"]
        ],
        "data_health_state": health.value,
        "data_health_reasons": reasons,
        "conservation": {
            "total_unique_reference_urls": total_unique_urls,
            "mapped_plus_unmapped": mapped_unique_urls + unmapped_unique_urls,
            "valid": total_unique_urls == mapped_unique_urls + unmapped_unique_urls,
        },
        "outcomes": outcomes,
    }


def source_mapping_health_for_prompt(
    db: Session,
    project_id: int,
    prompt_id: int,
    evidence_package_id: int | None = None,
) -> dict:
    query = db.query(OptimizationEvidencePackage).filter(
        OptimizationEvidencePackage.project_id == project_id,
        OptimizationEvidencePackage.prompt_id == prompt_id,
    )
    if evidence_package_id is not None:
        package = query.filter(OptimizationEvidencePackage.id == evidence_package_id).first()
    else:
        package = (
            query.filter(OptimizationEvidencePackage.status == "active")
            .order_by(OptimizationEvidencePackage.created_at.desc(), OptimizationEvidencePackage.id.desc())
            .first()
        )
    if package is None:
        raise ValueError("CURRENT_EVIDENCE_PACKAGE_NOT_FOUND")

    run_ids = [int(run_id) for run_id in loads(package.source_run_ids_json, []) if run_id]
    references = db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(run_ids)).all() if run_ids else []
    retrievals = db.query(RetrievalCandidate).filter(RetrievalCandidate.run_id.in_(run_ids)).all() if run_ids else []
    report = build_source_mapping_report(db, references, retrievals)
    return {
        "project_id": project_id,
        "prompt_id": prompt_id,
        "evidence_package_id": int(package.id),
        "evidence_package_version": int(package.version or 0),
        "run_ids": run_ids,
        **report,
    }


def backfill_url_identity_fields(
    db: Session,
    *,
    references: list[ReferenceSource] | None = None,
    retrievals: list[RetrievalCandidate] | None = None,
    documents: list[SourceDocument] | None = None,
) -> dict[str, int]:
    """Deterministically migrate legacy rows without making version a hard wall."""
    groups = {
        "references": references if references is not None else db.query(ReferenceSource).all(),
        "retrievals": retrievals if retrievals is not None else db.query(RetrievalCandidate).all(),
        "documents": documents if documents is not None else db.query(SourceDocument).all(),
    }
    counts = {key: 0 for key in groups}
    for key, rows in groups.items():
        for row in rows:
            raw_url = (
                (row.original_url or row.url or "")
                if isinstance(row, SourceDocument)
                else (row.url or "")
            )
            identity = build_url_identity(raw_url, row.canonical_url or row.url or raw_url)
            if not identity.valid:
                continue
            if (
                row.canonical_url != identity.canonical_url
                or row.canonical_url_hash != identity.canonical_url_hash
                or row.canonicalization_version != CANONICALIZATION_VERSION
            ):
                row.canonical_url = identity.canonical_url
                row.canonical_url_hash = identity.canonical_url_hash
                row.canonicalization_version = CANONICALIZATION_VERSION
                counts[key] += 1
    db.commit()
    return counts
