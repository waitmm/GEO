from __future__ import annotations

from copy import deepcopy

import pytest

from app.modules.optimization.strategy_synthesis_shadow import (
    TARGET_OUTCOME,
    _bounded_llm_payload,
    _build_constraints,
    _deterministic_structural_proposal,
    _enrich_structure,
    _reason_pair_constraint,
    run_strategy_synthesis_core,
    apply_bounded_llm_outputs_or_fallback,
    apply_presentation_or_fallback,
    apply_structural_proposal_or_fallback,
    detect_synthesis_ambiguities,
    validate_business_rules,
    validate_bounded_llm_proposal,
    validate_presentation,
    validate_structural_synthesis,
    validate_theme_coverage,
    validate_theme_titles,
)


def _reason(
    reason_id: str,
    *,
    family: str = "短链生成",
    scenario: list[str] | None = None,
    mechanisms: list[str] | None = None,
    runs: list[int] | None = None,
) -> dict:
    return {
        "reason_id": reason_id,
        "original_reason": reason_id,
        "normalized_proposition": reason_id,
        "capability_family": family,
        "scenario": scenario or ["SHORT_LINK"],
        "qualifier": [],
        "intervention_mechanisms": mechanisms or ["LINK_EXPRESSION", "EVIDENCE_EXPRESSION"],
        "required_asset_type": "AUTHORITATIVE_EVIDENCE_ASSET",
        "observed_run_ids": runs or [1],
        "product_truth_ids": [1],
        "gap_item_ids": [reason_id.replace(":", "-")],
        "gap_type": "EVIDENCE_GAP",
        "gap_layer": "EVIDENCE_ADOPTION",
        "benchmark_tier": "NO_ELIGIBLE_BENCHMARK",
        "benchmark_source_document_ids": [],
    }


def _channel(key: str, role: str, reason_ids: list[str] | None = None) -> dict:
    return {
        "object_id": f"channel_resolution:1:{key}",
        "channel_key": key,
        "channel_label": key,
        "role": role,
        "rationale_path": "TEST_PATH" if role == "TEST" else "FIXED_PATH",
        "decision_reason_ids": reason_ids or [],
        "supporting_signal_ids": [f"signal:{key}"],
        "exposure": "PASS" if role == "TEST" else "UNKNOWN",
        "reason_coverage_count": len(reason_ids or []),
        "target_brand_gap": "PASS" if role == "TEST" else "UNKNOWN",
        "intervention_fit": "PASS" if role == "TEST" else "UNKNOWN",
        "measurability": "HIGH" if role == "TEST" else "UNKNOWN",
        "information_value": "HIGH" if role == "TEST" else "UNKNOWN",
        "test_metric": "citation_rate" if role == "TEST" else None,
        "resolver_rationale": "",
    }


def _context(
    reasons: list[dict] | None = None,
    channels: list[dict] | None = None,
) -> dict:
    reasons = reasons or [_reason("reason:1"), _reason("reason:2")]
    channels = channels or [
        _channel("OFFICIAL_SITE", "PRIMARY", [item["reason_id"] for item in reasons]),
        _channel("ZHIHU", "TEST", [item["reason_id"] for item in reasons]),
        _channel("SOHU", "OBSERVE"),
    ]
    return {
        "project_id": 1,
        "prompt_id": 1,
        "evidence_package_id": 1,
        "source_payload_hash": "synthetic-source",
        "strategy_basis": "BENCHMARK_BACKED_STRATEGY",
        "brand_name": "Synthetic Brand",
        "decision_reasons": reasons,
        "product_truths": [{"id": 1}],
        "channel_resolutions": channels,
        "eligible_metrics": [{"object_id": "metric:brand_mention_rate", "metric_key": "brand_mention_rate"}],
        "candidate_target_metric": "brand_mention_rate",
        "constraints": _build_constraints(reasons, channels),
        "coverage": {
            "total_analyzable_runs": len({run_id for item in reasons for run_id in item["observed_run_ids"]}),
        },
        "frozen_semantics": {
            "resolver_roles": {item["channel_key"]: item["role"] for item in channels},
            "benchmark_signature": [],
            "strategy_basis": "BENCHMARK_BACKED_STRATEGY",
        },
        "old_strategy_semantic_structure": {},
    }


def test_production_core_no_ambiguity_never_calls_external_llm(monkeypatch):
    context = _context()

    def fail_if_called(*args, **kwargs):
        raise AssertionError("unambiguous deterministic synthesis must not call an external LLM")

    monkeypatch.setattr(
        "app.modules.optimization.strategy_synthesis_shadow._call_bounded_llm",
        fail_if_called,
    )
    result = run_strategy_synthesis_core(context, use_llm=True)

    assert result["validation_status"] == "VALID"
    assert result["structural_synthesis"]["runtime"]["status"] == "SKIPPED_NOT_NECESSARY"
    assert result["structural_synthesis"]["runtime"]["external_llm_calls"] == 0


def test_production_core_ambiguity_with_external_disabled_preserves_strategy_truth():
    reasons = [_reason("reason:1"), _reason("reason:2")]
    channels = [_channel("OFFICIAL_SITE", "PRIMARY", ["reason:1", "reason:2"])] + [
        _channel(key, "TEST", ["reason:1", "reason:2"])
        for key in ("ZHIHU", "BAIJIAHAO", "SOHU")
    ]

    result = run_strategy_synthesis_core(_context(reasons, channels), use_llm=False)
    structure = result["structural_synthesis"]["validated_structure"]

    assert result["validation_status"] == "VALID"
    assert result["needs_human_synthesis"] is True
    assert structure["needs_human_prioritization"] is True
    assert structure["priority_tests"] == []
    assert {item["channel_key"] for item in structure["deferred_tests"]} == {"ZHIHU", "BAIJIAHAO", "SOHU"}


def test_production_core_rejects_whole_invalid_proposal_and_preserves_baseline():
    context = _context()
    baseline = run_strategy_synthesis_core(context, use_llm=False)
    invalid = _deterministic_structural_proposal(context)
    invalid["deferred_tests"].append({
        "channel_key": "XIAOHONGSHU",
        "frozen_role": "TEST",
        "execution_priority": "P2",
    })

    result = run_strategy_synthesis_core(context, structural_proposal=invalid)

    assert result["llm_acceptance"]["status"] == "LLM_SYNTHESIS_REJECTED"
    assert result["can_persist_current_candidate"] is True
    assert result["version_audit"]["output_hash"] == baseline["version_audit"]["output_hash"]
    assert result["hallucination_audit"]["new_channels"] == 1


def test_case_a_compatible_reasons_can_merge_into_one_theme():
    context = _context()

    proposal = _deterministic_structural_proposal(context)

    assert proposal["themes"][0]["reason_ids"] == ["reason:1", "reason:2"]
    assert validate_structural_synthesis(context, proposal)["status"] == "VALID"


def test_case_b_incompatible_reasons_are_kept_separate():
    reasons = [
        _reason("reason:1", family="短链生成", scenario=["SHORT_LINK"]),
        _reason("reason:2", family="数据回传", scenario=["MEASUREMENT"], mechanisms=["MEASUREMENT_EXPRESSION"]),
    ]
    context = _context(reasons=reasons)

    proposal = _deterministic_structural_proposal(context)

    assert len(proposal["themes"]) == 2
    assert _reason_pair_constraint(*reasons)["decision"] == "KEEP_SEPARATE"


def test_case_c_same_family_with_incompatible_scenario_cannot_merge():
    reasons = [
        _reason("reason:1", scenario=["SHORT_LINK"], mechanisms=["LINK_EXPRESSION"]),
        _reason("reason:2", scenario=["PAID_MARKETING"], mechanisms=["MEASUREMENT_EXPRESSION"]),
    ]

    result = _reason_pair_constraint(*reasons)

    assert result["allowed"] is False
    assert "SCENARIO_INCOMPATIBLE" in result["blockers"]
    assert "INTERVENTION_MECHANISM_INCOMPATIBLE" in result["blockers"]


def test_case_d_test_role_cannot_be_upgraded_to_primary():
    context = _context()
    proposal = _deterministic_structural_proposal(context)
    test = proposal["priority_tests"].pop()
    test["frozen_role"] = "PRIMARY"
    proposal["primary_interventions"].append(test)

    result = validate_structural_synthesis(context, proposal)

    assert result["status"] == "INVALID_SYNTHESIS"
    assert any(error.startswith("CHANNEL_ROLE_MUTATION:ZHIHU") for error in result["errors"])


def test_case_e_observe_cannot_enter_test_portfolio():
    context = _context()
    proposal = _deterministic_structural_proposal(context)
    observe = proposal["observe_channels"].pop()
    observe["frozen_role"] = "TEST"
    proposal["deferred_tests"].append(observe)

    result = validate_structural_synthesis(context, proposal)

    assert result["status"] == "INVALID_SYNTHESIS"
    assert any(error.startswith("CHANNEL_ROLE_MUTATION:SOHU") for error in result["errors"])


def test_case_f_new_channel_is_invalid():
    context = _context()
    proposal = _deterministic_structural_proposal(context)
    proposal["deferred_tests"].append({
        "channel_key": "XIAOHONGSHU",
        "frozen_role": "TEST",
        "execution_priority": "P2",
    })

    result = validate_structural_synthesis(context, proposal)

    assert "UNKNOWN_CHANNEL:XIAOHONGSHU" in result["errors"]


def test_case_g_new_product_truth_field_is_rejected_by_strict_schema():
    context = _context()
    proposal = _deterministic_structural_proposal(context)
    proposal["themes"][0]["product_truth_ids"] = [999]

    result = validate_structural_synthesis(context, proposal)

    assert "UNKNOWN_THEME_FIELD:product_truth_ids" in result["errors"]


def test_case_h_unknown_reason_id_is_invalid():
    context = _context()
    proposal = _deterministic_structural_proposal(context)
    proposal["themes"][0]["reason_ids"] = ["reason:invented"]

    result = validate_structural_synthesis(context, proposal)

    assert "UNKNOWN_REASON_ID:reason:invented" in result["errors"]


def test_case_i_unsupported_causal_presentation_is_rejected():
    context = _context()
    view = {
        "target_change": {
            "text": "知乎内容一定能够提升推荐率。",
            "provenance_ids": ["channel_resolution:1:ZHIHU"],
        }
    }

    result = validate_presentation(context, view)

    assert result["status"] == "UNGROUNDED"
    assert result["unsupported_causal_claims"] >= 1


def test_case_j_ambiguous_test_priority_requires_human_instead_of_arbitrary_top_two():
    reasons = [_reason("reason:1"), _reason("reason:2")]
    channels = [_channel("OFFICIAL_SITE", "PRIMARY", ["reason:1", "reason:2"])] + [
        _channel(key, "TEST", ["reason:1", "reason:2"])
        for key in ("ZHIHU", "BAIJIAHAO", "SOHU")
    ]
    context = _context(reasons=reasons, channels=channels)

    proposal = _deterministic_structural_proposal(context)

    assert proposal["priority_tests"] == []
    assert proposal["needs_human_prioritization"] is True
    assert validate_business_rules(context, proposal)["status"] == "VALID"


def test_extra_asset_or_free_fact_fields_are_not_silently_accepted():
    context = _context()
    proposal = _deterministic_structural_proposal(context)
    proposal["new_asset"] = {"url": "https://example.com"}

    result = validate_structural_synthesis(context, proposal)

    assert "UNKNOWN_STRUCTURAL_FIELD:new_asset" in result["errors"]


def test_validator_does_not_mutate_input_proposal():
    context = _context()
    proposal = _deterministic_structural_proposal(context)
    before = deepcopy(proposal)

    validate_structural_synthesis(context, proposal)

    assert proposal == before
    assert proposal["target_outcome"] == TARGET_OUTCOME


def _invalid_structural_proposals(context: dict) -> list[tuple[str, object, str]]:
    baseline = _deterministic_structural_proposal(context)
    new_channel = deepcopy(baseline)
    new_channel["deferred_tests"].append({
        "channel_key": "XIAOHONGSHU",
        "frozen_role": "TEST",
        "execution_priority": "P2",
    })
    role_upgrade = deepcopy(baseline)
    role_upgrade["priority_tests"][0]["frozen_role"] = "PRIMARY"
    new_capability = deepcopy(baseline)
    new_capability["themes"][0]["product_capability"] = "永久防封"
    fake_asset = deepcopy(baseline)
    fake_asset["asset"] = {"title": "Existing whitepaper"}
    fake_metric = deepcopy(baseline)
    fake_metric["selected_success_metrics"] = ["invented_conversion_rate"]
    fake_coverage = deepcopy(baseline)
    fake_coverage["themes"][0]["coverage"] = "99/100"
    unknown_id = deepcopy(baseline)
    unknown_id["themes"][0]["reason_ids"] = ["reason:unknown"]
    return [
        ("new_channel", new_channel, "UNKNOWN_CHANNEL:XIAOHONGSHU"),
        ("role_upgrade", role_upgrade, "CHANNEL_ROLE_MUTATION:ZHIHU"),
        ("new_capability", new_capability, "UNKNOWN_THEME_FIELD:product_capability"),
        ("fake_asset", fake_asset, "UNKNOWN_STRUCTURAL_FIELD:asset"),
        ("fake_metric", fake_metric, "UNKNOWN_METRIC:invented_conversion_rate"),
        ("fake_coverage", fake_coverage, "UNKNOWN_THEME_FIELD:coverage"),
        ("unknown_id", unknown_id, "UNKNOWN_REASON_ID:reason:unknown"),
        ("malformed", "not-json-object", "MALFORMED_STRUCTURAL_SCHEMA"),
    ]


@pytest.mark.parametrize("name,proposal,error_prefix", _invalid_structural_proposals(_context()))
def test_adversarial_structural_output_is_rejected_and_baseline_preserved(name, proposal, error_prefix):
    context = _context()
    baseline = _deterministic_structural_proposal(context)

    final_structure, acceptance = apply_structural_proposal_or_fallback(context, baseline, proposal)

    assert acceptance["status"] == "LLM_SYNTHESIS_REJECTED", name
    assert any(error.startswith(error_prefix) for error in acceptance["errors"]), name
    assert final_structure == baseline
    assert acceptance["deterministic_strategy_preserved"] is True


def test_illegal_theme_merge_is_rejected_and_baseline_preserved():
    reasons = [
        _reason("reason:1", family="短链生成", scenario=["SHORT_LINK"]),
        _reason("reason:2", family="数据回传", scenario=["MEASUREMENT"], mechanisms=["MEASUREMENT_EXPRESSION"]),
    ]
    context = _context(reasons=reasons)
    baseline = _deterministic_structural_proposal(context)
    proposal = deepcopy(baseline)
    proposal["themes"] = [{"theme_key": "T1", "reason_ids": ["reason:1", "reason:2"], "priority": "P1"}]

    final_structure, acceptance = apply_structural_proposal_or_fallback(context, baseline, proposal)

    assert acceptance["status"] == "LLM_SYNTHESIS_REJECTED"
    assert any(error.startswith("DISALLOWED_THEME_MERGE") for error in acceptance["errors"])
    assert final_structure == baseline


def test_causal_presentation_falls_back_to_deterministic_view():
    context = _context()
    structure = _enrich_structure(context, _deterministic_structural_proposal(context))
    reference = {
        "target_change": {
            "text": "验证是否出现新的引用信号。",
            "provenance_ids": ["reason:1"],
        }
    }
    malicious = deepcopy(reference)
    malicious["target_change"]["text"] = "知乎一定能够提升推荐率。"

    final_view, acceptance = apply_presentation_or_fallback(context, reference, malicious)

    assert structure["themes"]
    assert acceptance["status"] == "LLM_SYNTHESIS_REJECTED"
    assert final_view == reference


def test_unsupported_capability_asset_and_numeric_presentation_are_rejected():
    context = _context()
    view = {
        "target_change": {
            "text": "已有官网专题页支持永久防封，并将推荐率提高 99%。",
            "provenance_ids": ["reason:1"],
        }
    }

    result = validate_presentation(context, view)

    assert result["status"] == "UNGROUNDED"
    assert "UNSUPPORTED_FACTUAL_CLAIM:永久防封" in result["errors"]
    assert "UNSUPPORTED_FACTUAL_CLAIM:已有官网专题页" in result["errors"]
    assert "UNSUPPORTED_NUMERIC_CLAIM:99" in result["errors"]


def test_theme_coverage_is_exact_run_id_union_not_member_sum():
    reasons = [
        _reason("reason:1", runs=[1, 2, 3]),
        _reason("reason:2", runs=[2, 3, 4]),
    ]
    context = _context(reasons=reasons)
    structure = _enrich_structure(context, _deterministic_structural_proposal(context))
    theme = structure["themes"][0]

    assert theme["theme_observed_run_ids"] == [1, 2, 3, 4]
    assert theme["theme_observed_run_count"] == 4
    assert theme["theme_coverage"] == 1.0
    assert validate_theme_coverage(context, structure)["status"] == "VALID"

    theme["theme_observed_run_ids"] = [1, 2, 3]
    assert validate_theme_coverage(context, structure)["status"] == "INVALID_SYNTHESIS"


def test_theme_title_cannot_add_unsupported_qualifier():
    context = _context()
    structure = _enrich_structure(context, _deterministic_structural_proposal(context))
    structure["themes"][0]["title"] = "防封白名单短链能力"

    result = validate_theme_titles(context, structure)

    assert result["status"] == "UNGROUNDED"
    assert result["fallback_policy"] == "DETERMINISTIC_CAPABILITY_FAMILY_LABEL"


def test_deterministic_result_has_no_llm_ambiguity():
    assert detect_synthesis_ambiguities(_context()) == []


def test_bounded_test_priority_payload_contains_only_ambiguous_channels():
    reasons = [_reason("reason:1")]
    channels = [_channel("OFFICIAL_SITE", "PRIMARY", ["reason:1"])] + [
        _channel(key, "TEST", ["reason:1"])
        for key in ("ZHIHU", "BAIJIAHAO", "SOHU")
    ] + [_channel("BILIBILI", "OBSERVE")]
    context = _context(reasons=reasons, channels=channels)
    ambiguity = detect_synthesis_ambiguities(context)[0]

    payload = _bounded_llm_payload(context, ambiguity)

    assert ambiguity["ambiguity_type"] == "AMBIGUOUS_TEST_PRIORITY"
    assert {item["channel_key"] for item in payload["channels"]} == {"ZHIHU", "BAIJIAHAO", "SOHU"}
    assert "OFFICIAL_SITE" not in str(payload)
    assert "BILIBILI" not in str(payload)
    assert "product_truths" not in payload


def test_bounded_unknown_channel_rejects_entire_proposal_and_preserves_baseline():
    reasons = [_reason("reason:1")]
    channels = [_channel("OFFICIAL_SITE", "PRIMARY", ["reason:1"])] + [
        _channel(key, "TEST", ["reason:1"])
        for key in ("ZHIHU", "BAIJIAHAO", "SOHU")
    ]
    context = _context(reasons=reasons, channels=channels)
    baseline = _deterministic_structural_proposal(context)
    ambiguities = detect_synthesis_ambiguities(context)
    output = {
        "ambiguity_type": "AMBIGUOUS_TEST_PRIORITY",
        "decision": "SELECT",
        "channel_keys": ["DOUYIN"],
        "rationale_source_ids": ["reason:1"],
    }

    final_structure, acceptance = apply_bounded_llm_outputs_or_fallback(context, baseline, ambiguities, [output])

    assert validate_bounded_llm_proposal(context, ambiguities[0], output)["status"] == "INVALID_SYNTHESIS"
    assert acceptance["status"] == "LLM_SYNTHESIS_REJECTED"
    assert final_structure == baseline


def test_valid_looking_structure_cannot_drift_without_explicit_ambiguity():
    context = _context()
    baseline = _deterministic_structural_proposal(context)
    proposal = deepcopy(baseline)
    proposal["themes"][0]["priority"] = "P2"

    final_structure, acceptance = apply_structural_proposal_or_fallback(context, baseline, proposal)

    assert acceptance["status"] == "LLM_SYNTHESIS_REJECTED"
    assert "LLM_NOT_ALLOWED_WITHOUT_EXPLICIT_AMBIGUITY" in acceptance["errors"]
    assert final_structure == baseline


def test_valid_looking_presentation_drift_is_not_silently_accepted():
    context = _context()
    reference = {
        "target_change": {
            "text": "验证是否出现新的引用信号。",
            "provenance_ids": ["reason:1"],
        }
    }
    proposal = deepcopy(reference)
    proposal["target_change"]["text"] = "当前观察到新的引用信号。"

    final_view, acceptance = apply_presentation_or_fallback(context, reference, proposal)

    assert acceptance["status"] == "LLM_SYNTHESIS_REJECTED"
    assert "PRESENTATION_VARIANCE_NOT_ALLOWED_WITHOUT_EXPLICIT_AMBIGUITY" in acceptance["errors"]
    assert final_view == reference
