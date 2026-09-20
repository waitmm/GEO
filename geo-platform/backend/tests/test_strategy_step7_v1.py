from __future__ import annotations

import copy
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    EvidenceAlignment,
    OptimizationEvidencePackage,
    OptimizationStrategyCandidate,
    Project,
    Prompt,
    RecommendationEvent,
    TargetBrandCapabilityTruth,
)
from app.modules.optimization import service as optimization_service
from app.modules.optimization.service import (
    _channel_aggregation_for_rows,
    _citation_decision_values_from_benchmark_items,
    _current_answer_decision_evidence_gap_action,
    _supersede_current_pending_step7_candidates,
    current_step7_candidate_eligibility,
    _resolve_strategy_channels,
    _strategy_payload_from_vertical_action,
)
from app.services.serialization import dumps


def _project() -> Project:
    return Project(
        id=3,
        organization_id=1,
        name="爱短链品牌监测",
        brand_name="爱短链",
        website_url="https://www.aifabu.com",
    )


def _prompt() -> Prompt:
    return Prompt(id=40, project_id=3, prompt_text="长链接缩短工具推荐", title="长链接缩短")


def _package() -> OptimizationEvidencePackage:
    return OptimizationEvidencePackage(
        id=15,
        project_id=3,
        prompt_id=40,
        source_run_ids_json=dumps([238, 239, 240, 253, 254, 255]),
        package_payload_json=dumps({
            "metrics": [
                {"metric_name": "brand_mention_rate", "numerator": 0, "denominator": 6, "value": 0},
            ],
        }),
    )


def _action() -> dict:
    return {
        "action_key": "content-gap-zhihu-click-stat",
        "route": "CONTENT",
        "priority_level": "PRIORITY_HIGH",
        "gap_type": "CONTENT_GAP",
        "gap_label": "内容表达缺口",
        "summary": "补齐点击统计、自定义分享标题的品牌能力表达。",
        "decision_support_level": "RECOMMENDATION_REASON",
        "benchmark_source": {
            "source_document_id": 345,
            "title": "如何将长链接缩短-小码至营",
            "platform": "zhihu",
            "platform_label": "知乎",
        },
        "citation_decision_values": [
            {
                "citation_value_class": "DECISION_CITATION",
                "source_document_id": 345,
                "platform": "zhihu",
                "platform_label": "知乎",
                "supported_entity": "小码短链接",
                "supported_capability": "点击统计",
                "supported_reason": "点击统计",
                "evidence_alignment_ids": [9001],
                "support_run_ids": [238, 239, 240, 253, 254, 255],
                "observed_run_ids": [238, 239, 240, 253, 254, 255],
            }
        ],
        "citation_value_summary": {
            "class": "DECISION_CITATION",
            "label": "决策引用",
            "decision_citation_count": 1,
            "support_run_ids": [238, 239, 240, 253, 254, 255],
        },
        "channel_aggregation": [
            {
                "channel": "ZHIHU",
                "channel_label": "知乎",
                "retrieval_run_count": 6,
                "citation_run_count": 6,
                "decision_citation_run_count": 6,
                "answer_support_run_count": 0,
                "eligible_support_run_count": 6,
                "run_coverage_denominator": 6,
                "supported_entities": ["小码短链接"],
                "supported_reasons": ["点击统计", "自定义分享标题"],
                "supported_capabilities": ["点击统计", "自定义分享标题"],
                "primary_benchmark_count": 1,
                "secondary_benchmark_count": 0,
                "gap_types": ["CONTENT_GAP"],
            }
        ],
        "product_truth_status": "TRUE",
        "product_truth_ids": [701, 702],
        "content_requirements": ["直接回答 Prompt", "能力事实说明", "适用场景"],
        "gap_items": [
            {
                "gap_item_id": "gap-click-stat",
                "capability_label": "点击统计",
                "gap_type": "CONTENT_GAP",
                "gap_label": "内容表达缺口",
                "gap_layer": "RELEVANT_ASSET_EXPRESSION",
                "benchmark_tier": "PRIMARY_BENCHMARK",
                "decision_support_level": "RECOMMENDATION_REASON",
                "benchmark_evidence_ids": [9001],
                "observed_run_ids": [238, 239, 240, 253, 254, 255],
                "product_truth_ids": [701],
                "product_truth_status": "TRUE",
            },
            {
                "gap_item_id": "gap-custom-title",
                "capability_label": "自定义分享标题",
                "gap_type": "CONTENT_GAP",
                "gap_label": "内容表达缺口",
                "gap_layer": "RELEVANT_ASSET_EXPRESSION",
                "benchmark_tier": "PRIMARY_BENCHMARK",
                "decision_support_level": "RECOMMENDATION_REASON",
                "benchmark_evidence_ids": [9002, 9003],
                "observed_run_ids": [238, 239, 240, 253, 254, 255],
                "product_truth_ids": [702],
                "product_truth_status": "TRUE",
            },
            {
                "gap_item_id": "gap-marketing",
                "capability_label": "营销场景",
                "gap_type": "CONTENT_GAP",
                "gap_label": "内容表达缺口",
                "gap_layer": "RELEVANT_ASSET_EXPRESSION",
                "benchmark_tier": "SECONDARY_BENCHMARK",
                "decision_support_level": "CANDIDATE_OR_EVALUATION",
                "benchmark_evidence_ids": [9004],
                "observed_run_ids": [238, 239],
                "product_truth_ids": [703],
                "product_truth_status": "TRUE",
            },
        ],
    }


def test_step7_payload_has_strategy_fields_not_only_gap_restatement():
    payload = _strategy_payload_from_vertical_action(_project(), _prompt(), _package(), _action(), {})

    assert payload["strategy_phase"] == "PHASE_3_STRATEGY_CANDIDATE"
    assert "AI 回答" in payload["target_decision_change"]
    assert "品牌-能力-推荐理由关联" in payload["target_decision_change"]
    assert "AI 已在" in payload["strategic_hypothesis"]
    assert "Product Truth" in payload["strategic_hypothesis"]
    assert "第 8 步" in payload["strategic_hypothesis"]
    assert payload["recommended_action"] == "补齐点击统计、自定义分享标题的品牌能力表达。"


def test_step7_priority_capabilities_are_capability_level_and_allow_ties():
    payload = _strategy_payload_from_vertical_action(_project(), _prompt(), _package(), _action(), {})

    capabilities = payload["priority_capabilities"]
    assert [item["capability_label"] for item in capabilities] == ["点击统计", "自定义分享标题", "营销场景"]
    assert [item["priority_band"] for item in capabilities] == ["P1", "P1", "P2"]
    assert capabilities[0]["reason_run_coverage"] == "6/6"
    assert capabilities[1]["benchmark_evidence_count"] == 2
    assert "并列 P1" in capabilities[1]["priority_basis"]


def test_step7_required_signals_and_non_goals_do_not_choose_concrete_execution():
    payload = _strategy_payload_from_vertical_action(_project(), _prompt(), _package(), _action(), {})

    signal_text = " ".join(item["signal"] for item in payload["required_signals"])
    requirement_text = " ".join(item["evidence_requirement"] for item in payload["required_signals"])
    non_goals = " ".join(payload["non_goals"])

    assert "爱短链 支持 点击统计" in signal_text
    assert "目标品牌自己的真实能力表达" in requirement_text
    assert "不因为核心对标来源来自「知乎」就默认去该平台发布" in non_goals
    assert "不在第 7 步选择具体账号" in non_goals
    assert "页面区块" not in signal_text + requirement_text
    assert "FAQ" not in signal_text + requirement_text


def test_step7_strategy_core_includes_planned_channel_layer():
    payload = _strategy_payload_from_vertical_action(_project(), _prompt(), _package(), _action(), {})

    assert payload["intervention_mechanism"]
    assert payload["primary_intervention_path"].startswith("FIRST_PARTY_BRAND_CAPABILITY_EXPRESSION")
    assert payload["planned_channels"][0]["channel"] == "OFFICIAL_SITE"
    assert payload["planned_channels"][0]["intervention_priority"] == "PRIMARY"
    assert payload["planned_channels"][0]["channel_role"].startswith("承载目标品牌自己的能力事实表达")
    zhihu = next(item for item in payload["planned_channels"] if item["channel"] == "ZHIHU")
    assert zhihu["intervention_priority"] == "SECONDARY"
    assert "直接参与 AI 品牌决策" in zhihu["channel_role"]
    assert "Decision Citation 覆盖 6/6 Runs" in zhihu["selection_basis"]
    assert payload["channel_roles"]["OFFICIAL_SITE"]["intervention_priority"] == "PRIMARY"
    assert payload["channel_roles"]["ZHIHU"]["citation_decision_value_basis"]["decision_citation_run_count"] == 6
    assert payload["secondary_intervention"][0]["channel"] == "ZHIHU"
    assert payload["asset_direction"]["asset_operation"] == "CREATE_NEW"
    assert payload["execution_sequence"][0]["name"] == "确认执行资产"
    assert payload["attribution_intent"]["primary_capability"] == "点击统计"
    assert payload["attribution_intent"]["attribution_scope"] == "CAPABILITY_BUNDLE"
    assert "计划平台层" in payload["strategy_boundary_note"]


def test_step7_concrete_execution_fields_remain_unresolved_and_step8_compatible():
    payload = _strategy_payload_from_vertical_action(_project(), _prompt(), _package(), _action(), {})

    assert payload["target_platform"] == "UNRESOLVED"
    assert payload["target_asset"] == "UNRESOLVED"
    assert payload["target_content_type"] == "UNRESOLVED"
    assert payload["intervention_type"] == "UNRESOLVED"
    assert "Step 8" in payload["recommended_action_boundary"]
    assert "具体账号" in payload["recommended_action_boundary"]
    assert payload["changed_features"]
    assert payload["required_sections"] == ["直接回答 Prompt", "能力事实说明", "适用场景"]
    assert payload["target_metric"] == "brand_mention_rate"
    assert payload["benchmark_channel_boundary"].startswith("Benchmark 来源平台不能自动成为")


def test_citation_decision_value_is_source_entity_capability_grained():
    row = {
        "source_document_id": 345,
        "platform": "zhihu",
        "domain": "zhuanlan.zhihu.com",
        "url": "https://zhuanlan.zhihu.com/p/1",
        "benchmark_tier": "PRIMARY_BENCHMARK",
        "decision_support_level": "RECOMMENDATION_REASON",
        "citation_run_ids": [238, 239],
    }
    values = _citation_decision_values_from_benchmark_items(row, [
        {
            "alignment_id": 9001,
            "source_claim_id": 8001,
            "recommendation_event_id": 7001,
            "decision_binding_id": 6001,
            "answer_unit_id": 5001,
            "event_entity": "小码短链接",
            "event_speech_act": "RECOMMEND",
            "answer_unit_text": "点击统计",
            "claim_text": "小码短链接支持点击统计",
            "observed_run_ids": [238],
        },
        {
            "alignment_id": 9002,
            "source_claim_id": 8002,
            "recommendation_event_id": 7001,
            "decision_binding_id": 6002,
            "answer_unit_id": 5002,
            "event_entity": "小码短链接",
            "event_speech_act": "RECOMMEND",
            "answer_unit_text": "自定义分享标题",
            "claim_text": "小码短链接可设置分享标题",
            "observed_run_ids": [239],
        },
    ])

    assert len(values) == 2
    assert {item["supported_capability"] for item in values} == {"点击统计", "自定义分享标题"}
    assert all(item["citation_value_class"] == "DECISION_CITATION" for item in values)
    assert values[0]["source_document_id"] == 345
    assert values[0]["supported_entity"] == "小码短链接"


def test_answer_support_citation_requires_support_without_decision_binding():
    row = {
        "source_document_id": 88,
        "platform": "web",
        "benchmark_tier": "SECONDARY_BENCHMARK",
        "decision_support_level": "FACT_ONLY",
        "citation_run_ids": [1],
    }
    values = _citation_decision_values_from_benchmark_items(row, [
        {
            "alignment_id": 11,
            "source_claim_id": 12,
            "answer_unit_id": 13,
            "answer_unit_text": "短链接适合营销场景",
            "claim_text": "短链接可用于营销场景",
            "observed_run_ids": [1],
        }
    ])

    assert values[0]["citation_value_class"] == "ANSWER_SUPPORT_CITATION"


def test_channel_aggregation_counts_decision_answer_and_peripheral_runs():
    rows = [
        {
            "source_document_id": 345,
            "platform": "zhihu",
            "title": "小码文章",
            "benchmark_tier": "PRIMARY_BENCHMARK",
            "citation_run_ids": [238, 239],
            "retrieval_run_ids": [238, 239, 240],
            "citation_decision_values": [
                {
                    "citation_value_class": "DECISION_CITATION",
                    "supported_entity": "小码短链接",
                    "supported_capability": "点击统计",
                    "support_run_ids": [238, 239],
                }
            ],
        },
        {
            "source_document_id": 346,
            "platform": "zhihu",
            "title": "背景文章",
            "benchmark_tier": "REFERENCE_ONLY",
            "citation_run_ids": [240],
            "retrieval_run_ids": [240],
            "citation_decision_values": [],
            "citation_value_class": "PERIPHERAL_CITATION",
            "run_ids": [240],
        },
    ]

    aggregation = _channel_aggregation_for_rows(rows, [238, 239, 240])
    zhihu = aggregation[0]

    assert zhihu["channel"] == "ZHIHU"
    assert zhihu["decision_citation_run_count"] == 2
    assert zhihu["peripheral_run_count"] == 1
    assert zhihu["primary_benchmark_count"] == 1
    assert zhihu["supported_reasons"] == ["点击统计"]


def test_benchmark_channel_without_decision_citation_remains_observe():
    action = _action()
    action["channel_aggregation"] = [
        {
            "channel": "ZHIHU",
            "channel_label": "知乎",
            "decision_citation_run_count": 0,
            "eligible_support_run_count": 0,
            "run_coverage_denominator": 6,
            "supported_reasons": [],
            "primary_benchmark_count": 1,
        }
    ]
    payload = _strategy_payload_from_vertical_action(_project(), _prompt(), _package(), action, {})
    zhihu = next(item for item in payload["planned_channels"] if item["channel"] == "ZHIHU")

    assert zhihu["intervention_priority"] == "OBSERVE"
    assert "Benchmark 来源平台只说明" in zhihu["selection_basis"]


def _action_for_gap(gap_type: str, *, route: str | None = None, product_truth_status: str = "TRUE") -> dict:
    action = copy.deepcopy(_action())
    action["gap_type"] = gap_type
    action["gap_label"] = {
        "CONTENT_GAP": "内容表达缺口",
        "EVIDENCE_GAP": "证据采纳缺口",
        "DISCOVERABILITY_GAP": "检索发现缺口",
        "PRODUCT_GAP": "产品能力缺口",
        "UNKNOWN": "待确认缺口",
        "NO_GAP": "无明确缺口",
    }.get(gap_type, gap_type)
    action["route"] = route or {
        "CONTENT_GAP": "CONTENT",
        "EVIDENCE_GAP": "EVIDENCE",
        "DISCOVERABILITY_GAP": "DISCOVERABILITY",
        "PRODUCT_GAP": "PRODUCT",
        "UNKNOWN": "UNRESOLVED",
        "NO_GAP": "NO_ACTION",
    }.get(gap_type, "UNRESOLVED")
    action["product_truth_status"] = product_truth_status
    for item in action["gap_items"]:
        item["gap_type"] = gap_type
        item["gap_label"] = action["gap_label"]
        item["product_truth_status"] = product_truth_status
        item["gap_layer"] = {
            "CONTENT_GAP": "RELEVANT_ASSET_EXPRESSION",
            "EVIDENCE_GAP": "EVIDENCE_ADOPTION",
            "DISCOVERABILITY_GAP": "RETRIEVAL_CANDIDATE",
            "PRODUCT_GAP": "PRODUCT_TRUTH",
            "UNKNOWN": "UNKNOWN",
            "NO_GAP": "NO_GAP",
        }.get(gap_type, "")
    return action


def test_strategy_channel_resolver_content_gap_keeps_first_party_primary_with_strong_third_party_secondary():
    action = _action_for_gap("CONTENT_GAP")
    payload = _strategy_payload_from_vertical_action(_project(), _prompt(), _package(), action, {})

    assert payload["strategy_channel_resolver"]["name"] == "resolve_strategy_channels"
    assert payload["primary_intervention_path"] == "FIRST_PARTY_BRAND_CAPABILITY_EXPRESSION:OFFICIAL_SITE"
    assert payload["planned_channels"][0]["channel"] == "OFFICIAL_SITE"
    assert payload["planned_channels"][0]["intervention_priority"] == "PRIMARY"
    zhihu = next(item for item in payload["planned_channels"] if item["channel"] == "ZHIHU")
    assert zhihu["intervention_priority"] == "SECONDARY"
    assert "Decision Citation 覆盖 6/6 Runs" in zhihu["selection_basis"]
    assert "不是因为官网天然优先" in payload["planned_channels"][0]["selection_basis"]


def test_strategy_channel_resolver_evidence_gap_allows_third_party_primary_when_decision_citation_is_strong():
    action = _action_for_gap("EVIDENCE_GAP")
    payload = _strategy_payload_from_vertical_action(_project(), _prompt(), _package(), action, {})

    assert payload["primary_intervention_path"] == "THIRD_PARTY_DECISION_EVIDENCE:ZHIHU"
    assert payload["planned_channels"][0]["channel"] == "ZHIHU"
    assert payload["planned_channels"][0]["intervention_priority"] == "PRIMARY"
    assert "多个有效 Run" in payload["planned_channels"][0]["channel_role"]
    official = next(item for item in payload["planned_channels"] if item["channel"] == "OFFICIAL_SITE")
    assert official["intervention_priority"] == "SECONDARY"
    assert "第三方证据可成为主路径" in official["selection_basis"]


def test_strategy_channel_resolver_discoverability_gap_prioritizes_retrieval_expansion():
    action = _action_for_gap("DISCOVERABILITY_GAP")
    action["channel_aggregation"].append({
        "channel": "BAIJIAHAO",
        "channel_label": "百家号",
        "retrieval_run_count": 5,
        "citation_run_count": 1,
        "decision_citation_run_count": 0,
        "run_coverage_denominator": 6,
        "supported_reasons": [],
    })
    payload = _strategy_payload_from_vertical_action(_project(), _prompt(), _package(), action, {})

    assert payload["primary_intervention_path"] == "DISCOVERABILITY_RETRIEVAL_EXPANSION:OFFICIAL_SITE"
    assert payload["planned_channels"][0]["intervention_type"] == "DISCOVERABILITY_RETRIEVAL_EXPANSION"
    assert "Retrieval 缺口" in payload["planned_channels"][0]["selection_basis"]


def test_strategy_channel_resolver_product_gap_does_not_create_content_channel_primary():
    action = _action_for_gap("PRODUCT_GAP", product_truth_status="FALSE")
    payload = _strategy_payload_from_vertical_action(_project(), _prompt(), _package(), action, {})

    assert payload["primary_intervention_path"] == "PRODUCT_IMPROVEMENT"
    assert not any(item["intervention_priority"] == "PRIMARY" for item in payload["planned_channels"])
    assert payload["planned_channels"][0]["channel"] == "OTHER"
    assert payload["planned_channels"][0]["intervention_priority"] == "NOT_RECOMMENDED"
    assert "不能把未支持的产品能力包装成官网或第三方内容优化" in payload["planned_channels"][0]["selection_basis"]


def test_strategy_channel_resolver_unknown_does_not_force_primary_channel():
    action = _action_for_gap("UNKNOWN", product_truth_status="UNKNOWN")
    payload = _strategy_payload_from_vertical_action(_project(), _prompt(), _package(), action, {})

    assert payload["primary_intervention_path"] == "NEED_MORE_EVIDENCE"
    assert not any(item["intervention_priority"] == "PRIMARY" for item in payload["planned_channels"])
    assert payload["planned_channels"][0]["intervention_priority"] == "NOT_RECOMMENDED"
    assert "暂不生成确定执行平台" in payload["planned_channels"][0]["channel_role"]


def test_strategy_channel_resolver_benchmark_only_without_decision_citation_cannot_upgrade_channel():
    action = _action_for_gap("CONTENT_GAP")
    action["channel_aggregation"] = [
        {
            "channel": "ZHIHU",
            "channel_label": "知乎",
            "retrieval_run_count": 6,
            "citation_run_count": 6,
            "decision_citation_run_count": 0,
            "answer_support_run_count": 0,
            "eligible_support_run_count": 0,
            "run_coverage_denominator": 6,
            "supported_reasons": [],
            "primary_benchmark_count": 1,
            "secondary_benchmark_count": 0,
        }
    ]
    payload = _strategy_payload_from_vertical_action(_project(), _prompt(), _package(), action, {})
    zhihu = next(item for item in payload["planned_channels"] if item["channel"] == "ZHIHU")

    assert payload["primary_intervention_path"] == "FIRST_PARTY_BRAND_CAPABILITY_EXPRESSION:OFFICIAL_SITE"
    assert zhihu["intervention_priority"] == "OBSERVE"
    assert "没有 Decision Citation 时不能升级" in zhihu["selection_basis"]


def test_strategy_channel_resolver_step7_does_not_choose_step8_concrete_execution_fields():
    payload = _strategy_payload_from_vertical_action(_project(), _prompt(), _package(), _action(), {})

    assert payload["strategy_channel_resolver"]["scope"] == "STEP_7_CHANNEL_ROLE_AND_INTERVENTION_PATH_ONLY"
    assert "url" in payload["strategy_channel_resolver"]["does_not_decide"]
    assert payload["target_platform"] == "UNRESOLVED"
    assert payload["target_url"] == ""
    assert payload["target_asset"] == "UNRESOLVED"


def test_current_step7_generation_does_not_recompute_full_source_analysis(monkeypatch):
    project = _project()
    prompt = _prompt()
    package = _package()
    created_payloads = []

    class FakeDb:
        def get(self, model, object_id):
            if model is Project:
                return project
            if model is Prompt:
                return prompt
            if model is OptimizationEvidencePackage:
                return package
            return None

    def fail_full_source_analysis(*args, **kwargs):
        raise AssertionError("current Step 7 generation must not rebuild citation-decision-v1 source analysis")

    monkeypatch.setattr(optimization_service, "_source_analysis_for_package", fail_full_source_analysis)
    monkeypatch.setattr(
        optimization_service,
        "_current_step7_strategy_rows_for_package",
        lambda *args, **kwargs: [{"recommended_action": _action()}],
    )
    monkeypatch.setattr(optimization_service, "_supersede_current_pending_step7_candidates", lambda *args, **kwargs: None)
    monkeypatch.setattr(optimization_service, "_upsert_workflow_confirmation", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        optimization_service,
        "_attach_constraint_first_strategy_synthesis",
        lambda db, project, prompt, package, payload: {**payload, "strategy_synthesis": {"validator_status": "VALID"}},
    )

    def fake_create_strategy(db, project, package, payload, reviewer):
        created_payloads.append(payload)
        return object()

    monkeypatch.setattr(optimization_service, "_create_vertical_strategy_candidate", fake_create_strategy)
    monkeypatch.setattr(
        optimization_service,
        "strategy_candidate_to_read",
        lambda strategy, package_context=None: {"id": 999, "review_status": "PENDING_REVIEW"},
    )

    result = optimization_service.generate_current_step7_strategy_candidates(
        FakeDb(),
        project.id,
        prompt.id,
        {"evidence_package_id": package.id, "max_actions": 5},
    )

    assert result["status"] == "STRATEGY_CANDIDATES_CREATED"
    assert result["created"][0]["strategy_candidate"]["id"] == 999
    assert created_payloads[0]["candidate_origin"] == optimization_service.CURRENT_STEP7_CANDIDATE_ORIGIN
    assert created_payloads[0]["strategy_context"]["evidence_package_id"] == package.id
    assert created_payloads[0]["strategy_synthesis"]["validator_status"] == "VALID"


def test_answer_decision_gap_action_uses_product_truth_without_fake_benchmark():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        project = _project()
        prompt = Prompt(id=19, project_id=project.id, prompt_text="抖音跳转微信", title="抖音跳转微信")
        package = OptimizationEvidencePackage(
            id=12,
            project_id=project.id,
            prompt_id=prompt.id,
            source_run_ids_json=dumps([101, 102, 103]),
            package_payload_json=dumps({
                "metrics": [
                    {"metric_name": "brand_mention_rate", "numerator": 0, "denominator": 3, "value": 0},
                ],
            }),
        )
        db.add_all([project, prompt, package])
        db.add(TargetBrandCapabilityTruth(
            project_id=project.id,
            brand_id=None,
            capability_key="短链生成",
            capability_label="短链生成",
            product_truth_status="SUPPORTED",
        ))
        for run_id in [101, 102]:
            db.add(RecommendationEvent(
                project_id=project.id,
                prompt_id=prompt.id,
                run_id=run_id,
                entity_text="商加加",
                speech_act="RECOMMEND",
                recommendation_strength="STRONG",
                polarity="POSITIVE",
                reasons_json=dumps([
                    {"normalized_reason": "可以自动生成加密短链", "reason_scope": "ENTITY_SPECIFIC"},
                ]),
                review_status="MACHINE_GROUNDED",
            ))
        db.commit()

        action = _current_answer_decision_evidence_gap_action(
            db,
            project,
            prompt,
            package,
            [101, 102, 103],
            channel_aggregation=[],
        )

        assert action is not None
        assert action["route"] == "EVIDENCE"
        assert action["gap_type"] == "EVIDENCE_GAP"
        assert action["benchmark_source"]["benchmark_tier"] == "NO_ELIGIBLE_BENCHMARK"
        assert action["benchmark_source"]["supporting_alignment_ids"] == []
        assert action["benchmark_evidence_ids"] == []
        assert action["strategy_basis"] == "ANSWER_DECISION_EVIDENCE_GAP"
        assert action["evidence_gap_reason"] == "NO_ELIGIBLE_SUPPORT_WITH_REQUIRED_LINEAGE"
        assert action["decision_reason_ids"] == ["reason:可以自动生成加密短链"]
        assert action["eligible_support_count"] == 0
        assert action["eligible_contradiction_ids"] == []
        assert action["product_truth_status"] == "TRUE"
        assert action["gap_items"][0]["lineage_source"] == "ANSWER_DECISION_REASON_WITH_PRODUCT_TRUTH"
        assert action["gap_items"][0]["benchmark_evidence_ids"] == []
        assert action["gap_items"][0]["decision_reason_id"] == "reason:可以自动生成加密短链"
        assert action["gap_items"][0]["evidence_adoption_context"]["evidence_gap_cause"] == "NO_ELIGIBLE_SUPPORT_WITH_REQUIRED_LINEAGE"
        assert action["gap_items"][0]["relevant_asset_snapshot"] is None

        existing_support = EvidenceAlignment(
            id=9001,
            project_id=project.id,
            prompt_id=prompt.id,
            run_id=101,
            recommendation_event_id=1,
            recommendation_reason_id="reason:可以自动生成加密短链",
            source_document_id=999,
            source_claim_id=999,
            relation="SUPPORTS",
            review_status="HUMAN_CONFIRMED",
        )
        blocked_action = _current_answer_decision_evidence_gap_action(
            db,
            project,
            prompt,
            package,
            [101, 102, 103],
            channel_aggregation=[],
            eligible_supports=[existing_support],
        )
        assert blocked_action is None
    finally:
        db.close()


def test_current_step7_eligibility_allows_answer_decision_gap_without_benchmark_ids():
    project = _project()
    prompt = Prompt(id=19, project_id=project.id, prompt_text="抖音跳转微信", title="抖音跳转微信")
    package = OptimizationEvidencePackage(
        id=12,
        project_id=project.id,
        prompt_id=prompt.id,
        version=1,
        source_run_ids_json=dumps([101, 102]),
        package_payload_json=dumps({
            "metrics": [
                {"metric_name": "brand_mention_rate", "numerator": 0, "denominator": 2, "value": 0},
            ],
        }),
    )
    action = copy.deepcopy(_action())
    action.update({
        "route": "EVIDENCE",
        "gap_type": "EVIDENCE_GAP",
        "strategy_basis": "ANSWER_DECISION_EVIDENCE_GAP",
        "decision_reason_ids": ["reason:可以自动生成加密短链"],
        "decision_reason_event_ids": [1, 2],
        "evidence_gap_reason": "NO_ELIGIBLE_SUPPORT_WITH_REQUIRED_LINEAGE",
        "evidence_gap_cause": "NO_ELIGIBLE_SUPPORT_WITH_REQUIRED_LINEAGE",
        "eligible_support_count": 0,
        "eligible_contradiction_ids": [],
        "benchmark_evidence_ids": [],
        "benchmark_source": {
            "source_document_id": None,
            "title": "当前答案决策理由",
            "platform": "ANSWER",
            "platform_label": "AI 答案",
            "benchmark_tier": "NO_ELIGIBLE_BENCHMARK",
            "decision_support_level": "ANSWER_DECISION_REASON_WITHOUT_ELIGIBLE_SOURCE_SUPPORT",
            "supporting_alignment_ids": [],
        },
        "citation_value_summary": {
            "class": "ANSWER_DECISION_EVIDENCE_GAP",
            "label": "答案决策理由证据缺口",
        },
    })
    for item in action["gap_items"]:
        item["benchmark_evidence_ids"] = []
        item["benchmark_tier"] = "NO_ELIGIBLE_BENCHMARK"
        item["lineage_source"] = "ANSWER_DECISION_REASON_WITH_PRODUCT_TRUTH"

    payload = _strategy_payload_from_vertical_action(project, prompt, package, action, {})
    candidate = OptimizationStrategyCandidate(
        evidence_package_id=package.id,
        source_package_id=package.id,
        model=optimization_service.CURRENT_STEP7_MODEL,
        prompt_version=optimization_service.VERTICAL_SLICE_VERSION,
        structured_payload_json=dumps(payload),
        review_status="PENDING_REVIEW",
    )

    eligibility = current_step7_candidate_eligibility(candidate, package)

    assert eligibility["eligible"] is True
    assert eligibility["ineligibility_reasons"] == []
    assert payload["asset_direction"]["asset_operation"] == "CREATE_NEW"
    assert payload["benchmark_source"]["benchmark_tier"] == "NO_ELIGIBLE_BENCHMARK"
    assert "不包含 Benchmark Evidence" in payload["why_candidate"]


def test_answer_decision_gap_is_blocked_by_eligible_contradiction():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        project = _project()
        prompt = Prompt(id=19, project_id=project.id, prompt_text="抖音跳转微信", title="抖音跳转微信")
        package = OptimizationEvidencePackage(
            id=12,
            project_id=project.id,
            prompt_id=prompt.id,
            source_run_ids_json=dumps([101]),
            package_payload_json=dumps({"metrics": []}),
        )
        event = RecommendationEvent(
            project_id=project.id,
            prompt_id=prompt.id,
            run_id=101,
            entity_text="商加加",
            speech_act="RECOMMEND",
            recommendation_strength="STRONG",
            polarity="POSITIVE",
            reasons_json=dumps([{"normalized_reason": "可以自动生成加密短链"}]),
            review_status="HUMAN_CONFIRMED",
        )
        db.add_all([
            project,
            prompt,
            package,
            TargetBrandCapabilityTruth(
                project_id=project.id,
                capability_key="短链生成",
                capability_label="短链生成",
                product_truth_status="SUPPORTED",
            ),
            event,
        ])
        db.commit()
        contradiction = EvidenceAlignment(
            project_id=project.id,
            prompt_id=prompt.id,
            run_id=101,
            recommendation_event_id=event.id,
            recommendation_reason_id="reason:可以自动生成加密短链",
            source_document_id=999,
            source_claim_id=999,
            relation="CONTRADICTS",
            review_status="HUMAN_CONFIRMED",
            machine_payload_json=dumps({"semantic_reason_key": "可以自动生成加密短链|ENTITY_SPECIFIC|商加加"}),
        )
        db.add(contradiction)
        db.commit()

        with patch.object(
            optimization_service,
            "eligible_evidence_alignments_for_v1",
            side_effect=lambda _db, rows, **_kwargs: (list(rows), {}),
        ):
            action = _current_answer_decision_evidence_gap_action(
                db,
                project,
                prompt,
                package,
                [101],
                channel_aggregation=[],
            )

        assert action is None
    finally:
        db.close()


def test_supersede_marks_same_context_stale_user_candidate_but_not_legacy():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        package = OptimizationEvidencePackage(
            id=12,
            project_id=3,
            prompt_id=19,
            version=8,
            source_run_ids_json=dumps([101]),
            package_payload_json=dumps({"metrics": []}),
        )
        current_context = {
            "prompt_id": 19,
            "evidence_package_id": 12,
            "evidence_package_version": 8,
            "analysis_version": optimization_service.VERTICAL_SLICE_VERSION,
            "candidate_origin": optimization_service.CURRENT_STEP7_CANDIDATE_ORIGIN,
        }
        stale_user_candidate = OptimizationStrategyCandidate(
            project_id=3,
            evidence_package_id=12,
            model=optimization_service.CURRENT_STEP7_MODEL,
            prompt_version=optimization_service.VERTICAL_SLICE_VERSION,
            structured_payload_json=dumps({
                "candidate_origin": optimization_service.CURRENT_STEP7_CANDIDATE_ORIGIN,
                "strategy_context": current_context,
            }),
            review_status="PENDING_REVIEW",
        )
        invalid_channel_candidate = OptimizationStrategyCandidate(
            project_id=3,
            evidence_package_id=12,
            model=optimization_service.CURRENT_STEP7_MODEL,
            prompt_version=optimization_service.VERTICAL_SLICE_VERSION,
            structured_payload_json=dumps({
                "candidate_origin": optimization_service.CURRENT_STEP7_CANDIDATE_ORIGIN,
                "strategy_context": current_context,
                "strategy_channel_resolver": {"version": "strategy_channel_resolver.v1"},
                "planned_channels": [{
                    "channel": "OFFICIAL_SITE",
                    "intervention_priority": "PRIMARY",
                    "decision_citation_run_count": 0,
                    "brand_asset_basis": {"has_relevant_asset_snapshot": False},
                }],
            }),
            review_status="PENDING_REVIEW",
        )
        legacy_candidate = OptimizationStrategyCandidate(
            project_id=3,
            evidence_package_id=12,
            model="local-rule-v1",
            prompt_version="strategy_prompt.v2",
            structured_payload_json=dumps({}),
            review_status="PENDING_REVIEW",
        )
        db.add_all([package, stale_user_candidate, invalid_channel_candidate, legacy_candidate])
        db.commit()

        _supersede_current_pending_step7_candidates(db, package, "tester")
        db.flush()

        assert stale_user_candidate.review_status == "DEFERRED"
        assert '"semantic": "SUPERSEDED"' in stale_user_candidate.review_note
        assert '"reason": "NEW_CURRENT_STEP7_GENERATION"' in stale_user_candidate.review_note
        assert invalid_channel_candidate.review_status == "DEFERRED"
        assert '"reason": "CHANNEL_RESOLUTION_INVALID_DUE_TO_SOURCE_MAPPING_FAILURE"' in invalid_channel_candidate.review_note
        assert legacy_candidate.review_status == "PENDING_REVIEW"
    finally:
        db.close()


def test_pr4b_validator_failure_does_not_supersede_current_candidate(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        project = _project()
        prompt = _prompt()
        package = _package()
        package.version = 1
        current_payload = {
            "candidate_origin": optimization_service.CURRENT_STEP7_CANDIDATE_ORIGIN,
            "strategy_context": {
                "prompt_id": prompt.id,
                "evidence_package_id": package.id,
                "evidence_package_version": package.version,
                "analysis_version": optimization_service.VERTICAL_SLICE_VERSION,
            },
        }
        candidate = OptimizationStrategyCandidate(
            project_id=project.id,
            evidence_package_id=package.id,
            model=optimization_service.CURRENT_STEP7_MODEL,
            prompt_version=optimization_service.VERTICAL_SLICE_VERSION,
            structured_payload_json=dumps(current_payload),
            review_status="PENDING_REVIEW",
        )
        db.add_all([project, prompt, package, candidate])
        db.commit()
        original_payload = candidate.structured_payload_json
        monkeypatch.setattr(
            optimization_service,
            "_strategy_payload_from_vertical_action",
            lambda *args, **kwargs: {"source_action_key": "action-1"},
        )

        def reject_synthesis(*args, **kwargs):
            raise HTTPException(status_code=422, detail="validator rejected")

        monkeypatch.setattr(optimization_service, "_attach_constraint_first_strategy_synthesis", reject_synthesis)

        with pytest.raises(HTTPException):
            optimization_service._create_step7_strategy_candidates_from_actions(
                db,
                project=project,
                prompt=prompt,
                package=package,
                actions=[{"action_key": "action-1", "route": "CONTENT"}],
                payload={
                    "candidate_origin": optimization_service.CURRENT_STEP7_CANDIDATE_ORIGIN,
                    "use_constraint_first_strategy_synthesis_v1": True,
                },
            )

        db.refresh(candidate)
        assert candidate.review_status == "PENDING_REVIEW"
        assert candidate.structured_payload_json == original_payload
    finally:
        db.close()


def test_pr4b_production_payload_persists_shared_validated_synthesis():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        project = _project()
        prompt = _prompt()
        package = _package()
        package.version = 1
        truths = [
            TargetBrandCapabilityTruth(
                id=truth_id,
                project_id=project.id,
                capability_key=label,
                capability_label=label,
                product_truth_status="SUPPORTED",
            )
            for truth_id, label in (
                (701, "点击统计"),
                (702, "自定义分享标题"),
                (703, "营销场景"),
            )
        ]
        db.add_all([project, prompt, package, *truths])
        db.commit()
        base_payload = _strategy_payload_from_vertical_action(project, prompt, package, _action(), {})

        result = optimization_service._attach_constraint_first_strategy_synthesis(
            db,
            project,
            prompt,
            package,
            base_payload,
        )

        synthesis = result["strategy_synthesis"]
        assert synthesis["strategy_synthesis_contract_version"] == "STRATEGY_SYNTHESIS_V1"
        assert synthesis["synthesis_mode"] == "DETERMINISTIC"
        assert synthesis["external_llm_calls"] == 0
        assert synthesis["structural_prompt_version"] is None
        assert synthesis["model"] is None
        assert synthesis["validator_status"] == "VALID"
        assert all(item["status"] == "VALID" for item in synthesis["validators"].values())
        assert len(result["decision_reasons"]) == 3
        assert len(result["intervention_themes"]) == 3
        assert [item["coverage"] for item in result["intervention_themes"]] == ["6/6", "6/6", "2/6"]
        assert result["strategy_portfolio"]["primary_interventions"][0]["channel_key"] == "OFFICIAL_SITE"
        assert result["strategy_decision_view"]
        assert result["strategy_audit_view"]["system_fixed"]["resolver_roles"]
        from app.modules.optimization.strategy_synthesis_shadow import (
            build_strategy_synthesis_context_from_payload,
            run_strategy_synthesis_core,
        )
        replay_context = build_strategy_synthesis_context_from_payload(
            db,
            project,
            prompt,
            package,
            result,
            input_scope_id=synthesis["input_scope_id"],
        )
        replay = run_strategy_synthesis_core(replay_context, use_llm=False)
        assert replay["version_audit"]["output_hash"] == synthesis["structural_output_hash"]
        assert replay["structural_synthesis"]["validated_structure"]["themes"] == result["intervention_themes"]
    finally:
        db.close()


def test_pr4b_valid_synthesis_supersedes_history_without_mutating_payload(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        project = _project()
        prompt = _prompt()
        package = _package()
        package.version = 1
        old_payload = {
            "candidate_origin": optimization_service.CURRENT_STEP7_CANDIDATE_ORIGIN,
            "strategy_context": {
                "prompt_id": prompt.id,
                "evidence_package_id": package.id,
                "evidence_package_version": package.version,
                "analysis_version": optimization_service.VERTICAL_SLICE_VERSION,
            },
        }
        candidate = OptimizationStrategyCandidate(
            project_id=project.id,
            evidence_package_id=package.id,
            model=optimization_service.CURRENT_STEP7_MODEL,
            prompt_version=optimization_service.VERTICAL_SLICE_VERSION,
            structured_payload_json=dumps(old_payload),
            review_status="PENDING_REVIEW",
        )
        db.add_all([project, prompt, package, candidate])
        db.commit()
        original_payload = candidate.structured_payload_json
        monkeypatch.setattr(
            optimization_service,
            "_strategy_payload_from_vertical_action",
            lambda *args, **kwargs: {"source_action_key": "action-1"},
        )
        monkeypatch.setattr(
            optimization_service,
            "_attach_constraint_first_strategy_synthesis",
            lambda *args, **kwargs: {
                "source_action_key": "action-1",
                "strategy_synthesis": {"validator_status": "VALID"},
            },
        )
        monkeypatch.setattr(optimization_service, "_upsert_workflow_confirmation", lambda *args, **kwargs: None)
        monkeypatch.setattr(optimization_service, "_create_vertical_strategy_candidate", lambda *args, **kwargs: object())
        monkeypatch.setattr(
            optimization_service,
            "strategy_candidate_to_read",
            lambda *args, **kwargs: {"id": 999, "review_status": "PENDING_REVIEW"},
        )

        optimization_service._create_step7_strategy_candidates_from_actions(
            db,
            project=project,
            prompt=prompt,
            package=package,
            actions=[{"action_key": "action-1", "route": "CONTENT"}],
            payload={
                "candidate_origin": optimization_service.CURRENT_STEP7_CANDIDATE_ORIGIN,
                "use_constraint_first_strategy_synthesis_v1": True,
            },
        )
        db.flush()

        assert candidate.review_status == "DEFERRED"
        assert "SUPERSEDED_BY_VALIDATED_STRATEGY_SYNTHESIS_V1" in candidate.review_note
        assert candidate.structured_payload_json == original_payload
    finally:
        db.close()


def test_pr4_b1_valid_synthesis_uses_decision_view_without_mutating_candidate_payload():
    validators = {
        key: {"status": "VALID", "errors": []}
        for key in (
            "structural",
            "provenance",
            "business_rules",
            "theme_coverage",
            "theme_title",
            "unsupported_claim",
        )
    }
    themes = [
        {
            "theme_key": "T1",
            "title": "短链生成",
            "priority": "P1",
            "reason_ids": ["reason:1", "reason:2"],
            "original_reasons": ["自动生成加密短链", "一键生成跳转短链"],
            "coverage": "13/15",
        },
        {
            "theme_key": "T2",
            "title": "加粉数据回传优化投放效果",
            "priority": "P1",
            "reason_ids": ["reason:3", "reason:4"],
            "original_reasons": ["加粉数据回传", "优化投放效果"],
            "coverage": "13/15",
        },
        {
            "theme_key": "T3",
            "title": "抖音跳转微信",
            "priority": "P2",
            "reason_ids": ["reason:5"],
            "original_reasons": ["抖音跳转微信"],
            "coverage": "1/15",
        },
    ]

    def channel(channel_key: str, label: str, role: str, reason_ids: list[str]) -> dict:
        return {
            "channel_key": channel_key,
            "channel_label": label,
            "frozen_role": role,
            "execution_priority": "P1" if role in {"PRIMARY", "TEST"} else "P2",
            "decision_reason_ids": reason_ids,
            "decision_reason_texts": ["自动生成加密短链"],
            "rationale_path": "PATH_A",
            "supporting_signal_ids": [f"channel:{channel_key}"],
        }

    payload = {
        "strategy_basis": "ANSWER_DECISION_EVIDENCE_GAP",
        "strategy_synthesis": {
            "strategy_synthesis_contract_version": "STRATEGY_SYNTHESIS_V1",
            "synthesis_mode": "DETERMINISTIC",
            "validator_status": "VALID",
            "validators": validators,
        },
        "strategy_decision_view": {
            "current_ai_decision_opportunity": {"text": "旧审计表达", "provenance_ids": ["reason:1"]},
            "expected_decision_change": {"text": "观察候选、引用或推荐理由是否变化。", "provenance_ids": ["reason:1"]},
            "success_metrics": [{"text": "brand_mention_rate", "provenance_ids": ["metric:brand_mention_rate"]}],
            "observe_summary": {"text": "保持 OBSERVE。", "provenance_ids": ["channel:OTHER"]},
        },
        "strategy_audit_view": {
            "system_fixed": {
                "strategy_basis": "ANSWER_DECISION_EVIDENCE_GAP",
                "benchmark_tier": "NO_ELIGIBLE_BENCHMARK",
                "resolver_roles": {"OFFICIAL_SITE": "PRIMARY"},
            },
        },
        "intervention_themes": themes,
        "strategy_portfolio": {
            "primary_interventions": [channel("OFFICIAL_SITE", "官网", "PRIMARY", ["reason:1", "reason:2"])],
            "secondary_interventions": [],
            "priority_tests": [
                channel("BAIJIAHAO", "百家号", "TEST", ["reason:1"]),
                channel("ZHIHU", "知乎", "TEST", ["reason:3"]),
            ],
            "deferred_tests": [
                channel("BILIBILI", "B站", "TEST", ["reason:2"]),
                channel("SOHU", "搜狐", "TEST", ["reason:4"]),
            ],
            "observe_channels": [channel(f"OBSERVE_{index}", f"观察 {index}", "OBSERVE", []) for index in range(43)],
            "selected_success_metrics": ["brand_mention_rate"],
        },
    }
    serialized_before = dumps(payload)
    candidate = OptimizationStrategyCandidate(
        id=57,
        project_id=3,
        evidence_package_id=12,
        structured_payload_json=serialized_before,
        model=optimization_service.CURRENT_STEP7_MODEL,
        prompt_version=optimization_service.VERTICAL_SLICE_VERSION,
        review_status="PENDING_REVIEW",
    )

    result = optimization_service.strategy_candidate_to_read(candidate)
    decision = result["strategy_decision_view"]
    portfolio = decision["portfolio"]

    assert result["strategy_view_mode"] == "SYNTHESIS_DECISION_VIEW"
    assert len(decision["themes"]) == 3
    assert [item["coverage"] for item in decision["themes"]] == ["13/15", "13/15", "1/15"]
    assert [item["channel_key"] for item in portfolio["primary_interventions"]] == ["OFFICIAL_SITE"]
    assert [item["channel_key"] for item in portfolio["priority_tests"]] == ["BAIJIAHAO", "ZHIHU"]
    assert [item["channel_key"] for item in portfolio["deferred_tests"]] == ["BILIBILI", "SOHU"]
    assert len(portfolio["observe_channels"]) == 43
    assert [item["channel_key"] for item in decision["execution_channel_options"]] == [
        "OFFICIAL_SITE",
        "BAIJIAHAO",
        "ZHIHU",
    ]
    assert all("frozen_role" not in item and "rationale_path" not in item for item in portfolio["priority_tests"])
    assert "OBSERVE" not in decision["observe_summary"]["text"]
    assert result["strategy_audit_view"]["system_fixed"]["benchmark_tier"] == "NO_ELIGIBLE_BENCHMARK"
    assert candidate.structured_payload_json == serialized_before


def test_pr4_b1_invalid_or_missing_synthesis_keeps_legacy_view():
    payload = {
        "target_decision_change": "保留旧策略展示",
        "strategy_synthesis": {
            "strategy_synthesis_contract_version": "STRATEGY_SYNTHESIS_V1",
            "validator_status": "INVALID_SYNTHESIS",
        },
    }
    candidate = OptimizationStrategyCandidate(
        id=14,
        project_id=3,
        evidence_package_id=12,
        structured_payload_json=dumps(payload),
        model="legacy",
        prompt_version="legacy",
        review_status="PENDING_REVIEW",
    )

    result = optimization_service.strategy_candidate_to_read(candidate)

    assert result["strategy_view_mode"] == "LEGACY"
    assert result["strategy_decision_view"] == {}
    assert result["strategy_audit_view"] == {}
    assert result["structured_payload"]["target_decision_change"] == "保留旧策略展示"
