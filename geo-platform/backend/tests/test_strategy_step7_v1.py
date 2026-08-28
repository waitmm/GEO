from __future__ import annotations

from app.models import OptimizationEvidencePackage, Project, Prompt
from app.modules.optimization.service import _strategy_payload_from_vertical_action
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


def test_step7_required_signals_and_non_goals_do_not_choose_execution_channel():
    payload = _strategy_payload_from_vertical_action(_project(), _prompt(), _package(), _action(), {})

    signal_text = " ".join(item["signal"] for item in payload["required_signals"])
    requirement_text = " ".join(item["evidence_requirement"] for item in payload["required_signals"])
    non_goals = " ".join(payload["non_goals"])

    assert "爱短链 支持 点击统计" in signal_text
    assert "目标品牌自己的真实能力表达" in requirement_text
    assert "不因为核心对标来源来自「知乎」就默认去该平台发布" in non_goals
    assert "不在第 7 步选择发布平台" in non_goals
    assert "页面区块" not in signal_text + requirement_text
    assert "FAQ" not in signal_text + requirement_text


def test_step7_execution_fields_remain_unresolved_and_step8_compatible():
    payload = _strategy_payload_from_vertical_action(_project(), _prompt(), _package(), _action(), {})

    assert payload["target_platform"] == "UNRESOLVED"
    assert payload["target_asset"] == "UNRESOLVED"
    assert payload["target_content_type"] == "UNRESOLVED"
    assert payload["intervention_type"] == "UNRESOLVED"
    assert "Step 8" in payload["recommended_action_boundary"]
    assert payload["changed_features"]
    assert payload["required_sections"] == ["直接回答 Prompt", "能力事实说明", "适用场景"]
    assert payload["target_metric"] == "brand_mention_rate"
    assert payload["benchmark_channel_boundary"].startswith("Benchmark 来源平台不能自动成为")
