from __future__ import annotations

from copy import deepcopy
import json
import sqlite3

import pytest

from app.modules.runtime_projection.canonical import EMPTY_COLLECTION, FIELD_ABSENT, manifest_hash
from app.modules.runtime_projection.projector import (
    CASE_MANIFESTS,
    EXPECTED_STAGE_STATUS,
    RuntimeProjectionProjector,
    normative_vectors,
    run_projection_spike,
)


@pytest.fixture(scope="module")
def spike_report() -> dict:
    return run_projection_spike()


def test_frozen_normative_vectors_match_exactly() -> None:
    vectors = normative_vectors()
    assert all(vector["match"] for vector in vectors.values())
    assert vectors["source_ref_set_hash"]["actual"].endswith("a483")
    assert "d831" not in vectors["source_ref_set_hash"]["actual"]


def test_zero_output_manifest_is_stable_and_distinct_from_absent() -> None:
    zero_hash = manifest_hash(
        "StageOutputManifest/SOURCE_CLAIM",
        "runtime_stage.source_claim.v1/output",
        {"members": EMPTY_COLLECTION},
    )
    assert zero_hash == manifest_hash(
        "StageOutputManifest/SOURCE_CLAIM",
        "runtime_stage.source_claim.v1/output",
        {"members": EMPTY_COLLECTION},
    )
    assert zero_hash != manifest_hash(
        "StageOutputManifest/SOURCE_CLAIM",
        "runtime_stage.source_claim.v1/output",
        {"members": FIELD_ABSENT},
    )


def test_real_cases_match_frozen_stage_expectations(spike_report: dict) -> None:
    assert spike_report["result_classification"] == "SPIKE_PASS"
    for case_id, expected in EXPECTED_STAGE_STATUS.items():
        result = spike_report["cases"][case_id]
        actual = {stage["stage_type"]: stage["completeness"] for stage in result["stage_graph"]}
        assert actual == expected
        assert len(result["stage_graph"]) == 16
        assert result["stage_expectation_diff_count"] == 0
        assert result["root_projection"]["completeness"] == "PARTIAL"
        assert result["strategy_lineage"] == "UNSAFE"


def test_replay_is_deterministic_and_read_only(spike_report: dict) -> None:
    for result in spike_report["determinism"].values():
        assert result["diff"] is False
        assert result["virtual_context_id_identical"] is True
        assert result["stage_virtual_ids_identical"] is True
        assert result["source_ref_set_hashes_identical"] is True
        assert result["input_set_hashes_identical"] is True
        assert result["completeness_identical"] is True
        assert result["blocking_reasons_identical"] is True
    safety = spike_report["safety"]
    assert safety["latest_substitution_count"] == 0
    assert safety["semantic_invention_count"] == 0
    assert set(safety["semantic_invention_audit"].values()) == {0}
    assert safety["db_writes"] == 0
    assert safety["db_sha_before"] == safety["db_sha_after"]


def test_unsafe_projection_never_creates_current_or_authoritative_review(spike_report: dict) -> None:
    for result in spike_report["cases"].values():
        assert result["current_projection"]["status"] == "UNRESOLVED"
        assert result["current_projection"]["current_context_pointer"] is None
        assert set(result["current_projection"]["context_stage_selections"].values()) == {None}
        for stage in result["stage_graph"]:
            assert stage["current_eligibility"] is False
            if stage["review_binding_projection"] != "NONE":
                assert stage["authoritative_review_projection"] == "UNRESOLVED_LEGACY"
            assert stage["input_manifest"] is None
            assert stage["input_set_hash"] is None


def test_partial_preserves_missing_candidate_lineage(spike_report: dict) -> None:
    result = spike_report["cases"]["CASE-REAL-040"]
    assert result["root_projection"]["context_fingerprint"] is None
    assert result["root_projection"]["root_manifest_hash"] is None
    strategy = next(stage for stage in result["stage_graph"] if stage["stage_type"] == "STRATEGY_SYNTHESIS")
    assert strategy["completeness"] == "PARTIAL"
    assert strategy["virtual_stage_execution_id"].startswith("virtual-stage:")


def test_missing_fixed_object_is_unavailable_without_latest_substitution() -> None:
    manifest_path = CASE_MANIFESTS["CASE-REAL-019"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing = deepcopy(manifest)
    missing["fixed_input"]["evidence_package_id"] = 999999999
    with RuntimeProjectionProjector() as projector:
        result = projector.project_manifest(missing)
    assert result["root_projection"]["completeness"] == "UNAVAILABLE"
    assert result["latest_substitution_count"] == 0
    assert result["current_projection"]["current_context_pointer"] is None
    assert {stage["completeness"] for stage in result["stage_graph"]} == {"UNAVAILABLE"}


def test_projection_connection_rejects_database_writes() -> None:
    with RuntimeProjectionProjector() as projector:
        with pytest.raises(sqlite3.DatabaseError):
            projector.connection.execute("UPDATE prompts SET id=id WHERE id=-1")
