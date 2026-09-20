from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    BrowserMonitorRun,
    BrowserMonitorTask,
    Competitor,
    EvidenceAlignment,
    OptimizationAction,
    OptimizationEvidencePackage,
    OptimizationExperiment,
    OptimizationIssue,
    OptimizationStrategyCandidate,
    Organization,
    Project,
    Prompt,
    PromptAnalysisRun,
    RecommendationEvent,
    SourceClaim,
    SourceDocument,
    TargetBrandCapabilityTruth,
    WorkflowConfirmation,
)
from app.modules.optimization.schemas import StrategyCandidateReviewPayload
from app.modules.optimization.service import (
    CURRENT_STEP7_CANDIDATE_ORIGIN,
    CURRENT_STEP7_GENERATOR_FAMILY,
    CURRENT_STEP7_MODEL,
    CURRENT_STEP7_STRATEGY_SCHEMA_VERSION,
    FORMAL_V1_1_INPUT_VERSION,
    VERTICAL_SLICE_VERSION,
    review_strategy_candidate,
    strategy_to_experiment_plan,
)
from app.modules.optimization.workflow import (
    batch_confirm_alignments,
    build_continue_review_context,
    resolve_decision_market_entity,
    review_queue,
    workflow_status,
)
from app.modules.optimization.evidence_alignment import (
    _alignment_review_signature,
    _review_carry_forward_index,
)
from app.services.serialization import dumps, loads


def _ready_strategy_workflow_base(db):
    project = Project(id=30, organization_id=1, name="当前态测试", brand_name="目标品牌")
    prompt = Prompt(id=300, project_id=30, prompt_text="短链推荐", title="短链推荐")
    task = BrowserMonitorTask(id=3000, project_id=30, status="success")
    run = BrowserMonitorRun(
        id=3001,
        task_id=3000,
        project_id=30,
        prompt_id=300,
        status="success",
        answer_text="推荐竞品短链。",
    )
    event = RecommendationEvent(
        id=3002,
        project_id=30,
        prompt_id=300,
        run_id=3001,
        answer_hash="hash-current",
        entity_text="竞品短链",
        speech_act="RECOMMEND",
        recommendation_strength="STRONG",
        polarity="POSITIVE",
        answer_span="推荐竞品短链",
        review_status="HUMAN_CONFIRMED",
    )
    truth = TargetBrandCapabilityTruth(
        id=3003,
        project_id=30,
        capability_key="点击统计",
        capability_label="点击统计",
        product_truth_status="SUPPORTED",
    )
    package = OptimizationEvidencePackage(
        id=3004,
        project_id=30,
        prompt_id=300,
        version=1,
        source_run_ids_json=dumps([3001]),
        package_hash="current-state-package",
        status="active",
    )
    db.add_all([Organization(id=30, name="测试组织"), project, prompt, task, run, event, truth, package])
    db.commit()
    return project, prompt, package


def _strategy_candidate(
    candidate_id: int,
    project_id: int,
    package_id: int,
    *,
    review_status: str,
    experiment_id: int | None = None,
    reviewed_by: str = "",
    prompt_id: int = 300,
    package_version: int = 1,
    origin: str = CURRENT_STEP7_CANDIDATE_ORIGIN,
    model: str = CURRENT_STEP7_MODEL,
    prompt_version: str = VERTICAL_SLICE_VERSION,
    payload_overrides: dict | None = None,
) -> OptimizationStrategyCandidate:
    payload = {
        "candidate_origin": origin,
        "generator_family": CURRENT_STEP7_GENERATOR_FAMILY,
        "strategy_schema_version": CURRENT_STEP7_STRATEGY_SCHEMA_VERSION,
        "strategy_context": {
            "prompt_id": prompt_id,
            "evidence_package_id": package_id,
            "evidence_package_version": package_version,
            "analysis_version": VERTICAL_SLICE_VERSION,
            "strategy_input_version": FORMAL_V1_1_INPUT_VERSION,
            "answer_binding_mode": "ANSWER_BINDING_V1_1_ON",
            "use_answer_binding_v1_1": True,
            "strategy_schema_version": CURRENT_STEP7_STRATEGY_SCHEMA_VERSION,
            "generator_family": CURRENT_STEP7_GENERATOR_FAMILY,
            "candidate_origin": origin,
        },
        "gap_item_ids": ["gap-click-stat"],
        "benchmark_evidence_ids": [801],
        "target_decision_change": "让 AI 在短链推荐中把目标品牌与点击统计能力建立关联",
        "priority_capabilities": [{"capability_label": "点击统计", "gap_item_id": "gap-click-stat"}],
        "strategic_hypothesis": "如果目标品牌资产补齐点击统计能力表达，后续回答更可能识别该能力。",
        "intervention_mechanism": "补齐目标品牌事实到 AI 决策理由之间的可引用表达。",
        "primary_intervention_path": "FIRST_PARTY_BRAND_CAPABILITY_EXPRESSION",
        "planned_channels": [{"channel": "OFFICIAL_SITE", "intervention_priority": "PRIMARY"}],
        "channel_roles": {"OFFICIAL_SITE": {"channel_role": "承载目标品牌自己的能力事实表达"}},
        "asset_direction": {"channel": "OFFICIAL_SITE", "asset_operation": "CREATE_NEW"},
        "execution_sequence": [{"step": 1, "name": "确认执行资产"}],
        "required_signals": [{"signal": "目标品牌支持点击统计", "evidence_requirement": "目标品牌事实"}],
        "non_goals": ["不在第 7 步选择具体 URL"],
        "attribution_intent": {"primary_capability": "点击统计", "attribution_scope": "SINGLE_CAPABILITY"},
        "product_truth_gate": {"status": "READY_FOR_STRATEGY_REVIEW"},
        "intervention_type": "UNRESOLVED",
        "target_platform": "UNRESOLVED",
        "target_object": "UNRESOLVED",
        "target_asset": "UNRESOLVED",
        "target_content_type": "UNRESOLVED",
        "recommended_action": "补齐点击统计表达",
    }
    payload.update(payload_overrides or {})
    return OptimizationStrategyCandidate(
        id=candidate_id,
        project_id=project_id,
        evidence_package_id=package_id,
        source_package_id=package_id,
        experiment_id=experiment_id,
        structured_payload_json=dumps(payload),
        effective_payload_json=dumps(payload) if review_status in {"ACCEPTED", "ACCEPTED_WITH_EDITS"} else dumps({}),
        effective_payload_version="effective_payload.v1" if review_status in {"ACCEPTED", "ACCEPTED_WITH_EDITS"} else "",
        effective_validation_status="PENDING_HUMAN_CHANNEL_REVIEW" if review_status in {"ACCEPTED", "ACCEPTED_WITH_EDITS"} else "PENDING",
        evidence_validation_status="VALIDATED",
        hypothesis_validation_status="VALIDATED",
        review_status=review_status,
        reviewed_by=reviewed_by,
        model=model,
        prompt_version=prompt_version,
    )


def _session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_validation_failed_events_do_not_create_empty_review_loop():
    db = _session()
    try:
        project = Project(id=3, organization_id=1, name="爱短链品牌监测", brand_name="爱短链")
        prompt = Prompt(id=40, project_id=3, prompt_text="抖音跳转微信怎么做", title="抖音跳转微信怎么做")
        task = BrowserMonitorTask(id=1, project_id=3, status="success")
        run = BrowserMonitorRun(
            id=401,
            task_id=1,
            project_id=3,
            prompt_id=40,
            status="success",
            answer_text="可通过第三方工具完成跳转配置。",
        )
        truth = TargetBrandCapabilityTruth(
            project_id=3,
            capability_key="抖音跳转微信",
            capability_label="抖音跳转微信",
            product_truth_status="SUPPORTED",
        )
        competitor = Competitor(id=1, project_id=3, name="商加加", aliases_json="[]")
        events = [
            RecommendationEvent(
                project_id=3,
                prompt_id=40,
                run_id=401,
                answer_hash=f"hash-{idx}",
                entity_text="商加加",
                speech_act="INCLUDE_AS_OPTION",
                recommendation_strength="MODERATE",
                polarity="POSITIVE",
                answer_span="可通过商加加等第三方工具",
                review_status="VALIDATION_FAILED",
            )
            for idx in range(4)
        ]
        unknown_event = RecommendationEvent(
            project_id=3,
            prompt_id=40,
            run_id=401,
            answer_hash="hash-unknown",
            entity_text="未知短链工具",
            speech_act="INCLUDE_AS_OPTION",
            recommendation_strength="MODERATE",
            polarity="POSITIVE",
            answer_span="也可以考虑未知短链工具",
            review_status="VALIDATION_FAILED",
        )
        db.add_all([Organization(id=1, name="测试组织"), project, prompt, task, run, truth, competitor, *events, unknown_event])
        db.commit()

        queue = review_queue(db, project, 40)
        status = workflow_status(db, project, 40)

        assert queue["status"] == "READY"
        assert queue["unique_events"] == []
        assert queue["alignments"] == []
        assert status["pending_review_steps"] == 0
        assert status["all_reviews_done"] is True
        assert status["answer_semantic_done"] is False
        assert status["ready_to_continue"] is False
        event_step = next(step for step in status["steps"] if step["key"] == "event_review")
        assert event_step["done"] is True
        assert event_step["detail"] == "无可审核事件，无需审核"
        labels = {step["key"]: step["label"] for step in status["steps"]}
        details = {step["key"]: step["detail"] for step in status["steps"]}
        assert labels["evidence"] == "证据分析"
        assert labels["gap"] == "缺口诊断"
        assert labels["action"] == "策略确认"
        assert "SUPPORTS" not in details["evidence"]
        assert "Action" not in details["experiment"]

        context = build_continue_review_context(db, project, 40, [401])
        assert context["answer_samples"][0]["run_id"] == 401
        assert "第三方工具完成跳转配置" in context["answer_samples"][0]["answer_excerpt"]
        assert context["event_status_counts"] == {"VALIDATION_FAILED": 5}
        assert len(context["event_diagnostics"]) == 5
        assert context["event_diagnostics"][0]["review_status"] == "VALIDATION_FAILED"
        entities = context["answer_samples"][0]["detected_entities"]
        assert {"entity_text": "商加加", "relation": "CONFIRMED_COMPETITOR", "relation_label": "已确认竞品", "speech_acts": ["INCLUDE_AS_OPTION"], "review_statuses": ["VALIDATION_FAILED"]} in entities
        assert any(item["entity_text"] == "未知短链工具" and item["relation_label"] == "待确认对象" for item in entities)
        assert "先核对答案样本" in context["review_instruction"]
    finally:
        db.close()


def test_review_queue_groups_duplicate_run_level_alignments_and_batch_confirms_group():
    db = _session()
    try:
        project = Project(id=3, organization_id=1, name="爱短链品牌监测", brand_name="爱短链")
        prompt = Prompt(id=40, project_id=3, prompt_text="长链接缩短", title="长链接缩短")
        task = BrowserMonitorTask(id=1, project_id=3, status="success")
        run_a = BrowserMonitorRun(id=401, task_id=1, project_id=3, prompt_id=40, status="success", answer_text="可以优先考虑小码短链接。")
        run_b = BrowserMonitorRun(id=402, task_id=1, project_id=3, prompt_id=40, status="success", answer_text="可以优先考虑小码短链接。")
        event_a = RecommendationEvent(
            id=501,
            project_id=3,
            prompt_id=40,
            run_id=401,
            answer_hash="hash-a",
            entity_text="小码短链接",
            speech_act="RECOMMEND",
            recommendation_strength="STRONG",
            polarity="POSITIVE",
            answer_span="小码短链接自带点击统计",
            review_status="HUMAN_CONFIRMED",
        )
        event_b = RecommendationEvent(
            id=502,
            project_id=3,
            prompt_id=40,
            run_id=402,
            answer_hash="hash-b",
            entity_text="小码短链接",
            speech_act="RECOMMEND",
            recommendation_strength="STRONG",
            polarity="POSITIVE",
            answer_span="小码短链接自带点击统计",
            review_status="HUMAN_CONFIRMED",
        )
        doc = SourceDocument(id=601, url="https://zhuanlan.zhihu.com/p/test", canonical_url="https://zhuanlan.zhihu.com/p/test", domain="zhuanlan.zhihu.com", fetch_status="SUCCESS", clean_text="小码短链接可以查看点击次数。")
        claim = SourceClaim(
            id=701,
            project_id=3,
            source_document_id=601,
            normalized_claim="小码短链接可以查看每个链接的点击次数",
            source_span="小码短链接可以查看每个链接的点击次数。",
            review_status="MACHINE_GROUNDED",
        )
        duplicate_claim = SourceClaim(
            id=702,
            project_id=3,
            source_document_id=601,
            normalized_claim="小码短链接可以查看每个链接的点击次数",
            source_span="小码短链接可以查看每个链接的点击次数。",
            review_status="MACHINE_GROUNDED",
        )
        alignment_a = EvidenceAlignment(
            id=801,
            project_id=3,
            prompt_id=40,
            run_id=401,
            recommendation_event_id=501,
            recommendation_reason_id="answer_unit:1001:binding:2001",
            source_document_id=601,
            source_claim_id=701,
            relation="SUPPORTS",
            machine_payload_json=dumps({
                "semantic_reason_key": "小码短链接自带点击统计|ENTITY_SPECIFIC|小码短链接",
                "observed_run_ids": [401, 402],
                "reason_source": "ANSWER_DECISION_BINDING",
            }),
            review_status="MACHINE_GROUNDED",
        )
        alignment_b = EvidenceAlignment(
            id=802,
            project_id=3,
            prompt_id=40,
            run_id=402,
            recommendation_event_id=502,
            recommendation_reason_id="answer_unit:1002:binding:2002",
            source_document_id=601,
            source_claim_id=701,
            relation="SUPPORTS",
            machine_payload_json=dumps({
                "semantic_reason_key": "小码短链接自带点击统计|ENTITY_SPECIFIC|小码短链接",
                "observed_run_ids": [401, 402],
                "reason_source": "ANSWER_DECISION_BINDING",
            }),
            review_status="MACHINE_GROUNDED",
        )
        alignment_c = EvidenceAlignment(
            id=803,
            project_id=3,
            prompt_id=40,
            run_id=401,
            recommendation_event_id=501,
            recommendation_reason_id="answer_unit:1001:binding:2001",
            source_document_id=601,
            source_claim_id=702,
            relation="SUPPORTS",
            machine_payload_json=dumps({
                "semantic_reason_key": "小码短链接自带点击统计|ENTITY_SPECIFIC|小码短链接",
                "observed_run_ids": [401, 402],
                "reason_source": "ANSWER_DECISION_BINDING",
            }),
            review_status="MACHINE_GROUNDED",
        )
        db.add_all([Organization(id=1, name="测试组织"), project, prompt, task, run_a, run_b, event_a, event_b, doc, claim, duplicate_claim, alignment_a, alignment_b, alignment_c])
        db.commit()

        queue = review_queue(db, project, 40)

        assert queue["status"] == "READY"
        assert queue["unique_events"] == []
        assert len(queue["alignments"]) == 1
        group = queue["alignments"][0]
        assert group["review_group_key"]
        assert group["alignment_ids"] == [801, 802, 803]
        assert group["alignment_count"] == 3
        assert group["run_ids"] == [401, 402]
        assert group["run_count"] == 2
        assert group["semantic_observed_run_ids"] == [401, 402]
        assert group["semantic_observed_run_count"] == 2
        assert group["reason_text"] == "小码短链接自带点击统计"
        assert group["source_document_id"] == 601
        assert group["source_claim_id"] == 701
        assert group["source_claim_ids"] == [701, 702]
        status_before = workflow_status(db, project, 40)
        evidence_step_before = next(step for step in status_before["steps"] if step["key"] == "evidence")
        evidence_review_step_before = next(step for step in status_before["steps"] if step["key"] == "evidence_review")
        assert evidence_step_before["detail"] == "1 组支持证据"
        assert evidence_review_step_before["detail"] == "0/1 组已审"
        assert status_before["support_alignment_row_count"] == 3
        assert status_before["support_review_group_count"] == 1

        result = batch_confirm_alignments(db, group["alignment_ids"], reviewer="human")

        assert result["updated"] == 3
        refreshed = db.query(EvidenceAlignment).order_by(EvidenceAlignment.id).all()
        assert [row.review_status for row in refreshed] == ["HUMAN_CONFIRMED", "HUMAN_CONFIRMED", "HUMAN_CONFIRMED"]
        assert [row.reviewer for row in refreshed] == ["human", "human", "human"]
        status_after = workflow_status(db, project, 40)
        evidence_review_step_after = next(step for step in status_after["steps"] if step["key"] == "evidence_review")
        assert evidence_review_step_after["detail"] == "1/1 组已审"
        assert status_after["support_alignment_reviewed_row_count"] == 3
        assert status_after["support_reviewed_group_count"] == 1
    finally:
        db.close()


def test_evidence_review_carry_forward_uses_semantic_signature_not_source_claim_id():
    db = _session()
    try:
        project = Project(id=3, organization_id=1, name="爱短链品牌监测", brand_name="爱短链")
        prompt = Prompt(id=40, project_id=3, prompt_text="长链接缩短", title="长链接缩短")
        task = BrowserMonitorTask(id=1, project_id=3, status="success")
        run = BrowserMonitorRun(id=401, task_id=1, project_id=3, prompt_id=40, status="success", answer_text="可以优先考虑小码短链接。")
        event = RecommendationEvent(
            id=501,
            project_id=3,
            prompt_id=40,
            run_id=401,
            answer_hash="hash-a",
            entity_text="小码短链接",
            speech_act="RECOMMEND",
            recommendation_strength="STRONG",
            polarity="POSITIVE",
            answer_span="小码短链接自带点击统计",
            review_status="HUMAN_CONFIRMED",
        )
        doc = SourceDocument(id=601, url="https://zhuanlan.zhihu.com/p/test", canonical_url="https://zhuanlan.zhihu.com/p/test", domain="zhuanlan.zhihu.com", fetch_status="SUCCESS")
        old_claim = SourceClaim(
            id=701,
            project_id=3,
            source_document_id=601,
            normalized_claim="小码短链接可以查看每个链接的点击次数",
            source_span="小码短链接可以查看每个链接的点击次数。",
            review_status="MACHINE_GROUNDED",
        )
        new_duplicate_claim = SourceClaim(
            id=702,
            project_id=3,
            source_document_id=601,
            normalized_claim="小码短链接可以查看每个链接的点击次数",
            source_span="小码短链接可以查看每个链接的点击次数。",
            review_status="MACHINE_GROUNDED",
        )
        reviewed_alignment = EvidenceAlignment(
            id=801,
            project_id=3,
            prompt_id=40,
            run_id=401,
            recommendation_event_id=501,
            recommendation_reason_id="answer_unit:1001:binding:2001",
            source_document_id=601,
            source_claim_id=701,
            relation="SUPPORTS",
            machine_payload_json=dumps({
                "semantic_reason_key": "小码短链接自带点击统计|ENTITY_SPECIFIC|小码短链接",
                "reason_source": "ANSWER_DECISION_BINDING",
            }),
            review_status="HUMAN_CONFIRMED",
            reviewer="human",
        )
        db.add_all([Organization(id=1, name="测试组织"), project, prompt, task, run, event, doc, old_claim, new_duplicate_claim, reviewed_alignment])
        db.commit()

        carry_index = _review_carry_forward_index(db, 3, 40)
        new_alignment = EvidenceAlignment(
            project_id=3,
            prompt_id=40,
            run_id=401,
            recommendation_event_id=501,
            recommendation_reason_id="answer_unit:2002:binding:3003",
            source_document_id=601,
            source_claim_id=702,
            relation="SUPPORTS",
        )
        signature = _alignment_review_signature(
            new_alignment,
            new_duplicate_claim,
            relation="SUPPORTS",
            payload={"semantic_reason_key": "小码短链接自带点击统计|ENTITY_SPECIFIC|小码短链接"},
        )
        relation_mismatch = _alignment_review_signature(
            new_alignment,
            new_duplicate_claim,
            relation="RELATED",
            payload={"semantic_reason_key": "小码短链接自带点击统计|ENTITY_SPECIFIC|小码短链接"},
        )

        assert carry_index[signature]["review_status"] == "HUMAN_CONFIRMED"
        assert carry_index[signature]["source_alignment_id"] == 801
        assert relation_mismatch not in carry_index
    finally:
        db.close()


def test_decision_market_entity_resolution_repairs_validation_failed_choice_event():
    db = _session()
    try:
        project = Project(id=3, organization_id=1, name="爱短链品牌监测", brand_name="爱短链")
        prompt = Prompt(id=40, project_id=3, prompt_text="长链接缩短", title="长链接缩短")
        task = BrowserMonitorTask(id=1, project_id=3, status="success")
        run = BrowserMonitorRun(
            id=401,
            task_id=1,
            project_id=3,
            prompt_id=40,
            status="success",
            answer_text="可以优先考虑小码短链接。",
        )
        event = RecommendationEvent(
            project_id=3,
            prompt_id=40,
            run_id=401,
            answer_hash="hash-xm",
            entity_text="小码短链接",
            speech_act="RECOMMENDATION",
            recommendation_strength="STRONG",
            polarity="POSITIVE",
            answer_span="可以优先考虑小码短链接",
            review_status="VALIDATION_FAILED",
        )
        db.add_all([Organization(id=1, name="测试组织"), project, prompt, task, run, event])
        db.commit()

        before = workflow_status(db, project, 40)
        before_answer = next(step for step in before["steps"] if step["key"] == "answer_semantic")
        assert before_answer["done"] is False

        result = resolve_decision_market_entity(db, project, 40, "小码短链接", "CONFIRMED_COMPETITOR")

        assert result["status"] == "CONFIRMED_COMPETITOR"
        assert result["updated_events"] == 1
        assert db.query(Competitor).filter(Competitor.project_id == 3, Competitor.name == "小码短链接").first()
        repaired_event = db.query(RecommendationEvent).filter(RecommendationEvent.entity_text == "小码短链接").one()
        assert repaired_event.review_status == "HUMAN_CONFIRMED"
        assert repaired_event.entity_type == "BRAND"
        after = workflow_status(db, project, 40)
        after_answer = next(step for step in after["steps"] if step["key"] == "answer_semantic")
        assert after_answer["done"] is True
        assert after_answer["detail"] == "1 组有效选择事件"
        assert after["answer_semantic_done"] is True
    finally:
        db.close()


def test_rejected_decision_market_entity_does_not_become_valid_choice_event():
    db = _session()
    try:
        project = Project(id=3, organization_id=1, name="爱短链品牌监测", brand_name="爱短链")
        prompt = Prompt(id=40, project_id=3, prompt_text="长链接缩短", title="长链接缩短")
        task = BrowserMonitorTask(id=1, project_id=3, status="success")
        run = BrowserMonitorRun(
            id=401,
            task_id=1,
            project_id=3,
            prompt_id=40,
            status="success",
            answer_text="这里不是品牌推荐。",
        )
        event = RecommendationEvent(
            project_id=3,
            prompt_id=40,
            run_id=401,
            answer_hash="hash-reject",
            entity_text="普通教程",
            speech_act="RECOMMENDATION",
            recommendation_strength="STRONG",
            polarity="POSITIVE",
            answer_span="普通教程",
            review_status="VALIDATION_FAILED",
        )
        db.add_all([Organization(id=1, name="测试组织"), project, prompt, task, run, event])
        db.commit()

        result = resolve_decision_market_entity(db, project, 40, "普通教程", "REJECTED")

        assert result["status"] == "REJECTED"
        rejected_event = db.query(RecommendationEvent).filter(RecommendationEvent.entity_text == "普通教程").one()
        assert rejected_event.review_status == "HUMAN_REJECTED"
        after = workflow_status(db, project, 40)
        after_answer = next(step for step in after["steps"] if step["key"] == "answer_semantic")
        assert after_answer["done"] is False
        assert "0 组有效选择事件" in after_answer["detail"]
        assert after["ready_to_continue"] is False
    finally:
        db.close()


def test_step7_current_state_uses_bound_strategy_candidate_not_history():
    db = _session()
    try:
        project, prompt, package = _ready_strategy_workflow_base(db)
        issue = OptimizationIssue(id=3100, project_id=project.id, prompt_id=prompt.id, issue_type="CONTENT_GAP")
        action = OptimizationAction(id=3101, issue_id=3100, action_type="content_update")
        historical_experiment = OptimizationExperiment(id=3102, action_id=3101, status="draft", target_prompt_scope_json=dumps([prompt.id]))
        historical = _strategy_candidate(
            3103,
            project.id,
            package.id,
            review_status="ACCEPTED_WITH_EDITS",
            experiment_id=historical_experiment.id,
            reviewed_by="phase4_audit",
            origin="AUDIT",
        )
        current_pending = _strategy_candidate(3104, project.id, package.id, review_status="PENDING_REVIEW")
        legacy_confirmation = WorkflowConfirmation(
            project_id=project.id,
            prompt_id=prompt.id,
            step_key="action",
            decision_status="CONFIRMED",
            decision_note="旧动作确认，没有 StrategyCandidate 上下文",
            reviewer="human",
        )
        db.add_all([issue, action, historical_experiment, historical, current_pending, legacy_confirmation])
        db.commit()

        status = workflow_status(db, project, prompt.id)
        action_step = next(step for step in status["steps"] if step["key"] == "action")
        experiment_step = next(step for step in status["steps"] if step["key"] == "experiment")

        assert status["strategy_step_status"] == "PENDING_REVIEW"
        assert status["current_strategy_candidate_ids"] == [3104]
        assert status["current_strategy_confirmed"] is False
        assert status["historical_strategy_candidate_count"] == 1
        assert status["legacy_action_confirmation_ignored"] is True
        assert action_step["label"] == "策略确认"
        assert action_step["done"] is False
        assert "待人工审核" in action_step["detail"]
        assert status["execution_step_status"] == "LOCKED"
        assert status["current_experiment_id"] is None
        assert status["historical_experiment_count"] == 1
        assert experiment_step["label"] == "实验方案落地"
        assert experiment_step["done"] is False
        assert experiment_step["detail"] == "等待当前策略确认"
    finally:
        db.close()


def test_strategy_review_writes_current_step7_context_and_unlocks_step8():
    db = _session()
    try:
        project, prompt, package = _ready_strategy_workflow_base(db)
        candidate = _strategy_candidate(3201, project.id, package.id, review_status="PENDING_REVIEW")
        db.add(candidate)
        db.commit()

        before = workflow_status(db, project, prompt.id)
        assert before["strategy_step_status"] == "PENDING_REVIEW"

        reviewed = review_strategy_candidate(
            db,
            candidate.id,
            StrategyCandidateReviewPayload(
                review_status="ACCEPTED",
                reviewed_by="human",
                review_note="当前策略确认",
            ),
        )

        assert reviewed["review_status"] == "ACCEPTED"
        assert reviewed["effective_validation_status"] == "PENDING_HUMAN_CHANNEL_REVIEW"
        after = workflow_status(db, project, prompt.id)
        action_step = next(step for step in after["steps"] if step["key"] == "action")
        experiment_step = next(step for step in after["steps"] if step["key"] == "experiment")

        assert after["strategy_step_status"] == "CONFIRMED"
        assert after["current_strategy_candidate_id"] == candidate.id
        assert after["current_effective_payload_valid"] is True
        assert action_step["done"] is True
        assert after["execution_step_status"] == "READY_TO_CREATE"
        assert experiment_step["done"] is False
        assert "可进入实验方案落地" in experiment_step["detail"]

        confirmation = db.query(WorkflowConfirmation).filter(
            WorkflowConfirmation.project_id == project.id,
            WorkflowConfirmation.prompt_id == prompt.id,
            WorkflowConfirmation.step_key == "action",
        ).one()
        context = loads(confirmation.decision_note, {})
        assert context["strategy_candidate_id"] == candidate.id
        assert context["evidence_package_id"] == package.id
        assert context["prompt_id"] == prompt.id
    finally:
        db.close()


def test_step8_complete_only_for_current_confirmed_candidate_experiment():
    db = _session()
    try:
        project, prompt, package = _ready_strategy_workflow_base(db)
        issue = OptimizationIssue(id=3300, project_id=project.id, prompt_id=prompt.id, issue_type="CONTENT_GAP")
        action = OptimizationAction(id=3301, issue_id=3300, action_type="content_update")
        experiment = OptimizationExperiment(id=3302, action_id=3301, status="draft", target_prompt_scope_json=dumps([prompt.id]))
        candidate = _strategy_candidate(
            3303,
            project.id,
            package.id,
            review_status="ACCEPTED",
            experiment_id=experiment.id,
            reviewed_by="human",
        )
        confirmation = WorkflowConfirmation(
            project_id=project.id,
            prompt_id=prompt.id,
            step_key="action",
            decision_status="CONFIRMED",
            decision_note=dumps({
                "semantic": "STEP7_STRATEGY_CONFIRMATION",
                "strategy_candidate_id": candidate.id,
                "evidence_package_id": package.id,
                "prompt_id": prompt.id,
            }),
            reviewer="human",
        )
        db.add_all([issue, action, experiment, candidate, confirmation])
        db.commit()

        status = workflow_status(db, project, prompt.id)
        experiment_step = next(step for step in status["steps"] if step["key"] == "experiment")

        assert status["strategy_step_status"] == "CONFIRMED"
        assert status["execution_step_status"] == "CREATED"
        assert status["current_action_id"] == action.id
        assert status["current_experiment_id"] == experiment.id
        assert experiment_step["done"] is True
        assert "当前实验草案" in experiment_step["detail"]
    finally:
        db.close()


def test_reviewed_workflow_with_upstream_signal_without_current_v1_1_input_needs_current_analysis():
    db = _session()
    try:
        project, prompt, package = _ready_strategy_workflow_base(db)
        legacy_pending = _strategy_candidate(
            3401,
            project.id,
            package.id,
            review_status="PENDING_REVIEW",
            origin="LEGACY",
            model="local-rule-v1",
            prompt_version="strategy_prompt.v2",
            payload_overrides={
                "strategy_context": {},
                "target_decision_change": "",
                "priority_capabilities": [],
                "gap_item_ids": [],
                "benchmark_evidence_ids": [],
            },
        )
        db.add(legacy_pending)
        db.commit()

        status = workflow_status(db, project, prompt.id)
        action_step = next(step for step in status["steps"] if step["key"] == "action")
        experiment_step = next(step for step in status["steps"] if step["key"] == "experiment")

        assert status["strategy_step_status"] == "NEEDS_CURRENT_ANALYSIS"
        assert status["execution_step_status"] == "LOCKED"
        assert status["current_strategy_candidate_ids"] == []
        assert action_step["done"] is False
        assert "尚未生成 V1.1 正式证据" in action_step["detail"]
        assert experiment_step["done"] is False
        assert experiment_step["detail"] == "等待 V1.1 正式证据输入生成策略候选"
        assert status["historical_strategy_candidate_count"] == 1
        assert status["ineligible_strategy_candidates"][0]["id"] == legacy_pending.id
        assert "LEGACY_STRATEGY_GENERATOR" in status["ineligible_strategy_candidates"][0]["ineligibility_reasons"]
    finally:
        db.close()


def test_reviewed_workflow_with_supportless_current_v1_1_input_needs_rebuild():
    db = _session()
    try:
        project, prompt, _package = _ready_strategy_workflow_base(db)
        doc = SourceDocument(
            id=3701,
            url="https://example.com/current-v1",
            canonical_url="https://example.com/current-v1",
            domain="example.com",
            fetch_status="SUCCESS",
            clean_text="当前正式链已运行但没有形成支持缺口。",
        )
        claim = SourceClaim(
            id=3702,
            project_id=project.id,
            source_document_id=doc.id,
            normalized_claim="当前正式链已运行但没有形成支持缺口",
            source_span="当前正式链已运行但没有形成支持缺口。",
            review_status="MACHINE_GROUNDED",
        )
        alignment = EvidenceAlignment(
            id=3703,
            project_id=project.id,
            prompt_id=prompt.id,
            run_id=3001,
            recommendation_event_id=3002,
            recommendation_reason_id="answer_unit:3700:binding:3700",
            source_document_id=doc.id,
            source_claim_id=claim.id,
            relation="NONE",
            machine_payload_json=dumps({
                "formal_input_version": FORMAL_V1_1_INPUT_VERSION,
                "reason_source": "ANSWER_DECISION_BINDING",
            }),
            review_status="MACHINE_GROUNDED",
        )
        db.add_all([doc, claim, alignment])
        db.commit()

        status = workflow_status(db, project, prompt.id)
        action_step = next(step for step in status["steps"] if step["key"] == "action")
        experiment_step = next(step for step in status["steps"] if step["key"] == "experiment")

        assert status["strategy_step_status"] == "NEEDS_CURRENT_ANALYSIS"
        assert status["execution_step_status"] == "LOCKED"
        assert status["current_v1_1_input_state"]["formal_v1_1_support_count"] == 0
        assert status["current_v1_1_input_state"]["supportless_formal_input_needs_rebuild"] is True
        assert action_step["done"] is False
        assert action_step["detail"] == "当前 V1.1 正式证据输入未形成可用 SUPPORTS，请重新生成证据语义关系后再进入策略确认"
        assert experiment_step["done"] is False
        assert experiment_step["detail"] == "等待 V1.1 正式证据输入生成策略候选"
    finally:
        db.close()


def test_legacy_support_does_not_make_step7_ready_when_formal_v1_1_has_no_support():
    db = _session()
    try:
        project, prompt, _package = _ready_strategy_workflow_base(db)
        doc = SourceDocument(
            id=3711,
            url="https://example.com/formal-related",
            canonical_url="https://example.com/formal-related",
            domain="example.com",
            fetch_status="SUCCESS",
            clean_text="正式 V1.1 只判断为相关，legacy 行曾判断为支持。",
        )
        claim = SourceClaim(
            id=3712,
            project_id=project.id,
            source_document_id=doc.id,
            normalized_claim="正式 V1.1 只判断为相关",
            source_span="正式 V1.1 只判断为相关。",
            review_status="MACHINE_GROUNDED",
        )
        formal_related = EvidenceAlignment(
            id=3713,
            project_id=project.id,
            prompt_id=prompt.id,
            run_id=3001,
            recommendation_event_id=3002,
            recommendation_reason_id="answer_unit:3710:binding:3710",
            source_document_id=doc.id,
            source_claim_id=claim.id,
            relation="RELATED",
            machine_payload_json=dumps({
                "formal_input_version": FORMAL_V1_1_INPUT_VERSION,
                "reason_source": "ANSWER_DECISION_BINDING",
            }),
            review_status="MACHINE_GROUNDED",
        )
        legacy_support = EvidenceAlignment(
            id=3714,
            project_id=project.id,
            prompt_id=prompt.id,
            run_id=3001,
            recommendation_event_id=3002,
            recommendation_reason_id="legacy:3710",
            source_document_id=doc.id,
            source_claim_id=claim.id,
            relation="SUPPORTS",
            machine_payload_json=dumps({"reason_source": "RECOMMENDATION_EVENT_REASONS_JSON"}),
            review_status="HUMAN_CONFIRMED",
        )
        db.add_all([doc, claim, formal_related, legacy_support])
        db.commit()

        status = workflow_status(db, project, prompt.id)

        assert status["strategy_step_status"] == "NEEDS_CURRENT_ANALYSIS"
        assert status["current_v1_1_input_state"]["formal_v1_1_alignment_count"] == 1
        assert status["current_v1_1_input_state"]["formal_v1_1_support_count"] == 0
        assert status["current_v1_1_input_state"]["legacy_support_count"] == 1
        assert status["current_v1_1_input_state"]["supportless_formal_input_needs_rebuild"] is True
    finally:
        db.close()


def test_current_analysis_running_is_visible_in_step7():
    db = _session()
    try:
        project, prompt, _package = _ready_strategy_workflow_base(db)
        db.add(PromptAnalysisRun(
            project_id=project.id,
            prompt_id=prompt.id,
            status="RUNNING",
            runs_associated=1,
            errors_json=dumps([]),
        ))
        db.commit()

        status = workflow_status(db, project, prompt.id)
        action_step = next(step for step in status["steps"] if step["key"] == "action")
        experiment_step = next(step for step in status["steps"] if step["key"] == "experiment")

        assert status["strategy_step_status"] == "CURRENT_ANALYSIS_RUNNING"
        assert status["execution_step_status"] == "LOCKED"
        assert action_step["done"] is False
        assert "后台运行" in action_step["detail"]
        assert experiment_step["detail"] == "等待当前主链运行完成"
    finally:
        db.close()


def test_current_analysis_failed_is_visible_in_step7():
    db = _session()
    try:
        project, prompt, _package = _ready_strategy_workflow_base(db)
        db.add(PromptAnalysisRun(
            project_id=project.id,
            prompt_id=prompt.id,
            status="FAILED",
            runs_associated=1,
            errors_json=dumps(["database is locked"]),
        ))
        db.commit()

        status = workflow_status(db, project, prompt.id)
        action_step = next(step for step in status["steps"] if step["key"] == "action")
        experiment_step = next(step for step in status["steps"] if step["key"] == "experiment")

        assert status["strategy_step_status"] == "CURRENT_ANALYSIS_FAILED"
        assert status["execution_step_status"] == "LOCKED"
        assert action_step["done"] is False
        assert "database is locked" in action_step["detail"]
        assert experiment_step["detail"] == "先重新生成 V1.1 正式证据输入，成功后才能进入策略确认"
    finally:
        db.close()


def test_restart_interrupted_analysis_does_not_mask_completed_current_chain():
    db = _session()
    try:
        project, prompt, package = _ready_strategy_workflow_base(db)
        source_document = SourceDocument(
            id=3051,
            url="https://example.com/restart",
            canonical_url="https://example.com/restart",
            domain="example.com",
            title="竞品短链点击统计",
            fetch_status="SUCCESS",
        )
        source_claim = SourceClaim(
            id=3052,
            project_id=project.id,
            source_document_id=source_document.id,
            normalized_claim="竞品短链支持点击统计",
            source_span="竞品短链支持点击统计",
        )
        alignment = EvidenceAlignment(
            id=3053,
            project_id=project.id,
            prompt_id=prompt.id,
            run_id=3001,
            recommendation_event_id=3002,
            source_document_id=source_document.id,
            source_claim_id=source_claim.id,
            relation="SUPPORTS",
            review_status="HUMAN_CONFIRMED",
            machine_payload_json=dumps({
                "formal_input_version": FORMAL_V1_1_INPUT_VERSION,
                "evidence_package_id": package.id,
            }),
        )
        completed_run = PromptAnalysisRun(
            project_id=project.id,
            prompt_id=prompt.id,
            status="COMPLETED",
            runs_associated=1,
            errors_json=dumps([]),
        )
        restart_failed_run = PromptAnalysisRun(
            project_id=project.id,
            prompt_id=prompt.id,
            status="FAILED",
            runs_associated=1,
            errors_json=dumps(["服务重启中断了本次后台分析，请重新运行当前主链"]),
        )
        db.add_all([source_document, source_claim, alignment, completed_run, restart_failed_run])
        db.commit()

        status = workflow_status(db, project, prompt.id)
        action_step = next(step for step in status["steps"] if step["key"] == "action")

        assert status["strategy_step_status"] == "READY_TO_GENERATE"
        assert status["execution_step_status"] == "LOCKED"
        assert action_step["detail"] == "证据审核完成，可生成策略候选"
    finally:
        db.close()


def test_current_analysis_running_masks_pending_event_review():
    db = _session()
    try:
        project, prompt, _package = _ready_strategy_workflow_base(db)
        event = db.get(RecommendationEvent, 3002)
        event.review_status = "MACHINE_CANDIDATE"
        db.add(PromptAnalysisRun(
            project_id=project.id,
            prompt_id=prompt.id,
            status="RUNNING",
            runs_associated=1,
            errors_json=dumps([]),
        ))
        db.commit()

        status = workflow_status(db, project, prompt.id)
        action_step = next(step for step in status["steps"] if step["key"] == "action")
        experiment_step = next(step for step in status["steps"] if step["key"] == "experiment")

        assert status["strategy_step_status"] == "CURRENT_ANALYSIS_RUNNING"
        assert action_step["done"] is False
        assert "后台运行" in action_step["detail"]
        assert experiment_step["detail"] == "等待当前主链运行完成"
    finally:
        db.close()


def test_step7_not_ready_detail_points_to_pending_event_review():
    db = _session()
    try:
        project, prompt, _package = _ready_strategy_workflow_base(db)
        event = db.get(RecommendationEvent, 3002)
        event.review_status = "MACHINE_CANDIDATE"
        db.commit()

        status = workflow_status(db, project, prompt.id)
        action_step = next(step for step in status["steps"] if step["key"] == "action")
        experiment_step = next(step for step in status["steps"] if step["key"] == "experiment")

        assert status["strategy_step_status"] == "NOT_READY"
        assert action_step["detail"] == "待推荐行为人工确认完成后生成策略候选"
        assert experiment_step["detail"] == "等待推荐行为人工确认"
    finally:
        db.close()


def test_reviewed_support_evidence_unlocks_strategy_generation_without_recomputing_citation(monkeypatch):
    db = _session()
    try:
        project, prompt, package = _ready_strategy_workflow_base(db)
        source_document = SourceDocument(
            id=3005,
            url="https://example.com/a",
            canonical_url="https://example.com/a",
            domain="example.com",
            title="竞品短链点击统计",
            fetch_status="SUCCESS",
        )
        source_claim = SourceClaim(
            id=3006,
            project_id=project.id,
            source_document_id=source_document.id,
            normalized_claim="竞品短链支持点击统计",
            source_span="竞品短链支持点击统计",
        )
        alignment = EvidenceAlignment(
            id=3007,
            project_id=project.id,
            prompt_id=prompt.id,
            run_id=3001,
            recommendation_event_id=3002,
            source_document_id=source_document.id,
            source_claim_id=source_claim.id,
            relation="SUPPORTS",
            review_status="HUMAN_CONFIRMED",
            machine_payload_json=dumps({
                "formal_input_version": FORMAL_V1_1_INPUT_VERSION,
                "evidence_package_id": package.id,
            }),
        )
        db.add_all([source_document, source_claim, alignment])
        db.commit()

        def fake_citation_decision(*args, **kwargs):
            raise AssertionError("workflow/status must not recompute Citation Decision")

        monkeypatch.setattr(
            "app.modules.optimization.workflow.citation_decision_vertical_slice",
            fake_citation_decision,
            raising=False,
        )

        status = workflow_status(db, project, prompt.id)
        action_step = next(step for step in status["steps"] if step["key"] == "action")

        assert status["strategy_step_status"] == "READY_TO_GENERATE"
        assert status["execution_step_status"] == "LOCKED"
        assert action_step["detail"] == "证据审核完成，可生成策略候选"
    finally:
        db.close()


def test_audit_confirmed_strategy_does_not_confirm_current_step7():
    db = _session()
    try:
        project, prompt, package = _ready_strategy_workflow_base(db)
        audit_candidate = _strategy_candidate(
            3501,
            project.id,
            package.id,
            review_status="ACCEPTED",
            reviewed_by="phase_strategy_core_regression",
            origin="REGRESSION",
        )
        db.add(audit_candidate)
        db.commit()

        reviewed = review_strategy_candidate(
            db,
                audit_candidate.id,
                StrategyCandidateReviewPayload(
                    review_status="ACCEPTED",
                    reviewed_by="phase_strategy_core_regression",
                    review_note="phase regression audit",
                ),
            )
        status = workflow_status(db, project, prompt.id)

        assert reviewed["eligible_for_current_step7"] is False
        assert reviewed["candidate_origin"] == "REGRESSION"
        assert status["strategy_step_status"] == "NEEDS_CURRENT_ANALYSIS"
        assert status["current_strategy_confirmed"] is False
        assert status["execution_step_status"] == "LOCKED"
        assert db.query(WorkflowConfirmation).filter(WorkflowConfirmation.step_key == "action").count() == 0
    finally:
        db.close()


def test_incomplete_strategy_core_is_ineligible_for_current_step7():
    db = _session()
    try:
        project, prompt, package = _ready_strategy_workflow_base(db)
        incomplete = _strategy_candidate(
            3601,
            project.id,
            package.id,
            review_status="PENDING_REVIEW",
            payload_overrides={
                "planned_channels": [],
                "required_signals": [],
            },
        )
        db.add(incomplete)
        db.commit()

        listed = [
            row for row in workflow_status(db, project, prompt.id)["ineligible_strategy_candidates"]
            if row["id"] == incomplete.id
        ]
        assert listed
        assert "MISSING_STRATEGY_CORE" in listed[0]["ineligibility_reasons"]
    finally:
        db.close()


def test_step8_rejects_ineligible_legacy_strategy_even_when_accepted():
    db = _session()
    try:
        project, prompt, package = _ready_strategy_workflow_base(db)
        legacy_accepted = _strategy_candidate(
            3701,
            project.id,
            package.id,
            review_status="ACCEPTED",
            origin="LEGACY",
            model="local-rule-v1",
            prompt_version="strategy_prompt.v2",
            payload_overrides={"strategy_context": {}},
        )
        db.add(legacy_accepted)
        db.commit()

        with pytest.raises(Exception) as excinfo:
            strategy_to_experiment_plan(db, legacy_accepted.id)

        assert "不属于当前单 Prompt V1.1 主链" in str(excinfo.value)
        assert db.query(OptimizationAction).count() == 0
        assert db.query(OptimizationExperiment).count() == 0
    finally:
        db.close()
