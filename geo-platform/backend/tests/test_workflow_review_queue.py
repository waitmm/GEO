from __future__ import annotations

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
    RecommendationEvent,
    SourceClaim,
    SourceDocument,
    TargetBrandCapabilityTruth,
    WorkflowConfirmation,
)
from app.modules.optimization.schemas import StrategyCandidateReviewPayload
from app.modules.optimization.service import review_strategy_candidate
from app.modules.optimization.workflow import (
    batch_confirm_alignments,
    build_continue_review_context,
    resolve_decision_market_entity,
    review_queue,
    workflow_status,
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
) -> OptimizationStrategyCandidate:
    payload = {
        "product_truth_gate": {"status": "READY_FOR_STRATEGY_REVIEW"},
        "intervention_type": "UNRESOLVED",
        "target_platform": "UNRESOLVED",
        "target_object": "UNRESOLVED",
        "target_asset": "UNRESOLVED",
        "target_content_type": "UNRESOLVED",
        "recommended_action": "补齐点击统计表达",
    }
    return OptimizationStrategyCandidate(
        id=candidate_id,
        project_id=project_id,
        evidence_package_id=package_id,
        experiment_id=experiment_id,
        structured_payload_json=dumps(payload),
        effective_payload_json=dumps(payload) if review_status in {"ACCEPTED", "ACCEPTED_WITH_EDITS"} else dumps({}),
        effective_payload_version="effective_payload.v1" if review_status in {"ACCEPTED", "ACCEPTED_WITH_EDITS"} else "",
        effective_validation_status="PENDING_HUMAN_CHANNEL_REVIEW" if review_status in {"ACCEPTED", "ACCEPTED_WITH_EDITS"} else "PENDING",
        evidence_validation_status="VALIDATED",
        hypothesis_validation_status="VALIDATED",
        review_status=review_status,
        reviewed_by=reviewed_by,
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
        db.add_all([Organization(id=1, name="测试组织"), project, prompt, task, run_a, run_b, event_a, event_b, doc, claim, alignment_a, alignment_b])
        db.commit()

        queue = review_queue(db, project, 40)

        assert queue["status"] == "READY"
        assert queue["unique_events"] == []
        assert len(queue["alignments"]) == 1
        group = queue["alignments"][0]
        assert group["alignment_ids"] == [801, 802]
        assert group["alignment_count"] == 2
        assert group["run_ids"] == [401, 402]
        assert group["run_count"] == 2
        assert group["semantic_observed_run_ids"] == [401, 402]
        assert group["semantic_observed_run_count"] == 2
        assert group["reason_text"] == "小码短链接自带点击统计"
        assert group["source_document_id"] == 601
        assert group["source_claim_id"] == 701

        result = batch_confirm_alignments(db, group["alignment_ids"], reviewer="human")

        assert result["updated"] == 2
        refreshed = db.query(EvidenceAlignment).order_by(EvidenceAlignment.id).all()
        assert [row.review_status for row in refreshed] == ["HUMAN_CONFIRMED", "HUMAN_CONFIRMED"]
        assert [row.reviewer for row in refreshed] == ["human", "human"]
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
