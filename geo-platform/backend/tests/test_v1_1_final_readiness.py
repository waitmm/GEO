from app.modules.optimization.readiness_report import (
    citation_explosion_stress,
    duplicate_run_stress,
)


def test_duplicate_run_stress_keeps_expensive_semantic_work_stable():
    rows = duplicate_run_stress()

    assert [row["runs"] for row in rows] == [1, 10, 100]
    assert [row["source_claim_unique_jobs"] for row in rows] == [1, 1, 1]
    assert [row["alignment_unique_jobs"] for row in rows] == [1, 1, 1]
    assert [row["expensive_semantic_work_delta"] for row in rows] == [2, 0, 0]


def test_citation_explosion_stress_keeps_llm_ratio_below_naive_pairs():
    rows = citation_explosion_stress(semantic_reasons=20, top_k=5)

    assert [row["citations"] for row in rows] == [50, 100, 500]
    assert all(row["final_candidates"] == 100 for row in rows)
    assert rows[0]["llm_amplification_ratio"] == 0.1
    assert rows[1]["llm_amplification_ratio"] == 0.05
    assert rows[2]["llm_amplification_ratio"] == 0.01
