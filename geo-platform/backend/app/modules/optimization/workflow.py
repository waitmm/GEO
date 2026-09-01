"""人工审核工作流 — 机器分析 → 人工确认 → 一键继续 → 下一 Gate。

产品化目标：用户只负责"确认"，系统负责"接着往后跑"。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import (
    AnswerEvidenceShadowRun,
    BrowserMonitorRun,
    Competitor,
    CompetitorRejection,
    EvidenceAlignment,
    OptimizationAction,
    OptimizationEvidencePackage,
    OptimizationExperiment,
    OptimizationIssue,
    OptimizationStrategyCandidate,
    Project,
    Prompt,
    PromptAnalysisRun,
    RecommendationEvent,
    SourceClaim,
    TargetBrandCapabilityTruth,
    WorkflowConfirmation,
)
from app.services.serialization import dumps, loads
from app.modules.optimization.service import (
    citation_decision_vertical_slice,
    current_step7_candidate_eligibility,
)
from app.modules.optimization.passage_retrieval import (
    ANSWER_BINDING_REASON_SOURCE,
    FORMAL_V1_1_INPUT_VERSION,
    SHADOW_INPUT_PIPELINE_VERSION,
)

REVIEWABLE_RECOMMENDATION_EVENT_STATUSES = {
    "MACHINE_GROUNDED",
    "MACHINE_CANDIDATE",
    "HUMAN_CONFIRMED",
    "HUMAN_REJECTED",
}
PENDING_RECOMMENDATION_EVENT_STATUSES = {
    "MACHINE_GROUNDED",
    "MACHINE_CANDIDATE",
}
VALID_DECISION_EVENT_STATUSES = {
    "MACHINE_GROUNDED",
    "MACHINE_CANDIDATE",
    "HUMAN_CONFIRMED",
}
ACCEPTED_STRATEGY_REVIEW_STATUSES = {"ACCEPTED", "ACCEPTED_WITH_EDITS"}
STEP7_EFFECTIVE_PAYLOAD_STATUSES = {"VALIDATED", "PENDING_HUMAN_CHANNEL_REVIEW"}
CURRENT_ANALYSIS_DECISION_ACTS = {"RECOMMEND", "INCLUDE_AS_OPTION", "COMPARE"}


def _compact_review_text(value: str) -> str:
    return " ".join((value or "").split())


def _review_reason_text(alignment: EvidenceAlignment, machine_payload: dict) -> str:
    semantic_key = machine_payload.get("semantic_reason_key") or ""
    if semantic_key:
        return _compact_review_text(str(semantic_key).split("|")[0])
    return _compact_review_text(alignment.recommendation_reason_id.replace("reason:", ""))


def _semantic_observed_run_ids(alignment: EvidenceAlignment, machine_payload: dict) -> list[int]:
    run_ids = {
        int(run_id)
        for run_id in (machine_payload.get("observed_run_ids") or [])
        if run_id
    }
    if alignment.run_id:
        run_ids.add(int(alignment.run_id))
    return sorted(run_ids)


def _alignment_run_ids(alignment: EvidenceAlignment) -> list[int]:
    return [int(alignment.run_id)] if alignment.run_id else []


def _current_v1_1_input_state(
    db: Session,
    project: Project,
    prompt_id: int,
    package: OptimizationEvidencePackage | None,
) -> dict:
    """判断当前 Prompt 是否已经生成可供正式 V1.1 消费的 Evidence 输入。

    这里专门区分两种状态：
    1. 当前正式链已运行，但没有可生成策略的缺口；
    2. 上游已有答案决策/历史证据线索，但 V1.1 正式 Evidence 还没生成。

    第二种不能被展示成"无策略"，否则用户会卡在第 7 步空转。
    """
    run_ids = {
        int(run_id)
        for run_id in loads(package.source_run_ids_json if package else "[]", [])
        if run_id
    }
    if not run_ids:
        run_ids = {
            int(row[0])
            for row in db.query(BrowserMonitorRun.id).filter(
                BrowserMonitorRun.project_id == project.id,
                BrowserMonitorRun.prompt_id == prompt_id,
                BrowserMonitorRun.status.in_(["success", "partial_success"]),
            ).all()
        }

    formal_alignment_count = 0
    legacy_support_count = 0
    legacy_related_count = 0
    if run_ids:
        alignments = (
            db.query(EvidenceAlignment)
            .filter(
                EvidenceAlignment.project_id == project.id,
                EvidenceAlignment.prompt_id == prompt_id,
                EvidenceAlignment.run_id.in_(run_ids),
            )
            .all()
        )
        for alignment in alignments:
            payload = loads(alignment.machine_payload_json, {})
            is_v1_1_input = (
                payload.get("reason_source") == ANSWER_BINDING_REASON_SOURCE
                or payload.get("formal_input_version") == FORMAL_V1_1_INPUT_VERSION
            )
            if is_v1_1_input:
                formal_alignment_count += 1
            elif alignment.relation == "SUPPORTS":
                legacy_support_count += 1
            elif alignment.relation == "RELATED":
                legacy_related_count += 1

    event_query = db.query(RecommendationEvent).filter(
        RecommendationEvent.project_id == project.id,
        RecommendationEvent.prompt_id == prompt_id,
        RecommendationEvent.review_status.in_(VALID_DECISION_EVENT_STATUSES),
        RecommendationEvent.speech_act.in_(CURRENT_ANALYSIS_DECISION_ACTS),
    )
    if run_ids:
        event_query = event_query.filter(RecommendationEvent.run_id.in_(run_ids))
    decision_events = event_query.all()
    event_reason_count = sum(1 for row in decision_events if loads(row.reasons_json, []))

    shadow_query = db.query(AnswerEvidenceShadowRun).filter(
        AnswerEvidenceShadowRun.project_id == project.id,
        AnswerEvidenceShadowRun.prompt_id == prompt_id,
        AnswerEvidenceShadowRun.pipeline_version == SHADOW_INPUT_PIPELINE_VERSION,
        AnswerEvidenceShadowRun.status.in_(["completed", "completed_with_warnings"]),
        AnswerEvidenceShadowRun.formal_output_impact == "NONE",
    )
    if package is not None:
        shadow_query = shadow_query.filter(AnswerEvidenceShadowRun.evidence_package_id == package.id)
    shadow_run_count = shadow_query.count()

    has_upstream_signal = bool(decision_events or legacy_support_count or legacy_related_count)
    needs_current_analysis = (
        has_upstream_signal
        and formal_alignment_count == 0
    )
    return {
        "run_ids": sorted(run_ids),
        "decision_event_count": len(decision_events),
        "event_reason_count": event_reason_count,
        "formal_v1_1_alignment_count": formal_alignment_count,
        "legacy_support_count": legacy_support_count,
        "legacy_related_count": legacy_related_count,
        "shadow_run_count": shadow_run_count,
        "has_upstream_signal": has_upstream_signal,
        "needs_current_analysis": needs_current_analysis,
    }


def _latest_prompt_evidence_package(db: Session, project_id: int, prompt_id: int) -> OptimizationEvidencePackage | None:
    return (
        db.query(OptimizationEvidencePackage)
        .filter(
            OptimizationEvidencePackage.project_id == project_id,
            OptimizationEvidencePackage.prompt_id == prompt_id,
            OptimizationEvidencePackage.status == "active",
        )
        .order_by(OptimizationEvidencePackage.version.desc(), OptimizationEvidencePackage.id.desc())
        .first()
    )


def _candidate_time_key(candidate: OptimizationStrategyCandidate) -> tuple[datetime, int]:
    marker = candidate.reviewed_at or candidate.updated_at or candidate.generated_at or candidate.created_at or datetime.min
    return marker, int(candidate.id or 0)


def _is_step7_confirmable_strategy(
    candidate: OptimizationStrategyCandidate,
    package: OptimizationEvidencePackage | None,
) -> bool:
    return (
        current_step7_candidate_eligibility(candidate, package)["eligible"]
        and
        candidate.review_status in ACCEPTED_STRATEGY_REVIEW_STATUSES
        and candidate.effective_validation_status in STEP7_EFFECTIVE_PAYLOAD_STATUSES
    )


def _workflow_confirmation_context(row: WorkflowConfirmation | None) -> dict:
    if row is None:
        return {}
    parsed = loads(row.decision_note or "", {})
    return parsed if isinstance(parsed, dict) else {}


def _strategy_confirmation_matches(
    row: WorkflowConfirmation | None,
    candidate: OptimizationStrategyCandidate | None,
    package: OptimizationEvidencePackage | None,
) -> bool:
    """Only JSON-bound Strategy confirmations count as current Step 7 state.

    Legacy ``WorkflowConfirmation(step_key="action")`` rows remain available as
    audit history, but they cannot light the current single-Prompt main chain
    because they do not identify the current StrategyCandidate/EvidencePackage.
    """
    if row is None or candidate is None or package is None:
        return False
    if row.decision_status != "CONFIRMED" or row.step_key != "action":
        return False
    context = _workflow_confirmation_context(row)
    return (
        int(context.get("strategy_candidate_id") or 0) == int(candidate.id)
        and int(context.get("evidence_package_id") or 0) == int(package.id)
        and int(context.get("prompt_id") or 0) == int(package.prompt_id or 0)
    )


def _current_strategy_chain_state(
    db: Session,
    project: Project,
    prompt_id: int,
    *,
    reviews_done: bool,
) -> dict:
    package = _latest_prompt_evidence_package(db, project.id, prompt_id)
    candidates: list[OptimizationStrategyCandidate] = []
    if package is not None:
        candidates = (
            db.query(OptimizationStrategyCandidate)
            .filter(
                OptimizationStrategyCandidate.project_id == project.id,
                OptimizationStrategyCandidate.evidence_package_id == package.id,
            )
            .all()
        )

    eligibility_by_id = {
        row.id: current_step7_candidate_eligibility(row, package)
        for row in candidates
    }
    eligible_candidates = [
        row for row in candidates
        if eligibility_by_id.get(row.id, {}).get("eligible")
    ]
    pending_candidates = sorted(
        [row for row in eligible_candidates if row.review_status == "PENDING_REVIEW"],
        key=_candidate_time_key,
        reverse=True,
    )
    accepted_candidates = sorted(
        [row for row in eligible_candidates if _is_step7_confirmable_strategy(row, package)],
        key=_candidate_time_key,
        reverse=True,
    )
    confirmation = (
        db.query(WorkflowConfirmation)
        .filter(
            WorkflowConfirmation.project_id == project.id,
            WorkflowConfirmation.prompt_id == prompt_id,
            WorkflowConfirmation.step_key == "action",
        )
        .first()
    )
    confirmed_candidate = next(
        (row for row in accepted_candidates if _strategy_confirmation_matches(confirmation, row, package)),
        None,
    )
    v1_1_input_state = _current_v1_1_input_state(db, project, prompt_id, package)
    if pending_candidates:
        strategy_status = "PENDING_REVIEW"
        current_ids = [pending_candidates[0].id]
        current_candidate = pending_candidates[0]
        detail = "1 个当前策略候选待人工审核"
    elif confirmed_candidate is not None:
        strategy_status = "CONFIRMED"
        current_ids = [confirmed_candidate.id]
        current_candidate = confirmed_candidate
        detail = f"当前策略 #{confirmed_candidate.id} 已人工确认"
    elif reviews_done:
        proposal = citation_decision_vertical_slice(
            db,
            project.id,
            prompt_id,
            package.id if package is not None else None,
            use_answer_binding_v1_1=True,
        ) if package is not None else {}
        generatable_actions = [
            action
            for action in (proposal.get("recommended_actions") or [])
            if action.get("route") in {"CONTENT", "EVIDENCE"}
        ]
        current_ids = []
        current_candidate = None
        if generatable_actions:
            strategy_status = "READY_TO_GENERATE"
            detail = f"{len(generatable_actions)} 个缺口可生成策略候选"
        elif v1_1_input_state.get("needs_current_analysis"):
            strategy_status = "NEEDS_CURRENT_ANALYSIS"
            detail = "当前有答案决策/证据线索，但尚未生成 V1.1 正式证据与缺口，请重新运行当前主链"
        else:
            strategy_status = "NO_STRATEGY"
            detail = "当前正式链已完成，没有可生成策略的内容/证据缺口"
    else:
        strategy_status = "NOT_READY"
        current_ids = []
        current_candidate = None
        detail = "待缺口诊断后生成策略候选"

    current_experiment = None
    if confirmed_candidate is not None and confirmed_candidate.experiment_id:
        current_experiment = db.get(OptimizationExperiment, confirmed_candidate.experiment_id)

    all_experiments = (
        db.query(OptimizationExperiment)
        .join(OptimizationAction, OptimizationAction.id == OptimizationExperiment.action_id)
        .join(OptimizationIssue, OptimizationIssue.id == OptimizationAction.issue_id)
        .filter(OptimizationIssue.project_id == project.id, OptimizationIssue.prompt_id == prompt_id)
        .order_by(OptimizationExperiment.id.desc())
        .all()
    )
    current_experiment_ids = {current_experiment.id} if current_experiment else set()
    historical_experiments = [row for row in all_experiments if row.id not in current_experiment_ids]

    if current_experiment is not None:
        execution_status = "CREATED"
        execution_detail = f"当前实验草案 #{current_experiment.id} 已创建，等待发布闸门"
    elif confirmed_candidate is not None:
        execution_status = "READY_TO_CREATE"
        execution_detail = "当前策略已确认，可进入实验方案落地"
    elif strategy_status == "NO_STRATEGY":
        execution_status = "NO_EXPERIMENT"
        execution_detail = "本轮没有策略候选，无需创建实验草案"
    elif strategy_status == "NEEDS_CURRENT_ANALYSIS":
        execution_status = "LOCKED"
        execution_detail = "等待重新运行当前主链生成正式证据与策略候选"
    else:
        execution_status = "LOCKED"
        execution_detail = "等待当前策略确认"

    historical_candidate_ids = [row.id for row in candidates if row.id not in set(current_ids)]
    ineligible_candidate_details = [
        {
            "id": row.id,
            "candidate_origin": eligibility_by_id.get(row.id, {}).get("candidate_origin"),
            "ineligibility_reasons": eligibility_by_id.get(row.id, {}).get("ineligibility_reasons", []),
        }
        for row in candidates
        if row.id not in set(current_ids) and not eligibility_by_id.get(row.id, {}).get("eligible")
    ]
    return {
        "context": {
            "prompt_id": prompt_id,
            "evidence_package_id": package.id if package else None,
            "package_version": package.version if package else None,
        },
        "strategy_step_status": strategy_status,
        "strategy_step_detail": detail,
        "current_strategy_candidate_id": current_candidate.id if current_candidate else None,
        "current_strategy_candidate_ids": current_ids,
        "current_strategy_confirmed": confirmed_candidate is not None,
        "current_effective_payload_status": (
            confirmed_candidate.effective_validation_status if confirmed_candidate else current_candidate.effective_validation_status if current_candidate else None
        ),
        "current_effective_payload_valid": (
            confirmed_candidate is not None
            and confirmed_candidate.effective_validation_status in STEP7_EFFECTIVE_PAYLOAD_STATUSES
        ),
        "current_v1_1_input_state": v1_1_input_state,
        "execution_step_status": execution_status,
        "execution_step_detail": execution_detail,
        "current_action_id": current_experiment.action_id if current_experiment else None,
        "current_experiment_id": current_experiment.id if current_experiment else None,
        "current_experiment_status": current_experiment.status if current_experiment else None,
        "historical_strategy_candidate_ids": historical_candidate_ids,
        "historical_strategy_candidate_count": len(historical_candidate_ids),
        "ineligible_strategy_candidates": ineligible_candidate_details,
        "historical_experiment_ids": [row.id for row in historical_experiments],
        "historical_experiment_count": len(historical_experiments),
        "legacy_action_confirmation_ignored": bool(
            confirmation
            and confirmation.decision_status == "CONFIRMED"
            and not _workflow_confirmation_context(confirmation)
        ),
    }


# ---------------------------------------------------------------------------
# 竞品候选发现
# ---------------------------------------------------------------------------

def discover_competitor_candidates(db: Session, project: Project, prompt_id: int) -> list[dict]:
    """从 RecommendationEvent 中发现潜在竞品（未在项目竞品库中的实体）。

    发现依据：Grounding 通过的事件实体，排除目标品牌自身。
    """
    events = db.query(RecommendationEvent).filter(
        RecommendationEvent.project_id == project.id,
        RecommendationEvent.prompt_id == prompt_id,
        RecommendationEvent.review_status.in_(["MACHINE_GROUNDED", "HUMAN_CONFIRMED"]),
    ).all()

    known = {project.brand_name, *(c.name for c in db.query(Competitor).filter(Competitor.project_id == project.id).all())}
    # 目标品牌别名也算已知
    known |= set(loads(project.brand_aliases_json, []))
    # 人工已判定「不是竞品」的实体不再反复出现
    known |= {
        r.entity_name
        for r in db.query(CompetitorRejection).filter(CompetitorRejection.project_id == project.id).all()
    }

    seen: dict[str, dict] = {}
    for e in events:
        name = (e.entity_text or "").strip()
        if not name or name in known:
            continue
        row = seen.setdefault(name, {"entity": name, "run_ids": set(), "speech_acts": set(), "answer_span": e.answer_span})
        row["run_ids"].add(e.run_id)
        row["speech_acts"].add(e.speech_act)

    return [
        {
            "entity": v["entity"],
            "run_coverage": f"{len(v['run_ids'])}/{len(events)}",
            "speech_acts": sorted(v["speech_acts"]),
            "answer_span": v["answer_span"][:200],
        }
        for v in sorted(seen.values(), key=lambda x: -len(x["run_ids"]))
    ]


def confirm_competitor(db: Session, project: Project, name: str, website_url: str = "") -> dict:
    """确认竞品 → 永久加入 Project Competitors。"""
    existing = db.query(Competitor).filter(
        Competitor.project_id == project.id, Competitor.name == name,
    ).first()
    if existing:
        return {"status": "EXISTS", "id": existing.id}
    comp = Competitor(project_id=project.id, name=name, aliases_json="[]", website_url=website_url)
    db.add(comp)
    db.commit()
    db.refresh(comp)
    return {"status": "CONFIRMED", "id": comp.id}


def reject_competitor(db: Session, project: Project, name: str) -> dict:
    """人工判定「不是竞品」→ 记录拒绝，候选发现时排除（幂等）。"""
    name = (name or "").strip()
    if not name:
        return {"status": "EMPTY_NAME"}
    existing = db.query(CompetitorRejection).filter(
        CompetitorRejection.project_id == project.id, CompetitorRejection.entity_name == name,
    ).first()
    if existing:
        return {"status": "EXISTS", "id": existing.id}
    row = CompetitorRejection(project_id=project.id, entity_name=name)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"status": "REJECTED", "id": row.id}


def resolve_decision_market_entity(
    db: Session,
    project: Project,
    prompt_id: int,
    entity_text: str,
    resolution: str,
    reviewer: str = "human",
) -> dict:
    """人工修正答案决策识别中的未知对象。

    这是第 2 步「答案决策识别」的修正入口：把机器校验失败但答案里
    确实出现的推荐对象，明确为目标品牌、竞品，或排除出决策对象。
    """
    entity = (entity_text or "").strip()
    normalized_resolution = (resolution or "").strip().upper()
    if not entity:
        return {"status": "EMPTY_ENTITY", "updated_events": 0}
    if normalized_resolution not in {"TARGET_BRAND", "CONFIRMED_COMPETITOR", "REJECTED"}:
        return {"status": "INVALID_RESOLUTION", "updated_events": 0}

    if normalized_resolution == "TARGET_BRAND":
        aliases = loads(project.brand_aliases_json, [])
        if entity != project.brand_name and entity not in aliases:
            aliases.append(entity)
            project.brand_aliases_json = dumps(aliases)
    elif normalized_resolution == "CONFIRMED_COMPETITOR":
        db.query(CompetitorRejection).filter(
            CompetitorRejection.project_id == project.id,
            CompetitorRejection.entity_name == entity,
        ).delete()
        if not db.query(Competitor).filter(
            Competitor.project_id == project.id,
            Competitor.name == entity,
        ).first():
            db.add(Competitor(project_id=project.id, name=entity, aliases_json="[]", website_url=""))
    else:
        reject_competitor(db, project, entity)

    events = db.query(RecommendationEvent).filter(
        RecommendationEvent.project_id == project.id,
        RecommendationEvent.prompt_id == prompt_id,
        RecommendationEvent.entity_text == entity,
    ).all()
    next_status = "HUMAN_REJECTED" if normalized_resolution == "REJECTED" else "HUMAN_CONFIRMED"
    now = datetime.utcnow()
    for event in events:
        event.review_status = next_status
        event.reviewer = reviewer
        event.reviewed_at = now
        event.entity_type = "BRAND" if normalized_resolution != "REJECTED" else event.entity_type
        payload = loads(event.human_payload_json, {})
        payload["decision_entity_resolution"] = normalized_resolution
        event.human_payload_json = dumps(payload)

    db.commit()
    return {
        "status": normalized_resolution,
        "entity_text": entity,
        "updated_events": len(events),
    }


# ---------------------------------------------------------------------------
# 工作流状态
# ---------------------------------------------------------------------------

def workflow_status(db: Session, project: Project, prompt_id: int) -> dict:
    """返回 Prompt 级工作流状态（9 步）。"""
    run_ids = [
        r.id for r in db.query(BrowserMonitorRun).filter(
            BrowserMonitorRun.project_id == project.id,
            BrowserMonitorRun.prompt_id == prompt_id,
        ).all()
    ]
    total_runs = len(run_ids) or 1

    all_events = db.query(RecommendationEvent).filter(
        RecommendationEvent.project_id == project.id,
        RecommendationEvent.prompt_id == prompt_id,
    ).all()
    reviewable_events = [
        e for e in all_events
        if e.review_status in REVIEWABLE_RECOMMENDATION_EVENT_STATUSES
    ]
    valid_decision_events = [
        e for e in all_events
        if e.review_status in VALID_DECISION_EVENT_STATUSES
    ]
    unique_event_keys = {(e.answer_hash, e.entity_text, e.speech_act) for e in valid_decision_events}
    answer_semantic_done = len(unique_event_keys) >= 1
    reviewable_event_keys = {(e.answer_hash, e.entity_text, e.speech_act) for e in reviewable_events}
    reviewed_event_keys = {
        (e.answer_hash, e.entity_text, e.speech_act)
        for e in reviewable_events
        if e.review_status in {"HUMAN_CONFIRMED", "HUMAN_REJECTED"}
    }
    validation_failed_events = [e for e in all_events if e.review_status == "VALIDATION_FAILED"]

    supports = db.query(EvidenceAlignment).filter(
        EvidenceAlignment.project_id == project.id,
        EvidenceAlignment.prompt_id == prompt_id,
        EvidenceAlignment.relation == "SUPPORTS",
    ).all()
    supports_reviewed = sum(1 for a in supports if a.review_status in {"HUMAN_CONFIRMED", "HUMAN_REJECTED"})

    truths = db.query(TargetBrandCapabilityTruth).filter(
        TargetBrandCapabilityTruth.project_id == project.id,
    ).all()
    truths_pending = [t for t in truths if t.product_truth_status in {"UNKNOWN", ""}]

    # 分析运行记录：区分「分析过但 0 事件」与「从未分析」
    analysis_run = (
        db.query(PromptAnalysisRun)
        .filter(
            PromptAnalysisRun.project_id == project.id,
            PromptAnalysisRun.prompt_id == prompt_id,
        )
        .order_by(PromptAnalysisRun.id.desc())
        .first()
    )
    analyzed = bool(all_events) or analysis_run is not None

    # 无 SUPPORTS 对齐时证据审核视为已通过（没有可审项，不阻塞流程）
    evidence_review_done = supports_reviewed >= len(supports)
    # 只有可人工审核的事件才进入审核分母；VALIDATION_FAILED 等机器失败事件不能造成空队列死循环。
    event_review_done = (
        bool(reviewable_events) and len(reviewed_event_keys) >= len(reviewable_event_keys)
    ) or (analyzed and not reviewable_events)
    reviews_done = (
        analyzed
        and answer_semantic_done
        and event_review_done
        and evidence_review_done
        and bool(truths) and not truths_pending
    )

    # gap 的旧人工确认状态仍用于缺口卡片。Step 7/8 不再直接消费
    # step_key="action" 的存在性，必须由 StrategyCandidate + 当前证据包
    # 上下文绑定决定，避免历史候选/实验点亮当前主链。
    confirmed = {
        row.step_key
        for row in db.query(WorkflowConfirmation).filter(
            WorkflowConfirmation.project_id == project.id,
            WorkflowConfirmation.prompt_id == prompt_id,
            WorkflowConfirmation.decision_status == "CONFIRMED",
        ).all()
    }
    gap_confirmed = "gap" in confirmed

    # 人工搁置（机器 UNRESOLVED 且人工选择搁置结束）
    shelved_row = (
        db.query(WorkflowConfirmation)
        .filter(
            WorkflowConfirmation.project_id == project.id,
            WorkflowConfirmation.prompt_id == prompt_id,
            WorkflowConfirmation.step_key == "gap",
            WorkflowConfirmation.decision_status == "SHELVED",
        )
        .first()
    )
    shelved = shelved_row is not None
    shelved_note = shelved_row.decision_note if shelved_row else ""

    current_chain = _current_strategy_chain_state(db, project, prompt_id, reviews_done=reviews_done)
    if analysis_run and current_chain["strategy_step_status"] == "NEEDS_CURRENT_ANALYSIS":
        if analysis_run.status == "RUNNING":
            current_chain = {
                **current_chain,
                "strategy_step_status": "CURRENT_ANALYSIS_RUNNING",
                "strategy_step_detail": "当前主链正在后台运行：生成 V1.1 正式证据、缺口和策略候选状态",
                "execution_step_status": "LOCKED",
                "execution_step_detail": "等待当前主链运行完成",
            }
        elif analysis_run.status == "FAILED":
            error_items = loads(analysis_run.errors_json, [])
            error_text = str(error_items[0]) if error_items else "后台分析失败，请查看日志"
            current_chain = {
                **current_chain,
                "strategy_step_status": "CURRENT_ANALYSIS_FAILED",
                "strategy_step_detail": f"当前主链运行失败：{error_text[:160]}",
                "execution_step_status": "LOCKED",
                "execution_step_detail": "先重新运行当前主链，成功后才能进入策略确认",
            }
    strategy_done = current_chain["strategy_step_status"] in {"CONFIRMED", "NO_STRATEGY"}
    experiment_done = current_chain["execution_step_status"] in {"CREATED", "NO_EXPERIMENT"}

    steps = [
        {"key": "collection", "label": "数据采集", "done": total_runs >= 1, "detail": f"{total_runs} Runs"},
        {"key": "answer_semantic", "label": "推荐行为分析", "done": answer_semantic_done, "detail": f"{len(unique_event_keys)} 组有效选择事件" if unique_event_keys else (f"已分析：0 组有效选择事件（{len(validation_failed_events)} 条机器校验未通过）" if validation_failed_events else (f"已分析：0 组有效选择事件（答案中无推荐或已被人工排除）" if analyzed else "未分析"))},
        {"key": "event_review", "label": "推荐行为人工确认", "done": event_review_done, "detail": f"{min(len(reviewed_event_keys), len(reviewable_event_keys))}/{len(reviewable_event_keys)} 组已审" if reviewable_events else ("无可审核事件，无需审核" if analyzed else "待分析")},
        {"key": "evidence", "label": "证据分析", "done": bool(supports), "detail": f"{len(supports)} 条支持对齐" if supports else "无支持对齐（AI 理由无来源证据支持）"},
        {"key": "evidence_review", "label": "证据人工确认", "done": evidence_review_done, "detail": f"{supports_reviewed}/{len(supports)} 条已审" if supports else "无需审核"},
        {"key": "product_truth", "label": "目标品牌能力确认", "done": bool(truths) and not truths_pending, "detail": f"{len(truths)-len(truths_pending)}/{len(truths)} 条已确认" if truths else "0 条"},
        {"key": "gap", "label": "缺口诊断", "done": gap_confirmed, "detail": ("人工搁置-无法分析" if shelved else "已人工确认" if gap_confirmed else ("待答案决策识别修正" if analyzed and not answer_semantic_done else ("可生成（点「继续分析」）" if reviews_done else "待审核完成后生成")))},
        {"key": "action", "label": "策略确认", "done": strategy_done, "detail": ("人工搁置-无法分析" if shelved else current_chain["strategy_step_detail"] if answer_semantic_done else "待答案决策识别修正")},
        {"key": "experiment", "label": "实验方案落地", "done": experiment_done, "detail": current_chain["execution_step_detail"]},
    ]
    pending = sum(1 for s in steps if not s["done"] and s["key"] not in {"gap", "action", "experiment", "evidence", "answer_semantic"})
    return {
        "project_id": project.id,
        "prompt_id": prompt_id,
        "steps": steps,
        "pending_review_steps": pending,
        "shelved": shelved,
        "shelved_note": shelved_note,
        "all_reviews_done": pending == 0,
        "answer_semantic_done": answer_semantic_done,
        "ready_to_continue": reviews_done,
        "current_state_context": current_chain["context"],
        "strategy_step_status": current_chain["strategy_step_status"],
        "execution_step_status": current_chain["execution_step_status"],
        "current_strategy_candidate_id": current_chain["current_strategy_candidate_id"],
        "current_strategy_candidate_ids": current_chain["current_strategy_candidate_ids"],
        "current_strategy_confirmed": current_chain["current_strategy_confirmed"],
        "current_effective_payload_status": current_chain["current_effective_payload_status"],
        "current_effective_payload_valid": current_chain["current_effective_payload_valid"],
        "current_action_id": current_chain["current_action_id"],
        "current_experiment_id": current_chain["current_experiment_id"],
        "current_experiment_status": current_chain["current_experiment_status"],
        "historical_strategy_candidate_ids": current_chain["historical_strategy_candidate_ids"],
        "historical_strategy_candidate_count": current_chain["historical_strategy_candidate_count"],
        "ineligible_strategy_candidates": current_chain["ineligible_strategy_candidates"],
        "historical_experiment_ids": current_chain["historical_experiment_ids"],
        "historical_experiment_count": current_chain["historical_experiment_count"],
        "legacy_action_confirmation_ignored": current_chain["legacy_action_confirmation_ignored"],
        "strategy_step": {
            "status": current_chain["strategy_step_status"],
            "detail": current_chain["strategy_step_detail"],
            "current_strategy_candidate_id": current_chain["current_strategy_candidate_id"],
            "current_strategy_candidate_ids": current_chain["current_strategy_candidate_ids"],
            "current_strategy_confirmed": current_chain["current_strategy_confirmed"],
            "effective_payload_status": current_chain["current_effective_payload_status"],
            "effective_payload_valid": current_chain["current_effective_payload_valid"],
            "ineligible_strategy_candidates": current_chain["ineligible_strategy_candidates"],
        },
        "execution_step": {
            "status": current_chain["execution_step_status"],
            "detail": current_chain["execution_step_detail"],
            "current_action_id": current_chain["current_action_id"],
            "current_experiment_id": current_chain["current_experiment_id"],
            "current_experiment_status": current_chain["current_experiment_status"],
            "historical_experiment_count": current_chain["historical_experiment_count"],
        },
    }


def build_continue_review_context(
    db: Session,
    project: Project,
    prompt_id: int,
    run_ids: list[int],
    *,
    limit: int = 12,
) -> dict:
    """Return raw answer context for human verification before overriding an unresolved decision."""
    runs = (
        db.query(BrowserMonitorRun)
        .filter(
            BrowserMonitorRun.project_id == project.id,
            BrowserMonitorRun.prompt_id == prompt_id,
            BrowserMonitorRun.id.in_(run_ids),
        )
        .order_by(BrowserMonitorRun.sample_index.asc(), BrowserMonitorRun.id.asc())
        .all()
    )
    events = (
        db.query(RecommendationEvent)
        .filter(
            RecommendationEvent.project_id == project.id,
            RecommendationEvent.prompt_id == prompt_id,
            RecommendationEvent.run_id.in_(run_ids),
        )
        .order_by(RecommendationEvent.run_id.asc(), RecommendationEvent.id.asc())
        .all()
    )
    status_counts = Counter(event.review_status or "UNKNOWN" for event in events)
    target_aliases = {
        item.strip()
        for item in [project.brand_name, *loads(project.brand_aliases_json, [])]
        if item and item.strip()
    }
    competitors = db.query(Competitor).filter(Competitor.project_id == project.id).all()
    competitor_aliases: dict[str, str] = {}
    for competitor in competitors:
        names = [competitor.name, *loads(competitor.aliases_json, [])]
        for name in names:
            if name and name.strip():
                competitor_aliases[name.strip()] = competitor.name

    entities_by_run: dict[int, dict[str, dict]] = defaultdict(dict)
    for event in events:
        entity = (event.entity_text or "").strip()
        if not entity:
            continue
        if any(alias and alias in entity for alias in target_aliases):
            relation = "TARGET_BRAND"
            relation_label = "目标品牌"
        else:
            matched_competitor = next(
                (canonical for alias, canonical in competitor_aliases.items() if alias and alias in entity),
                "",
            )
            if matched_competitor:
                relation = "CONFIRMED_COMPETITOR"
                relation_label = "已确认竞品"
                entity = matched_competitor
            else:
                relation = "UNCONFIRMED_ENTITY"
                relation_label = "待确认对象"
        row = entities_by_run[event.run_id].setdefault(entity, {
            "entity_text": entity,
            "relation": relation,
            "relation_label": relation_label,
            "speech_acts": set(),
            "review_statuses": set(),
        })
        row["speech_acts"].add(event.speech_act)
        row["review_statuses"].add(event.review_status or "UNKNOWN")

    answer_samples = []
    for run in runs[:limit]:
        answer_text = (run.answer_text or "").strip()
        detected_entities = []
        for entity_row in entities_by_run.get(run.id, {}).values():
            detected_entities.append({
                "entity_text": entity_row["entity_text"],
                "relation": entity_row["relation"],
                "relation_label": entity_row["relation_label"],
                "speech_acts": sorted(entity_row["speech_acts"]),
                "review_statuses": sorted(entity_row["review_statuses"]),
            })
        answer_samples.append({
            "run_id": run.id,
            "sample_index": run.sample_index,
            "run_sequence": run.run_sequence,
            "status": run.status,
            "question": run.original_query or run.page_query or "",
            "brand_mentioned": bool(run.brand_mentioned),
            "brand_recommendation_level": run.brand_recommendation_level,
            "detected_entities": detected_entities,
            "answer_excerpt": answer_text[:1200],
            "answer_char_count": len(answer_text),
        })

    event_diagnostics = []
    for event in events[: limit * 3]:
        event_diagnostics.append({
            "event_id": event.id,
            "run_id": event.run_id,
            "entity_text": event.entity_text,
            "speech_act": event.speech_act,
            "recommendation_strength": event.recommendation_strength,
            "polarity": event.polarity,
            "review_status": event.review_status,
            "answer_span": event.answer_span,
            "reasons": loads(event.reasons_json, []),
        })

    return {
        "answer_samples": answer_samples,
        "event_diagnostics": event_diagnostics,
        "event_status_counts": dict(status_counts),
        "review_instruction": (
            "请先核对答案样本：如果答案确实没有品牌/方案选择事件，可以搁置或人工指定方向；"
            "如果答案里有推荐但机器没有识别，应先回到决策诊断修正推荐事件，而不是盲目确认缺口。"
        ),
    }


def project_prompt_overview(db: Session, project: Project) -> dict:
    """项目级 Prompt 概览（项目视图用）：纯统计，不展示单个 Prompt 工作流。"""
    prompts = db.query(Prompt).filter(Prompt.project_id == project.id).all()

    run_rows = (
        db.query(BrowserMonitorRun.prompt_id, BrowserMonitorRun.brand_mentioned)
        .filter(BrowserMonitorRun.project_id == project.id)
        .all()
    )
    prompts_with_runs = {pid for pid, _ in run_rows}
    brand_mentioned_prompts = {pid for pid, mentioned in run_rows if mentioned}

    brand_aliases = {project.brand_name, *loads(getattr(project, "brand_aliases_json", "[]"), [])}

    event_rows = (
        db.query(
            RecommendationEvent.prompt_id,
            RecommendationEvent.entity_text,
            RecommendationEvent.speech_act,
        )
        .filter(RecommendationEvent.project_id == project.id)
        .all()
    )
    analyzed_prompts = {pid for pid, _, _ in event_rows}
    any_recommended_prompts = {
        pid for pid, _, speech_act in event_rows if speech_act == "INCLUDE_AS_OPTION"
    }
    brand_recommended_prompts = {
        pid
        for pid, entity_text, speech_act in event_rows
        if speech_act == "INCLUDE_AS_OPTION"
        and any(alias in (entity_text or "") for alias in brand_aliases)
    }

    reviews_done_count = 0
    for p in prompts:
        if p.id not in analyzed_prompts:
            continue
        try:
            if workflow_status(db, project, p.id).get("all_reviews_done"):
                reviews_done_count += 1
        except Exception:
            continue

    return {
        "project_id": project.id,
        "total_prompts": len(prompts),
        "prompts_with_runs": len(prompts_with_runs),
        "prompts_analyzed": len(analyzed_prompts),
        "prompts_brand_recommended": len(brand_recommended_prompts),
        "prompts_any_recommended": len(any_recommended_prompts),
        "prompts_brand_mentioned": len(brand_mentioned_prompts),
        "prompts_reviews_done": reviews_done_count,
    }


# ---------------------------------------------------------------------------
# 审核队列（去重：相同 answer_hash / 相同语义证据组只审一次）
# ---------------------------------------------------------------------------

def review_queue(db: Session, project: Project, prompt_id: int) -> dict:
    """返回去重后的待审核队列：事件按 answer_hash，对齐按语义证据组。"""
    events = db.query(RecommendationEvent).filter(
        RecommendationEvent.project_id == project.id,
        RecommendationEvent.prompt_id == prompt_id,
        RecommendationEvent.review_status.in_(PENDING_RECOMMENDATION_EVENT_STATUSES),
    ).all()

    # 按 answer_hash 去重事件
    unique_events: dict[str, dict] = {}
    for e in events:
        key = e.answer_hash or e.answer_span
        row = unique_events.setdefault(key, {
            "answer_hash": e.answer_hash,
            "entity_text": e.entity_text,
            "speech_act": e.speech_act,
            "recommendation_strength": e.recommendation_strength,
            "polarity": e.polarity,
            "answer_span": e.answer_span,
            "reasons": loads(e.reasons_json, []),
            "run_ids": set(),
            "event_ids": [],
        })
        row["run_ids"].add(e.run_id)
        row["event_ids"].append(e.id)

    # 审核队列只包含需要人工判断的对齐：
    # SUPPORTS（可能过度断言）—— RELATED/NONE/COMPETITOR_CONTEXT 为确定性或低价值，不占用人工
    supports = db.query(EvidenceAlignment).filter(
        EvidenceAlignment.project_id == project.id,
        EvidenceAlignment.prompt_id == prompt_id,
        EvidenceAlignment.relation == "SUPPORTS",
        EvidenceAlignment.review_status == "MACHINE_GROUNDED",
    ).all()

    align_groups: dict[tuple, dict] = {}
    for a in supports:
        claim = db.get(SourceClaim, a.source_claim_id) if a.source_claim_id else None
        machine_payload = loads(a.machine_payload_json, {})
        evidence_role = machine_payload.get("evidence_role") or machine_payload.get("classification") or ""
        reason_text = _review_reason_text(a, machine_payload)
        claim_text = _compact_review_text(claim.normalized_claim if claim else "")
        claim_span = _compact_review_text(claim.source_span if claim else "")
        key = (
            reason_text,
            a.source_document_id,
            a.source_claim_id,
            a.relation,
            evidence_role,
        )
        row = align_groups.setdefault(key, {
            "alignment_id": a.id,
            "alignment_ids": [],
            "reason_text": reason_text,
            "source_document_id": a.source_document_id,
            "source_claim_id": a.source_claim_id,
            "claim_text": claim_text,
            "claim_span": claim_span,
            "relation": a.relation,
            "evidence_role": evidence_role,
            "run_ids": set(),
            "semantic_observed_run_ids": set(),
        })
        row["alignment_ids"].append(a.id)
        row["run_ids"].update(_alignment_run_ids(a))
        row["semantic_observed_run_ids"].update(_semantic_observed_run_ids(a, machine_payload))

    align_items = [
        {
            **{k: v for k, v in row.items() if k not in {"run_ids", "semantic_observed_run_ids"}},
            "run_ids": sorted(row["run_ids"]),
            "run_count": len(row["run_ids"]),
            "semantic_observed_run_ids": sorted(row["semantic_observed_run_ids"]),
            "semantic_observed_run_count": len(row["semantic_observed_run_ids"]),
            "alignment_count": len(row["alignment_ids"]),
        }
        for row in align_groups.values()
    ]

    # 「尚未分析」的判定依据：该 Prompt 是否执行过机器分析
    # （有语义事件记录，或有分析运行记录——分析过但 0 事件也算分析过），
    # 而不是当前是否还有待审项（全部审完后待审项为空，不应误报未分析）
    analyzed = (
        db.query(RecommendationEvent.id)
        .filter(
            RecommendationEvent.project_id == project.id,
            RecommendationEvent.prompt_id == prompt_id,
        )
        .first()
        is not None
    ) or (
        db.query(PromptAnalysisRun.id)
        .filter(
            PromptAnalysisRun.project_id == project.id,
            PromptAnalysisRun.prompt_id == prompt_id,
        )
        .first()
        is not None
    )
    if not unique_events and not align_items and not analyzed:
        return {"status": "NOT_ANALYZED", "unique_events": [], "alignments": [], "message": "该 Prompt 尚未执行机器分析，请先运行分析。"}

    return {
        "status": "READY",
        "unique_events": [
            {**{k: v for k, v in row.items() if k not in {"run_ids", "event_ids"}},
             "run_ids": sorted(row["run_ids"]), "event_ids": row["event_ids"], "run_count": len(row["run_ids"])}
            for row in unique_events.values()
        ],
        "alignments": align_items,
    }


def batch_confirm_events(db: Session, event_ids: list[int], reviewer: str = "human") -> dict:
    """批量确认事件（answer_hash 相同的全部 Runs 一起确认）。"""
    updated = 0
    for eid in event_ids:
        e = db.get(RecommendationEvent, eid)
        if e:
            e.review_status = "HUMAN_CONFIRMED"
            e.reviewer = reviewer
            updated += 1
    db.commit()
    return {"updated": updated}


def confirm_alignment(db: Session, alignment_id: int, relation: str, reviewer: str = "human") -> dict:
    a = db.get(EvidenceAlignment, alignment_id)
    if not a:
        return {"status": "NOT_FOUND"}
    a.review_status = "HUMAN_CONFIRMED"
    a.relation = relation
    a.reviewer = reviewer
    db.commit()
    return {"status": "CONFIRMED", "relation": relation}


def batch_confirm_alignments(db: Session, alignment_ids: list[int], relation: str = "SUPPORTS", reviewer: str = "human") -> dict:
    """批量确认同一语义证据组。

    只更新人工审核字段和人工确认后的 relation，不合并、不删除底层
    Run-level EvidenceAlignment。
    """
    updated = 0
    missing_ids: list[int] = []
    for alignment_id in alignment_ids:
        a = db.get(EvidenceAlignment, alignment_id)
        if not a:
            missing_ids.append(alignment_id)
            continue
        a.review_status = "HUMAN_CONFIRMED"
        a.relation = relation
        a.reviewer = reviewer
        updated += 1
    db.commit()
    return {"status": "CONFIRMED", "updated": updated, "missing_ids": missing_ids, "relation": relation}
