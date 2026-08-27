from __future__ import annotations

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
    OptimizationExperiment,
    OptimizationIssue,
    PageSnapshot,
    Prompt,
    RecommendationEvent,
    ReferenceSource,
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
    create_evidence_package,
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


def test_vertical_slice_proposes_action_channel_and_experiment():
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
        assert created["strategy_candidate"]["review_status"] == "ACCEPTED"
        assert created["experiment_plan"]["experiment_id"] is not None
        experiment = db.get(OptimizationExperiment, created["experiment_plan"]["experiment_id"])
        assert experiment.channel == "ZHIHU"
        assert experiment.experiment_mode == "PER_CHANNEL"
        assert experiment.release_blocked is True
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
