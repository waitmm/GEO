from __future__ import annotations

from app.models import EvidenceAlignment, RecommendationEvent
from app.modules.optimization.service import (
    _benchmark_tier_for_decision,
    _citation_prominence,
    _decision_support_from_alignments,
    _source_analysis_sort_key,
)


def test_citation_prominence_uses_only_citation_behavior():
    citation_stats = {
        "sample_count": 3,
        "cited_run_count": 2,
        "citation_occurrence_count": 3,
        "answer_citation_rate": 2 / 3,
        "avg_reference_position": 2.5,
    }

    level, basis, breakdown = _citation_prominence(cited=True, citation_stats=citation_stats)

    assert level == "HIGH"
    assert "引用覆盖：2/3 个可引用样本。" in basis
    assert breakdown["uses_only_citation_behavior"] is True
    assert set(breakdown) == {
        "sample_count",
        "cited_run_count",
        "citation_occurrence_count",
        "answer_citation_rate",
        "avg_reference_position",
        "position_tier",
        "uses_only_citation_behavior",
    }


def test_source_analysis_sort_prefers_prominence_over_legacy_score():
    high_prominence_low_legacy_score = {
        "citation_prominence_level": "HIGH",
        "cited": True,
        "answer_citation_rate": 0.67,
        "citation_occurrence_count": 3,
        "avg_reference_position": 2.5,
        "source_score": 20,
        "run_id": 1,
        "source_id": 1,
    }
    low_prominence_high_legacy_score = {
        "citation_prominence_level": "LOW",
        "cited": False,
        "answer_citation_rate": 0,
        "citation_occurrence_count": 0,
        "avg_reference_position": 0,
        "source_score": 95,
        "run_id": 2,
        "source_id": 2,
    }

    rows = sorted(
        [low_prominence_high_legacy_score, high_prominence_low_legacy_score],
        key=_source_analysis_sort_key,
    )

    assert rows[0] is high_prominence_low_legacy_score


def _alignment(
    relation: str,
    *,
    alignment_id: int = 1,
    scope_relation: str = "PASS",
) -> EvidenceAlignment:
    return EvidenceAlignment(
        id=alignment_id,
        project_id=1,
        prompt_id=43,
        run_id=1,
        recommendation_event_id=1,
        source_document_id=1,
        source_claim_id=1,
        relation=relation,
        scope_relation=scope_relation,
        review_status="MACHINE_GROUNDED",
    )


def _event(
    speech_act: str,
    *,
    strength: str = "NONE",
    polarity: str = "NEUTRAL",
) -> RecommendationEvent:
    return RecommendationEvent(
        id=1,
        project_id=1,
        prompt_id=43,
        run_id=1,
        entity_text="测试品牌",
        speech_act=speech_act,
        recommendation_strength=strength,
        polarity=polarity,
    )


def test_decision_support_ignores_legacy_related():
    payload = _decision_support_from_alignments([
        (_alignment("RELATED", alignment_id=101), _event("RECOMMEND", strength="STRONG", polarity="POSITIVE")),
    ])

    assert payload["decision_support_level"] == "NONE"
    assert payload["supporting_alignment_ids"] == []
    assert payload["has_contradiction"] is False


def test_no_supports_cannot_create_recommendation_reason():
    payload = _decision_support_from_alignments([
        (_alignment("NONE", alignment_id=102), _event("RECOMMEND", strength="STRONG", polarity="POSITIVE")),
    ])

    assert payload["decision_support_level"] == "NONE"


def test_content_unavailable_is_not_evaluable():
    tier = _benchmark_tier_for_decision(
        content_status="CONTENT_UNAVAILABLE",
        relevance="DIRECT",
        decision_support="RECOMMENDATION_REASON",
    )

    assert tier == "NOT_EVALUABLE"


def test_citation_prominence_does_not_upgrade_benchmark_tier():
    primary_low_prominence = {
        "benchmark_tier": "PRIMARY_BENCHMARK",
        "citation_prominence_level": "LOW",
        "cited": True,
        "answer_citation_rate": 0.1,
        "citation_occurrence_count": 1,
        "avg_reference_position": 9,
        "run_id": 1,
        "source_id": 1,
    }
    reference_high_prominence = {
        "benchmark_tier": "REFERENCE_ONLY",
        "citation_prominence_level": "HIGH",
        "cited": True,
        "answer_citation_rate": 1,
        "citation_occurrence_count": 99,
        "avg_reference_position": 1,
        "run_id": 2,
        "source_id": 2,
    }

    rows = sorted([reference_high_prominence, primary_low_prominence], key=_source_analysis_sort_key)

    assert rows[0] is primary_low_prominence


def test_contradiction_is_independent_from_decision_support_level():
    payload = _decision_support_from_alignments([
        (_alignment("CONTRADICTS", alignment_id=103), _event("RECOMMEND", strength="STRONG", polarity="POSITIVE")),
    ])

    assert payload["decision_support_level"] == "NONE"
    assert payload["has_contradiction"] is True
    assert payload["contradicting_alignment_ids"] == [103]


def test_benchmark_rules_allow_zero_primary():
    tiers = [
        _benchmark_tier_for_decision("CONTENT_VALID", "TANGENTIAL", "NONE"),
        _benchmark_tier_for_decision("CONTENT_UNAVAILABLE", "DIRECT", "RECOMMENDATION_REASON"),
        _benchmark_tier_for_decision("CONTENT_VALID", "DIRECT", "FACT_ONLY"),
    ]

    assert "PRIMARY_BENCHMARK" not in tiers
    assert tiers == ["REFERENCE_ONLY", "NOT_EVALUABLE", "SECONDARY_BENCHMARK"]
