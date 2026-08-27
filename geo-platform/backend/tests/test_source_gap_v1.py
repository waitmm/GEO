from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Organization, Project, TargetBrandCapabilityTruth
from app.models import (
    AnswerDecisionBinding,
    AnswerUnit,
    BrowserMonitorRun,
    BrowserMonitorTask,
    EvidenceAlignment,
    OptimizationAction,
    OptimizationEvidencePackage,
    OptimizationExperiment,
    OptimizationIssue,
    OptimizationStrategyCandidate,
    PageSnapshot,
    Prompt,
    RecommendationEvent,
    ReferenceSource,
    RetrievalCandidate,
    SourceClaim,
    SourceDocument,
    SourceQuality,
)
from app.modules.optimization.passage_retrieval import ANSWER_BINDING_REASON_SOURCE, FORMAL_V1_1_INPUT_VERSION
from app.modules.optimization.service import (
    _attach_priority_action_routes,
    _attach_source_gap_analysis,
    _benchmark_evidence_text,
    _match_product_truths,
    _source_analysis_sort_key,
    _source_gap_for_benchmark,
    _suggested_capability_label_for_benchmark,
    analyze_experiment,
    citation_decision_vertical_slice,
    confirm_citation_decision_vertical_slice,
    confirm_strategy_execution_plan,
    create_evidence_package,
    decision_stability_for_package,
    review_strategy_candidate,
    strategy_to_experiment_plan,
)
from app.modules.optimization.schemas import EvidencePackageCreate
from app.services.serialization import dumps, loads


def _truth(status: str, label: str = "批量短链生成", truth_id: int = 1) -> TargetBrandCapabilityTruth:
    return TargetBrandCapabilityTruth(
        id=truth_id,
        project_id=3,
        capability_key=label,
        capability_label=label,
        product_truth_status=status,
    )


def _benchmark(label: str = "批量短链生成") -> list[dict]:
    return [{
        "alignment_id": 101,
        "claim_text": f"{label} 有客户案例和数据证明，已服务 20 家客户，成功率 99%。",
        "source_span": f"案例：{label} 服务 20 家客户，成功率 99%。",
        "claim_object": label,
        "claim_predicate": "支持",
        "event_answer_span": f"推荐理由是 {label} 有真实案例。",
        "event_reasons": [{"normalized_reason": f"{label} 有真实案例和数据"}],
    }]


def _asset(text: str, status: str = "AVAILABLE") -> dict:
    return {
        "status": status,
        "snapshot_id": 9 if status == "AVAILABLE" else None,
        "text": text,
        "reason": "fixture asset",
    }


def test_source_gap_content_gap_when_truth_true_and_asset_missing():
    payload = _source_gap_for_benchmark(
        _benchmark(),
        [_truth("SUPPORTED")],
        _asset("爱短链官网介绍品牌服务和联系方式。"),
    )

    assert payload["source_gap_type"] == "CONTENT_GAP"
    assert payload["source_gap_precondition"] == "READY"
    assert payload["existing_asset_coverage"] == "MISSING"


def test_source_gap_evidence_gap_when_asset_claims_but_lacks_proof():
    payload = _source_gap_for_benchmark(
        _benchmark(),
        [_truth("SUPPORTED")],
        _asset("爱短链支持批量短链生成，适合日常推广。"),
    )

    assert payload["source_gap_type"] == "EVIDENCE_GAP"
    assert payload["existing_asset_coverage"] == "CLAIM_ONLY"


def test_source_gap_product_gap_when_truth_false():
    payload = _source_gap_for_benchmark(
        _benchmark(),
        [_truth("NOT_SUPPORTED")],
        _asset("爱短链官网介绍品牌服务和联系方式。"),
    )

    assert payload["source_gap_type"] == "PRODUCT_GAP"
    assert payload["matched_product_truth_status"] == "FALSE"
    assert "高价值产品发现" in payload["source_gap_basis"][0]


def test_source_gap_unknown_when_product_truth_unknown():
    payload = _source_gap_for_benchmark(
        _benchmark(),
        [_truth("UNKNOWN")],
        _asset("爱短链支持批量短链生成，案例显示已服务 20 家客户，成功率 99%。"),
    )

    assert payload["source_gap_type"] == "UNKNOWN"
    assert payload["source_gap_precondition"] == "PRODUCT_TRUTH_UNKNOWN"


def test_source_gap_no_gap_when_truth_and_asset_cover_key_evidence():
    payload = _source_gap_for_benchmark(
        _benchmark(),
        [_truth("SUPPORTED")],
        _asset("爱短链支持批量短链生成，案例显示已服务 20 家客户，成功率 99%。"),
    )

    assert payload["source_gap_type"] == "NO_GAP"
    assert payload["existing_asset_coverage"] == "SUFFICIENT"


def test_capability_gap_stops_at_product_truth_before_asset_retrieval_or_adoption():
    payload = _source_gap_for_benchmark(
        [{
            **_benchmark("点击统计")[0],
            "event_entity": "小码短链接",
            "answer_unit_id": 101,
            "answer_unit_text": "小码短链接自带点击统计",
        }],
        [_truth("SUPPORTED", "短链生成")],
        _asset("爱短链支持点击统计，案例显示已服务 20 家客户。"),
        retrievals=[],
        references=[],
    )

    assert payload["source_gap_type"] == "UNKNOWN"
    assert payload["capability_gap_layer"] == "PRODUCT_TRUTH"
    assert payload["retrieval_candidate_context"]["status"] == "NOT_RETRIEVED"


def test_capability_gap_stops_at_relevant_asset_expression_before_retrieval():
    payload = _source_gap_for_benchmark(
        _benchmark("点击统计"),
        [_truth("SUPPORTED", "点击统计")],
        _asset("爱短链官网介绍品牌服务和联系方式。"),
        retrievals=[
            RetrievalCandidate(id=1, run_id=101, rank=1, title="爱短链点击统计", url="https://www.aifabu.com", domain="aifabu.com")
        ],
        references=[
            ReferenceSource(id=1, run_id=101, display_title="爱短链点击统计", url="https://www.aifabu.com", domain="aifabu.com")
        ],
    )

    assert payload["source_gap_type"] == "CONTENT_GAP"
    assert payload["capability_gap_layer"] == "RELEVANT_ASSET_EXPRESSION"


def test_capability_gap_uses_only_valid_retrieval_for_discoverability():
    payload = _source_gap_for_benchmark(
        [{
            **_benchmark("点击统计")[0],
            "observed_run_ids": [101],
        }],
        [_truth("SUPPORTED", "点击统计")],
        _asset("爱短链支持点击统计，案例显示服务 20 家客户，成功率 99%。"),
        project=Project(id=3, organization_id=1, name="爱短链", brand_name="爱短链", website_url="https://www.aifabu.com"),
        retrievals=[
            RetrievalCandidate(id=1, run_id=999, rank=1, title="爱短链点击统计", url="https://www.aifabu.com", domain="aifabu.com"),
            RetrievalCandidate(id=2, run_id=101, rank=1, title="", url="", domain=""),
        ],
        references=[],
    )

    assert payload["source_gap_type"] == "DISCOVERABILITY_GAP"
    assert payload["capability_gap_layer"] == "RETRIEVAL_CANDIDATE"
    assert payload["retrieval_candidate_context"]["valid_retrieval_count"] == 0


def test_capability_gap_retrieved_but_not_adopted_is_evidence_gap():
    payload = _source_gap_for_benchmark(
        [{
            **_benchmark("点击统计")[0],
            "observed_run_ids": [101],
        }],
        [_truth("SUPPORTED", "点击统计")],
        _asset("爱短链支持点击统计，案例显示服务 20 家客户，成功率 99%。"),
        project=Project(id=3, organization_id=1, name="爱短链", brand_name="爱短链", website_url="https://www.aifabu.com"),
        retrievals=[
            RetrievalCandidate(id=1, run_id=101, rank=1, title="爱短链点击统计", url="https://www.aifabu.com", domain="aifabu.com")
        ],
        references=[],
    )

    assert payload["source_gap_type"] == "EVIDENCE_GAP"
    assert payload["source_gap_precondition"] == "EVIDENCE_ADOPTION_MISSING"
    assert payload["capability_gap_layer"] == "EVIDENCE_ADOPTION"


def test_capability_gap_no_gap_requires_retrieval_and_adoption_context():
    payload = _source_gap_for_benchmark(
        [{
            **_benchmark("点击统计")[0],
            "observed_run_ids": [101],
        }],
        [_truth("SUPPORTED", "点击统计")],
        _asset("爱短链支持点击统计，案例显示服务 20 家客户，成功率 99%。"),
        project=Project(id=3, organization_id=1, name="爱短链", brand_name="爱短链", website_url="https://www.aifabu.com"),
        retrievals=[
            RetrievalCandidate(id=1, run_id=101, rank=1, title="爱短链点击统计", url="https://www.aifabu.com", domain="aifabu.com")
        ],
        references=[
            ReferenceSource(id=1, run_id=101, display_title="爱短链点击统计", url="https://www.aifabu.com", domain="aifabu.com")
        ],
    )

    assert payload["source_gap_type"] == "NO_GAP"
    assert payload["capability_gap_layer"] == "NONE"
    assert payload["capability_gap_diagnosis"]["retrieval_candidate_context"]["retrieved"] is True
    assert payload["capability_gap_diagnosis"]["evidence_adoption_context"]["adopted"] is True


def test_source_gap_requires_capability_level_product_truth_for_answer_unit():
    payload = _source_gap_for_benchmark(
        [{
            **_benchmark("点击统计")[0],
            "event_entity": "小码短链接",
            "answer_unit_id": 101,
            "answer_unit_text": "小码短链接自带点击统计",
        }],
        [_truth("SUPPORTED", "短链生成")],
        _asset("爱短链支持短链生成。"),
    )

    assert payload["source_gap_type"] == "UNKNOWN"
    assert payload["source_gap_precondition"] == "PRODUCT_TRUTH_UNKNOWN"
    assert payload["matched_product_truth_ids"] == []
    assert payload["unmatched_capability_truth_targets"] == ["点击统计"]


def test_source_gap_accepts_exact_capability_level_product_truth_for_answer_unit():
    payload = _source_gap_for_benchmark(
        [{
            **_benchmark("点击统计")[0],
            "event_entity": "小码短链接",
            "answer_unit_id": 101,
            "answer_unit_text": "小码短链接自带点击统计",
        }],
        [_truth("SUPPORTED", "点击统计")],
        _asset("爱短链官网介绍品牌服务。"),
    )

    assert payload["source_gap_type"] == "CONTENT_GAP"
    assert payload["matched_product_truth_ids"] == [1]


def test_benchmark_suggests_compact_capability_label_not_full_title():
    label = _suggested_capability_label_for_benchmark([{
        "alignment_id": 101,
        "claim_text": "商加加支持抖音跳转微信合规又高效，完整跳转路径搭建清晰。",
        "source_span": "抖音跳转微信合规又高效，完整跳转路径搭建教程2026版。",
        "claim_subject": "商加加",
        "claim_object": "",
        "claim_predicate": "支持",
        "event_entity": "商加加",
        "event_answer_span": "推荐商加加，因为它支持抖音跳转微信。",
        "event_reasons": [{"normalized_reason": "抖音跳转微信合规高效完整跳转路径搭建"}],
    }])

    assert "商加加" not in label
    assert "教程" not in label
    assert "2026" not in label
    assert "抖音跳转微信" in label


def test_product_truth_matching_accepts_compact_capability_overlap():
    matches = _match_product_truths(
        "推荐理由是抖音跳转微信合规又高效，完整跳转路径搭建清晰。",
        [_truth("SUPPORTED", "抖音跳转微信完整路径搭建")],
    )

    assert matches


def test_benchmark_text_keeps_only_relevant_event_reasons():
    items = [{
        "alignment_id": 101,
        "claim_text": "商加加支持将加粉成功的事件回传至巨量引擎。",
        "source_span": "它还可以支持将加粉成功的事件回传至巨量引擎。",
        "claim_subject": "商加加",
        "claim_object": "加粉成功的事件至巨量引擎",
        "claim_predicate": "支持回传",
        "event_entity": "商加加",
        "event_answer_span": "可通过商加加外链等第三方工具",
        "event_reasons": [
            {"normalized_reason": "可以自动生成加密短链"},
            {"normalized_reason": "可以规避平台拦截"},
            {"normalized_reason": "支持加粉数据回传优化投放效果"},
        ],
    }]

    text = _benchmark_evidence_text(items)
    label = _suggested_capability_label_for_benchmark(items)

    assert "自动生成加密短链" not in text
    assert "规避平台拦截" not in text
    assert "加粉数据回传优化投放效果" in text
    assert label == "加粉数据回传优化投放效果"
    assert not _match_product_truths(text, [_truth("SUPPORTED", "短链生成")])


def test_capability_label_keeps_platform_blocking_reason_for_risk_control_claim():
    items = [{
        "alignment_id": 102,
        "claim_text": "商加加系统生成的加密跳转链接能够避免因为进行导流而触发风控。",
        "source_span": "能够避免因为进行导流而触发风控。",
        "claim_subject": "商加加系统生成的加密跳转链接",
        "claim_object": "因为进行导流而触发风控",
        "claim_predicate": "能够避免",
        "event_entity": "商加加",
        "event_answer_span": "可通过商加加外链等第三方工具",
        "event_reasons": [
            {"normalized_reason": "可以自动生成加密短链"},
            {"normalized_reason": "可以规避平台拦截"},
        ],
    }]

    label = _suggested_capability_label_for_benchmark(items)

    assert "规避平台拦截" in label


def test_reference_only_source_does_not_enter_gap_analysis():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        project = Project(id=3, organization_id=1, name="爱短链品牌监测", brand_name="爱短链")
        db.add_all([Organization(id=1, name="测试组织"), project])
        db.commit()
        rows = _attach_source_gap_analysis(db, project, [{"benchmark_tier": "REFERENCE_ONLY"}])

        assert rows[0]["source_gap_type"] is None
        assert rows[0]["gap_analysis_status"] == "NOT_ELIGIBLE"
        assert rows[0]["source_gap_precondition"] == "NO_ELIGIBLE_BENCHMARK"
    finally:
        db.close()


def _priority_row(benchmark_tier: str, source_gap_type: str | None) -> dict:
    return {
        "benchmark_tier": benchmark_tier,
        "source_gap_type": source_gap_type,
        "source_gap_precondition": "READY" if source_gap_type else "NO_ELIGIBLE_BENCHMARK",
        "decision_support_level": "RECOMMENDATION_REASON",
        "citation_prominence_level": "HIGH",
    }


def test_priority_action_primary_content_gap():
    row = _attach_priority_action_routes([_priority_row("PRIMARY_BENCHMARK", "CONTENT_GAP")])[0]

    assert row["priority_level"] == "PRIORITY_HIGH"
    assert row["action_route"] == "CONTENT"


def test_priority_action_primary_evidence_gap():
    row = _attach_priority_action_routes([_priority_row("PRIMARY_BENCHMARK", "EVIDENCE_GAP")])[0]

    assert row["priority_level"] == "PRIORITY_HIGH"
    assert row["action_route"] == "EVIDENCE"


def test_priority_action_primary_product_gap():
    row = _attach_priority_action_routes([_priority_row("PRIMARY_BENCHMARK", "PRODUCT_GAP")])[0]

    assert row["priority_level"] == "PRIORITY_HIGH"
    assert row["action_route"] == "PRODUCT"


def test_priority_action_primary_no_gap():
    row = _attach_priority_action_routes([_priority_row("PRIMARY_BENCHMARK", "NO_GAP")])[0]

    assert row["priority_level"] == "NOT_PRIORITY"
    assert row["action_route"] == "NO_ACTION"


def test_priority_action_primary_unknown():
    row = _attach_priority_action_routes([_priority_row("PRIMARY_BENCHMARK", "UNKNOWN")])[0]

    assert row["priority_level"] == "UNRESOLVED"
    assert row["action_route"] == "UNRESOLVED"


def test_priority_action_secondary_content_gap():
    row = _attach_priority_action_routes([_priority_row("SECONDARY_BENCHMARK", "CONTENT_GAP")])[0]

    assert row["priority_level"] == "PRIORITY_MEDIUM"
    assert row["action_route"] == "CONTENT"


def test_priority_action_reference_only_not_priority_without_route():
    row = _attach_priority_action_routes([_priority_row("REFERENCE_ONLY", None)])[0]

    assert row["priority_level"] == "NOT_PRIORITY"
    assert row["action_route"] is None


def test_priority_action_not_evaluable_has_no_priority_or_route():
    row = _attach_priority_action_routes([_priority_row("NOT_EVALUABLE", None)])[0]

    assert row["priority_level"] is None
    assert row["action_route"] is None


def test_sort_prefers_priority_over_citation_prominence():
    high_priority_low_prominence = {
        "priority_level": "PRIORITY_HIGH",
        "decision_support_level": "CANDIDATE_OR_EVALUATION",
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
        "priority_level": "NOT_PRIORITY",
        "decision_support_level": "NONE",
        "benchmark_tier": "REFERENCE_ONLY",
        "citation_prominence_level": "HIGH",
        "cited": True,
        "answer_citation_rate": 1,
        "citation_occurrence_count": 99,
        "avg_reference_position": 1,
        "run_id": 2,
        "source_id": 2,
    }

    rows = sorted([reference_high_prominence, high_priority_low_prominence], key=_source_analysis_sort_key)

    assert rows[0] is high_priority_low_prominence


def _vertical_slice_fixture(db):
    project = Project(
        id=11,
        organization_id=1,
        name="爱短链品牌监测",
        brand_name="爱短链",
        brand_aliases_json=dumps(["aifabu"]),
        website_url="https://www.aifabu.com",
    )
    prompt = Prompt(id=43, project_id=11, prompt_text="短链工具推荐", title="短链工具推荐")
    task = BrowserMonitorTask(id=1, project_id=11, question_ids_json="[43]", status="completed")
    run = BrowserMonitorRun(
        id=101,
        task_id=1,
        project_id=11,
        prompt_id=43,
        status="success",
        original_query=prompt.prompt_text,
        answer_text="推荐 ToolX，因为它支持批量短链生成并有客户案例。",
        brand_mentioned=False,
        brand_recommendation_level=0,
        reference_complete=True,
        parsed_reference_count=1,
        ui_declared_count=1,
    )
    ref = ReferenceSource(
        id=201,
        run_id=101,
        reference_index=1,
        display_title="知乎短链工具推荐",
        url="https://www.zhihu.com/question/short-link",
        canonical_url="https://www.zhihu.com/question/short-link",
        domain="zhihu.com",
    )
    doc = SourceDocument(
        id=301,
        url=ref.url,
        canonical_url=ref.canonical_url,
        domain=ref.domain,
        fetch_status="success",
        title=ref.display_title,
        clean_text="ToolX 支持批量短链生成，案例显示服务 20 家客户，成功率 99%。",
    )
    quality = SourceQuality(
        id=401,
        source_document_id=301,
        content_quality_status="CONTENT_VALID",
        clean_text_hash="h1",
        extractor_version="test",
    )
    event = RecommendationEvent(
        id=501,
        project_id=11,
        prompt_id=43,
        run_id=101,
        answer_hash="answer-1",
        entity_text="ToolX",
        speech_act="RECOMMEND",
        recommendation_strength="STRONG",
        polarity="POSITIVE",
        answer_span="推荐 ToolX，因为它支持批量短链生成并有客户案例。",
        reasons_json=dumps([{"normalized_reason": "批量短链生成 有客户案例和数据"}]),
        review_status="MACHINE_GROUNDED",
    )
    unit = AnswerUnit(
        id=551,
        project_id=11,
        prompt_id=43,
        run_id=101,
        answer_claim_id=551,
        unit_text_original="ToolX 支持批量短链生成并有客户案例",
        unit_text_normalized="ToolX 支持批量短链生成并有客户案例",
        source_span="ToolX 支持批量短链生成并有客户案例",
        entity_hint="ToolX",
    )
    binding = AnswerDecisionBinding(
        id=561,
        project_id=11,
        prompt_id=43,
        run_id=101,
        recommendation_event_id=501,
        answer_unit_id=551,
        decision_role="SUPPORTING_REASON",
        binding_strength="MEDIUM",
        scope_type="SAME_PARAGRAPH",
        review_status="MACHINE_GROUNDED",
    )
    claim = SourceClaim(
        id=601,
        project_id=11,
        source_document_id=301,
        subject_entity="ToolX",
        normalized_claim="批量短链生成 有客户案例和数据，服务 20 家客户，成功率 99%。",
        predicate="支持",
        object_text="批量短链生成",
        source_span="案例显示服务 20 家客户，成功率 99%。",
        review_status="MACHINE_GROUNDED",
    )
    alignment = EvidenceAlignment(
        id=701,
        project_id=11,
        prompt_id=43,
        run_id=101,
        recommendation_event_id=501,
        recommendation_reason_id="answer_unit:551:binding:561",
        source_document_id=301,
        source_claim_id=601,
        relation="SUPPORTS",
        scope_relation="PASS",
        review_status="MACHINE_GROUNDED",
        machine_payload_json=dumps({
            "reason_source": ANSWER_BINDING_REASON_SOURCE,
            "formal_input_version": FORMAL_V1_1_INPUT_VERSION,
            "answer_unit_id": 551,
            "decision_binding_id": 561,
        }),
    )
    truth = TargetBrandCapabilityTruth(
        id=801,
        project_id=11,
        capability_key="批量短链生成",
        capability_label="批量短链生成",
        product_truth_status="SUPPORTED",
    )
    asset = PageSnapshot(
        id=901,
        project_id=11,
        target_url="https://www.aifabu.com",
        url="https://www.aifabu.com",
        final_url="https://www.aifabu.com",
        canonical_url="https://www.aifabu.com",
        capture_status="success",
        snapshot_type="PRE_RELEASE",
        raw_html="<html>爱短链官网</html>",
        title="爱短链",
        h1="爱短链",
        main_text="爱短链官网介绍品牌服务、短链接管理、推广落地页和联系方式，但尚未说明批量短链生成能力。",
    )
    db.add_all([
        Organization(id=1, name="测试组织"),
        project,
        prompt,
        task,
        run,
        ref,
        doc,
        quality,
        event,
        unit,
        binding,
        claim,
        alignment,
        truth,
        asset,
    ])
    db.commit()
    package = create_evidence_package(
        db,
        project.id,
        EvidencePackageCreate(prompt_id=prompt.id, run_ids=[run.id], target_page_urls=[]),
    )
    return project, prompt, package


def _vertical_slice_v1_1_only_fixture(db):
    project = Project(
        id=12,
        organization_id=1,
        name="爱短链品牌监测",
        brand_name="爱短链",
        website_url="https://www.aifabu.com",
    )
    prompt = Prompt(id=45, project_id=12, prompt_text="短链工具推荐", title="短链工具推荐")
    task = BrowserMonitorTask(id=2, project_id=12, question_ids_json="[45]", status="completed")
    run = BrowserMonitorRun(
        id=102,
        task_id=2,
        project_id=12,
        prompt_id=45,
        status="success",
        original_query=prompt.prompt_text,
        answer_text="推荐 ToolX，它自带点击统计。",
        reference_complete=True,
        parsed_reference_count=1,
        ui_declared_count=1,
    )
    ref = ReferenceSource(
        id=202,
        run_id=102,
        reference_index=1,
        display_title="知乎短链工具推荐",
        url="https://zhuanlan.zhihu.com/p/test",
        canonical_url="https://zhuanlan.zhihu.com/p/test",
        domain="zhuanlan.zhihu.com",
    )
    doc = SourceDocument(
        id=302,
        url=ref.url,
        canonical_url=ref.canonical_url,
        domain=ref.domain,
        fetch_status="success",
        title=ref.display_title,
        clean_text="ToolX 可以查看每个链接的访问量、点击次数等数据。",
    )
    quality = SourceQuality(
        id=402,
        source_document_id=302,
        content_quality_status="CONTENT_VALID",
        clean_text_hash="h2",
        extractor_version="test",
    )
    event = RecommendationEvent(
        id=502,
        project_id=12,
        prompt_id=45,
        run_id=102,
        answer_hash="answer-2",
        entity_text="ToolX",
        speech_act="RECOMMEND",
        recommendation_strength="STRONG",
        polarity="POSITIVE",
        answer_span="推荐 ToolX，它自带点击统计。",
        reasons_json=dumps([]),
        review_status="MACHINE_GROUNDED",
    )
    unit = AnswerUnit(
        id=602,
        shadow_run_id=1,
        project_id=12,
        prompt_id=45,
        run_id=102,
        answer_claim_id=1,
        unit_text_original="ToolX 自带点击统计",
        unit_text_normalized="ToolX 自带点击统计",
        source_span="ToolX 自带点击统计",
        entity_hint="ToolX",
    )
    binding = AnswerDecisionBinding(
        id=612,
        project_id=12,
        prompt_id=45,
        run_id=102,
        recommendation_event_id=502,
        answer_unit_id=602,
        decision_role="SUPPORTING_REASON",
        binding_strength="MEDIUM",
        scope_type="SAME_PARAGRAPH",
        review_status="MACHINE_GROUNDED",
    )
    claim = SourceClaim(
        id=603,
        project_id=12,
        source_document_id=302,
        subject_entity="ToolX",
        normalized_claim="ToolX 可以查看每个链接的访问量、点击次数等数据。",
        predicate="支持",
        object_text="点击统计",
        source_span="可以查看每个链接的访问量、点击次数等数据。",
        review_status="MACHINE_GROUNDED",
    )
    alignment = EvidenceAlignment(
        id=702,
        project_id=12,
        prompt_id=45,
        run_id=102,
        recommendation_event_id=502,
        recommendation_reason_id="answer_unit:602",
        source_document_id=302,
        source_claim_id=603,
        relation="SUPPORTS",
        scope_relation="PASS",
        review_status="MACHINE_GROUNDED",
        machine_payload_json=dumps({
            "reason_source": ANSWER_BINDING_REASON_SOURCE,
            "formal_input_version": FORMAL_V1_1_INPUT_VERSION,
            "answer_unit_id": 602,
            "decision_binding_id": 612,
            "observed_run_ids": [102],
            "run_coverage_count": 1,
            "run_coverage_denominator": 1,
        }),
    )
    truth = TargetBrandCapabilityTruth(
        id=802,
        project_id=12,
        capability_key="点击统计",
        capability_label="点击统计",
        product_truth_status="SUPPORTED",
    )
    asset = PageSnapshot(
        id=902,
        project_id=12,
        target_url="https://www.aifabu.com",
        url="https://www.aifabu.com",
        final_url="https://www.aifabu.com",
        canonical_url="https://www.aifabu.com",
        capture_status="success",
        snapshot_type="PRE_RELEASE",
        raw_html="<html>爱短链官网</html>",
        title="爱短链",
        h1="爱短链",
        main_text="爱短链官网介绍短链接管理、推广落地页、访问分析入口和品牌联系方式，暂未覆盖该对标能力。",
    )
    db.add_all([
        Organization(id=1, name="测试组织"),
        project,
        prompt,
        task,
        run,
        ref,
        doc,
        quality,
        event,
        unit,
        binding,
        claim,
        alignment,
        truth,
        asset,
    ])
    db.commit()
    package = create_evidence_package(
        db,
        project.id,
        EvidencePackageCreate(prompt_id=prompt.id, run_ids=[run.id], target_page_urls=[]),
    )
    return project, prompt, package


def test_vertical_slice_creates_pending_strategy_candidate_without_experiment():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        project, prompt, package = _vertical_slice_fixture(db)

        proposal = citation_decision_vertical_slice(db, project.id, prompt.id, package.id, use_answer_binding_v1_1=True)

        assert proposal["status"] == "READY_FOR_HUMAN_CONFIRM"
        assert proposal["summary"]["primary_benchmark_count"] == 1
        assert proposal["recommended_actions"][0]["route"] == "EVIDENCE"
        assert proposal["channel_opportunities"][0]["channel"] == "zhihu"

        action_count_before = db.query(OptimizationAction).count()
        experiment_count_before = db.query(OptimizationExperiment).count()
        confirmed = confirm_citation_decision_vertical_slice(
            db,
            project.id,
            prompt.id,
                {
                    "evidence_package_id": package.id,
                    "action_keys": [proposal["recommended_actions"][0]["action_key"]],
                    "reviewer": "human",
                    "create_experiments": True,
                    "use_answer_binding_v1_1": True,
                },
            )

        created = confirmed["created"][0]
        assert confirmed["status"] == "STRATEGY_CANDIDATES_CREATED"
        assert confirmed["intervention_plan"] is None
        assert created["strategy_candidate"]["review_status"] == "PENDING_REVIEW"
        assert created["strategy_candidate"]["effective_payload"] == {}
        assert created["strategy_candidate"]["effective_validation_status"] == "PENDING"
        assert created["strategy_candidate"]["experiment_id"] is None
        assert created["experiment_plan"] is None
        assert db.query(OptimizationAction).count() == action_count_before
        assert db.query(OptimizationExperiment).count() == experiment_count_before

        structured = created["strategy_candidate"]["structured_payload"]
        assert structured["gap_item_ids"]
        assert structured["target_capabilities"][0]["capability_label"]
        assert structured["target_capabilities"][0]["gap_item_id"] in structured["gap_item_ids"]
        assert structured["benchmark_evidence_ids"]
        assert structured["product_truth_refs"]["status"] == "TRUE"
        assert structured["target_platform"] == "UNRESOLVED"
        assert structured["benchmark_channel_boundary"].startswith("Benchmark 来源平台不能自动成为 Strategy 执行平台")

        with pytest.raises(Exception):
            strategy_to_experiment_plan(db, created["strategy_candidate"]["id"])

        reviewed = review_strategy_candidate(
            db,
            created["strategy_candidate"]["id"],
            type(
                "Payload",
                (),
                {
                    "review_status": "ACCEPTED_WITH_EDITS",
                    "reviewed_by": "human",
                    "review_note": "确认策略机制，不进入执行。",
                    "human_edited_payload": {"review_summary": "能力表达缺口成立"},
                },
            )(),
        )
        assert reviewed["review_status"] == "ACCEPTED_WITH_EDITS"
        assert reviewed["effective_payload"]["review_summary"] == "能力表达缺口成立"
        assert reviewed["effective_validation_status"] == "PENDING_HUMAN_CHANNEL_REVIEW"
        assert db.query(OptimizationAction).count() == action_count_before
        assert db.query(OptimizationExperiment).count() == experiment_count_before

        with pytest.raises(Exception):
            strategy_to_experiment_plan(db, created["strategy_candidate"]["id"])
    finally:
        db.close()


def test_step8_accepts_confirmed_strategy_pending_channel_review_and_freezes_snapshot():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        project, prompt, package = _vertical_slice_fixture(db)
        proposal = citation_decision_vertical_slice(db, project.id, prompt.id, package.id, use_answer_binding_v1_1=True)
        confirmed = confirm_citation_decision_vertical_slice(
            db,
            project.id,
            prompt.id,
            {
                "evidence_package_id": package.id,
                "action_keys": [proposal["recommended_actions"][0]["action_key"]],
                "reviewer": "human",
                "use_answer_binding_v1_1": True,
            },
        )
        candidate_id = confirmed["created"][0]["strategy_candidate"]["id"]
        review_strategy_candidate(
            db,
            candidate_id,
            type(
                "Payload",
                (),
                {
                    "review_status": "ACCEPTED_WITH_EDITS",
                    "reviewed_by": "human",
                    "review_note": "确认策略机制，待 Step 8 选择资产。",
                    "human_edited_payload": {"review_summary": "能力表达缺口成立"},
                },
            )(),
        )

        result = confirm_strategy_execution_plan(
            db,
            candidate_id,
            type(
                "Payload",
                (),
                {
                    "channel": "OFFICIAL_SITE",
                    "asset_operation": "UPDATE_EXISTING",
                    "selected_asset_id": 901,
                    "selected_asset_type": "ARTICLE",
                    "target_content_type": "ARTICLE",
                    "target_object": "CONTENT_ASSET",
                    "baseline_run_ids": [101],
                    "confirmed_by": "human",
                    "confirmation_note": "官网已有页更新。",
                    "new_asset_proposal": {},
                },
            )(),
        )

        assert result["readiness_status"] == "DRAFT_CREATED"
        candidate = db.get(OptimizationStrategyCandidate, candidate_id)
        experiment = db.get(OptimizationExperiment, result["experiment_id"])
        action = db.get(OptimizationAction, result["action_id"])
        assert candidate.effective_validation_status == "VALIDATED"
        assert experiment.status == "draft"
        assert loads(experiment.baseline_run_ids_json, []) == [101]
        metrics = loads(experiment.baseline_metrics_json, {})
        assert metrics["fixed_run_ids"] == [101]
        assert metrics["metrics"]["brand_mention"]["denominator"] == 1
        assert loads(action.release_evidence_json, {})["selected_asset_ref"]["asset_ref_type"] == "PAGE_SNAPSHOT"

        snapshot = loads(experiment.intervention_variables_json, {})["strategy_snapshot"]["effective_payload"]
        candidate.effective_payload_json = dumps({**loads(candidate.effective_payload_json, {}), "review_summary": "后续误改"})
        db.commit()
        db.refresh(experiment)
        frozen = loads(experiment.intervention_variables_json, {})["strategy_snapshot"]["effective_payload"]
        assert frozen == snapshot
        assert frozen["review_summary"] == "能力表达缺口成立"
    finally:
        db.close()


def test_step8_rejects_pending_review_strategy_candidate():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        project, prompt, package = _vertical_slice_fixture(db)
        proposal = citation_decision_vertical_slice(db, project.id, prompt.id, package.id, use_answer_binding_v1_1=True)
        confirmed = confirm_citation_decision_vertical_slice(
            db,
            project.id,
            prompt.id,
            {
                "evidence_package_id": package.id,
                "action_keys": [proposal["recommended_actions"][0]["action_key"]],
                "reviewer": "human",
                "use_answer_binding_v1_1": True,
            },
        )
        candidate_id = confirmed["created"][0]["strategy_candidate"]["id"]

        with pytest.raises(Exception):
            confirm_strategy_execution_plan(
                db,
                candidate_id,
                {
                    "channel": "OFFICIAL_SITE",
                    "asset_operation": "UPDATE_EXISTING",
                    "selected_asset_id": 901,
                    "baseline_run_ids": [101],
                },
            )
        assert db.query(OptimizationAction).count() == 0
        assert db.query(OptimizationExperiment).count() == 0
    finally:
        db.close()


def test_step8_requires_real_asset_ref_for_existing_asset_and_allows_new_asset_proposal():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        project, prompt, package = _vertical_slice_fixture(db)
        proposal = citation_decision_vertical_slice(db, project.id, prompt.id, package.id, use_answer_binding_v1_1=True)
        confirmed = confirm_citation_decision_vertical_slice(
            db,
            project.id,
            prompt.id,
            {
                "evidence_package_id": package.id,
                "action_keys": [proposal["recommended_actions"][0]["action_key"]],
                "reviewer": "human",
                "use_answer_binding_v1_1": True,
            },
        )
        candidate_id = confirmed["created"][0]["strategy_candidate"]["id"]
        review_strategy_candidate(
            db,
            candidate_id,
            type(
                "Payload",
                (),
                {
                    "review_status": "ACCEPTED",
                    "reviewed_by": "human",
                    "review_note": "确认策略机制。",
                    "human_edited_payload": {},
                },
            )(),
        )

        with pytest.raises(Exception):
            confirm_strategy_execution_plan(
                db,
                candidate_id,
                {
                    "channel": "OFFICIAL_SITE",
                    "asset_operation": "UPDATE_EXISTING",
                    "baseline_run_ids": [101],
                },
            )

        result = confirm_strategy_execution_plan(
            db,
            candidate_id,
            {
                "channel": "ZHIHU",
                "asset_operation": "CREATE_NEW",
                "selected_asset_type": "ARTICLE",
                "target_content_type": "ARTICLE",
                "target_object": "CONTENT_ASSET",
                "baseline_run_ids": [101],
                "new_asset_proposal": {
                    "title": "短链工具点击统计能力说明",
                    "url": "https://zhuanlan.zhihu.com/p/new-proposal",
                },
            },
        )
        selected = result["plan_payload"]["selected_asset_ref"]
        assert selected["asset_ref_type"] == "NEW_ASSET"
        assert selected["asset_operation"] == "CREATE_NEW"
        assert selected["channel"] == "ZHIHU"
        assert selected["asset_id"] is None
    finally:
        db.close()


def test_step8_baseline_reason_adoption_uses_target_brand_not_competitor():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        project, prompt, package = _vertical_slice_fixture(db)
        proposal = citation_decision_vertical_slice(db, project.id, prompt.id, package.id, use_answer_binding_v1_1=True)
        confirmed = confirm_citation_decision_vertical_slice(
            db,
            project.id,
            prompt.id,
            {
                "evidence_package_id": package.id,
                "action_keys": [proposal["recommended_actions"][0]["action_key"]],
                "reviewer": "human",
                "use_answer_binding_v1_1": True,
            },
        )
        candidate_id = confirmed["created"][0]["strategy_candidate"]["id"]
        review_strategy_candidate(
            db,
            candidate_id,
            type(
                "Payload",
                (),
                {
                    "review_status": "ACCEPTED",
                    "reviewed_by": "human",
                    "review_note": "确认策略机制。",
                    "human_edited_payload": {},
                },
            )(),
        )
        result = confirm_strategy_execution_plan(
            db,
            candidate_id,
            {
                "channel": "OFFICIAL_SITE",
                "asset_operation": "UPDATE_EXISTING",
                "selected_asset_id": 901,
                "selected_asset_type": "ARTICLE",
                "target_content_type": "ARTICLE",
                "target_object": "CONTENT_ASSET",
                "baseline_run_ids": [101],
            },
        )

        metrics = result["plan_payload"]["baseline_metrics"]["metrics"]
        assert metrics["target_reason_adoption"]["numerator"] == 0
        assert metrics["target_reason_adoption"]["source_run_ids"] == []
    finally:
        db.close()


def test_vertical_slice_feature_flag_controls_v1_1_read_path():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        project, prompt, package = _vertical_slice_v1_1_only_fixture(db)

        off = citation_decision_vertical_slice(
            db,
            project.id,
            prompt.id,
            package.id,
            use_answer_binding_v1_1=False,
        )
        on = citation_decision_vertical_slice(
            db,
            project.id,
            prompt.id,
            package.id,
            use_answer_binding_v1_1=True,
        )

        assert off["summary"]["primary_benchmark_count"] == 0
        assert off["recommended_actions"] == []
        assert on["summary"]["primary_benchmark_count"] == 1
        assert on["recommended_actions"][0]["route"] == "CONTENT"
        assert on["source_analysis"][0]["capability_truth_targets"][0]["label"] == "点击统计"
    finally:
        db.close()


def _decision_stability_fixture(db, entity_by_run: list[str | None]) -> tuple[Project, Prompt, OptimizationEvidencePackage]:
    project = Project(id=31, organization_id=1, name="爱短链品牌监测", brand_name="爱短链")
    prompt = Prompt(id=61, project_id=31, prompt_text="短链工具推荐", title="短链工具推荐")
    task = BrowserMonitorTask(id=31, project_id=31, question_ids_json="[61]", status="completed")
    db.add_all([Organization(id=1, name="测试组织"), project, prompt, task])
    runs = []
    events = []
    units = []
    bindings = []
    for index, entity in enumerate(entity_by_run, start=1):
        run_id = 3100 + index
        run = BrowserMonitorRun(
            id=run_id,
            task_id=31,
            project_id=31,
            prompt_id=61,
            status="success",
            original_query=prompt.prompt_text,
            answer_text=f"推荐 {entity}，因为它自带点击统计。" if entity else "这些工具各有优劣。",
        )
        runs.append(run)
        if not entity:
            continue
        event_id = 3200 + index
        unit_id = 3300 + index
        binding_id = 3400 + index
        events.append(RecommendationEvent(
            id=event_id,
            project_id=31,
            prompt_id=61,
            run_id=run_id,
            answer_hash=f"answer-{index}",
            entity_text=entity,
            speech_act="RECOMMEND",
            recommendation_strength="STRONG",
            polarity="POSITIVE",
            answer_span=f"推荐 {entity}，因为它自带点击统计。",
            reasons_json=dumps([]),
            review_status="MACHINE_GROUNDED",
        ))
        units.append(AnswerUnit(
            id=unit_id,
            project_id=31,
            prompt_id=61,
            run_id=run_id,
            answer_claim_id=unit_id,
            unit_text_original=f"{entity} 自带点击统计",
            unit_text_normalized=f"{entity} 自带点击统计",
            source_span=f"{entity} 自带点击统计",
            semantic_type="FEATURE",
            entity_hint=entity,
        ))
        bindings.append(AnswerDecisionBinding(
            id=binding_id,
            project_id=31,
            prompt_id=61,
            run_id=run_id,
            recommendation_event_id=event_id,
            answer_unit_id=unit_id,
            decision_role="SUPPORTING_REASON",
            binding_strength="MEDIUM",
            review_status="MACHINE_GROUNDED",
        ))
    package = OptimizationEvidencePackage(
        id=3501,
        project_id=31,
        prompt_id=61,
        version=1,
        source_run_ids_json=dumps([run.id for run in runs]),
        target_page_urls_json=dumps([]),
        environment_snapshot_json=dumps({}),
        package_payload_json=dumps({}),
        package_hash="decision-stability-fixture",
        status="active",
    )
    db.add_all([*runs, *events, *units, *bindings, package])
    db.commit()
    return project, prompt, package


def _decision_stability_multi_entity_fixture(
    db,
    entities_by_run: list[list[str]],
) -> tuple[Project, Prompt, OptimizationEvidencePackage]:
    project = Project(id=32, organization_id=1, name="爱短链品牌监测", brand_name="爱短链")
    prompt = Prompt(id=62, project_id=32, prompt_text="短链工具推荐", title="短链工具推荐")
    task = BrowserMonitorTask(id=32, project_id=32, question_ids_json="[62]", status="completed")
    db.add_all([Organization(id=1, name="测试组织"), project, prompt, task])
    runs = []
    events = []
    units = []
    bindings = []
    for run_index, entities in enumerate(entities_by_run, start=1):
        run_id = 4100 + run_index
        runs.append(BrowserMonitorRun(
            id=run_id,
            task_id=32,
            project_id=32,
            prompt_id=62,
            status="success",
            original_query=prompt.prompt_text,
            answer_text="；".join([f"推荐 {entity}，因为它自带点击统计" for entity in entities]) or "没有明确推荐。",
        ))
        for entity_index, entity in enumerate(entities, start=1):
            base_id = 4200 + run_index * 10 + entity_index
            events.append(RecommendationEvent(
                id=base_id,
                project_id=32,
                prompt_id=62,
                run_id=run_id,
                answer_hash=f"answer-{run_index}",
                entity_text=entity,
                speech_act="RECOMMEND",
                recommendation_strength="STRONG",
                polarity="POSITIVE",
                answer_span=f"推荐 {entity}，因为它自带点击统计。",
                reasons_json=dumps([]),
                review_status="MACHINE_GROUNDED",
            ))
            units.append(AnswerUnit(
                id=base_id + 1000,
                project_id=32,
                prompt_id=62,
                run_id=run_id,
                answer_claim_id=base_id + 1000,
                unit_text_original=f"{entity} 自带点击统计",
                unit_text_normalized=f"{entity} 自带点击统计",
                source_span=f"{entity} 自带点击统计",
                semantic_type="FEATURE",
                entity_hint=entity,
            ))
            bindings.append(AnswerDecisionBinding(
                id=base_id + 2000,
                project_id=32,
                prompt_id=62,
                run_id=run_id,
                recommendation_event_id=base_id,
                answer_unit_id=base_id + 1000,
                decision_role="SUPPORTING_REASON",
                binding_strength="MEDIUM",
                review_status="MACHINE_GROUNDED",
            ))
    package = OptimizationEvidencePackage(
        id=4501,
        project_id=32,
        prompt_id=62,
        version=1,
        source_run_ids_json=dumps([run.id for run in runs]),
        target_page_urls_json=dumps([]),
        environment_snapshot_json=dumps({}),
        package_payload_json=dumps({}),
        package_hash="decision-stability-multi-entity-fixture",
        status="active",
    )
    db.add_all([*runs, *events, *units, *bindings, package])
    db.commit()
    return project, prompt, package


@pytest.mark.parametrize(
    ("entity_by_run", "expected_score", "expected_level"),
    [
        (["ToolX", "ToolX", "ToolX", "ToolX", "ToolX", None], 83, "HIGH_STABILITY"),
        (["ToolX", "ToolX", "ToolX", "ToolY", "ToolY", "ToolY"], 50, "MIXED"),
        (["ToolX", "ToolX", "ToolY", "ToolY", "ToolZ", "ToolZ"], 33, "HIGH_VOLATILITY"),
    ],
)
def test_decision_stability_reports_simple_run_distribution(entity_by_run, expected_score, expected_level):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        project, prompt, package = _decision_stability_fixture(db, entity_by_run)

        result = decision_stability_for_package(db, project.id, prompt.id, package.id)

        assert result["valid_run_count"] == 6
        assert result["decision_stability_score"] == expected_score
        assert result["stability_level"] == expected_level
        assert result["formula"] == "round(dominant_recommendation_outcome.run_count / valid_run_count * 100)"
        assert result["metric_role"] == "POST_HOC_DESCRIPTIVE_ONLY"
        assert result["dominant_recommendation_outcome"]["observed_run_ids"]
    finally:
        db.close()


def test_decision_stability_single_top_entity_keeps_unique_dominant():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        project, prompt, package = _decision_stability_fixture(db, ["ToolX", "ToolX", "ToolX", "ToolY", "ToolY", None])

        result = decision_stability_for_package(db, project.id, prompt.id, package.id)
        dominant = result["dominant_recommendation_outcome"]

        assert dominant["outcome_type"] == "RECOMMENDATION_ENTITY"
        assert dominant["entity_text"] == "ToolX"
        assert dominant["run_count"] == 3
        assert dominant["is_tie"] is False
        assert result["decision_stability_score"] == 50
    finally:
        db.close()


def test_decision_stability_reports_co_dominant_when_entities_fully_tie():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        project, prompt, package = _decision_stability_multi_entity_fixture(
            db,
            [["Bitly", "小码短链接", "缩我短链接", "轻松短链接"] for _ in range(6)],
        )

        result = decision_stability_for_package(db, project.id, prompt.id, package.id)
        dominant = result["dominant_recommendation_outcome"]

        assert dominant["outcome_type"] == "CO_DOMINANT_RECOMMENDATION_ENTITIES"
        assert dominant["entity_text"] == ""
        assert dominant["run_count"] == 6
        assert dominant["co_dominant_count"] == 4
        assert {item["entity_text"] for item in dominant["co_dominant_entities"]} == {"Bitly", "小码短链接", "缩我短链接", "轻松短链接"}
        assert result["decision_stability_score"] == 100
        assert result["stability_level"] == "HIGH_STABILITY"
    finally:
        db.close()


def test_decision_stability_reports_co_dominant_when_entities_partially_tie():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        project, prompt, package = _decision_stability_multi_entity_fixture(
            db,
            [["ToolX", "ToolY"], ["ToolX", "ToolY"], ["ToolZ"]],
        )

        result = decision_stability_for_package(db, project.id, prompt.id, package.id)
        dominant = result["dominant_recommendation_outcome"]

        assert dominant["outcome_type"] == "CO_DOMINANT_RECOMMENDATION_ENTITIES"
        assert dominant["run_count"] == 2
        assert {item["entity_text"] for item in dominant["co_dominant_entities"]} == {"ToolX", "ToolY"}
        assert result["decision_stability_score"] == 67
    finally:
        db.close()


def test_decision_stability_tie_does_not_select_entity_by_name_sorting():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        project, prompt, package = _decision_stability_multi_entity_fixture(
            db,
            [["Zeta", "Alpha"], ["Zeta", "Alpha"]],
        )

        result = decision_stability_for_package(db, project.id, prompt.id, package.id)
        dominant = result["dominant_recommendation_outcome"]

        assert dominant["outcome_type"] == "CO_DOMINANT_RECOMMENDATION_ENTITIES"
        assert dominant["entity_text"] == ""
        assert {item["entity_text"] for item in dominant["co_dominant_entities"]} == {"Alpha", "Zeta"}
    finally:
        db.close()


def test_decision_stability_reason_coverage_uses_recommendation_entity_denominator():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        project, prompt, package = _decision_stability_fixture(db, ["ToolX", "ToolX", "ToolX", "ToolY", None, None])

        result = decision_stability_for_package(db, project.id, prompt.id, package.id)
        toolx_reason = next(item for item in result["recommendation_reasons"] if item["entity_text"] == "ToolX")

        assert toolx_reason["reason_observed_run_count"] == 3
        assert toolx_reason["denominator"] == 3
        assert toolx_reason["value"] == 1
        assert toolx_reason["observed_run_ids"] == [3101, 3102, 3103]
    finally:
        db.close()


def test_decision_stability_reason_coverage_uses_current_formal_input_batch():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        project, prompt, package = _decision_stability_fixture(db, ["ToolX"])
        current_unit = AnswerUnit(
            id=3905,
            shadow_run_id=2,
            project_id=project.id,
            prompt_id=prompt.id,
            run_id=3101,
            answer_claim_id=3905,
            unit_text_original="ToolX 当前支持自定义短链",
            unit_text_normalized="ToolX 当前支持自定义短链",
            source_span="ToolX 当前支持自定义短链",
            semantic_type="FEATURE",
            entity_hint="ToolX",
        )
        stale_unit = AnswerUnit(
            id=3906,
            shadow_run_id=1,
            project_id=project.id,
            prompt_id=prompt.id,
            run_id=3101,
            answer_claim_id=3906,
            unit_text_original="ToolX 历史错误理由",
            unit_text_normalized="ToolX 历史错误理由",
            source_span="ToolX 历史错误理由",
            semantic_type="FEATURE",
            entity_hint="ToolX",
        )
        current_binding = AnswerDecisionBinding(
            id=3907,
            shadow_run_id=2,
            project_id=project.id,
            prompt_id=prompt.id,
            run_id=3101,
            recommendation_event_id=3201,
            answer_unit_id=3905,
            decision_role="SUPPORTING_REASON",
            binding_strength="MEDIUM",
            review_status="MACHINE_GROUNDED",
        )
        stale_binding = AnswerDecisionBinding(
            id=3908,
            shadow_run_id=1,
            project_id=project.id,
            prompt_id=prompt.id,
            run_id=3101,
            recommendation_event_id=3201,
            answer_unit_id=3906,
            decision_role="SUPPORTING_REASON",
            binding_strength="MEDIUM",
            review_status="MACHINE_GROUNDED",
        )
        doc = SourceDocument(
            id=3909,
            url="https://example.com/toolx",
            original_url="https://example.com/toolx",
            canonical_url="https://example.com/toolx",
            domain="example.com",
            fetch_status="SUCCESS",
            clean_text="ToolX 当前支持自定义短链",
        )
        claim = SourceClaim(
            id=3910,
            project_id=project.id,
            source_document_id=3909,
            normalized_claim="ToolX 当前支持自定义短链",
            subject_entity="ToolX",
        )
        alignment = EvidenceAlignment(
            id=3911,
            project_id=project.id,
            prompt_id=prompt.id,
            run_id=3101,
            recommendation_event_id=3201,
            source_document_id=3909,
            source_claim_id=3910,
            relation="SUPPORTS",
            machine_payload_json=dumps({
                "reason_source": ANSWER_BINDING_REASON_SOURCE,
                "formal_input_version": FORMAL_V1_1_INPUT_VERSION,
                "shadow_run_id": 2,
                "answer_unit_id": 3905,
                "decision_binding_id": 3907,
            }),
        )
        db.add_all([current_unit, stale_unit, current_binding, stale_binding, doc, claim, alignment])
        db.commit()

        result = decision_stability_for_package(db, project.id, prompt.id, package.id)
        reason_texts = {item["reason_text"] for item in result["recommendation_reasons"]}

        assert reason_texts == {"ToolX 当前支持自定义短链"}
    finally:
        db.close()


def test_decision_stability_reason_attribution_uses_answer_unit_entity_scope():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        project, prompt, package = _decision_stability_fixture(db, ["ToolX"])
        tooly_event = RecommendationEvent(
            id=3901,
            project_id=project.id,
            prompt_id=prompt.id,
            run_id=3101,
            answer_hash="answer-1",
            entity_text="ToolY",
            speech_act="RECOMMEND",
            recommendation_strength="STRONG",
            polarity="POSITIVE",
            answer_span="同时推荐 ToolY。",
            reasons_json=dumps([]),
            review_status="MACHINE_GROUNDED",
        )
        overly_broad_binding = AnswerDecisionBinding(
            id=3902,
            project_id=project.id,
            prompt_id=prompt.id,
            run_id=3101,
            recommendation_event_id=3901,
            answer_unit_id=3301,
            decision_role="SUPPORTING_REASON",
            binding_strength="MEDIUM",
            review_status="MACHINE_GROUNDED",
        )
        db.add_all([tooly_event, overly_broad_binding])
        db.commit()

        result = decision_stability_for_package(db, project.id, prompt.id, package.id)
        toolx_reasons = [
            item for item in result["recommendation_reasons"]
            if item["reason_text"] == "ToolX 自带点击统计"
        ]

        assert toolx_reasons
        assert {item["entity_text"] for item in toolx_reasons} == {"ToolX"}
    finally:
        db.close()


def test_decision_stability_reason_coverage_excludes_procedure_units():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        project, prompt, package = _decision_stability_fixture(db, ["ToolX"])
        procedure_unit = AnswerUnit(
            id=3903,
            project_id=project.id,
            prompt_id=prompt.id,
            run_id=3101,
            answer_claim_id=3903,
            unit_text_original="打开官网并粘贴链接",
            unit_text_normalized="打开官网并粘贴链接",
            source_span="打开官网并粘贴链接",
            semantic_type="FEATURE",
            entity_hint="ToolX",
        )
        procedure_binding = AnswerDecisionBinding(
            id=3904,
            project_id=project.id,
            prompt_id=prompt.id,
            run_id=3101,
            recommendation_event_id=3201,
            answer_unit_id=3903,
            decision_role="SUPPORTING_REASON",
            binding_strength="MEDIUM",
            review_status="MACHINE_GROUNDED",
        )
        db.add_all([procedure_unit, procedure_binding])
        db.commit()

        result = decision_stability_for_package(db, project.id, prompt.id, package.id)

        assert all(
            item["reason_text"] != "打开官网并粘贴链接"
            for item in result["recommendation_reasons"]
        )
    finally:
        db.close()


def test_decision_stability_isolation_does_not_change_formal_chain_outputs():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        project, prompt, package = _vertical_slice_fixture(db)
        before = citation_decision_vertical_slice(db, project.id, prompt.id, package.id, use_answer_binding_v1_1=True)
        before_counts = {
            "strategy_candidates": db.query(OptimizationStrategyCandidate).count(),
            "actions": db.query(OptimizationAction).count(),
            "experiments": db.query(OptimizationExperiment).count(),
            "alignments": db.query(EvidenceAlignment).count(),
        }

        stability = decision_stability_for_package(db, project.id, prompt.id, package.id)
        after = citation_decision_vertical_slice(db, project.id, prompt.id, package.id, use_answer_binding_v1_1=True)
        after_counts = {
            "strategy_candidates": db.query(OptimizationStrategyCandidate).count(),
            "actions": db.query(OptimizationAction).count(),
            "experiments": db.query(OptimizationExperiment).count(),
            "alignments": db.query(EvidenceAlignment).count(),
        }

        assert stability["metric_role"] == "POST_HOC_DESCRIPTIVE_ONLY"
        assert after_counts == before_counts
        assert after["summary"] == before["summary"]
        assert after["status"] == before["status"]
        assert after["recommended_actions"] == before["recommended_actions"]
    finally:
        db.close()


def test_step8_baseline_snapshot_ignores_prompt_runs_added_after_experiment_creation():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        project, prompt, package = _vertical_slice_fixture(db)
        proposal = citation_decision_vertical_slice(db, project.id, prompt.id, package.id, use_answer_binding_v1_1=True)
        confirmed = confirm_citation_decision_vertical_slice(
            db,
            project.id,
            prompt.id,
            {
                "evidence_package_id": package.id,
                "action_keys": [proposal["recommended_actions"][0]["action_key"]],
                "reviewer": "human",
                "use_answer_binding_v1_1": True,
            },
        )
        candidate_id = confirmed["created"][0]["strategy_candidate"]["id"]
        review_strategy_candidate(
            db,
            candidate_id,
            type(
                "Payload",
                (),
                {
                    "review_status": "ACCEPTED_WITH_EDITS",
                    "reviewed_by": "human",
                    "review_note": "确认策略机制，待 Step 8 选择资产。",
                    "human_edited_payload": {"review_summary": "能力表达缺口成立"},
                },
            )(),
        )
        result = confirm_strategy_execution_plan(
            db,
            candidate_id,
            {
                "channel": "OFFICIAL_SITE",
                "asset_operation": "UPDATE_EXISTING",
                "selected_asset_id": 901,
                "selected_asset_type": "ARTICLE",
                "target_content_type": "ARTICLE",
                "target_object": "CONTENT_ASSET",
                "baseline_run_ids": [101],
            },
        )
        experiment = db.get(OptimizationExperiment, result["experiment_id"])
        baseline_before = loads(experiment.baseline_metrics_json, {})
        db.add(BrowserMonitorRun(
            id=199,
            task_id=1,
            project_id=project.id,
            prompt_id=prompt.id,
            status="success",
            original_query=prompt.prompt_text,
            answer_text="后来新增的采样不应改变已冻结 Baseline。",
            brand_mentioned=True,
        ))
        db.commit()
        db.refresh(experiment)

        assert loads(experiment.baseline_run_ids_json, []) == [101]
        assert loads(experiment.baseline_metrics_json, {}) == baseline_before
        assert baseline_before["metrics"]["brand_mention"]["denominator"] == 1
    finally:
        db.close()


def test_step8_benchmark_channel_does_not_auto_become_execution_channel():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        project, prompt, package = _vertical_slice_fixture(db)
        proposal = citation_decision_vertical_slice(db, project.id, prompt.id, package.id, use_answer_binding_v1_1=True)
        assert proposal["channel_opportunities"][0]["channel"] == "zhihu"
        confirmed = confirm_citation_decision_vertical_slice(
            db,
            project.id,
            prompt.id,
            {
                "evidence_package_id": package.id,
                "action_keys": [proposal["recommended_actions"][0]["action_key"]],
                "reviewer": "human",
                "use_answer_binding_v1_1": True,
            },
        )
        candidate_id = confirmed["created"][0]["strategy_candidate"]["id"]
        candidate = db.get(OptimizationStrategyCandidate, candidate_id)
        assert loads(candidate.structured_payload_json, {})["target_platform"] == "UNRESOLVED"
        review_strategy_candidate(
            db,
            candidate_id,
            type(
                "Payload",
                (),
                {
                    "review_status": "ACCEPTED",
                    "reviewed_by": "human",
                    "review_note": "只确认策略机制，不从 Benchmark 平台继承执行渠道。",
                    "human_edited_payload": {},
                },
            )(),
        )

        result = confirm_strategy_execution_plan(
            db,
            candidate_id,
            {
                "channel": "OFFICIAL_SITE",
                "asset_operation": "UPDATE_EXISTING",
                "selected_asset_id": 901,
                "selected_asset_type": "ARTICLE",
                "target_content_type": "ARTICLE",
                "target_object": "CONTENT_ASSET",
                "baseline_run_ids": [101],
            },
        )

        assert result["plan_payload"]["channel"] == "OFFICIAL_SITE"
        assert result["plan_payload"]["selected_asset_ref"]["channel"] == "OFFICIAL_SITE"
        assert result["plan_payload"]["strategy_snapshot"]["effective_payload"]["target_platform"] == "OFFICIAL_SITE"
    finally:
        db.close()


def test_recommendation_outcome_tracks_candidate_reason_and_citation():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        project = Project(
            id=21,
            organization_id=1,
            name="爱短链品牌监测",
            brand_name="爱短链",
            website_url="https://www.aifabu.com",
        )
        prompt = Prompt(id=44, project_id=21, prompt_text="短链工具推荐", title="短链工具推荐")
        task = BrowserMonitorTask(id=21, project_id=21, question_ids_json="[44]", status="completed")
        baseline = BrowserMonitorRun(
            id=2101,
            task_id=21,
            project_id=21,
            prompt_id=44,
            status="success",
            original_query=prompt.prompt_text,
            answer_text="可以考虑 ToolX。",
            reference_complete=True,
        )
        validation = BrowserMonitorRun(
            id=2102,
            task_id=21,
            project_id=21,
            prompt_id=44,
            status="success",
            original_query=prompt.prompt_text,
            answer_text="可以优先考虑爱短链，因为它支持批量短链生成。",
            brand_mentioned=True,
            brand_recommendation_level=2,
            reference_complete=True,
        )
        issue = OptimizationIssue(id=210, project_id=21, prompt_id=44, issue_type="brand_not_recommended", status="in_action")
        action = OptimizationAction(id=211, issue_id=210, action_type="article_publish", target_type="external_platform")
        experiment = OptimizationExperiment(
            id=212,
            action_id=211,
            status="analyzing",
            baseline_run_ids_json=dumps([baseline.id]),
            validation_run_ids_json=dumps([validation.id]),
            primary_metric="brand_recommendation_rate",
            secondary_metrics_json=dumps(["brand_mention_rate", "official_reference_rate"]),
        )
        event = RecommendationEvent(
            id=213,
            project_id=21,
            prompt_id=44,
            run_id=validation.id,
            answer_hash="validation",
            entity_text="爱短链",
            speech_act="RECOMMEND",
            recommendation_strength="STRONG",
            polarity="POSITIVE",
            answer_span=validation.answer_text,
            reasons_json=dumps([{"normalized_reason": "支持批量短链生成"}]),
            review_status="MACHINE_GROUNDED",
        )
        ref = ReferenceSource(
            id=214,
            run_id=validation.id,
            reference_index=1,
            display_title="爱短链官网",
            url="https://www.aifabu.com",
            domain="aifabu.com",
            is_official_domain=True,
        )
        db.add_all([Organization(id=1, name="测试组织"), project, prompt, task, baseline, validation, issue, action, experiment, event, ref])
        db.commit()

        analyzed = analyze_experiment(db, experiment.id)
        outcome = loads(analyzed.outcome_summary_json, {})

        assert outcome["recommendation_before_after"]["baseline"] == 0
        assert outcome["recommendation_before_after"]["validation"] == 1
        assert outcome["target_reason_before_after"]["validation"] == 1
        assert outcome["citation_before_after"]["validation"] == 1
        assert outcome["human_conclusion_required"] is True
    finally:
        db.close()
