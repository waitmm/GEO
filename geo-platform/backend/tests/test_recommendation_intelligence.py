from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    BrowserMonitorRun,
    BrowserMonitorTask,
    Competitor,
    OptimizationAction,
    OptimizationEvidencePackage,
    OptimizationExperiment,
    OptimizationIssue,
    OptimizationStrategyCandidate,
    Organization,
    PageSnapshot,
    AnswerClaim,
    PassageAlignment,
    Project,
    Prompt,
    ReferenceSource,
    RetrievalCandidate,
    SourceDocument,
)
from app.modules.optimization import recommendation
from app.modules.optimization import service
from app.modules.optimization.schemas import StrategyCandidateReviewPayload
from app.modules.optimization.service import strategy_to_experiment_plan
from app.services.serialization import dumps


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _seed_project(db, prompt_text: str, prompt_id: int = 19):
    org = Organization(id=1, name="测试组织")
    project = Project(
        id=3,
        organization_id=1,
        name="爱短链品牌监测",
        brand_name="爱短链",
        brand_aliases_json=dumps(["aifabu", "爱发布"]),
        website_url="https://www.aifabu.com/",
    )
    competitor = Competitor(id=1, project_id=3, name="商加加", aliases_json=dumps(["商加加外链"]))
    prompt = Prompt(id=prompt_id, project_id=3, prompt_text=prompt_text, title=prompt_text)
    task = BrowserMonitorTask(id=1, project_id=3, question_ids_json=f"[{prompt_id}]", status="completed")
    runs = [
        BrowserMonitorRun(
            id=173,
            task_id=1,
            project_id=3,
            prompt_id=prompt_id,
            status="success",
            original_query=prompt_text,
            answer_text="抖音跳转微信：可通过商加加外链等第三方工具，填写目标微信信息自动生成加密短链。",
        ),
        BrowserMonitorRun(
            id=174,
            task_id=1,
            project_id=3,
            prompt_id=prompt_id,
            status="success",
            original_query=prompt_text,
            answer_text="如果需要引流场景，可以使用商加加外链；爱短链仅被提到，没有形成推荐判断。",
        ),
    ]
    db.add_all([org, project, competitor, prompt, task, *runs])
    db.add_all([
        ReferenceSource(id=1, run_id=173, reference_index=1, display_title="商加加外链制作教程", url="https://example.com/shangjiajia", domain="example.com"),
        ReferenceSource(id=2, run_id=174, reference_index=1, display_title="商加加外链引流场景说明", url="https://example.com/shangjiajia-guide", domain="example.com"),
        RetrievalCandidate(id=1, run_id=173, rank=1, title="商加加外链制作教程", url="https://example.com/shangjiajia", domain="example.com"),
        RetrievalCandidate(id=2, run_id=174, rank=1, title="商加加外链引流场景说明", url="https://example.com/shangjiajia-guide", domain="example.com"),
    ])
    db.commit()
    return project, prompt, runs


def _seed_evidence_package(db, project_id: int = 3, prompt_id: int = 19, package_id: int = 91):
    package = OptimizationEvidencePackage(
        id=package_id,
        project_id=project_id,
        prompt_id=prompt_id,
        version=1,
        source_run_ids_json=dumps([173, 174]),
        target_page_urls_json=dumps(["https://www.aifabu.com/card"]),
        package_payload_json=dumps({
            "prompt": {"prompt_text": "抖音跳转链接"},
            "retrieval_metrics_status": "ok",
            "metrics": [
                {
                    "metric_name": "candidate_capture_rate",
                    "calculation_status": "ok",
                    "numerator": 0,
                    "denominator": 2,
                    "value": 0,
                },
                {
                    "metric_name": "capability_recognition_rate",
                    "calculation_status": "ok",
                    "numerator": 0,
                    "denominator": 2,
                    "value": 0,
                },
            ],
        }),
        package_hash=f"decision-market-{package_id}",
        status="active",
    )
    db.add(package)
    db.commit()
    return package


def test_how_to_prompt_does_not_make_recommendation_metric_core(db):
    _seed_project(db, "抖音跳转链接怎么设置")

    result = recommendation.run_recommendation_analysis(db, 3, 19)

    assert result["decision_mode"] == "HOW_TO"
    assert result["decision_mode_label"] == "操作方法"
    assert result["metric_eligibility"]["recommendation_metrics_label"] == "仅作诊断观察"
    assert result["metric_eligibility"]["task_completion_metrics_label"] == "可作为核心指标"


def test_recommendation_landscape_counts_candidates_and_mentions(db):
    _seed_project(db, "抖音跳转链接用什么工具")

    result = recommendation.run_recommendation_analysis(db, 3, 19)
    rows = {row["entity_name"]: row for row in result["landscape"]}

    assert rows["商加加"]["candidate_run_count"] == 2
    assert rows["商加加"]["recommendation_run_count"] == 0
    assert rows["爱短链"]["mention_run_count"] == 1
    assert rows["爱短链"]["candidate_run_count"] == 0
    assert result["positioning"]
    assert result["evidence_links"]
    assert result["decision_market"]["citation_source_analysis"]["metrics"]["retrieval_overlap_rate"]["numerator"] == 2
    assert result["decision_market"]["citation_source_analysis"]["metrics"]["full_reference_in_retrieval_rate"]["numerator"] == 2
    assert "不是包含关系" in result["decision_market"]["citation_source_analysis"]["boundary_note"]
    assert result["decision_market"]["citation_context"]["metrics"]["retrieval_overlap_rate"]["numerator"] == 2
    assert all(item["retrieved"] for item in result["decision_market"]["citation_context"]["adoptions"])
    assert all(item["supports_claim"] is False for item in result["decision_market"]["citation_context"]["adoptions"])
    assert {item["evidence_status"] for item in result["decision_market"]["citation_context"]["adoptions"]} <= {"LINKED", "PARTIALLY_LINKED", "UNCERTAIN", "UNLINKED"}
    assert all(link["id"] for link in result["evidence_links"])
    assert result["gap_diagnosis"]
    assert result["intervention_candidates"]
    assert result["answer_samples"]
    assert result["citation_sources"]
    assert result["action_brief"]["must_answer"]
    assert result["action_brief"]["content_sections"]


def test_no_brand_recommendation_reports_brand_opportunity(db):
    _seed_project(db, "抖音卡片")
    for run in db.query(BrowserMonitorRun).all():
        run.answer_text = "抖音卡片需要借助合规工具制作，可以设置跳转目标、追踪点击数据，并规避违规风险。"
    db.commit()

    result = recommendation.run_recommendation_analysis(db, 3, 19)

    assert result["landscape"] == []
    assert result["brand_opportunity"]["status"] == "NO_BRAND_RECOMMENDATION_WITH_OPPORTUNITY"
    assert result["brand_opportunity"]["opportunity_detected"] is True
    assert "当前回答没有推荐任何品牌" in result["brand_opportunity"]["summary"]
    assert result["brand_opportunity"]["signals"]
    assert result["answer_samples"]
    assert result["action_brief"]["evidence_to_collect"]


def test_decision_market_extracts_solution_slot_criteria_and_funnel(db):
    _seed_project(db, "抖音跳转链接")

    result = recommendation.run_recommendation_analysis(db, 3, 19)
    market = result["decision_market"]

    assert market["schema_version"] == "decision_market_schema.v2_choice_gate"
    assert market["choice_slot"]["choice_slot_status"] in {"OPTIONAL", "REQUIRED"}
    assert market["choice_slot"]["choice_slot_metric"]["numerator"] == 2
    assert market["answer_semantic_facts"]["metrics"]["has_choice_slot"]["numerator"] == 2
    assert market["brand_opportunity_gate"]["metrics"]["choice_slot_rate"]["numerator"] == 2
    assert any(row["criterion_label"] == "微信兼容" for row in market["selection_criteria_market"]["criteria"])

    rows = {row["brand_name"]: row for row in market["brand_funnel"]["rows"]}
    assert rows["爱短链"]["metrics"]["mention_rate"]["numerator"] == 1
    assert rows["爱短链"]["metrics"]["candidate_capture_rate"]["numerator"] == 0
    assert rows["商加加"]["metrics"]["candidate_capture_rate"]["numerator"] == 2
    assert market["gap_diagnosis"]
    assert market["action_package"]["experiment_proposal"]["primary_metric"] in {
        "need_association_rate",
        "capability_recognition_rate",
        "candidate_capture_rate",
        "evidence_link_rate",
        "explicit_recommendation_rate",
        "manual_review",
    }


def test_single_prompt_run_eligibility_excludes_continuous_context_runs(db):
    _seed_project(db, "抖音跳转链接用什么工具")
    continuous_run = db.get(BrowserMonitorRun, 174)
    continuous_run.collection_mode = "single_continuous"
    continuous_run.answer_text = "连续会话里继续推荐商加加外链，但这条不能进入正式单 Prompt 分析。"
    db.commit()

    result = recommendation.run_recommendation_analysis(db, 3, 19)
    eligibility = result["run_eligibility"]
    market = result["decision_market"]

    assert eligibility["total_runs"] == 2
    assert eligibility["eligible_runs"] == 1
    assert eligibility["analysis_usable_runs"] == 1
    assert eligibility["ineligible_run_ids"] == [174]
    blocked = next(row for row in eligibility["rows"] if row["run_id"] == 174)
    assert "CONTEXT_CONTAMINATION" in blocked["reasons"]
    assert result["run_ids"] == [173]
    assert market["recommendation_market"]["eligible_runs"] == 1
    rows = {row["entity_name"]: row for row in market["recommendation_market"]["rows"]}
    assert rows["商加加"]["candidate"]["denominator"] == 1


def test_single_prompt_decision_market_exposes_position_drivers_and_interventions(db):
    _seed_project(db, "抖音跳转链接用什么工具")

    result = recommendation.run_recommendation_analysis(db, 3, 19)
    market = result["decision_market"]

    assert market["analysis_unit"] == "SINGLE_PROMPT"
    assert market["decision_space"]["status"] in {
        "SOLUTION_CHOICE_SPACE",
        "BRAND_CANDIDATE_SPACE",
        "BRAND_RECOMMENDATION_PRESENT",
        "BRAND_COMPARISON_PRESENT",
    }
    assert market["recommendation_market"]["rows"]
    assert all("denominator" in row["candidate"] for row in market["recommendation_market"]["rows"])
    assert market["target_brand_position"]["brand_name"] == "爱短链"
    assert market["target_brand_position"]["primary_gap"]["gap_type"] in {
        "ASSOCIATION_GAP",
        "CAPABILITY_RECOGNITION_GAP",
        "CANDIDATE_INCLUSION_GAP",
        "RECOMMENDATION_GAP",
        "TOP_RECOMMENDATION_GAP",
        "INTENT_FIT_GAP",
    }
    assert market["recommendation_drivers"]["rows"]
    assert any(row["product_truth_status"] == "UNKNOWN" for row in market["recommendation_drivers"]["rows"])
    assert market["intervention_feasibility"]["status"] == "BLOCKED_PRODUCT_TRUTH"
    assert market["intervention_candidates"][0]["target_platform"] == "UNRESOLVED"
    assert market["intervention_candidates"][0]["target_url"] == ""


def test_source_content_pattern_keeps_retrieval_and_citation_boundary(db):
    _seed_project(db, "抖音跳转链接用什么工具")

    result = recommendation.run_recommendation_analysis(db, 3, 19)
    pattern = result["decision_market"]["source_content_pattern"]

    assert pattern["rows"]
    assert pattern["metrics"]["citation_occurrence_count"] == 2
    assert "RetrievalCandidate 不是 ReferenceSource 的上游漏斗" in pattern["boundary_note"]
    assert "target_page_conversion_rate" not in pattern["metrics"]


def test_decision_market_strategy_draft_carries_single_prompt_candidate_context(db):
    _seed_project(db, "抖音跳转链接用什么工具")
    _seed_evidence_package(db)
    result = recommendation.run_recommendation_analysis(db, 3, 19)

    draft = recommendation.create_decision_market_experiment_draft(db, result["id"], {"owner": "geo"})
    payload = draft["strategy_candidate"]["structured_payload"]

    assert payload["decision_market"]["intervention_candidate"]["schema_version"] == "prompt_intervention_candidate.v1"
    assert payload["decision_market"]["intervention_feasibility"]["status"] == "BLOCKED_PRODUCT_TRUTH"
    assert payload["decision_market"]["target_brand_position"]["brand_name"] == "爱短链"
    assert payload["decision_market"]["recommendation_drivers"]
    assert payload["decision_market"]["source_content_pattern"]
    assert payload["intervention_type"] == "UNRESOLVED"
    assert payload["target_platform"] == "UNRESOLVED"
    assert payload["execution_gate"]["blocked_materialization"] is True


def test_decision_market_keeps_recommendation_rate_diagnostic_for_prompt19(db):
    _seed_project(db, "抖音跳转链接")

    result = recommendation.run_recommendation_analysis(db, 3, 19)
    market = result["decision_market"]

    assert "推荐率仅作诊断" in market["primary_metric_note"]
    target = next(row for row in market["brand_funnel"]["rows"] if row["brand_name"] == "爱短链")
    assert target["metrics"]["candidate_capture_rate"]["eligible_denominator"] == market["choice_slot"]["choice_slot_metric"]["numerator"]
    assert all("denominator" in metric for metric in target["metrics"].values())


def test_gap_diagnosis_text_does_not_hardcode_prompt19_for_other_prompts(db):
    project, _, _ = _seed_project(db, "抖音跳转链接怎么设置", prompt_id=9)
    recommendation_gap = next(
        item
        for item in recommendation._derive_gap_reads(
            project,
            {
                "rows": [{
                    "brand_name": "爱短链",
                    "metrics": {
                        "need_association_rate": {"metric": "need_association_rate", "numerator": 1, "denominator": 10, "eligible_denominator": 10, "value": 0.1, "sample_size": 10},
                        "capability_recognition_rate": {"metric": "capability_recognition_rate", "numerator": 1, "denominator": 10, "eligible_denominator": 10, "value": 0.1, "sample_size": 10},
                        "candidate_capture_rate": {"metric": "candidate_capture_rate", "numerator": 1, "denominator": 10, "eligible_denominator": 10, "value": 0.1, "sample_size": 10},
                        "explicit_recommendation_rate": {"metric": "explicit_recommendation_rate", "numerator": 0, "denominator": 10, "eligible_denominator": 10, "value": 0.0, "sample_size": 10},
                    },
                    "brand_mention_run_ids": [173],
                    "need_association_run_ids": [173],
                    "capability_recognized_run_ids": [173],
                    "candidate_run_ids": [173],
                }],
                "recommendation_primary_metric": False,
            },
            {"criteria": [], "target_used_selection_run_count": 0},
            {"metrics": {"evidence_link_rate": {"metric": "evidence_link_rate", "numerator": 1, "denominator": 10, "eligible_denominator": 10, "value": 0.1, "sample_size": 10}}},
            {"solution_required": "OPTIONAL", "solution_slot_run_ids": [173], "solution_slot_metric": {"metric": "solution_slot_rate", "numerator": 10, "denominator": 10, "eligible_denominator": 10, "value": 1.0, "sample_size": 10}},
            {"opportunity_level": "HIGH_BRAND_OPPORTUNITY"},
            {"boundary_note": "Product Truth 边界"},
        )
        if item["gap_type"] == "RECOMMENDATION_GAP"
    )

    assert "#19" not in recommendation_gap["diagnosis_text"]
    assert "当前这类信息/操作问题" in recommendation_gap["diagnosis_text"]


def test_recommendation_action_copy_uses_current_prompt_context(db):
    _seed_project(db, "抖音卡片怎么做？", prompt_id=9)

    result = recommendation.run_recommendation_analysis(db, 3, 9)
    rendered = dumps({
        "faq": result["decision_market"]["action_package"]["content_brief"]["faq"],
        "target_capability_claims": result["decision_market"]["action_package"]["content_brief"]["target_capability_claims"],
        "must_answer": result["action_brief"]["must_answer"],
        "content_sections": result["action_brief"]["content_sections"],
    })

    assert "抖音跳转链接" not in rendered
    assert "抖音卡片怎么做？" in result["action_brief"]["title"]
    assert any("抖音卡片怎么做？" in item for item in result["decision_market"]["action_package"]["content_brief"]["faq"])
    assert any("抖音卡片怎么做？" in item for item in result["action_brief"]["content_sections"])


def test_local_strategy_hypothesis_uses_current_prompt_context(db):
    project, prompt, _ = _seed_project(db, "抖音卡片怎么做？", prompt_id=9)
    project.brand_name = "测试品牌"
    db.commit()
    snapshot = PageSnapshot(id=9, project_id=3, url="https://www.aifabu.com/card", snapshot_type="PRE_RELEASE", title="原始标题", h1="原始H1")
    evidence = {
        "prompt": {
            "id": prompt.id,
            "prompt_text": prompt.prompt_text,
            "display_label": f"Prompt #{prompt.id} · {prompt.prompt_text}",
        },
        "platform_gap_matrix": [],
        "retrieval_metrics_status": "ok",
        "metrics": [
            {
                "metric_name": "target_page_retrieval_rate",
                "calculation_status": "ok",
                "numerator": 0,
                "denominator": 2,
                "value": 0.0,
            },
            {
                "metric_name": "official_reference_rate",
                "calculation_status": "ok",
                "numerator": 0,
                "denominator": 2,
                "value": 0.0,
            },
        ],
        "source_run_ids": [173, 174],
    }

    hypothesis = service._local_strategy_hypothesis(project, evidence, snapshot, "https://www.aifabu.com/card")
    rendered = dumps(hypothesis)

    assert "Prompt 19" not in rendered
    assert "抖音跳转链接" not in rendered
    assert "爱短链" not in rendered
    assert "owned_site" not in rendered
    assert "抖音卡片怎么做" in hypothesis["recommended_title"]
    assert hypothesis["target_intent"] == "抖音卡片怎么做？"
    assert hypothesis["target_platform"] == "UNRESOLVED"
    assert hypothesis["target_object"] == "UNRESOLVED"


def test_answer_semantic_fact_can_be_reviewed(db):
    _seed_project(db, "抖音跳转链接")
    result = recommendation.run_recommendation_analysis(db, 3, 19)

    facts = recommendation.list_answer_semantic_facts(db, result["id"])
    choice_fact = next(item for item in facts if item["fact_type"] == "has_choice_slot")
    reviewed = recommendation.review_answer_semantic_fact(db, choice_fact["id"], {
        "review_status": "CONFIRMED",
        "fact_value": choice_fact["fact_value"],
        "reviewer": "geo",
    })

    assert reviewed["review_status"] == "CONFIRMED"
    assert reviewed["fact_type_label"] == "存在品牌选择空间"
    assert reviewed["human_labels"]["reviewer"] == "geo"


def test_decision_market_creates_non_executable_strategy_candidate(db):
    _seed_project(db, "抖音跳转链接")
    package = _seed_evidence_package(db)
    result = recommendation.run_recommendation_analysis(db, 3, 19)

    issue_count = db.query(OptimizationIssue).count()
    action_count = db.query(OptimizationAction).count()
    experiment_count = db.query(OptimizationExperiment).count()
    draft = recommendation.create_decision_market_experiment_draft(db, result["id"], {"owner": "geo"})

    assert draft["status"] == "STRATEGY_CANDIDATE_CREATED"
    assert draft["blocked_materialization"] is True
    assert db.query(OptimizationIssue).count() == issue_count
    assert db.query(OptimizationAction).count() == action_count
    assert db.query(OptimizationExperiment).count() == experiment_count
    candidate = db.get(OptimizationStrategyCandidate, draft["strategy_candidate"]["id"])
    assert candidate is not None
    assert candidate.evidence_package_id == package.id
    assert candidate.experiment_id is None
    assert candidate.target_url == ""
    assert candidate.target_platform == "UNRESOLVED"
    assert candidate.intervention_type == "UNRESOLVED"
    assert candidate.effective_validation_status == "BLOCKED_PRODUCT_TRUTH"
    structured = dumps(draft["strategy_candidate"]["structured_payload"])
    assert "owned_content" not in structured
    assert "OFFICIAL_NEW_PAGE" not in structured
    assert draft["strategy_candidate"]["structured_payload"]["target_platform"] == "UNRESOLVED"
    assert draft["strategy_candidate"]["structured_payload"]["target_url"] == ""
    assert draft["strategy_candidate"]["structured_payload"]["product_truth_gate"]["status"] == "NEEDS_HUMAN_CONFIRMATION"
    assert draft["strategy_candidate"]["structured_payload"]["primary_metric"] in {
        "need_association_rate",
        "capability_recognition_rate",
        "candidate_capture_rate",
        "evidence_link_rate",
        "manual_review",
    }


def test_decision_market_requires_evidence_package_before_strategy_candidate(db):
    _seed_project(db, "抖音跳转链接")
    result = recommendation.run_recommendation_analysis(db, 3, 19)

    with pytest.raises(Exception) as exc:
        recommendation.create_decision_market_experiment_draft(db, result["id"], {"owner": "geo"})

    assert "Evidence Package" in str(exc.value)


def test_product_truth_unknown_blocks_strategy_acceptance(db):
    _seed_project(db, "抖音跳转链接")
    _seed_evidence_package(db)
    result = recommendation.run_recommendation_analysis(db, 3, 19)
    draft = recommendation.create_decision_market_experiment_draft(db, result["id"], {"owner": "geo"})

    with pytest.raises(Exception) as exc:
        service.review_strategy_candidate(db, draft["strategy_candidate"]["id"], StrategyCandidateReviewPayload(
            review_status="ACCEPTED_WITH_EDITS",
            reviewed_by="human",
            human_edited_payload={
                "intervention_type": "OFFICIAL_PAGE_UPDATE",
                "target_platform": "OFFICIAL_SITE",
                "target_url": "https://www.aifabu.com/card",
            },
        ))

    assert "Product Truth" in str(exc.value)


def test_unresolved_effective_payload_cannot_materialize_experiment(db):
    _seed_project(db, "抖音跳转链接")
    package = _seed_evidence_package(db)
    payload = {
        "observed_problem": "品牌还没有形成可执行策略。",
        "hypothesized_cause": "可能是渠道、资产和执行类型仍未确认。",
        "core_mechanism": "先完成人工审核，再决定执行路径。",
        "intervention_type": "UNRESOLVED",
        "target_platform": "UNRESOLVED",
        "target_asset": "UNRESOLVED",
        "target_url": "",
        "target_metric": "candidate_capture_rate",
        "validation_plan": {"minimum_sample_count": 2},
        "invalidating_result": "人工审核无法确定执行路径。",
    }
    candidate = OptimizationStrategyCandidate(
        project_id=3,
        evidence_package_id=package.id,
        target_url="",
        provider="test",
        model="test",
        prompt_version="test",
        prompt_text="",
        generated_at=datetime.utcnow(),
        generation_status="GENERATED",
        intervention_type="UNRESOLVED",
        target_platform="UNRESOLVED",
        target_asset="UNRESOLVED",
        target_content_type="UNRESOLVED",
        expected_primary_metric="candidate_capture_rate",
        source_package_id=package.id,
        original_llm_payload_json=dumps(payload),
        structured_payload_json=dumps(payload),
        human_edited_payload_json=dumps({}),
        effective_payload_json=dumps(payload),
        effective_payload_version="effective_payload.v1",
        effective_validation_status="VALIDATED",
        evidence_validation_status="VALIDATED",
        evidence_validation_errors_json=dumps([]),
        evidence_validation_warnings_json=dumps([]),
        hypothesis_validation_status="VALIDATED",
        hypothesis_validation_errors_json=dumps([]),
        hypothesis_validation_warnings_json=dumps([]),
        review_status="ACCEPTED",
    )
    db.add(candidate)
    db.commit()

    with pytest.raises(Exception) as exc:
        strategy_to_experiment_plan(db, candidate.id)

    assert "unresolved execution fields" in str(exc.value)


def test_recommendation_reason_claims_can_be_reviewed(db):
    _seed_project(db, "抖音跳转链接")
    result = recommendation.run_recommendation_analysis(db, 3, 19)

    reasons = recommendation.list_recommendation_reason_claims(db, result["id"])
    assert reasons

    reviewed = recommendation.review_recommendation_reason_claim(db, reasons[0]["id"], {
        "review_status": "CONFIRMED",
        "reviewer": "geo",
        "reason_type": "CAPABILITY",
    })

    assert reviewed["review_status"] == "CONFIRMED"
    assert reviewed["reason_type"] == "CAPABILITY"
    assert reviewed["human_labels"]["reviewer"] == "geo"


def test_recommendation_entities_can_be_reviewed_without_losing_choice_boundary(db):
    _seed_project(db, "抖音跳转链接")
    result = recommendation.run_recommendation_analysis(db, 3, 19)

    entities = recommendation.list_recommendation_entities(db, result["id"])
    assert entities

    reviewed = recommendation.review_recommendation_entity(db, entities[0]["id"], {
        "entity_role": "AUTHORITY",
        "is_choice_candidate": False,
    })

    assert reviewed["entity_role"] == "AUTHORITY"
    assert reviewed["entity_role_label"] == "规则/权威方"
    assert reviewed["is_choice_candidate"] is False
    assert reviewed["source"] == "HUMAN_REVIEWED"


def test_strategy_experiment_plan_exposes_p2_verification_boundary(db):
    _seed_project(db, "抖音跳转链接")
    payload = {
        "observed_problem": "目标页未形成稳定官方引用。",
        "hypothesized_cause": "页面缺少可被引用的定义、步骤和失败排查信息。",
        "core_mechanism": "强化现有页面对抖音跳转链接意图的直接承接。",
        "intervention_type": "OFFICIAL_PAGE_UPDATE",
        "target_platform": "OFFICIAL_SITE",
        "target_url": "https://www.aifabu.com/card",
        "target_metric": "target_page_retrieval_rate",
        "changed_features": [
            {"feature": "DIRECT_ANSWER_BLOCK", "description": "新增直接回答区块"},
            {"feature": "TROUBLESHOOTING_FAQ", "description": "新增失败排查"},
        ],
        "controlled_variables": ["collection_prompt", "target_url", "product_capabilities"],
        "validation_plan": {
            "entry_observed_condition": "同一问题和同一采集环境复采。",
            "sustained_improvement_condition": "目标页进入合格检索候选。",
        },
        "invalidating_result": "复采后目标页仍未进入候选。",
    }
    package = OptimizationEvidencePackage(
        id=31,
        project_id=3,
        prompt_id=19,
        version=1,
        source_run_ids_json=dumps([173, 174]),
        target_page_urls_json=dumps(["https://www.aifabu.com/card"]),
        package_payload_json=dumps({
            "retrieval_metrics_status": "ok",
            "metrics": [
                {
                    "metric_name": "target_page_retrieval_rate",
                    "calculation_status": "ok",
                    "numerator": 0,
                    "denominator": 2,
                    "value": 0,
                }
            ],
        }),
        package_hash="strategy-plan-p2",
    )
    candidate = OptimizationStrategyCandidate(
        id=41,
        project_id=3,
        evidence_package_id=31,
        target_url="https://www.aifabu.com/card",
        structured_payload_json=dumps(payload),
        effective_payload_json=dumps(payload),
        effective_payload_version="test",
        effective_validation_status="VALIDATED",
        evidence_validation_status="VALIDATED",
        hypothesis_validation_status="VALIDATED",
        review_status="ACCEPTED",
        reviewed_by="human",
    )
    db.add_all([package, candidate])
    db.commit()

    plan = strategy_to_experiment_plan(db, 41)
    experiment = db.get(OptimizationExperiment, plan["experiment_id"])

    assert plan["readiness_status"] == "BLOCKED"
    assert plan["plan_payload"]["comparability_status"] == "INSUFFICIENT_CONTEXT"
    assert "黑盒 AI 环境" in plan["plan_payload"]["known_environment_audit"]["boundary_note"]
    assert "DIRECT_ANSWER_BLOCK" in plan["plan_payload"]["controlled_intervention"]["allowed_changes"]
    assert "collection_prompt" in plan["plan_payload"]["controlled_intervention"]["forbidden_changes"]
    assert experiment is not None
    assert experiment.comparability_status == "INSUFFICIENT_CONTEXT"
    assert "一个主要机制假设" in experiment.controlled_intervention_json


def test_decision_passage_support_summarizes_answer_claim_alignment(db):
    _seed_project(db, "抖音跳转链接")
    result = recommendation.run_recommendation_analysis(db, 3, 19)
    doc = SourceDocument(
        id=501,
        url="https://example.com/shangjiajia",
        original_url="https://example.com/shangjiajia",
        domain="example.com",
        title="商加加外链制作教程",
        fetch_status="SUCCESS",
        clean_text="可通过商加加外链等第三方工具，填写目标微信信息自动生成加密短链。",
    )
    answer_claim = AnswerClaim(
        id=601,
        run_id=173,
        claim_index=1,
        raw_text="可通过商加加外链等第三方工具，填写目标微信信息自动生成加密短链。",
        claim_type="操作步骤",
        citation_anchor=1,
        citation_ids_json=dumps([1]),
    )
    alignment = PassageAlignment(
        id=701,
        answer_claim_id=601,
        run_id=173,
        citation_id=1,
        source_document_id=501,
        passage_index=1,
        alignment_level="L1_EXACT_OVERLAP",
        alignment_method="exact_substring_15chars",
        score=1.0,
        evidence="Exact match",
    )
    db.add_all([doc, answer_claim, alignment])
    db.commit()

    support = recommendation.list_passage_support_summary(db, result["id"])

    assert support["eligibility"] == "PASSAGE_ALIGNMENT_AVAILABLE"
    assert support["metrics"]["direct_text_match_rate"]["numerator"] == 1
    assert support["rows"][0]["alignment_status_label"] == "原文精确对齐"
    assert "不是因果证明" in support["rows"][0]["support_boundary"]


def test_claim_review_preserves_machine_payload(db):
    _seed_project(db, "抖音跳转链接用什么工具")
    result = recommendation.run_recommendation_analysis(db, 3, 19)
    claim = recommendation.list_recommendation_claims(db, result["id"])[0]

    reviewed = recommendation.review_recommendation_claim(db, claim["id"], {"review_status": "CONFIRMED", "reviewer": "human"})

    assert reviewed["review_status"] == "CONFIRMED"
    assert reviewed["answer_span"] == claim["answer_span"]
    assert reviewed["human_payload"]["reviewer"] == "human"


def test_choice_slot_requires_alternative_choice_space(db):
    value, _, _ = recommendation._answer_has_choice_slot(
        "抖音跳转链接怎么设置",
        "进入抖音后台，点击分享，然后复制链接。",
        [],
    )
    assert value is False

    value, span, _ = recommendation._answer_has_choice_slot(
        "抖音跳转链接怎么设置",
        "可以直接复制官方链接，也可以使用短链服务生成跳转链接。",
        [],
    )
    assert value is True
    assert "短链服务" in span


def test_recommendation_speech_act_is_not_keyword_only(db):
    assert recommendation._classify_recommendation("网上很多人推荐天天外链，但这种方式存在较高风险") == "MENTION_ONLY"
    assert recommendation._classify_recommendation("如果主要做微信私域承接，可以优先考虑天天外链") == "POSITIVE_RECOMMENDATION"


def test_product_truth_is_manual_and_unknown_by_default(db):
    _seed_project(db, "抖音跳转链接用什么工具")
    result = recommendation.run_recommendation_analysis(db, 3, 19)

    truths = result["decision_market"]["product_truth"]["truths"]
    assert truths
    assert all(item["product_truth_status"] == "UNKNOWN" for item in truths)
    assert result["decision_market"]["action_package"]["product_truth_gate"]["status"] == "NEEDS_HUMAN_CONFIRMATION"

    reviewed = recommendation.upsert_target_brand_capability_truth(db, 3, {
        "capability_label": truths[0]["capability_label"],
        "product_truth_status": "SUPPORTED",
        "truth_source": "MANUAL_CONFIRMED",
        "reviewed_by": "geo",
    })
    assert reviewed["product_truth_status"] == "SUPPORTED"


def test_noisy_sentence_fragments_are_not_entities():
    assert recommendation._is_noisy_entity_name("2026年平台")
    assert recommendation._is_noisy_entity_name("进入工具")
    assert recommendation._is_noisy_entity_name("遇到这类卡片")
    assert recommendation._is_noisy_entity_name("链接会自动转为卡片")
    assert not recommendation._is_noisy_entity_name("私信卡片")
