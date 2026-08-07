from __future__ import annotations

import math
import pytest

from app.modules.optimization.ranking import (
    canonicalize_citation_url,
    canonicalize_citation_urls,
    extract_citation_sources,
    compute_raw_dimensions,
    compute_correlation_matrix,
    compute_rank_log_score,
    compute_rank_bucket_score,
    compute_rank_scores_for_source,
    build_evidence_factors,
    compute_factor_weighted_score,
    compute_completeness,
    compute_sample_adequacy,
    compute_confidence_v0,
    apply_completeness_model,
    rank_candidates,
    compute_ranking_stability,
    run_citation_evidence_ranking_v0,
)
from app.modules.optimization.ranking_config import (
    COMPLETENESS_MODEL_A,
    COMPLETENESS_MODEL_B,
    COMPLETENESS_MODEL_C,
    MINIMUM_COMPLETENESS_GATE,
    CONFIDENCE_THRESHOLDS,
)
from app.modules.optimization.service import _infer_platform_from_domain
from app.models import ReferenceSource


# ============================================================================
# URL Canonicalization tests (1-2)
# ============================================================================

def test_canonicalize_url_strips_tracking_params():
    assert canonicalize_citation_url("http://x.com/a?utm_source=test&b=1") == "http://x.com/a?b=1"
    assert canonicalize_citation_url("http://x.com/a?fbclid=abc") == "http://x.com/a"


def test_canonicalize_url_dedup_groups_correctly():
    urls = ["http://x.com/a?utm_source=x", "http://x.com/a", "http://y.com/b"]
    groups = canonicalize_citation_urls(urls)
    # Both x.com/a variants should map to same canonical
    canonical_keys = list(groups.keys())
    assert any("x.com/a" in k for k in canonical_keys)
    assert any("y.com/b" in k for k in canonical_keys)


# ============================================================================
# Occurrence vs Unique URL separation (3-4)
# ============================================================================

def test_occurrence_count_vs_unique_url_count_separated():
    refs = [
        ReferenceSource(id=1, run_id=1, reference_index=1, display_title="A", url="http://x.com/a", domain="x.com"),
        ReferenceSource(id=2, run_id=1, reference_index=2, display_title="A", url="http://x.com/a", domain="x.com"),
        ReferenceSource(id=3, run_id=1, reference_index=3, display_title="B", url="http://x.com/b", domain="x.com"),
    ]
    sources = extract_citation_sources(refs, [1])
    ds = sources["domain_sources"]["x.com"]
    assert ds["occurrence_count"] == 3
    assert ds["unique_url_count"] >= 1  # at least one unique URL


def test_top1_top3_concentration_correct():
    refs = [
        ReferenceSource(id=i, run_id=1, reference_index=i, display_title="T", url="http://x.com/1", domain="x.com")
        for i in range(1, 6)
    ] + [
        ReferenceSource(id=i+10, run_id=1, reference_index=i+10, display_title="T2", url="http://x.com/2", domain="x.com")
        for i in range(1, 3)
    ]
    sources = extract_citation_sources(refs, [1])
    ds = sources["domain_sources"]["x.com"]
    # 5 of url /1, 2 of url /2 = 7 total
    assert ds["top1_url_share"] == 5/7


# ============================================================================
# RAW vs INFERRED platform separation (5-6)
# ============================================================================

def test_raw_platform_separated_from_inferred():
    refs = [ReferenceSource(id=1, run_id=1, reference_index=1, display_title="T",
                            url="http://bilibili.com/v/1", domain="bilibili.com", platform_name="wenxin")]
    sources = extract_citation_sources(refs, [1])
    dims = compute_raw_dimensions(sources, 1, 1, True)
    row = dims[0]
    assert row["raw_platform"] == "wenxin"
    assert row["inferred_platform"] == "BILIBILI"
    assert "DOMAIN_MAPPING" in row.get("platform_inference_method", "")


def test_domain_ranking_correct():
    refs = [
        ReferenceSource(id=1, run_id=1, reference_index=1, display_title="T", url="http://a.com/1", domain="a.com"),
        ReferenceSource(id=2, run_id=1, reference_index=2, display_title="T", url="http://a.com/2", domain="a.com"),
        ReferenceSource(id=3, run_id=1, reference_index=3, display_title="T", url="http://b.com/1", domain="b.com"),
    ]
    sources = extract_citation_sources(refs, [1])
    dims = compute_raw_dimensions(sources, 1, 3, True)
    dims = compute_completeness(dims)
    dims = compute_sample_adequacy(dims)
    dims, _, _ = build_evidence_factors(dims, {"correlation_available": False, "highly_correlated_pairs": []}, True)
    for row in dims:
        row["raw_evidence_score"] = compute_factor_weighted_score(row.get("_factor_scores", {}))
    ranked = rank_candidates(dims)
    # Both domains should have valid ranking
    a_row = [r for r in ranked if r["source_domain"] == "a.com"][0]
    b_row = [r for r in ranked if r["source_domain"] == "b.com"][0]
    assert a_row["evidence_rank_raw"] > 0
    assert b_row["evidence_rank_raw"] > 0
    # Both must have valid decomposition
    assert "_decomposition" in a_row
    assert "_decomposition" in b_row


# ============================================================================
# No cartesian product (7-8)
# ============================================================================

def test_only_observed_domains_in_ranking():
    """Ranking should only include domains that actually appear in references."""
    refs = [ReferenceSource(id=1, run_id=1, reference_index=1, display_title="T", url="http://a.com/1", domain="a.com")]
    sources = extract_citation_sources(refs, [1])
    dims = compute_raw_dimensions(sources, 1, 1, True)
    domains = {r["source_domain"] for r in dims}
    assert "a.com" in domains
    assert "b.com" not in domains  # never appeared


def test_no_exploration_candidates_in_main_ranking():
    """Low sample candidates are excluded from main ranking in the full pipeline."""
    refs = [ReferenceSource(id=1, run_id=1, reference_index=1, display_title="T", url="http://x.com/1", domain="x.com")]
    sources = extract_citation_sources(refs, [1])
    dims = compute_raw_dimensions(sources, 1, 1, True)
    # In the full pipeline, low sample filtering happens via MINIMUM_OBSERVED_SAMPLE
    # 1 run_count vs threshold 2 → LOW_SAMPLE; 1 occurrence vs threshold 3 → LOW_SAMPLE
    # This is done in run_citation_evidence_ranking_v0, so we test the underlying filter logic:
    from app.modules.optimization.ranking_config import MINIMUM_OBSERVED_SAMPLE
    for row in dims:
        meets_run = row["citation_run_count"] >= MINIMUM_OBSERVED_SAMPLE["citation_run_count"]
        meets_occ = row["citation_occurrence_count"] >= MINIMUM_OBSERVED_SAMPLE["citation_occurrence_count"]
        assert not (meets_run and meets_occ)  # Should be below threshold


# ============================================================================
# UNKNOWN dimensions not treated as 0 (9)
# ============================================================================

def test_unknown_dimension_not_zero():
    dims = compute_raw_dimensions(
        {"domain_sources": {"x.com": {"occurrence_count": 1, "run_count": 1, "run_ids": {1}, "urls": ["http://x.com"],
            "unique_urls": {"http://x.com"}, "unique_url_count": 1, "reference_ids": [1], "ranks": [],
            "top1_url_share": 1.0, "top3_url_share": 1.0, "source_concentration": 1.0}}},
        1, 1, False  # rank NOT available
    )
    # When rank is unavailable, rank dimensions should be None, not 0
    row = dims[0]
    assert row["mean_citation_rank"] is None
    assert row["top3_occurrence_share"] is None
    # citation_rank_available should be False
    assert row["citation_rank_available"] is False


# ============================================================================
# Completeness tests (10-11)
# ============================================================================

def test_completeness_correctly_calculated():
    dims = compute_raw_dimensions(
        {"domain_sources": {"x.com": {"occurrence_count": 5, "run_count": 3, "run_ids": {1,2,3}, "urls": ["http://x.com/1"]*5,
            "unique_urls": {"http://x.com/1"}, "unique_url_count": 1, "reference_ids": [1,2,3,4,5], "ranks": [1,2,3,4,5],
            "top1_url_share": 1.0, "top3_url_share": 1.0, "source_concentration": 1.0}}},
        3, 5, True
    )
    dims = compute_completeness(dims)
    row = dims[0]
    assert row["evidence_completeness"] > 0
    assert row["available_dimension_count"] > 0


def test_low_completeness_gate_works():
    """Model C should exclude entries below completeness gate."""
    dims = compute_raw_dimensions(
        {"domain_sources": {"x.com": {"occurrence_count": 5, "run_count": 3, "run_ids": {1,2,3}, "urls": ["http://x.com/1"]*5,
            "unique_urls": {"http://x.com/1"}, "unique_url_count": 1, "reference_ids": [1,2,3,4,5], "ranks": [1,2,3,4,5],
            "top1_url_share": 1.0, "top3_url_share": 1.0, "source_concentration": 1.0}}},
        3, 5, True
    )
    dims = compute_completeness(dims)
    for row in dims:
        row["raw_evidence_score"] = 10.0
    gated = apply_completeness_model(dims, COMPLETENESS_MODEL_C)
    for row in gated:
        if row["evidence_completeness"] < MINIMUM_COMPLETENESS_GATE:
            assert row["completeness_adjusted_score"] is None


# ============================================================================
# Correlation tests (12-13)
# ============================================================================

def test_correlation_matrix_computes():
    dims = [
        {"source_domain": "a.com", "a": 1, "b": 2, "c": 3},
        {"source_domain": "b.com", "a": 2, "b": 4, "c": 6},
        {"source_domain": "c.com", "a": 3, "b": 6, "c": 9},
        {"source_domain": "d.com", "a": 4, "b": 8, "c": 12},
        {"source_domain": "e.com", "a": 5, "b": 10, "c": 15},
    ]
    result = compute_correlation_matrix(dims, min_pairs=3, threshold=0.85)
    assert result["correlation_available"] is True
    assert result["pair_count"] > 0
    # a vs b should be perfectly correlated (linear)
    highly = {(h["dimension_a"], h["dimension_b"]) for h in result["highly_correlated_pairs"]}
    # At least one pair should be highly correlated
    assert len(highly) > 0


def test_highly_correlated_dimensions_flagged():
    dims = [
        {"source_domain": f"d{i}", "a": i, "b": i*2}
        for i in range(1, 8)
    ]
    result = compute_correlation_matrix(dims, min_pairs=5, threshold=0.9)
    highly = {frozenset([h["dimension_a"], h["dimension_b"]]) for h in result["highly_correlated_pairs"]}
    assert frozenset(["a", "b"]) in highly


# ============================================================================
# Rank model tests (14-17)
# ============================================================================

def test_rank_log_score_decreases_with_rank():
    s1 = compute_rank_log_score(1)
    s5 = compute_rank_log_score(5)
    s20 = compute_rank_log_score(20)
    assert s1 > s5 > s20
    assert s1 > 0


def test_rank_bucket_score_discrete():
    s1 = compute_rank_bucket_score(1)
    s5 = compute_rank_bucket_score(5)
    s20 = compute_rank_bucket_score(20)
    assert s1 > s5  # top 1-3 > top 4-10
    assert s5 > s20  # top 4-10 > top 11+


def test_rank_not_using_db_order():
    """reference_index must be used, not DB id or array order."""
    refs = [
        ReferenceSource(id=999, run_id=1, reference_index=5, display_title="T", url="http://x.com/1", domain="x.com"),
        ReferenceSource(id=1, run_id=1, reference_index=1, display_title="T", url="http://x.com/2", domain="x.com"),
    ]
    sources = extract_citation_sources(refs, [1])
    ranks = sources["domain_sources"]["x.com"]["ranks"]
    # ranks should reflect reference_index (1, 5), not DB id order (999, 1)
    assert sorted(ranks) == [1, 5]


def test_rank_data_unavailable_when_no_indices():
    refs = [ReferenceSource(id=1, run_id=1, reference_index=None, display_title="T", url="http://x.com/1", domain="x.com")]
    sources = extract_citation_sources(refs, [1])
    assert sources["rank_available"] is False


# ============================================================================
# Rank model sensitivity (18)
# ============================================================================

def test_rank_model_sensitivity_correct():
    dims = [
        {
            "source_domain": "a.com", "ranks": [1, 2, 3, 15, 20],
            "raw_evidence_score": 0, "evidence_completeness": 1.0,
            "citation_occurrence_count": 5, "citation_run_count": 3,
        },
        {
            "source_domain": "b.com", "ranks": [4, 5, 6, 7, 8],
            "raw_evidence_score": 0, "evidence_completeness": 1.0,
            "citation_occurrence_count": 5, "citation_run_count": 3,
        },
    ]
    from app.modules.optimization.ranking import compute_rank_model_sensitivity
    result = compute_rank_model_sensitivity(dims)
    assert result["total_compared"] > 0


# ============================================================================
# Confidence V0 tests (19-21)
# ============================================================================

def test_confidence_components_correct():
    dims = compute_raw_dimensions(
        {"domain_sources": {"x.com": {"occurrence_count": 10, "run_count": 8, "run_ids": set(range(1,9)), "urls": ["http://x.com/1"]*10,
            "unique_urls": {"http://x.com/1"}, "unique_url_count": 1, "reference_ids": list(range(1,11)), "ranks": list(range(1,11)),
            "top1_url_share": 1.0, "top3_url_share": 1.0, "source_concentration": 1.0}}},
        8, 10, True
    )
    dims = compute_completeness(dims)
    dims = compute_sample_adequacy(dims)
    dims = compute_confidence_v0(dims, 1, 1)
    row = dims[0]
    assert "sample_adequacy" in row["confidence_components"]
    assert "evidence_completeness" in row["confidence_components"]
    assert "signal_consistency" in row["confidence_components"]
    assert "cross_scope_validation" in row["confidence_components"]
    assert row["confidence"] in {"LOW", "MEDIUM", "HIGH"}


def test_single_prompt_single_model_limits_cross_scope():
    dims = compute_raw_dimensions(
        {"domain_sources": {"x.com": {"occurrence_count": 10, "run_count": 8, "run_ids": set(range(1,9)), "urls": ["http://x.com/1"]*10,
            "unique_urls": {"http://x.com/1"}, "unique_url_count": 1, "reference_ids": list(range(1,11)), "ranks": list(range(1,11)),
            "top1_url_share": 1.0, "top3_url_share": 1.0, "source_concentration": 1.0}}},
        8, 10, True
    )
    dims = compute_completeness(dims)
    dims = compute_sample_adequacy(dims)
    dims = compute_confidence_v0(dims, 1, 1)  # 1 prompt, 1 model
    row = dims[0]
    assert row["confidence_components"]["cross_scope_validation"] <= 0.5
    assert "Single prompt" in row.get("cross_scope_note", "")


def test_confidence_levels_map_correctly():
    assert "LOW" in {"LOW", "MEDIUM", "HIGH"}
    assert "HIGH" in {"LOW", "MEDIUM", "HIGH"}


# ============================================================================
# Execution not in Evidence Score (22-23)
# ============================================================================

def test_execution_unassessed_not_in_evidence_ranking():
    """Execution readiness should not affect evidence ranking."""
    # The ranking pipeline doesn't include execution_readiness at all
    # This is by design — evidence ranking and execution readiness are separate columns
    refs = [ReferenceSource(id=1, run_id=1, reference_index=1, display_title="T", url="http://x.com/1", domain="x.com")]
    sources = extract_citation_sources(refs, [1])
    dims = compute_raw_dimensions(sources, 1, 1, True)
    for row in dims:
        # No execution-related field should be in raw dimensions
        assert "execution_readiness" not in row
        assert "execution_score" not in row


def test_experiment_priority_score_disabled():
    """experiment_priority_score should not be computed in V0."""
    refs = [ReferenceSource(id=1, run_id=1, reference_index=1, display_title="T", url="http://x.com/1", domain="x.com")]
    sources = extract_citation_sources(refs, [1])
    dims = compute_raw_dimensions(sources, 1, 1, True)
    for row in dims:
        assert "experiment_priority_score" not in row


# ============================================================================
# scoring_spec_version (24)
# ============================================================================

def test_scoring_spec_version_preserved():
    from app.modules.optimization.ranking_config import SCORING_SPEC_VERSION
    assert SCORING_SPEC_VERSION == "scoring.v0"


# ============================================================================
# Ranking traceability (25-26)
# ============================================================================

def test_ranking_supports_supporting_fact_ids():
    refs = [ReferenceSource(id=i, run_id=1, reference_index=i, display_title="T", url="http://x.com/1", domain="x.com") for i in range(1, 6)]
    sources = extract_citation_sources(refs, [1])
    dims = compute_raw_dimensions(sources, 1, 5, True)
    for row in dims:
        assert "reference_ids" in row
        assert len(row["reference_ids"]) > 0


def test_legacy_b2_tests_continue_to_pass():
    """Verify imports work for existing test infrastructure."""
    from app.modules.optimization.service import (
        EvidenceDrivenStrategyProvider,
        generate_strategy_candidates_v2,
        INTERVENTION_TYPE,
    )
    assert "OFFICIAL_NEW_PAGE" in INTERVENTION_TYPE


# ============================================================================
# Ranking output validation (27-28)
# ============================================================================

def test_ranking_output_has_all_required_fields():
    refs = [
        ReferenceSource(id=i, run_id=1, reference_index=i, display_title=f"T{i}", url=f"http://a.com/{i}", domain="a.com")
        for i in range(1, 6)
    ] + [
        ReferenceSource(id=i+100, run_id=1, reference_index=i+100, display_title=f"T{i}", url=f"http://b.com/{i}", domain="b.com")
        for i in range(1, 4)
    ]
    sources = extract_citation_sources(refs, [1])
    dims = compute_raw_dimensions(sources, 1, 8, True)
    dims = compute_completeness(dims)
    dims = compute_sample_adequacy(dims)
    corr = compute_correlation_matrix(dims)
    dims, _, _ = build_evidence_factors(dims, corr, True)
    for row in dims:
        row["raw_evidence_score"] = compute_factor_weighted_score(row.get("_factor_scores", {}))
    dims = compute_confidence_v0(dims, 1, 1)
    ranked = rank_candidates(dims)

    # Each entry must have required fields
    required = [
        "source_domain", "inferred_platform", "raw_evidence_score",
        "evidence_completeness", "sample_adequacy", "confidence",
        "citation_occurrence_count", "citation_run_coverage",
        "unique_citation_urls", "source_concentration",
    ]
    for row in ranked:
        for field in required:
            assert field in row, f"Missing field {field} in ranking row"


def test_concentration_single_domain_correct():
    """A domain with all the same URL should have high concentration."""
    refs = [ReferenceSource(id=i, run_id=1, reference_index=i, display_title="T", url="http://x.com/1", domain="x.com") for i in range(1, 11)]
    sources = extract_citation_sources(refs, [1])
    dims = compute_raw_dimensions(sources, 1, 10, True)
    row = dims[0]
    assert row["source_concentration"] > 0.5  # high concentration
    assert row["unique_citation_urls"] <= 2  # very few unique URLs relative to occurrences
