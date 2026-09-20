from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, ReferenceSource, SourceDocument
from app.modules.optimization.source_mapping import (
    DataHealthState,
    SourceMappingOutcome,
    backfill_url_identity_fields,
    build_source_mapping_report,
)
from app.services.url_identity import (
    CANONICALIZATION_VERSION,
    build_url_identity,
    canonicalize_url,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _ref(db, url: str, canonical_url: str = "", **kwargs) -> ReferenceSource:
    row = ReferenceSource(
        run_id=1,
        reference_index=1,
        url=url,
        canonical_url=canonical_url,
        domain="example.com",
        **kwargs,
    )
    db.add(row)
    db.flush()
    return row


def _doc(db, url: str, original_url: str = "", canonical_url: str = "", **kwargs) -> SourceDocument:
    row = SourceDocument(
        url=url,
        original_url=original_url,
        canonical_url=canonical_url,
        domain="example.com",
        **kwargs,
    )
    db.add(row)
    db.flush()
    return row


def _single_outcome(report: dict) -> dict:
    assert len(report["outcomes"]) == 1
    return report["outcomes"][0]


def test_canonicalize_url_is_idempotent_and_strips_tracking():
    raw = "HTTPS://WWW.Example.com/a//b/?utm_source=x&b=2&a=1#fragment"
    canonical = canonicalize_url(raw)
    assert canonical == "https://example.com/a/b?a=1&b=2"
    assert canonicalize_url(canonical) == canonical


def test_same_version_canonical_hash_match(db):
    identity = build_url_identity("https://example.com/a")
    ref = _ref(
        db,
        "http://www.example.com/a",
        identity.canonical_url,
        canonical_url_hash=identity.canonical_url_hash,
        canonicalization_version=CANONICALIZATION_VERSION,
    )
    doc = _doc(
        db,
        "https://example.com/a",
        canonical_url=identity.canonical_url,
        canonical_url_hash=identity.canonical_url_hash,
        canonicalization_version=CANONICALIZATION_VERSION,
    )

    outcome = _single_outcome(build_source_mapping_report(db, [ref]))
    assert outcome["outcome"] == SourceMappingOutcome.MAPPED_CANONICAL
    assert outcome["source_document_ids"] == [doc.id]


def test_raw_url_fallback_maps_when_canonical_metadata_is_legacy(db):
    ref = _ref(db, "http://example.com/raw")
    doc = _doc(db, "http://example.com/raw")

    outcome = _single_outcome(build_source_mapping_report(db, [ref]))
    assert outcome["outcome"] == SourceMappingOutcome.MAPPED_EXACT
    assert outcome["source_document_ids"] == [doc.id]


def test_raw_url_differs_but_current_recanonicalization_maps_legacy_document(db):
    ref = _ref(db, "https://example.com/a")
    doc = _doc(
        db,
        "https://www.example.com/a/?utm_source=legacy",
        canonicalization_version="legacy.v0",
    )

    outcome = _single_outcome(build_source_mapping_report(db, [ref]))
    assert outcome["outcome"] == SourceMappingOutcome.MAPPED_COMPATIBLE_VERSION
    assert outcome["source_document_ids"] == [doc.id]


def test_invalid_url_has_explicit_outcome_and_manual_review(db):
    ref = _ref(db, "not a valid url")
    outcome = _single_outcome(build_source_mapping_report(db, [ref]))

    assert outcome["outcome"] == SourceMappingOutcome.UNMAPPED_INVALID_URL
    assert outcome["requires_manual_review"] is True
    assert outcome["retryability"] == "MANUAL_REVIEW"


def test_version_locator_mismatch_is_not_silently_no_source(db):
    ref = _ref(db, "https://example.com/a?view=one")
    _doc(
        db,
        "https://example.com/a?view=two",
        canonicalization_version="legacy.v0",
    )

    outcome = _single_outcome(build_source_mapping_report(db, [ref]))
    assert outcome["outcome"] == SourceMappingOutcome.UNMAPPED_VERSION_INCOMPATIBLE
    assert outcome["retryability"] == "RECANONICALIZE"


def test_references_present_with_zero_mapped_is_input_invalid(db):
    ref = _ref(db, "https://missing.example.com/a")
    report = build_source_mapping_report(db, [ref])

    assert report["data_health_state"] == DataHealthState.INVALID
    assert report["mapped_unique_urls"] == 0
    assert report["unmapped_unique_urls"] == 1
    assert report["conservation"]["valid"] is True
    assert "REFERENCE_URLS_PRESENT_BUT_NONE_MAPPED" in report["data_health_reasons"]


def test_input_invalid_recovers_after_source_is_available(db):
    ref = _ref(db, "https://recover.example.com/a")
    assert build_source_mapping_report(db, [ref])["data_health_state"] == DataHealthState.INVALID

    _doc(db, "https://recover.example.com/a")
    recovered = build_source_mapping_report(db, [ref])
    assert recovered["data_health_state"] == DataHealthState.HEALTHY
    assert recovered["mapped_unique_urls"] == 1


def test_backfill_materializes_current_identity_without_changing_raw_url(db):
    ref = _ref(db, "https://www.example.com/a/?utm_source=old")
    doc = _doc(db, "https://example.com/a", original_url="https://www.example.com/a/?utm_source=old")

    result = backfill_url_identity_fields(db, references=[ref], retrievals=[], documents=[doc])

    assert result == {"references": 1, "retrievals": 0, "documents": 1}
    assert ref.url == "https://www.example.com/a/?utm_source=old"
    assert ref.canonical_url == "https://example.com/a"
    assert ref.canonicalization_version == CANONICALIZATION_VERSION
    assert len(ref.canonical_url_hash) == 64
    assert doc.original_url == "https://www.example.com/a/?utm_source=old"


def test_compatible_mapping_does_not_admit_unrelated_historical_document(db):
    ref = _ref(db, "https://example.com/current")
    current = _doc(db, "https://www.example.com/current/?utm_source=old")
    _doc(db, "https://history.example.com/unrelated")

    report = build_source_mapping_report(db, [ref])

    assert report["source_document_ids"] == [current.id]
    assert report["aggregation_input_documents"] == 1
