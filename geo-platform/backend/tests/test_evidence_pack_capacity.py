"""Offline Evidence Pack v3 capacity and provenance pressure matrix.

These tests deliberately exercise the projection with synthetic, traceable
scopes.  They never call a provider and never touch the Beta database.  The
matrix is intended to make a future capacity change measurable without
mistaking synthetic results for business-quality validation.
"""

from __future__ import annotations

import json
from collections import Counter

import pytest

from app.modules.agent_experiment.evidence_pack import (
    EvidencePackCapacityError,
    build_evidence_pack,
)


SIZES = (22, 50, 100, 300, 1000)
PROFILES = ("high_repeat_url", "high_unique_url", "long_source")
BUDGET = 90_000


def _url(index: int) -> str:
    return f"https://example-{index}.invalid/articles/guide-{index}"


def _make_scope(run_count: int, profile: str) -> dict:
    runs: list[dict] = []
    references: list[dict] = []
    snapshots: list[dict] = []
    if profile == "high_repeat_url":
        url_count = 8
    elif profile == "high_unique_url":
        url_count = run_count * 3
    else:
        url_count = max(4, min(run_count, 20))

    for offset in range(run_count):
        run_id = offset + 1
        # 1,600 CJK characters models a moderately long observed answer and
        # keeps the test close to the real 22-run failure shape.
        answer = (
            f"synthetic-answer-run-{run_id} "
            + ("这是冻结回答中的可追溯观察内容。" * 80)
        )
        row_refs = []
        for ref_index in range(3):
            if profile == "high_unique_url":
                url_index = offset * 3 + ref_index
            else:
                url_index = (offset * 3 + ref_index) % url_count
            row_refs.append({
                "reference_id": f"r{run_id}-{ref_index}",
                "index": ref_index + 1,
                "canonical_url": _url(url_index),
                "title": f"来源文章 {url_index}",
            })
            references.append({
                **row_refs[-1],
                "run_id": run_id,
            })
        runs.append({
            "run_id": run_id,
            "status": "success",
            "answer_text": answer,
            "brand_mentioned": False,
            "competitors": [],
            "references": row_refs,
        })

    if profile == "long_source":
        # Keep two versions of one URL.  They have distinct snapshot hashes
        # and must remain distinct provenance objects even when the URL is the
        # same.  The source projection may omit them under the text budget,
        # but it must never merge the versions into one object.
        for index in range(url_count):
            url = _url(index)
            for version in ("a", "b"):
                snapshots.append({
                    "snapshot_id": f"snapshot-{index}-{version}",
                    "source_key": f"source-{index}-{version}",
                    "canonical_url": url,
                    "title": f"长来源 {index} 版本 {version}",
                    "content_hash": f"hash-{index}-{version}",
                    "passages": [{
                        "passage_id": "p1",
                        "content_hash": f"passage-hash-{index}-{version}",
                        "text": (f"正文版本 {version} URL {url}。" * 900),
                    }],
                })

    return {
        "identity": {
            "project_id": 1,
            "prompt_id": 1,
            "prompt_version_id": 1,
            "configuration_version_id": 1,
        },
        "prompt": {"prompt_id": 1, "text": "synthetic GEO question"},
        "project_configuration": {
            "brand": {"brand_name": "Synthetic Brand", "website_url": "https://brand.invalid"},
        },
        "runs": runs,
        "citation_manifest": None,
        "source_snapshots": snapshots,
        "product_truth": {"set_hash": "truth-set-v1", "facts": []},
        "brand_context": {"mode": "EMPTY"},
        "monitor_metrics": {},
        "qualification": {},
        # The helper is kept for a raw occurrence-count cross-check.  The
        # production projection derives occurrences from runs and ignores
        # this convenience field.
        "_synthetic_references": references,
    }


def _raw_chars(scope: dict) -> int:
    return len(json.dumps(scope, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _pack_chars(pack: dict) -> int:
    return len(json.dumps(pack, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _matrix_rows() -> list[dict]:
    rows: list[dict] = []
    for profile in PROFILES:
        for run_count in SIZES:
            scope = _make_scope(run_count, profile)
            raw_chars = _raw_chars(scope)
            expected_urls = {
                item["canonical_url"] for run in scope["runs"] for item in run["references"]
            }
            expected_occurrences = sum(len(run["references"]) for run in scope["runs"])
            try:
                pack = build_evidence_pack(scope, text_budget=BUDGET)
            except EvidencePackCapacityError as exc:
                rows.append({
                    "profile": profile,
                    "runs": run_count,
                    "raw_chars": raw_chars,
                    "pack_chars": None,
                    "unique_urls": len(expected_urls),
                    "citation_occurrences": expected_occurrences,
                    "included_urls": None,
                    "omitted_urls": None,
                    "omission_identity": "NOT_AVAILABLE_PRODUCTION_V3",
                    "included_runs": None,
                    "source_passages": len(scope["source_snapshots"]),
                    "source_passages_included": None,
                    "status": "CAPACITY_ERROR",
                    "error": str(exc),
                })
                continue
            coverage = pack["coverage"]
            included_runs = {str(item["run_id"]) for item in pack["runs"]}
            included_urls = {
                item["canonical_url"] for item in pack["citation_occurrences"]
            }
            omitted_urls = {
                # v3 reports this count but intentionally does not emit a
                # per-entry omission object.  Identity recovery is tested in
                # the shadow planner, not inferred here.
                item["canonical_url"] for item in coverage["omitted_materials"]
                if item.get("kind") == "citation_catalog_entry"
            }
            omitted_url_count = int(coverage.get("citation_evidence_omitted", 0))
            if omitted_url_count:
                assert not omitted_urls, (
                    "production v3 must not silently claim per-entry omission identity"
                )
            rows.append({
                "profile": profile,
                "runs": run_count,
                "raw_chars": raw_chars,
                "pack_chars": _pack_chars(pack),
                "unique_urls": len(expected_urls),
                "citation_occurrences": coverage["citation_occurrence_count"],
                "included_urls": len(included_urls),
                "omitted_urls": omitted_url_count,
                "omission_identity": (
                    "AVAILABLE" if omitted_url_count == len(omitted_urls)
                    else "NOT_AVAILABLE_PRODUCTION_V3"
                ),
                "included_runs": len(included_runs),
                "source_passages": coverage["source_passage_total"],
                "source_passages_included": coverage["source_passage_included"],
                "status": "PASS",
                "error": None,
            })
    return rows


def test_capacity_matrix_is_deterministic_and_loss_explicit():
    first = _matrix_rows()
    second = _matrix_rows()
    assert first == second
    assert len(first) == len(SIZES) * len(PROFILES)
    for row in first:
        if row["status"] == "CAPACITY_ERROR":
            # A capacity refusal is acceptable at the current v3 boundary,
            # but no unrelated exception or silent partial pack is allowed.
            assert row["error"].startswith("EVIDENCE_PACK_CORE_EXCEEDS_BUDGET:")
            continue
        assert row["included_runs"] == row["runs"]
        assert row["citation_occurrences"] == row["runs"] * 3
        assert row["included_urls"] + row["omitted_urls"] == row["unique_urls"]
        if row["omitted_urls"]:
            assert row["omission_identity"] == "NOT_AVAILABLE_PRODUCTION_V3"
        assert row["pack_chars"] is not None


@pytest.mark.parametrize("profile", PROFILES)
def test_provenance_versions_are_not_merged(profile):
    scope = _make_scope(22, profile)
    pack = build_evidence_pack(scope, text_budget=BUDGET)
    # Every source snapshot identity is either included or explicitly omitted;
    # no two different snapshot hashes can collapse into one selected object.
    selected = pack["selected_source_passages"]
    selected_ids = [item["snapshot_id"] for item in selected]
    assert len(selected_ids) == len(set(selected_ids))
    selected_hashes = [item["passage_hash"] for item in selected]
    assert len(selected_hashes) == len(set(selected_hashes))
    omitted = pack["coverage"]["omitted_materials"]
    omitted_keys = {(item["snapshot_id"], item["passage_id"]) for item in omitted}
    all_keys = {
        (snapshot["snapshot_id"], snapshot["passages"][0]["passage_id"])
        for snapshot in scope["source_snapshots"]
    }
    assert set((item["snapshot_id"], item["passage_id"]) for item in selected) | omitted_keys == all_keys


def test_citation_frequency_and_run_membership_survive_url_projection():
    scope = _make_scope(50, "high_repeat_url")
    pack = build_evidence_pack(scope, text_budget=BUDGET)
    catalog = pack["citation_occurrences"]
    assert sum(item["occurrence_count"] for item in catalog) == 50 * 3
    assert set(run_id for item in catalog for run_id in item["run_ids"]) == {
        str(index) for index in range(1, 51)
    }
    assert Counter(item["occurrence_count"] for item in catalog)
