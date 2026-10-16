from __future__ import annotations

import hashlib

from app.modules.single_prompt_v2.observation import measure_scope


IDENTITY = {
    "canonical_brand_name": "MetricTarget",
    "accepted_aliases": [],
    "official_domains": [],
    "official_urls": [],
}

BASELINE_CONTEXT = {
    "context_id": "ctx-d6f2bc78-9fc4-4894-8557-1ce0d1f33c43",
    "raw_output_hash": "f3410ddee046b5f18eecc0fced4f37f4f9081b2bb5c0f345dca49290fbd6e10e",
}
COMPARISON_CONTEXT = {
    "context_id": "ctx-6fd3ae9e-c61f-4bb7-bfd6-e15985ed6906",
    "raw_output_hash": "d9a1beaeedb1f6bde381b93f20938112db18c8388ef48a99de14838a35a3f43d",
}


def _run(run_id: int, answer_text: str, *, status: str = "success") -> dict:
    return {
        "run_id": run_id,
        "status": status,
        "answer_text": answer_text,
        "reference_complete": True,
        "references": [],
    }


def _scope(ref: dict, runs: list[dict], semantics: dict | None = None) -> dict:
    return {"ref": ref, "raw": {"runs": runs}, "semantics": semantics}


def test_saved_isolated_nine_run_counts_trace_to_original_text_and_replay_exactly():
    baseline_runs = [
        _run(run_id, f"维护前核对设备说明，第{index}份隔离回答。")
        for index, run_id in enumerate(range(3, 12), start=1)
    ]
    comparison_runs = [
        _run(12, "MetricTarget 是一个名称。"),
        *[
            _run(run_id, f"维护前核对设备说明，第{index}份隔离回答。")
            for index, run_id in enumerate(range(13, 21), start=2)
        ],
    ]
    baseline_scope = _scope(BASELINE_CONTEXT, baseline_runs)
    comparison_scope = _scope(COMPARISON_CONTEXT, comparison_runs)

    baseline = measure_scope(baseline_scope, IDENTITY)
    comparison = measure_scope(comparison_scope, IDENTITY)
    replay = measure_scope(comparison_scope, IDENTITY)

    baseline_mention = baseline["metrics"]["brand_mention_rate"]
    comparison_mention = comparison["metrics"]["brand_mention_rate"]
    assert (baseline_mention["hit_count"], baseline_mention["evaluable_count"]) == (0, 9)
    assert (comparison_mention["hit_count"], comparison_mention["evaluable_count"]) == (1, 9)
    assert comparison_mention["hit_run_ids"] == [12]
    assert next(run["answer_text"] for run in comparison["runs"] if run["run_id"] == 12) == "MetricTarget 是一个名称。"
    assert comparison["contract_version"] == "single_prompt_measurement.v4_alias_evidence"
    assert comparison["input"] == COMPARISON_CONTEXT
    assert comparison["raw_output_hash"] != baseline["raw_output_hash"]
    assert replay == comparison


def test_negative_semantic_failure_and_failed_run_never_become_positive_or_zero():
    negative_text = "明确不建议使用 MetricTarget。"
    unknown_text = "MetricTarget 是否适用仍需人工判断。"
    runs = [
        _run(1, negative_text),
        _run(2, unknown_text),
        _run(3, "", status="failed"),
    ]
    semantics = {
        "answer_jobs": [
            {"answer_hash": hashlib.sha256(negative_text.encode()).hexdigest(), "status": "DONE", "run_ids": [1]},
            {"answer_hash": hashlib.sha256(unknown_text.encode()).hexdigest(), "status": "FAILED_SCHEMA", "run_ids": [2]},
        ],
        "events": [
            {
                "run_id": 1,
                "entity_text": "MetricTarget",
                "effective_speech_act": "DISCOURAGE",
                "fact_consumption_eligible": True,
            },
            {
                "run_id": 2,
                "entity_text": "MetricTarget",
                "effective_speech_act": "RECOMMEND",
                "fact_consumption_eligible": True,
            },
        ],
    }

    measured = measure_scope(_scope({"context_id": "negative-and-unknown"}, runs, semantics), IDENTITY)
    mention = measured["metrics"]["brand_mention_rate"]
    option = measured["metrics"]["brand_option_rate"]
    recommendation = measured["metrics"]["brand_recommendation_rate"]

    assert mention["hit_run_ids"] == [1, 2]
    assert [run["answer_text"] for run in measured["runs"] if run["run_id"] in mention["hit_run_ids"]] == [
        negative_text,
        unknown_text,
    ]
    for metric in (option, recommendation):
        assert metric["planned_count"] == 3
        assert metric["valid_raw_count"] == 2
        assert metric["evaluable_run_ids"] == [1]
        assert metric["hit_count"] == 0
        assert metric["value"] == 0
        assert metric["status"] == "PARTIAL"
    assert option["unevaluated"] == [{"run_id": 2, "reason": "ANSWER_SEMANTIC_NOT_EVALUATED"}]
    assert recommendation["unevaluated"] == [{"run_id": 2, "reason": "FAILED_SCHEMA"}]
