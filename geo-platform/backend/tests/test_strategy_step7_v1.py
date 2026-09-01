from __future__ import annotations

import copy

from app.models import OptimizationEvidencePackage, Project, Prompt
from app.modules.optimization.service import (
    _channel_aggregation_for_rows,
    _citation_decision_values_from_benchmark_items,
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
