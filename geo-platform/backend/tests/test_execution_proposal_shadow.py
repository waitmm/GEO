from __future__ import annotations

from copy import deepcopy

from app.modules.optimization.execution_proposal_shadow import (
    CONTRACT_VERSION,
    build_claim_usage_policy,
    build_execution_proposal_portfolio,
    validate_asset_fit,
    validate_baseline,
    validate_channel_roles,
    validate_claim_grounding,
    validate_metric_eligibility,
    validate_section_provenance,
    validate_title_claims,
    validate_asset_package_quality,
    validate_channel_hypothesis_quality,
    revalidate_execution_proposal,
    revalidate_execution_proposal_portfolio,
)


def _truth(truth_id: int = 1, label: str = "短链生成", *, source_reference: str = "") -> dict:
    return {
        "product_truth_id": truth_id,
        "capability_key": f"capability-{truth_id}",
        "capability_label": label,
        "approved_aliases": [],
        "product_truth_status": "SUPPORTED",
        "truth_source": "MANUAL_CONFIRMED",
        "source_reference": source_reference,
        "reviewed_by": "human",
        "reviewed_at": "2026-01-01T00:00:00",
    }


def _reason(
    reason_id: str = "reason:short-link",
    *,
    text: str = "短链生成",
    truth_id: int = 1,
    runs: list[int] | None = None,
    qualifiers: list[str] | None = None,
) -> dict:
    return {
        "reason_id": reason_id,
        "original_reason": text,
        "normalized_proposition": "短链生成",
        "capability_family": "短链生成",
        "scenario": ["SHORT_LINK"],
        "qualifier": qualifiers or [],
        "intervention_mechanisms": ["LINK_EXPRESSION"],
        "required_asset_type": "AUTHORITATIVE_EVIDENCE_ASSET",
        "observed_run_ids": runs or list(range(1, 16)),
        "product_truth_ids": [truth_id] if truth_id else [],
        "gap_item_ids": [f"gap:{reason_id}"],
        "gap_type": "EVIDENCE_GAP",
        "gap_layer": "EVIDENCE_ADOPTION",
        "benchmark_tier": "NO_ELIGIBLE_BENCHMARK",
        "benchmark_source_document_ids": [],
    }


def _channel(key: str, role: str, reason_ids: list[str]) -> dict:
    signals = [f"signal:{key}"]
    if key == "BAIJIAHAO":
        signals = ["reference:1", "reference:2", "retrieval:1", "source_claim:1", "source_document:1"]
    elif key == "ZHIHU":
        signals = ["reference:3", "reference:4", "source_claim:2", "source_document:2"]
    return {
        "object_id": f"channel_resolution:fixture:{key}",
        "channel_key": key,
        "channel_label": key,
        "role": role,
        "decision_reason_ids": reason_ids,
        "supporting_signal_ids": signals,
        "rationale_path": "RETRIEVAL_EXPOSURE_OPPORTUNITY" if role == "TEST" else "AUTHORITATIVE_PRODUCT_TRUTH_INTERVENTION",
        "intervention_fit": "PASS" if role == "TEST" else "UNKNOWN",
        "information_value": "HIGH" if role == "TEST" else "UNKNOWN",
    }


def _context(*, include_baseline: bool = True) -> dict:
    reasons = [
        _reason(),
        _reason(
            "reason:encrypted",
            text="自动生成加密短链",
            runs=list(range(1, 14)),
            qualifiers=["自动", "加密"],
        ),
    ]
    themes = [{
        "theme_key": "T1",
        "reason_ids": [row["reason_id"] for row in reasons],
        "priority": "P1",
        "title": "短链生成",
        "theme_observed_run_ids": list(range(1, 16)),
        "theme_observed_run_count": 15,
    }]
    channels = [
        _channel("OFFICIAL_SITE", "PRIMARY", [row["reason_id"] for row in reasons]),
        _channel("BAIJIAHAO", "TEST", [row["reason_id"] for row in reasons]),
        _channel("ZHIHU", "TEST", [row["reason_id"] for row in reasons]),
        _channel("SOHU", "TEST", [row["reason_id"] for row in reasons]),
    ]
    calculation_status = "ok" if include_baseline else "not_applicable"
    denominator = 40 if include_baseline else 0
    package_payload = {
        "metrics": [
            {
                "metric_name": key,
                "calculation_status": calculation_status,
                "numerator": 0,
                "denominator": denominator,
                "value": 0.0 if include_baseline else None,
            }
            for key in ("official_reference_rate", "brand_mention_rate", "brand_recommendation_rate")
        ]
    }
    return {
        "contract_version": CONTRACT_VERSION,
        "project_id": 1,
        "prompt_id": 1,
        "brand_name": "Target Brand",
        "strategy_candidate_id": 57,
        "strategy_candidate_status": "ACCEPTED",
        "strategy_candidate_semantic_hash": "candidate-hash",
        "strategy_contract_version": "strategy_synthesis.v1.1",
        "evidence_package_id": 12,
        "evidence_package_version": 8,
        "metric_spec_version": "metric.v3",
        "strategy_basis": "ANSWER_DECISION_EVIDENCE_GAP",
        "replay_mode": "CONFIRMED_STRATEGY_SHADOW_REPLAY",
        "strategy_view_source": "CONFIRMED_EFFECTIVE_PAYLOAD",
        "decision_reasons": reasons,
        "themes": themes,
        "product_truths": [_truth()],
        "channel_resolutions": channels,
        "active_channel_keys": ["OFFICIAL_SITE", "BAIJIAHAO", "ZHIHU"],
        "deferred_channel_keys": ["SOHU"],
        "baseline_run_ids": list(range(1, 41)),
        "strategy_analyzable_run_ids": list(range(1, 16)),
        "required_signal_ids": ["required_signal:1:fixture"],
        "package_payload": package_payload,
        "resampling_plan": {
            "target_prompt_scope": [1],
            "baseline_run_ids": list(range(1, 41)),
            "default_sample_count": 3,
            "collection_mode": "single_independent",
            "execute_now_default": False,
        },
        "channel_evidence_snapshot_ref": {
            "source": "FROZEN_RESOLVER_CHANNEL_EVIDENCE_PROJECTION",
            "evidence_package_id": 12,
            "projection_hash": "channel-evidence-hash",
        },
        "frozen_semantics": {
            "resolver_roles": {row["channel_key"]: row["role"] for row in channels},
            "benchmark_signature": [],
            "strategy_basis": "ANSWER_DECISION_EVIDENCE_GAP",
        },
    }


def _managed_asset(asset_id: int) -> dict:
    return {
        "asset_id": asset_id,
        "channel": "OFFICIAL_SITE",
        "asset_type": "FEATURE_PAGE",
        "theme_ids": ["T1"],
        "purpose": "AUTHORITATIVE_PRODUCT_TRUTH",
        "product_truth_ids": [1],
        "version": 1,
    }


def _official(result: dict) -> dict:
    return next(row for row in result["active_proposals"] if row["channel"] == "OFFICIAL_SITE")


def _multi_theme_context() -> dict:
    context = _context()
    extra_reason = _reason(
        "reason:analytics",
        text="访问统计",
        truth_id=2,
        runs=list(range(1, 8)),
    )
    extra_reason["capability_family"] = "访问统计"
    extra_reason["normalized_proposition"] = "访问统计"
    extra_reason["scenario"] = ["GENERAL"]
    context["decision_reasons"].append(extra_reason)
    context["themes"].append({
        "theme_key": "T2",
        "reason_ids": [extra_reason["reason_id"]],
        "priority": "P2",
        "title": "访问统计",
        "theme_observed_run_ids": list(range(1, 8)),
        "theme_observed_run_count": 7,
    })
    context["product_truths"].append(_truth(2, "访问统计"))
    context["required_signal_ids"].append("required_signal:2:fixture")
    official = next(row for row in context["channel_resolutions"] if row["channel_key"] == "OFFICIAL_SITE")
    official["decision_reason_ids"].append(extra_reason["reason_id"])
    return context


def test_case_a_no_managed_assets_creates_new_asset():
    result = build_execution_proposal_portfolio(_context())
    official = _official(result)

    assert official["asset_operation"] == "CREATE_NEW"
    assert official["asset_resolution_status"] == "RESOLVED"


def test_case_b_one_compatible_managed_asset_is_resolved_update():
    result = build_execution_proposal_portfolio(_context(), [_managed_asset(10)])
    official = _official(result)

    assert official["asset_operation"] == "UPDATE_MANAGED"
    assert official["asset_resolution_status"] == "RESOLVED"
    assert official["selected_managed_asset_id"] == 10


def test_case_c_two_equal_managed_assets_require_human_selection():
    result = build_execution_proposal_portfolio(_context(), [_managed_asset(10), _managed_asset(11)])
    official = _official(result)

    assert official["asset_operation"] == "UPDATE_MANAGED"
    assert official["asset_resolution_status"] == "NEEDS_HUMAN_SELECTION"
    assert official["selected_managed_asset_id"] is None


def test_case_d_competitor_fact_is_context_only():
    policies = build_claim_usage_policy("Target Brand", [_truth()], [_reason("reason:competitor", text="竞品自动生成加密短链", qualifiers=["自动", "加密"])])

    competitor = [row for row in policies if row["policy"] == "COMPETITOR_CONTEXT_ONLY"]
    assert competitor
    assert all(row["may_become_target_fact"] is False for row in competitor)
    assert not any(
        row["policy"] == "TARGET_ASSERTION_ALLOWED" and row["proposition"]["object"] == "竞品自动生成加密短链"
        for row in policies
    )


def test_case_e_unknown_target_capability_stays_question_and_unknown():
    policies = build_claim_usage_policy("Target Brand", [], [_reason(truth_id=0, text="支持防封")])

    assert any(row["policy"] == "PLANNING_QUESTION" for row in policies)
    assert any(row["policy"] == "UNKNOWN_MUST_REMAIN_UNKNOWN" for row in policies)
    assert any(row["policy"] == "TARGET_ASSERTION_FORBIDDEN" for row in policies)


def test_case_f_unknown_question_is_not_publishable_faq():
    policies = build_claim_usage_policy("Target Brand", [], [_reason(truth_id=0, text="支持白名单")])

    assert not any(row["policy"] == "PUBLISHABLE_QUESTION_ALLOWED" for row in policies)
    question = next(row for row in policies if row["policy"] == "PLANNING_QUESTION")
    assert question["publishable"] is False


def test_case_g_manual_confirmed_truth_without_external_url_is_valid():
    context = _context()
    result = build_execution_proposal_portfolio(context)

    assert context["product_truths"][0]["source_reference"] == ""
    assert result["validators"]["ClaimGroundingValidator"]["status"] == "VALID"


def test_case_h_create_new_only_has_new_asset_spec_and_no_fake_asset():
    result = build_execution_proposal_portfolio(_context())
    official = _official(result)

    assert official["new_asset_spec"]["spec_type"] == "NEW_ASSET_SPEC"
    assert official["new_asset_spec"]["managed_asset_id"] is None
    assert official["new_asset_spec"]["published_url"] is None
    assert result["safety_audit"]["fake_managed_assets"] == 0


def test_case_i_test_channels_are_independent_proposals():
    result = build_execution_proposal_portfolio(_context())
    tests = [row for row in result["active_proposals"] if row["channel_role"] == "TEST"]

    assert {row["channel"] for row in tests} == {"BAIJIAHAO", "ZHIHU"}
    assert len({row["proposal_key"] for row in tests}) == 2
    assert all(row["proposal_type"] == "CHANNEL_VALIDATION_EXPERIMENT" for row in tests)
    assert all(row["attribution_contract"]["future_experiment_count"] == 1 for row in tests)


def test_case_j_missing_baseline_keeps_metric_projection_but_blocks_readiness():
    result = build_execution_proposal_portfolio(_context(include_baseline=False))

    assert all(row["eligible_metrics"] for row in result["active_proposals"])
    assert all(row["proposal_readiness"] == "BLOCKED_BY_CONSTRAINT" for row in result["active_proposals"])


def test_case_k_section_without_provenance_fails():
    context = _context()
    result = build_execution_proposal_portfolio(context)
    proposal = deepcopy(_official(result))
    section = proposal["section_plan"][0]
    for field in ("theme_ids", "reason_ids", "product_truth_ids", "required_signal_ids", "claim_usage_policy_ids"):
        section[field] = []

    validation = validate_section_provenance(context, [proposal])

    assert validation["status"] == "INVALID"
    assert any(error.startswith("SECTION_WITHOUT_PROVENANCE") for error in validation["errors"])


def test_case_l_invented_metric_fails():
    context = _context()
    result = build_execution_proposal_portfolio(context)
    proposal = deepcopy(_official(result))
    proposal["eligible_metrics"].append({
        "metric_key": "ai_visibility_magic_score",
        "measurement_level": "PROMPT_BRAND",
        "calculator": "invented",
        "baseline_status": "ZERO_OBSERVED",
    })

    validation = validate_metric_eligibility(context, [proposal])

    assert validation["status"] == "INVALID"
    assert "INVENTED_METRIC:ai_visibility_magic_score" in validation["errors"]


def test_case_m_strategy_runs_cannot_replace_fixed_baseline_runs():
    context = _context()
    result = build_execution_proposal_portfolio(context)
    proposal = deepcopy(_official(result))
    proposal["baseline_ref"]["baseline_run_ids"] = context["strategy_analyzable_run_ids"]

    validation = validate_baseline(context, result["execution_input_snapshot"], [proposal])

    assert validation["status"] == "INVALID"
    assert any(error.startswith("PROPOSAL_BASELINE_DRIFT") for error in validation["errors"])
    assert any(error.startswith("STRATEGY_RUNS_USED_AS_BASELINE") for error in validation["errors"])


def test_case_n_role_edit_is_rejected():
    context = _context()
    result = build_execution_proposal_portfolio(context)
    proposal = deepcopy(next(row for row in result["active_proposals"] if row["channel"] == "ZHIHU"))
    proposal["channel_role"] = "PRIMARY"

    validation = validate_channel_roles(context, [proposal])

    assert validation["status"] == "INVALID"
    assert any(error.startswith("ROLE_MUTATION:ZHIHU") for error in validation["errors"])


def test_case_o_unsupported_user_title_edit_is_rejected():
    context = _context()
    result = build_execution_proposal_portfolio(context)
    proposal = deepcopy(_official(result))
    proposal["title_candidates"][0]["title"] = "Target Brand 支持永久防封"

    title_validation = validate_title_claims(context, [proposal])

    assert title_validation["status"] == "INVALID"
    assert any(error.startswith("NON_CANONICAL_TITLE_TEXT") for error in title_validation["errors"])


def test_all_generated_objects_pass_all_validators_and_semantic_hash_is_stable():
    first = build_execution_proposal_portfolio(_context())
    second = build_execution_proposal_portfolio(_context())

    assert first["validation_status"] == "VALID"
    assert all(row["status"] == "VALID" for row in first["validators"].values())
    assert first["execution_input_snapshot"]["input_contract_hash"] == second["execution_input_snapshot"]["input_contract_hash"]
    assert first["external_llm_calls"] == 0
    assert first["boundary"]["db_writes"] == 0


def test_claim_validator_rejects_unconfirmed_allowed_assertion():
    context = _context()
    result = build_execution_proposal_portfolio(context)
    proposal = deepcopy(_official(result))
    claim = next(row for row in proposal["claim_usage_policy"] if row["policy"] == "TARGET_ASSERTION_ALLOWED")
    claim["product_truth_id"] = 999

    validation = validate_claim_grounding(context, [proposal])

    assert validation["status"] == "INVALID"
    assert any(error.startswith("UNCONFIRMED_TARGET_ASSERTION") for error in validation["errors"])


def test_asset_validator_rejects_fake_managed_identity_for_create_new():
    result = build_execution_proposal_portfolio(_context())
    proposal = deepcopy(_official(result))
    proposal["new_asset_spec"]["managed_asset_id"] = 999

    validation = validate_asset_fit([proposal], [])

    assert validation["status"] == "INVALID"
    assert any(error.startswith("FAKE_MANAGED_ASSET") for error in validation["errors"])


def test_asset_package_candidate_is_self_contained_and_one_asset():
    result = build_execution_proposal_portfolio(_multi_theme_context())
    packages = _official(result)["asset_package_candidates"]

    assert {row["package_scope_mode"] for row in packages} == {"FULL_STRATEGY_SCOPE", "P1_FOCUS"}
    assert all(row["asset_count"] == 1 for row in packages)
    assert all(row["theme_titles"] and row["reason_titles"] and row["product_truth_labels"] for row in packages)
    assert all(row["eligible_asset_types"] and row["share_asset_basis"] and row["tradeoffs"] for row in packages)
    assert validate_asset_package_quality([_official(result)])["status"] == "PASS"


def test_product_truth_sections_do_not_carry_unrelated_reasons_or_signals():
    context = _multi_theme_context()
    result = build_execution_proposal_portfolio(context)
    official = _official(result)
    full_plan = next(
        row for row in official["section_plan_candidates"]
        if row["asset_package_key"].endswith("all-themes")
    )
    truth_sections = [row for row in full_plan["section_plan"] if row["section_purpose"] == "PRODUCT_TRUTH"]

    assert {tuple(row["product_truth_ids"]) for row in truth_sections} == {(1,), (2,)}
    assert all(row["reason_ids"] == [] for row in truth_sections)
    assert all(row["planning_context_ids"] == [] for row in truth_sections)
    assert next(row for row in truth_sections if row["product_truth_ids"] == [1])["required_signal_ids"] == ["required_signal:1:fixture"]
    assert next(row for row in truth_sections if row["product_truth_ids"] == [2])["required_signal_ids"] == ["required_signal:2:fixture"]
    p1_plan = next(
        row for row in official["section_plan_candidates"]
        if row["asset_package_key"].endswith("p1-focus")
    )
    p1_validation = next(row for row in p1_plan["section_plan"] if row["section_purpose"] == "VALIDATION")
    assert p1_validation["required_signal_ids"] == ["required_signal:1:fixture"]


def test_planning_questions_never_enter_faq_and_operation_is_omitted_without_fact():
    result = build_execution_proposal_portfolio(_multi_theme_context())
    sections = [
        section
        for candidate in _official(result)["section_plan_candidates"]
        for section in candidate["section_plan"]
    ]

    assert not any(row["section_purpose"] == "OPERATION" for row in sections)
    faqs = [row for row in sections if row["section_purpose"] == "FAQ"]
    assert faqs
    assert all(row["planning_question_ids"] == [] for row in faqs)


def test_test_channel_hypotheses_follow_distinct_evidence_profiles():
    result = build_execution_proposal_portfolio(_context())
    tests = {row["channel"]: row for row in result["active_proposals"] if row["channel_role"] == "TEST"}

    assert tests["BAIJIAHAO"]["channel_opportunity_profile"]["retrieval_observations"] == 1
    assert tests["ZHIHU"]["channel_opportunity_profile"]["retrieval_observations"] == 0
    assert tests["BAIJIAHAO"]["intervention_hypothesis"]["pattern"] == "EXISTING_RETRIEVAL_EXPOSURE"
    assert tests["ZHIHU"]["intervention_hypothesis"]["pattern"] == "REFERENCE_ENVIRONMENT_WITHOUT_RETRIEVAL"
    assert tests["BAIJIAHAO"]["intervention_hypothesis"]["text"] != tests["ZHIHU"]["intervention_hypothesis"]["text"]
    assert validate_channel_hypothesis_quality(list(tests.values()))["status"] == "PASS"


def test_generic_channel_hypothesis_template_is_rejected_for_distinct_profiles():
    result = build_execution_proposal_portfolio(_context())
    tests = [deepcopy(row) for row in result["active_proposals"] if row["channel_role"] == "TEST"]
    for proposal in tests:
        proposal["intervention_hypothesis"]["text"] = f"验证{proposal['channel_label']}"

    validation = validate_channel_hypothesis_quality(tests)

    assert validation["status"] == "FAIL"
    assert any(error.startswith("GENERIC_CHANNEL_HYPOTHESIS_TEMPLATE") for error in validation["errors"])


def test_final_quality_audit_passes_for_complete_fixture():
    result = build_execution_proposal_portfolio(_context())

    assert result["proposal_quality_audit"]["overall_quality"] == "PASS"
    assert all(
        row["status"] == "PASS"
        for key, row in result["proposal_quality_audit"].items()
        if key != "overall_quality"
    )


def _valid_edit_for(source: dict, *, execute: bool = True) -> dict:
    title = (source.get("title_candidates") or [{}])[0].get("title")
    package_key = source.get("selected_asset_package_key")
    if not package_key:
        package_key = next(
            row["package_key"]
            for row in source["asset_package_candidates"]
            if row["package_scope_mode"] == "P1_FOCUS"
        )
    plan = next(
        row for row in source["section_plan_candidates"]
        if row["asset_package_key"] == package_key
    )
    return {
        "execute_this_proposal": execute,
        "selected_asset_package_key": package_key,
        "selected_asset_type": "FEATURE_PAGE" if source["channel"] == "OFFICIAL_SITE" else "ARTICLE",
        "title": title,
        "section_order": [row["section_id"] for row in plan["section_plan"]],
        "publishing_metadata": {
            "publishing_account": f"account-{source['channel'].lower()}",
            "publishing_location": "content-center",
            "url_slug": f"pr5-b-{source['channel'].lower()}",
            "channel_specific_posting_metadata": {},
        },
        "selected_observation_window_index": 0,
    }


def _valid_portfolio_payload(context: dict, *, defer_zhihu: bool = False) -> tuple[dict, dict]:
    source = build_execution_proposal_portfolio(context)
    edits = []
    for proposal in source["active_proposals"]:
        edit = _valid_edit_for(proposal, execute=not (defer_zhihu and proposal["channel"] == "ZHIHU"))
        edits.append({"proposal_key": proposal["proposal_key"], "human_edits": edit})
    return source, {
        "strategy_candidate_id": context["strategy_candidate_id"],
        "edited_by": "reviewer",
        "proposal_edits": edits,
    }


def test_pr5_b_valid_portfolio_rebuilds_and_becomes_ready():
    context = _multi_theme_context()
    source, payload = _valid_portfolio_payload(context, defer_zhihu=True)

    result = revalidate_execution_proposal_portfolio(context, payload)

    official = next(row for row in result["proposal_drafts"] if row["canonical_proposal"]["channel"] == "OFFICIAL_SITE")
    zhihu = next(row for row in result["proposal_drafts"] if row["canonical_proposal"]["channel"] == "ZHIHU")
    assert result["portfolio_readiness"] == "READY_FOR_CONFIRMATION"
    assert result["ready_for_freeze"] is True
    assert official["canonical_proposal"]["selected_asset_package_key"].endswith("p1-focus")
    assert official["canonical_proposal"]["selected_asset_type"] == "FEATURE_PAGE"
    assert official["proposal_readiness"] == "READY_FOR_CONFIRMATION"
    assert set(official["all_validators_rerun"]) == {
        "SnapshotValidator", "ChannelRoleValidator", "AssetFitValidator", "ClaimGroundingValidator",
        "TitleClaimValidator", "SectionProvenanceValidator", "BaselineValidator", "MetricEligibilityValidator",
    }
    assert all(row["status"] == "VALID" for row in official["validator_results"].values())
    assert zhihu["proposal_execution_state"] == "DEFERRED_BY_HUMAN"
    assert zhihu["proposal_readiness"] == "DEFERRED_BY_HUMAN"
    assert source["active_proposals"] != result["canonical_rebuilt_proposals"]
    assert result["boundary"]["db_writes"] == 0
    assert result["external_llm_calls"] == 0
    assert all(value == 0 for value in result["safety_audit"].values())


def test_pr5_b_valid_section_reorder_is_preserved_and_valid():
    context = _multi_theme_context()
    source = build_execution_proposal_portfolio(context)
    official = _official(source)
    edits = _valid_edit_for(official)
    edits["section_order"] = list(reversed(edits["section_order"]))

    result = revalidate_execution_proposal(context, {
        "proposal_key": official["proposal_key"],
        "human_edits": edits,
    })

    assert result["draft_status"] == "VALID"
    assert [row["section_id"] for row in result["canonical_proposal"]["section_plan"]] == edits["section_order"]
    assert result["validator_results"]["SectionProvenanceValidator"]["status"] == "VALID"


def test_pr5_b_invalid_title_is_rejected_without_new_truth():
    context = _multi_theme_context()
    official = _official(build_execution_proposal_portfolio(context))
    edits = _valid_edit_for(official)
    edits["title"] = "Target Brand：自动生成加密短链能力说明"

    result = revalidate_execution_proposal(context, {"proposal_key": official["proposal_key"], "human_edits": edits})

    error = next(row for row in result["edit_errors"] if row["error_code"] == "UNSUPPORTED_TARGET_ASSERTION")
    assert result["draft_status"] == "INVALID_EDIT"
    assert error["offending_phrase"] == "自动生成加密短链"
    assert result["canonical_proposal"]["product_truth_ids"] == [1]


def test_pr5_b_immutable_edits_are_rejected_with_specific_codes():
    context = _multi_theme_context()
    source = build_execution_proposal_portfolio(context)
    zhihu = next(row for row in source["active_proposals"] if row["channel"] == "ZHIHU")
    cases = {
        "channel_role": ("PRIMARY", "IMMUTABLE_FIELD_EDIT"),
        "baseline_run_ids": ([999], "IMMUTABLE_BASELINE"),
        "product_truth_ids": ([999], "IMMUTABLE_PRODUCT_TRUTH"),
        "theme_ids": (["T2"], "INVALID_PACKAGE_SCOPE_EDIT"),
        "reason_ids": (["reason:analytics"], "IMMUTABLE_REASON_SCOPE"),
    }
    for field, (value, code) in cases.items():
        edits = _valid_edit_for(zhihu)
        edits[field] = value
        result = revalidate_execution_proposal(context, {"proposal_key": zhihu["proposal_key"], "human_edits": edits})
        assert result["draft_status"] == "INVALID_EDIT"
        assert any(row["error_code"] == code and row["field"] == field for row in result["edit_errors"])
        assert result["canonical_proposal"]["channel_role"] == "TEST"
        assert result["canonical_proposal"]["reason_ids"] == zhihu["reason_ids"]

    result = revalidate_execution_proposal(context, {
        "proposal_key": zhihu["proposal_key"],
        "human_edits": _valid_edit_for(zhihu),
        "baseline_run_ids": [999],
    })
    assert any(row["error_code"] == "IMMUTABLE_BASELINE" for row in result["edit_errors"])


def test_pr5_b_invalid_asset_type_and_observation_window_are_rejected():
    context = _multi_theme_context()
    official = _official(build_execution_proposal_portfolio(context))
    edits = _valid_edit_for(official)
    edits["selected_asset_type"] = "LANDING_PAGE"
    edits["selected_observation_window_index"] = 99

    result = revalidate_execution_proposal(context, {"proposal_key": official["proposal_key"], "human_edits": edits})

    assert result["draft_status"] == "INVALID_EDIT"
    assert {row["error_code"] for row in result["edit_errors"]} >= {"INVALID_ASSET_TYPE", "INVALID_OBSERVATION_WINDOW"}


def test_pr5_b_ungrounded_section_and_planning_question_faq_are_rejected():
    context = _multi_theme_context()
    official = _official(build_execution_proposal_portfolio(context))
    edits = _valid_edit_for(official)
    edits["section_order"].append("section:invented:industry-leadership")
    result = revalidate_execution_proposal(context, {"proposal_key": official["proposal_key"], "human_edits": edits})
    assert any(row["error_code"] == "UNGROUNDED_SECTION" for row in result["edit_errors"])

    edits = _valid_edit_for(official)
    edits["section_overrides"] = [{"section_purpose": "FAQ", "planning_question_ids": ["planning:unknown"]}]
    result = revalidate_execution_proposal(context, {"proposal_key": official["proposal_key"], "human_edits": edits})
    assert any(row["error_code"] == "FAQ_CONTAINS_PLANNING_QUESTION" for row in result["edit_errors"])


def test_pr5_b_merge_attempt_is_rejected_and_portfolio_is_invalid():
    context = _multi_theme_context()
    _source, payload = _valid_portfolio_payload(context)
    payload["merge_proposal_keys"] = [
        "proposal:57:baijiahao",
        "proposal:57:zhihu",
    ]

    result = revalidate_execution_proposal_portfolio(context, payload)

    assert result["portfolio_readiness"] == "HAS_INVALID_EDIT"
    assert result["ready_for_freeze"] is False
    assert any(row["error_code"] == "PROPOSAL_MERGE_FORBIDDEN" for row in result["portfolio_errors"])


def test_pr5_b_missing_decision_keeps_portfolio_needing_selection():
    context = _multi_theme_context()
    source, payload = _valid_portfolio_payload(context)
    payload["proposal_edits"] = payload["proposal_edits"][:-1]

    result = revalidate_execution_proposal_portfolio(context, payload)

    assert result["portfolio_readiness"] == "NEEDS_HUMAN_SELECTION"
    assert result["ready_for_freeze"] is False
    assert any(row["proposal_execution_state"] == "UNDECIDED" for row in result["proposal_drafts"])
    assert len(source["active_proposals"]) == len(result["proposal_drafts"])
