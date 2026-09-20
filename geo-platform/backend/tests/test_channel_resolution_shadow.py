from __future__ import annotations

from app.modules.optimization.channel_resolution_shadow import (
    _golden_context,
    resolve_channel_shadow,
    run_channel_resolver_golden_replay,
)
from app.modules.optimization import service as optimization_service
from app.models import OptimizationEvidencePackage, Project, Prompt


def _channel(result: dict, role: str) -> dict | None:
    return next((item for item in result["channels"] if item["role"] == role), None)


def _weak_relevance() -> dict:
    return {
        "ZHIHU": [{
            "reason_id": "reason:1",
            "reason_text": "支持自定义分享标题",
            "state": "WEAK",
            "supporting_signal_ids": [],
        }]
    }


def test_large_peripheral_volume_with_weak_relevance_is_observe_not_test():
    context = _golden_context(reason_relevance=_weak_relevance())
    context["channels"][0]["role_counts"]["PERIPHERAL_CITATION"].update({
        "observation_count": 500,
        "unique_url_count": 80,
        "observed_run_ids": list(range(1, 41)),
    })

    result = resolve_channel_shadow(context)

    assert _channel(result, "TEST") is None
    assert _channel(result, "OBSERVE")["channel_key"] == "ZHIHU"


def test_stable_exposure_relevance_target_gap_and_fit_create_test():
    result = resolve_channel_shadow(_golden_context())

    test = _channel(result, "TEST")
    evaluation = result["channel_evaluations"][0]["path_d"]["decision_reason_relevance"]["reason_results"][0]
    assert test["channel_key"] == "ZHIHU"
    assert test["rationale_path"] == "RETRIEVAL_EXPOSURE_OPPORTUNITY"
    assert test["test_hypothesis"]["success_metric"]
    assert test["test_hypothesis"]["observation_window"]
    assert test["decision_reason_ids"] == ["reason:1"]
    assert test["reason_relevance"]["reason_results"][0]["reason_id"] == "reason:1"
    assert test["exposure_signals"]["state"] == "PASS"
    assert test["target_gap"]["state"] == "PASS"
    assert test["intervention_fit"]["state"] == "PASS"
    assert evaluation["channel_exposure"] == "PASS"
    assert evaluation["target_gap"] == "PASS"
    assert evaluation["intervention_fit"] == "PASS"


def test_path_d_never_promotes_test_to_primary():
    result = resolve_channel_shadow(_golden_context())

    assert _channel(result, "PRIMARY") is None
    assert _channel(result, "TEST") is not None


def test_confirmed_test_with_step8_gates_is_validation_experiment_ready():
    context = _golden_context(
        strategy_opportunity_state="CONFIRMED",
        step8_other_gates_pass=True,
    )

    result = resolve_channel_shadow(context)

    assert result["execution_readiness"] == "READY"
    assert result["intervention_mode"] == "CHANNEL_VALIDATION_EXPERIMENT"


def test_observe_only_does_not_unlock_execution():
    context = _golden_context(
        strategy_opportunity_state="CONFIRMED",
        step8_other_gates_pass=True,
        reason_relevance=_weak_relevance(),
    )

    result = resolve_channel_shadow(context)

    assert result["channel_resolution_state"] == "OBSERVE_ONLY"
    assert result["execution_readiness"] == "NOT_READY"


def test_unresolved_does_not_unlock_execution():
    context = _golden_context(
        channels=[],
        reason_relevance={},
        channel_target_gaps={},
        strategy_opportunity_state="CONFIRMED",
        step8_other_gates_pass=True,
    )

    result = resolve_channel_shadow(context)

    assert result["channel_resolution_state"] == "UNRESOLVED"
    assert result["execution_readiness"] == "NOT_READY"


def test_invalid_input_emits_no_channel_decision():
    result = resolve_channel_shadow(_golden_context(data_health="INVALID"))

    assert result["channel_resolution_state"] == "INPUT_INVALID"
    assert result["channels"] == []
    assert result["execution_readiness"] == "NOT_READY"


def test_official_primary_requires_path_c_and_authority_asset_evidence():
    context = _golden_context(
        channels=[{
            **_golden_context()["channels"][0],
            "channel_key": "OFFICIAL_SITE",
            "channel_label": "官网",
        }],
        intervention_need={
            "route": "EVIDENCE",
            "gap_type": "EVIDENCE_GAP",
            "first_party_authority_required": True,
        },
        relevant_official_assets=[],
        reason_relevance={"OFFICIAL_SITE": []},
        channel_target_gaps={"OFFICIAL_SITE": {"state": "PASS"}},
    )

    result = resolve_channel_shadow(context)
    primary = _channel(result, "PRIMARY")

    assert primary["channel_key"] == "OFFICIAL_SITE"
    assert primary["rationale_path"] == "AUTHORITATIVE_PRODUCT_TRUTH_INTERVENTION"
    assert primary["authority_asset_evidence"]["asset_status"] == "MISSING_BUT_REQUIRED_ASSET"
    assert primary["authority_asset_evidence"]["decision_reason_ids"]
    assert primary["authority_asset_evidence"]["product_truth_refs"]


def test_path_c_product_truth_is_isolated_per_decision_reason():
    context = _golden_context(
        channels=[{
            **_golden_context()["channels"][0],
            "channel_key": "OFFICIAL_SITE",
            "channel_label": "官网",
        }],
        intervention_need={
            "route": "EVIDENCE",
            "gap_type": "EVIDENCE_GAP",
            "first_party_authority_required": True,
        },
        decision_reasons=[
            {"id": "reason:A", "text": "理由 A", "product_truth_ids": []},
            {"id": "reason:B", "text": "理由 B", "product_truth_ids": [1]},
        ],
        relevant_official_assets=[],
        reason_relevance={"OFFICIAL_SITE": []},
        channel_target_gaps={"OFFICIAL_SITE": {"state": "PASS"}},
    )

    result = resolve_channel_shadow(context)
    primary = _channel(result, "PRIMARY")
    reason_rows = primary["authority_asset_evidence"]["reason_evidence"]

    assert primary["decision_reason_ids"] == ["reason:B"]
    assert next(item for item in reason_rows if item["decision_reason_id"] == "reason:A")["eligible"] is False
    assert next(item for item in reason_rows if item["decision_reason_id"] == "reason:B")["eligible"] is True


def test_pending_review_has_proposed_but_no_active_intervention_mode():
    context = _golden_context()
    context["channels"] = [{
        **context["channels"][0],
        "channel_key": "OFFICIAL_SITE",
        "channel_label": "官网",
    }]
    context["intervention_need"] = {
        "route": "EVIDENCE",
        "gap_type": "EVIDENCE_GAP",
        "first_party_authority_required": True,
    }
    context["reason_relevance"] = {"OFFICIAL_SITE": []}
    context["channel_target_gaps"] = {"OFFICIAL_SITE": {"state": "PASS"}}

    result = resolve_channel_shadow(context)

    assert result["execution_readiness"] == "NOT_READY"
    assert result["proposed_intervention_mode"] == "CONFIRMED_CHANNEL_INTERVENTION"
    assert result["active_intervention_mode"] is None
    assert result["intervention_mode"] is None


def test_production_adapter_uses_exact_shadow_resolver_core(monkeypatch):
    context = _golden_context()
    expected = resolve_channel_shadow(context)
    monkeypatch.setattr(
        "app.modules.optimization.channel_resolution_shadow.build_channel_resolution_context",
        lambda *args, **kwargs: (context, {}),
    )

    result = optimization_service._resolve_strategy_channels(
        Project(id=3, brand_name="商加加"),
        {"gap_type": "EVIDENCE_GAP", "channel_aggregation": []},
        [],
        [],
        db=type("Db", (), {"query": lambda self, *args: None})(),
        prompt=Prompt(id=19, project_id=3, prompt_text="测试"),
        package=OptimizationEvidencePackage(id=12, project_id=3, prompt_id=19, version=1),
    )

    assert result["channels"] == expected["channels"]
    assert result["resolver"]["shared_shadow_production_core"] == "resolve_channel_shadow"
    assert all(item["rationale_path"] == "RETRIEVAL_EXPOSURE_OPPORTUNITY" for item in result["planned_channels"])


def test_peripheral_zhihu_with_weak_relevance_cannot_be_execution_channel():
    context = _golden_context(reason_relevance=_weak_relevance())
    result = resolve_channel_shadow(context)

    assert not any(item["role"] in {"PRIMARY", "SECONDARY", "TEST"} for item in result["channels"])
    assert _channel(result, "OBSERVE")["channel_key"] == "ZHIHU"


def test_observed_decision_and_benchmark_path_are_preserved_over_path_d():
    context = _golden_context()
    decision = {
        "observation_count": 6,
        "semantic_relation_count": 3,
        "unique_url_count": 1,
        "observed_run_count": 6,
        "observed_run_ids": [1, 2, 3, 4, 5, 6],
        "role_source_ids": {"evidence_alignment_ids": [10, 11, 12]},
        "entity_counts": {
            "target_brand": {"observation_count": 0},
            "competitor": {"observation_count": 6},
        },
    }
    context["channels"][0]["role_counts"]["DECISION_CITATION"] = decision
    context["benchmark_evidence_ids"] = [10]
    context["reason_breakdown"] = [{
        "reason_text": "支持自定义分享标题",
        "channels": [{
            "channel_key": "ZHIHU",
            "role_counts": {"DECISION_CITATION": decision},
        }],
    }]

    result = resolve_channel_shadow(context)

    assert _channel(result, "PRIMARY")["channel_key"] == "ZHIHU"
    assert _channel(result, "TEST") is None


def test_golden_replay_passes_all_eight_cases():
    result = run_channel_resolver_golden_replay()

    assert result["total_cases"] == 8
    assert result["passed"] == 8
    assert result["failed"] == 0
