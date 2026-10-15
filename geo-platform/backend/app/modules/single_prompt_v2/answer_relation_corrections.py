"""Task-scoped answer/relation corrections backed by append-only diagnosis revisions."""
from __future__ import annotations

import copy
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.models import (
    SinglePromptDiagnosisExecution,
    SinglePromptDiagnosisResult,
    SinglePromptExecutionProposal,
    SinglePromptExecutionProposalResult,
    SinglePromptStrategyResult,
    SinglePromptStrategyExecution,
    SinglePromptOptimizationTask,
)
from app.services.serialization import loads
from .automatic_delivery import require_task
from .delivery_text import digest


_VALUES = {
    "RECOMMENDATION_EVENT": {
        "RECOMMEND", "INCLUDE_AS_OPTION", "PRAISE", "COMPARE", "MENTION", "DISCOURAGE", "REJECT",
    },
    "EVIDENCE_RELATION": {"SOURCE_SUPPORTS_REASON", "SOURCE_CONTRADICTS_REASON", "RELATED", "NONE"},
}

_CORRECTION_READY_TASK_STATUSES = {"COMPLETED", "COMPLETED_WITH_LIMITATIONS"}


def _fixed_strategy_and_deliveries(db, task, objects: dict):
    strategy = db.query(SinglePromptStrategyResult).filter_by(
        strategy_id=objects["strategy_id"], result_version=objects["strategy_result_version"],
        output_hash=objects["strategy_result_hash"],
    ).one_or_none()
    if not strategy or digest(loads(strategy.output_json, {})) != strategy.output_hash:
        raise HTTPException(409, "自动优化任务的固定策略身份或 hash 不一致")
    directions = loads(strategy.output_json, {}).get("directions") or []
    direction_ids = [str(row.get("strategy_id") or row.get("direction_id") or "") for row in directions]
    if not direction_ids or any(not value for value in direction_ids) or len(set(direction_ids)) != len(direction_ids):
        raise HTTPException(409, "固定策略方向身份缺失或重复")

    bindings = objects.get("deliveries")
    if not isinstance(bindings, list) or not bindings:
        raise HTTPException(409, "自动优化任务尚未形成完整固定稿件集合，不能纠错")
    deliveries = []
    seen = set()
    for binding in bindings:
        if not isinstance(binding, dict):
            raise HTTPException(409, "自动优化任务的固定稿件身份缺失或重复")
        identity = (binding.get("proposal_id"), binding.get("result_version"), binding.get("result_hash"))
        if not all(identity) or identity in seen:
            raise HTTPException(409, "自动优化任务的固定稿件身份缺失或重复")
        seen.add(identity)
        proposal = db.query(SinglePromptExecutionProposal).filter_by(
            proposal_id=identity[0], strategy_id=objects["strategy_id"],
            strategy_result_version=objects["strategy_result_version"],
            strategy_result_hash=objects["strategy_result_hash"], diagnosis_id=objects["diagnosis_id"],
            analysis_id=task.analysis_id, context_id=task.context_id,
            project_id=task.project_id, prompt_id=task.prompt_id,
        ).one_or_none()
        result = db.query(SinglePromptExecutionProposalResult).filter_by(
            proposal_id=identity[0], result_version=identity[1], output_hash=identity[2],
        ).one_or_none() if proposal else None
        result_output = loads(result.output_json, {}) if result else {}
        if (not proposal or proposal.direction_id not in direction_ids or not result
                or digest(result_output) != result.output_hash
                or (result_output.get("validation") or {}).get("content_delivery_status") != "READY"):
            raise HTTPException(409, "自动优化任务的固定稿件身份、方向、版本或质量状态不一致")
        deliveries.append({
            "proposal_id": proposal.proposal_id,
            "strategy_id": proposal.direction_id,
            "result_version": result.result_version,
            "result_hash": result.output_hash,
        })
    delivery_direction_ids = [row["strategy_id"] for row in deliveries]
    if len(delivery_direction_ids) != len(direction_ids) or set(delivery_direction_ids) != set(direction_ids):
        raise HTTPException(409, "自动优化任务的固定稿件集合不完整或方向重复，不能纠错")
    return strategy, directions, deliveries


def _task_binding(db, *, task_id: str, project_id: int, prompt_id: int):
    task = require_task(db, task_id, project_id, prompt_id)
    fixed = loads(task.input_json, {})
    if fixed.get("delivery_revision") or fixed.get("truth_correction") or fixed.get("answer_relation_correction"):
        raise HTTPException(409, "答案与关系纠错必须从原始自动优化任务进入")
    if task.status not in _CORRECTION_READY_TASK_STATUSES:
        raise HTTPException(409, "答案与关系纠错仅允许在自动优化成功完成且稿件集合冻结后进行")
    objects = (loads(task.progress_json, {}).get("objects") or {})
    required = {
        "diagnosis_id", "answer_result_version", "answer_result_hash",
        "strategy_id", "strategy_result_version", "strategy_result_hash",
    }
    if not required.issubset(objects):
        raise HTTPException(409, "该任务尚未形成固定诊断、策略和稿件对象，不能纠错")
    execution = db.query(SinglePromptDiagnosisExecution).filter_by(
        diagnosis_id=objects["diagnosis_id"], analysis_id=task.analysis_id, context_id=task.context_id,
        project_id=project_id, prompt_id=prompt_id,
    ).one_or_none()
    frozen = db.query(SinglePromptDiagnosisResult).filter_by(
        diagnosis_id=objects["diagnosis_id"], result_version=objects["answer_result_version"],
        output_hash=objects["answer_result_hash"],
    ).one_or_none()
    if not execution or not frozen or digest(loads(frozen.output_json, {})) != frozen.output_hash:
        raise HTTPException(409, "自动优化任务的固定诊断身份或 hash 不一致")
    current = db.query(SinglePromptDiagnosisResult).filter_by(
        diagnosis_id=execution.diagnosis_id, result_version=execution.active_result_version,
    ).one_or_none()
    if not current or digest(loads(current.output_json, {})) != current.output_hash:
        raise HTTPException(409, "当前纠错版本缺失或 hash 不一致")

    # A formal task may consume its own correction descendants, never an unrelated/latest revision.
    by_version = {row.result_version: row for row in db.query(SinglePromptDiagnosisResult).filter_by(
        diagnosis_id=execution.diagnosis_id).all()}
    cursor = current
    seen = set()
    while cursor.result_version != frozen.result_version:
        if cursor.result_version in seen:
            raise HTTPException(409, "诊断版本 lineage 存在循环")
        seen.add(cursor.result_version)
        revision = (loads(cursor.output_json, {}).get("revision") or {})
        scope = revision.get("answer_relation_correction") or {}
        if scope.get("parent_task_id") != task.task_id:
            raise HTTPException(409, "当前诊断版本不属于该自动优化任务的纠错 lineage")
        cursor = by_version.get(cursor.parent_result_version)
        if not cursor:
            raise HTTPException(409, "诊断纠错 lineage 不完整")
    _fixed_strategy_and_deliveries(db, task, objects)
    return task, objects, frozen, current


def _target(output: dict, target_type: str, target_id: str) -> tuple[dict | None, str]:
    if target_type == "RECOMMENDATION_EVENT":
        rows = (output.get("answer_diagnosis") or {}).get("events") or []
        return next((row for row in rows if row.get("event_id") == target_id), None), "effective_speech_act"
    if target_type == "EVIDENCE_RELATION":
        rows = (output.get("evidence_diagnosis") or {}).get("source_relations") or []
        return next((row for row in rows if row.get("relation_id") == target_id), None), "effective_relation"
    return None, ""


def _identity_manifest(db, task, objects: dict, output: dict, affected_reason_ids: set[str]) -> dict:
    all_reason_ids = {
        str(reason["reason_id"])
        for event in (output.get("answer_diagnosis") or {}).get("events") or []
        for reason in event.get("reasons") or [] if reason.get("reason_id")
    }
    strategy, directions, deliveries = _fixed_strategy_and_deliveries(db, task, objects)
    affected_strategy_ids, unaffected_strategy_ids = [], []
    for row in directions:
        direction_id = str(row.get("strategy_id") or row.get("direction_id") or "")
        if not direction_id:
            raise HTTPException(409, "固定策略缺少方向身份")
        bucket = affected_strategy_ids if affected_reason_ids.intersection(
            str(value) for value in row.get("reason_ids") or []
        ) else unaffected_strategy_ids
        bucket.append(direction_id)

    affected_set = set(affected_strategy_ids)
    affected_deliveries = [row for row in deliveries if row["strategy_id"] in affected_set]
    unaffected_deliveries = [row for row in deliveries if row["strategy_id"] not in affected_set]
    return {
        "affected_reason_ids": sorted(affected_reason_ids),
        "unaffected_reason_ids": sorted(all_reason_ids - affected_reason_ids),
        "affected_strategy_ids": sorted(affected_strategy_ids),
        "unaffected_strategy_ids": sorted(unaffected_strategy_ids),
        "affected_deliveries": affected_deliveries,
        "unaffected_deliveries": unaffected_deliveries,
        "fixed_strategy": {
            "strategy_id": objects["strategy_id"], "result_version": strategy.result_version,
            "result_hash": strategy.output_hash,
        },
        "unchanged_objects": [
            "原回答正文与 span", "CitationContribution", "既有策略版本", "既有稿件版本", "历史验收记录",
        ],
        "recompute_task_created": False,
        "external_calls": 0,
    }


def correction_status(db, *, task_id: str, project_id: int, prompt_id: int) -> dict:
    task, objects, frozen, current = _task_binding(
        db, task_id=task_id, project_id=project_id, prompt_id=prompt_id,
    )
    output = loads(current.output_json, {})
    targets = []
    for event in (output.get("answer_diagnosis") or {}).get("events") or []:
        targets.append({
            "target_type": "RECOMMENDATION_EVENT", "target_id": event["event_id"],
            "target_hash": digest(event), "current_value": event.get("effective_speech_act"),
            "machine_value": event.get("machine_speech_act"), "can_correct": True,
            "label": event.get("entity_text") or event["event_id"],
            "reason_ids": [row["reason_id"] for row in event.get("reasons") or []],
            "allowed_values": sorted(_VALUES["RECOMMENDATION_EVENT"]),
        })
    for relation in (output.get("evidence_diagnosis") or {}).get("source_relations") or []:
        evaluated = relation.get("alignment_evaluation") == "EVALUATED"
        targets.append({
            "target_type": "EVIDENCE_RELATION", "target_id": relation["relation_id"],
            "target_hash": digest(relation), "current_value": relation.get("effective_relation"),
            "machine_value": relation.get("machine_relation"), "can_correct": evaluated,
            "blocked_reason": "仅允许纠正已评估关系" if not evaluated else "",
            "label": f"理由 {relation.get('reason_id')} / 来源 {relation.get('source_snapshot_id')}",
            "reason_ids": [relation["reason_id"]] if relation.get("reason_id") else [],
            "alignment_evaluation": relation.get("alignment_evaluation"),
            "allowed_values": sorted(_VALUES["EVIDENCE_RELATION"]),
        })
    history = []
    for row in db.query(SinglePromptDiagnosisResult).filter_by(diagnosis_id=objects["diagnosis_id"]).order_by(
        SinglePromptDiagnosisResult.version_number
    ):
        metadata = ((loads(row.output_json, {}).get("revision") or {}).get("answer_relation_correction") or {})
        if metadata.get("parent_task_id") == task.task_id:
            history.append({
                "result_version": row.result_version, "parent_result_version": row.parent_result_version,
                "result_hash": row.output_hash, "actor": metadata.get("actor"),
                "created_at": row.created_at.isoformat(), "summary": metadata.get("summary"),
                "impact": metadata.get("impact"),
            })
    return {
        "task_id": task.task_id, "diagnosis_id": objects["diagnosis_id"],
        "frozen_result_version": frozen.result_version, "base_result_version": current.result_version,
        "base_result_hash": current.output_hash, "reviewable_set_hash": current.reviewable_set_hash,
        "targets": targets, "history": history,
    }


def preview_correction(db, *, task_id: str, project_id: int, prompt_id: int,
                       base_result_version: str, base_result_hash: str, reviewable_set_hash: str,
                       target_type: str, target_id: str, target_hash: str, value: str, reason: str) -> dict:
    task, objects, _, current = _task_binding(db, task_id=task_id, project_id=project_id, prompt_id=prompt_id)
    if (current.result_version != base_result_version or current.output_hash != base_result_hash
            or current.reviewable_set_hash != reviewable_set_hash):
        raise HTTPException(409, "诊断纠错版本或 hash 已变化，请重新加载")
    reason = reason.strip()
    if not reason:
        raise HTTPException(422, "纠错依据不能为空")
    output = loads(current.output_json, {})
    target, field = _target(output, target_type, target_id)
    if not target or target_type not in _VALUES or value not in _VALUES[target_type]:
        raise HTTPException(422, "纠错对象或修改值非法")
    if digest(target) != target_hash:
        raise HTTPException(409, "纠错对象或 span 身份已变化，请重新加载")
    if target_type == "EVIDENCE_RELATION" and target.get("alignment_evaluation") != "EVALUATED":
        raise HTTPException(422, "FAILED、NOT_EVALUATED 或其他未完成判断的关系不能升级为 verdict")
    if target.get(field) == value:
        raise HTTPException(422, "纠错值与当前判断相同")
    affected = ({str(row["reason_id"]) for row in target.get("reasons") or []}
        if target_type == "RECOMMENDATION_EVENT" else {str(target["reason_id"])})
    impact = _identity_manifest(db, task, objects, output, affected)
    edit = {
        "target_type": target_type, "target_id": target_id, "target_hash": target_hash,
        "before": target.get(field), "after": value, "reason": reason,
    }
    payload = {
        "parent_task_id": task.task_id, "parent_input_hash": task.input_hash,
        "parent_task_revision": task.revision, "parent_task_status": task.status,
        "diagnosis_id": objects["diagnosis_id"], "base_result_version": current.result_version,
        "base_result_hash": current.output_hash, "reviewable_set_hash": current.reviewable_set_hash,
        "edit": edit, "impact": impact,
    }
    return {**payload, "preview_hash": digest(payload)}


def save_correction(db, *, actor: str, preview_hash: str, **values) -> dict:
    from .diagnosis import revise_diagnosis_result

    preview = preview_correction(db, **values)
    if preview["preview_hash"] != preview_hash:
        raise HTTPException(409, "影响预览已变化，请重新核对后提交")
    edit = preview["edit"]
    summary = {
        "target_type": edit["target_type"], "target_id": edit["target_id"],
        "before": edit["before"], "after": edit["after"], "reason": edit["reason"],
    }
    result = revise_diagnosis_result(
        db, diagnosis_id=preview["diagnosis_id"], base_result_version=preview["base_result_version"],
        base_result_hash=preview["base_result_hash"], reviewable_set_hash=preview["reviewable_set_hash"],
        edits=[{"target_type": edit["target_type"], "target_id": edit["target_id"],
                "value": edit["after"], "reason": edit["reason"]}], editor=actor,
        revision_metadata={"answer_relation_correction": {
            "parent_task_id": preview["parent_task_id"], "parent_input_hash": preview["parent_input_hash"],
            "actor": actor, "summary": summary, "impact": preview["impact"],
            "preview_hash": preview_hash,
            "notice": "本版本尚未重算或升级既有策略与稿件",
        }},
    )
    return {
        "result_version": result.result_version, "parent_result_version": result.parent_result_version,
        "result_hash": result.output_hash, "actor": actor, "created_at": result.created_at.isoformat(),
        "summary": summary, "impact": preview["impact"],
    }


def _reprojection_input(db, *, parent_task_id: str, project_id: int, prompt_id: int,
                        correction_result_version: str, correction_result_hash: str,
                        requested_by: str) -> tuple[SinglePromptOptimizationTask, dict]:
    parent, objects, _, current = _task_binding(
        db, task_id=parent_task_id, project_id=project_id, prompt_id=prompt_id,
    )
    if current.result_version != correction_result_version or current.output_hash != correction_result_hash:
        raise HTTPException(409, "答案与关系纠错已产生后续版本，或版本/hash 不匹配")
    output = loads(current.output_json, {})
    correction = ((output.get("revision") or {}).get("answer_relation_correction") or {})
    if (correction.get("parent_task_id") != parent.task_id
            or correction.get("parent_input_hash") != parent.input_hash
            or digest(output) != current.output_hash):
        raise HTTPException(409, "答案与关系纠错 lineage、父任务身份或 hash 不一致")
    impact = correction.get("impact")
    required_impact = {
        "affected_strategy_ids", "unaffected_strategy_ids",
        "affected_deliveries", "unaffected_deliveries", "fixed_strategy",
    }
    if not isinstance(impact, dict) or not required_impact.issubset(impact):
        raise HTTPException(409, "答案与关系纠错影响范围不完整")
    fixed_strategy = impact["fixed_strategy"]
    if (fixed_strategy.get("strategy_id") != objects["strategy_id"]
            or fixed_strategy.get("result_version") != objects["strategy_result_version"]
            or fixed_strategy.get("result_hash") != objects["strategy_result_hash"]):
        raise HTTPException(409, "纠错影响范围绑定的策略身份已变化")
    _, _, deliveries = _fixed_strategy_and_deliveries(db, parent, objects)
    frozen_deliveries = sorted(
        impact["affected_deliveries"] + impact["unaffected_deliveries"],
        key=lambda row: (row["strategy_id"], row["proposal_id"]),
    )
    if frozen_deliveries != sorted(deliveries, key=lambda row: (row["strategy_id"], row["proposal_id"])):
        raise HTTPException(409, "纠错影响范围绑定的稿件身份已变化")
    if not str(requested_by).strip():
        raise HTTPException(403, "缺少实际访问身份")
    fixed = loads(parent.input_json, {})
    fixed["source_fetch_authorized"] = False
    fixed["answer_relation_correction"] = {
        "parent_task_id": parent.task_id,
        "parent_input_hash": parent.input_hash,
        "parent_task_revision": parent.revision,
        "diagnosis_id": objects["diagnosis_id"],
        "correction_result_version": current.result_version,
        "correction_result_hash": current.output_hash,
        "reviewable_set_hash": current.reviewable_set_hash,
        "parent_answer_result_version": objects["answer_result_version"],
        "parent_answer_result_hash": objects["answer_result_hash"],
        "citation_results": objects.get("citation_results") or [],
        "impact": impact,
        "fixed_strategy": fixed_strategy,
        "fixed_deliveries": deliveries,
        "requested_by": requested_by.strip(),
    }
    return parent, fixed


def validate_reprojection(db, task: SinglePromptOptimizationTask) -> dict:
    fixed = loads(task.input_json, {})
    ref = fixed.get("answer_relation_correction") or {}
    required = {
        "parent_task_id", "correction_result_version", "correction_result_hash", "requested_by",
    }
    if not required.issubset(ref):
        raise HTTPException(409, "答案与关系策略重投影缺少冻结身份")
    _, expected = _reprojection_input(
        db, parent_task_id=ref["parent_task_id"], project_id=task.project_id,
        prompt_id=task.prompt_id, correction_result_version=ref["correction_result_version"],
        correction_result_hash=ref["correction_result_hash"], requested_by=ref["requested_by"],
    )
    if fixed != expected or digest(expected) != task.input_hash:
        raise HTTPException(409, "答案与关系策略重投影输入、lineage 或影响范围已变化")
    return ref


def create_reprojection_task(db, *, parent_task_id: str, project_id: int, prompt_id: int,
                             correction_result_version: str, correction_result_hash: str,
                             idempotency_key: str, requested_by: str):
    from .automatic_delivery import encode

    parent, fixed = _reprojection_input(
        db, parent_task_id=parent_task_id, project_id=project_id, prompt_id=prompt_id,
        correction_result_version=correction_result_version,
        correction_result_hash=correction_result_hash, requested_by=requested_by,
    )
    fingerprint = digest(fixed)
    same_key = db.query(SinglePromptOptimizationTask).filter_by(
        project_id=project_id, idempotency_key=idempotency_key,
    ).one_or_none()
    if same_key and same_key.input_hash != fingerprint:
        raise HTTPException(409, "幂等键已绑定其他答案与关系策略重投影输入")
    existing = same_key or db.query(SinglePromptOptimizationTask).filter_by(
        analysis_id=parent.analysis_id, input_hash=fingerprint,
    ).one_or_none()
    if existing:
        return existing, False
    row = SinglePromptOptimizationTask(
        task_id=f"optimize-{uuid4()}", project_id=project_id, prompt_id=prompt_id,
        analysis_id=parent.analysis_id, context_id=parent.context_id,
        input_json=encode(fixed), input_hash=fingerprint, idempotency_key=idempotency_key,
        authorization_json=encode({"policy": "CACHE_ONLY", "max_requests": 0,
                                   "max_tokens": 0, "max_cost_cny": 0}),
        progress_json=encode({"stage": "STRATEGY", "objects": {}, "requests": [], "limitations": []}),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = db.query(SinglePromptOptimizationTask).filter_by(
            analysis_id=parent.analysis_id, input_hash=fingerprint,
        ).one_or_none()
        if concurrent:
            return concurrent, False
        raise
    return row, True


def execute_reprojection(db, task: SinglePromptOptimizationTask, fixed: dict) -> None:
    from .automatic_delivery import checkpoint
    from .context_provider import select_context
    from .qualification import _load_current_contribution_scope, evaluate_qualification_projection
    from .strategy import build_strategy_input_projection

    ref = validate_reprojection(db, task)
    context_version = (fixed.get("brand_context") or {}).get("context_version_id")
    projection = build_strategy_input_projection(
        db, analysis_id=task.analysis_id, diagnosis_id=ref["diagnosis_id"],
        result_version=ref["correction_result_version"], project_id=task.project_id,
        prompt_id=task.prompt_id,
    )
    if not projection.get("is_active_result"):
        raise HTTPException(409, "策略重投影只读取当前精确纠错版本")
    citation_versions = [row["result_version"] for row in ref["citation_results"]]
    contribution_scope = _load_current_contribution_scope(
        db, analysis_id=task.analysis_id, context_id=task.context_id,
        answer_result_version=ref["parent_answer_result_version"],
        answer_result_hash=ref["parent_answer_result_hash"], result_versions=citation_versions,
    )
    expected_citations = {row["result_version"]: row["result_hash"] for row in ref["citation_results"]}
    contribution = contribution_scope.get("result") or {}
    observed_citations = ({row["result_version"]: row["result_hash"]
        for row in contribution.get("results") or []} if contribution.get("results") is not None
        else ({contribution["result_version"]: contribution["result_hash"]}
              if contribution.get("result_version") else {}))
    if observed_citations != expected_citations:
        raise HTTPException(409, "父任务冻结的 CitationContribution 版本或 hash 不一致")
    qualification = evaluate_qualification_projection(
        projection, contribution_scope, str(projection["prompt_snapshot"]["text"]),
    )
    context = select_context(
        db, project_id=task.project_id, context_version_id=context_version,
        query=projection["prompt_snapshot"]["text"],
    )
    qualification["brand_context"] = context
    qualification["selected_contribution_result_versions"] = sorted(citation_versions)
    versions = (contribution_scope.get("result") or {}).get("result_versions") or []
    if len(versions) > 1:
        for direction in qualification["directions"]:
            dependencies = []
            for dependency in direction["dependencies"]:
                if dependency["object_type"] == "CITATION_CONTRIBUTION_SCOPE":
                    dependencies.extend({**dependency, "object_id": version,
                        "dependency_id": dependency["dependency_id"] + ":" + version} for version in versions)
                else:
                    dependencies.append(dependency)
            direction["dependencies"] = dependencies
    for direction in qualification["directions"]:
        direction["context_considerations"] = [{
            "passage_id": passage["passage_id"], "text": passage["text"],
            "source_reference": passage["source_reference"],
            "use": "INTERNAL_SCOPE_CHECK_NOT_PUBLIC_CLAIM",
        } for passage in context["passages"]]
        if context["passages"]:
            direction["reasoning_trace"].append({
                "step": "SUPPLEMENTAL_CONTEXT", "version_id": context["context_version_id"],
                "content_hash": context["content_hash"],
                "passage_ids": [passage["passage_id"] for passage in context["passages"]],
                "result": "INTERNAL_SCOPE_CHECK_NOT_VERIFIED_TRUTH",
            })
    impact = ref["impact"]
    affected_reason_ids = set(impact["affected_reason_ids"])
    scoped_directions = []
    projected_reason_ids = set()
    unscoped_directions = []
    for direction in qualification["directions"]:
        reason_ids = {str(value) for value in direction.get("reason_ids") or [] if value}
        if direction.get("reason_id"):
            reason_ids.add(str(direction["reason_id"]))
        if reason_ids and reason_ids.issubset(affected_reason_ids):
            scoped_directions.append(direction)
            projected_reason_ids.update(reason_ids)
        elif not reason_ids:
            unscoped_directions.append(direction)
    if not projected_reason_ids and affected_reason_ids and len(qualification["directions"]) == 1 \
            and len(unscoped_directions) == 1:
        direction = unscoped_directions[0]
        direction["reason_ids"] = sorted(affected_reason_ids)
        direction["reason_id"] = (next(iter(affected_reason_ids))
                                  if len(affected_reason_ids) == 1 else None)
        direction.setdefault("reasoning_trace", []).append({
            "step": "ANSWER_RELATION_REPROJECTION_SCOPE",
            "object_ids": sorted(affected_reason_ids),
            "result": "FROZEN_AFFECTED_REASON_IDENTITY",
        })
        scoped_directions = [direction]
        projected_reason_ids = set(affected_reason_ids)
    if projected_reason_ids != affected_reason_ids:
        raise HTTPException(409, "纠错后的策略投影不能完整覆盖冻结的受影响 reason identity")
    qualification["directions"] = scoped_directions
    projected_ids = {str(direction.get("strategy_id") or direction.get("direction_id") or "")
                     for direction in qualification["directions"]}
    qualification["execution_drafts"] = [draft for draft in qualification["execution_drafts"]
        if str(draft.get("direction_id") or "") in projected_ids]
    draft_direction_ids = {str(draft.get("direction_id") or "")
                           for draft in qualification["execution_drafts"]}
    if draft_direction_ids != projected_ids:
        raise HTTPException(409, "局部策略投影与执行草稿的 direction identity 集合不一致")
    final_plan = qualification.get("final_plan") or {}
    final_plan["machine_direction_count"] = len(qualification["directions"])
    final_plan["execution_draft_count"] = len(qualification["execution_drafts"])
    final_plan["execution_ready_count"] = sum(1 for draft in qualification["execution_drafts"]
        if (draft.get("boundary") or {}).get("public_claims_ready"))
    final_plan["draftable_verify_first_count"] = sum(1 for draft in qualification["execution_drafts"]
        if not (draft.get("boundary") or {}).get("public_claims_ready"))
    qualification["reprojection_scope"] = {
        "mode": "AFFECTED_STRATEGIES_ONLY",
        "affected_reason_ids": impact["affected_reason_ids"],
        "projected_reason_ids": sorted(projected_reason_ids),
        "affected_strategy_ids": impact["affected_strategy_ids"],
        "unaffected_parent_strategy": {
            **ref["fixed_strategy"], "strategy_ids": impact["unaffected_strategy_ids"],
        },
    }
    qualification.pop("projection_hash")
    qualification["projection_hash"] = digest(qualification)

    projection_hash = qualification["projection_hash"]
    authority_id = f"qualification:{projection_hash}"
    input_fingerprint = digest({
        "identity": qualification["input_identity"], "authority_id": authority_id,
        "qualification_contract_version": qualification.get("contract_version"),
    })
    strategy_key = f"{task.task_id}:answer-relation-reprojection"
    existing_strategy = db.query(SinglePromptStrategyExecution).filter_by(
        diagnosis_id=ref["diagnosis_id"], idempotency_key=strategy_key,
    ).one_or_none()
    if existing_strategy:
        if existing_strategy.input_fingerprint != input_fingerprint:
            raise HTTPException(409, "策略重投影幂等键已绑定其他冻结输入")
        strategy = existing_strategy
        strategy_result = db.query(SinglePromptStrategyResult).filter_by(
            strategy_id=strategy.strategy_id, result_version=strategy.active_result_version,
        ).one()
    else:
        strategy_id = f"strategy-{uuid4()}"
        strategy_output = {
            "contract_version": "single_prompt_v2.automatic_strategy_result.v1",
            "strategy_id": strategy_id,
            "authority": {"type": "MACHINE_QUALIFICATION", "authority_id": authority_id,
                "authority_hash": projection_hash, "human_review_required_for_computation": False,
                "business_confirmation_required_for_external_action": True},
            "input_identity": copy.deepcopy(qualification["input_identity"]),
            "input_projection_hash": projection_hash,
            "directions": copy.deepcopy(qualification["directions"]),
            "execution_drafts": copy.deepcopy(qualification["execution_drafts"]),
            "parent_strategy_reference": copy.deepcopy(qualification["reprojection_scope"]["unaffected_parent_strategy"]),
            "object_qualifications": copy.deepcopy(qualification.get("object_qualifications") or []),
            "analysis_scope": copy.deepcopy(qualification.get("analysis_scope") or {}),
            "evidence_scope": copy.deepcopy(qualification.get("evidence_scope") or {}),
            "limitations": copy.deepcopy(qualification.get("scope_limitations") or []),
            "boundary": copy.deepcopy(qualification.get("boundary") or {}),
        }
        strategy_hash = digest(strategy_output)
        strategy_result = SinglePromptStrategyResult(
            result_version=f"strategy-v1:{strategy_hash[:16]}", strategy_id=strategy_id,
            version_number=1, parent_result_version=None, output_json=_canonical(strategy_output),
            output_hash=strategy_hash, reviewable_set_hash=digest({
                "direction_ids": sorted(str(row.get("direction_id") or row.get("strategy_id"))
                                        for row in qualification["directions"]),
                "draft_ids": sorted(str(row.get("draft_id")) for row in qualification["execution_drafts"]),
                "authority_hash": projection_hash,
            }), limitations_json=_canonical(strategy_output["limitations"]),
        )
        strategy = SinglePromptStrategyExecution(
            strategy_id=strategy_id, analysis_id=task.analysis_id, context_id=task.context_id,
            diagnosis_id=ref["diagnosis_id"], project_id=task.project_id, prompt_id=task.prompt_id,
            idempotency_key=strategy_key, input_fingerprint=input_fingerprint,
            diagnosis_result_version=ref["correction_result_version"],
            diagnosis_result_hash=ref["correction_result_hash"], diagnosis_review_id="",
            review_snapshot_hash="", input_authority_type="MACHINE_QUALIFICATION",
            input_authority_id=authority_id, input_authority_hash=projection_hash,
            validation_contract_version="single_prompt_v2.machine_qualification.v1",
            input_snapshot_json=_canonical(qualification), input_snapshot_hash=projection_hash,
            status="READY_FOR_EXECUTION_DRAFT", active_result_version=strategy_result.result_version,
        )
        db.add_all([strategy, strategy_result])
        db.commit()
    affected_deliveries = sorted(impact["affected_deliveries"],
        key=lambda row: (row["strategy_id"], row["proposal_id"], row["result_version"], row["result_hash"]))
    regeneration_plan = _affected_delivery_regeneration_plan(db, ref, loads(strategy_result.output_json, {}))
    manifest = {
        "parent_task_id": ref["parent_task_id"],
        "parent_input_hash": ref["parent_input_hash"],
        "diagnosis_id": ref["diagnosis_id"],
        "correction_result_version": ref["correction_result_version"],
        "correction_result_hash": ref["correction_result_hash"],
        "reviewable_set_hash": ref["reviewable_set_hash"],
        "fixed_strategy": ref["fixed_strategy"],
        "new_strategy_id": strategy.strategy_id,
        "new_strategy_result_version": strategy_result.result_version,
        "new_strategy_result_hash": strategy_result.output_hash,
        "affected_strategy_ids": impact["affected_strategy_ids"],
        "unaffected_strategy_ids": impact["unaffected_strategy_ids"],
        "pending_delivery_updates": affected_deliveries,
        "affected_delivery_set_hash": digest(affected_deliveries),
        "affected_delivery_regeneration_plan": regeneration_plan,
        "unchanged_deliveries": impact["unaffected_deliveries"],
        "deliveries_regenerated": False,
    }
    checkpoint(
        db, task, stage="COMPLETE", objects={"answer_relation_reprojection": manifest},
        limitations=["ANSWER_RELATION_REPROJECTION_REQUIRES_EXPLICIT_DELIVERY_UPDATE"],
        status="COMPLETED_WITH_LIMITATIONS",
    )


def _direction_reason_ids(direction: dict) -> frozenset[str]:
    values = {str(value) for value in direction.get("reason_ids") or [] if value}
    if direction.get("reason_id"):
        values.add(str(direction["reason_id"]))
    return frozenset(values)


def _affected_delivery_regeneration_plan(db, ref: dict, new_strategy_output: dict) -> list[dict]:
    """Freeze an exact one-old-delivery to one-new-direction regeneration plan."""
    old = db.query(SinglePromptStrategyResult).filter_by(
        strategy_id=ref["fixed_strategy"]["strategy_id"],
        result_version=ref["fixed_strategy"]["result_version"],
        output_hash=ref["fixed_strategy"]["result_hash"],
    ).one_or_none()
    old_output = loads(old.output_json, {}) if old else {}
    if not old or digest(old_output) != old.output_hash:
        raise HTTPException(409, "受影响稿件的父策略版本或 hash 不一致")
    old_directions = {
        str(row.get("strategy_id") or row.get("direction_id") or ""): row
        for row in old_output.get("directions") or []
    }
    new_directions = {
        str(row.get("direction_id") or row.get("strategy_id") or ""): row
        for row in new_strategy_output.get("directions") or []
    }
    affected = sorted(ref["impact"]["affected_deliveries"],
        key=lambda row: (row["strategy_id"], row["proposal_id"], row["result_version"], row["result_hash"]))
    if len(affected) != len(new_directions):
        raise HTTPException(409, "受影响稿件与新策略方向数量不一致，禁止静默少生成或多生成")
    plan, used = [], set()
    for binding in affected:
        old_direction = old_directions.get(str(binding["strategy_id"]))
        old_reasons = _direction_reason_ids(old_direction or {})
        candidates = [direction_id for direction_id, direction in new_directions.items()
            if direction_id not in used and old_reasons and _direction_reason_ids(direction) == old_reasons]
        if len(candidates) != 1:
            raise HTTPException(409, "受影响稿件与新策略方向无法形成唯一 reason identity 映射")
        direction_id = candidates[0]
        used.add(direction_id)
        plan.append({"affected_delivery": copy.deepcopy(binding), "new_direction_id": direction_id,
                     "reason_ids": sorted(old_reasons)})
    if used != set(new_directions):
        raise HTTPException(409, "新策略包含未绑定受影响稿件的额外方向")
    return plan


def _delivery_regeneration_input(
    db, *, reprojection_task_id: str, project_id: int, prompt_id: int,
    expected_revision: int, strategy_result_version: str, strategy_result_hash: str,
    affected_delivery_set_hash: str, requested_by: str,
) -> tuple[SinglePromptOptimizationTask, dict, dict]:
    parent = require_task(db, reprojection_task_id, project_id, prompt_id)
    parent_fixed = loads(parent.input_json, {})
    if parent_fixed.get("answer_relation_delivery_regeneration") or not parent_fixed.get("answer_relation_correction"):
        raise HTTPException(409, "受影响稿件重新生成必须直接绑定答案与关系策略重投影任务")
    if parent.status not in _CORRECTION_READY_TASK_STATUSES:
        raise HTTPException(409, "答案与关系策略重投影尚未成功完成")
    if parent.revision != expected_revision:
        raise HTTPException(409, "策略重投影任务 revision 已变化，请重新加载")
    ref = validate_reprojection(db, parent)
    progress = loads(parent.progress_json, {})
    manifest = (progress.get("objects") or {}).get("answer_relation_reprojection") or {}
    impact = ref["impact"]
    expected_manifest = {
        "parent_task_id": ref["parent_task_id"],
        "parent_input_hash": ref["parent_input_hash"],
        "diagnosis_id": ref["diagnosis_id"],
        "correction_result_version": ref["correction_result_version"],
        "correction_result_hash": ref["correction_result_hash"],
        "reviewable_set_hash": ref["reviewable_set_hash"],
        "fixed_strategy": ref["fixed_strategy"],
        "affected_strategy_ids": impact["affected_strategy_ids"],
        "unaffected_strategy_ids": impact["unaffected_strategy_ids"],
        "pending_delivery_updates": sorted(impact["affected_deliveries"],
            key=lambda row: (row["strategy_id"], row["proposal_id"], row["result_version"], row["result_hash"])),
        "unchanged_deliveries": impact["unaffected_deliveries"],
        "deliveries_regenerated": False,
    }
    if any(manifest.get(key) != value for key, value in expected_manifest.items()):
        raise HTTPException(409, "策略重投影结果与冻结纠错影响范围不一致")
    if (manifest.get("new_strategy_result_version") != strategy_result_version
            or manifest.get("new_strategy_result_hash") != strategy_result_hash):
        raise HTTPException(409, "必须使用该重投影任务产生的新策略版本与 hash")
    affected = sorted(impact["affected_deliveries"],
        key=lambda row: (row["strategy_id"], row["proposal_id"], row["result_version"], row["result_hash"]))
    if not affected or digest(affected) != affected_delivery_set_hash:
        raise HTTPException(409, "受影响稿件集合 hash 不完整、已变化或不是完整冻结集合")
    unchanged = sorted(impact["unaffected_deliveries"],
        key=lambda row: (row["strategy_id"], row["proposal_id"], row["result_version"], row["result_hash"]))
    if set(row["proposal_id"] for row in affected) & set(row["proposal_id"] for row in unchanged):
        raise HTTPException(409, "受影响与未受影响稿件集合重叠")
    for binding in affected + unchanged:
        result = db.query(SinglePromptExecutionProposalResult).filter_by(
            proposal_id=binding["proposal_id"], result_version=binding["result_version"],
            output_hash=binding["result_hash"],
        ).one_or_none()
        if not result or digest(loads(result.output_json, {})) != result.output_hash:
            raise HTTPException(409, "父任务冻结稿件版本或 hash 已变化")
    strategy_id = manifest.get("new_strategy_id")
    strategy = db.query(SinglePromptStrategyExecution).filter_by(
        strategy_id=strategy_id, analysis_id=parent.analysis_id, context_id=parent.context_id,
        diagnosis_id=ref["diagnosis_id"], project_id=project_id, prompt_id=prompt_id,
        active_result_version=strategy_result_version,
    ).one_or_none()
    strategy_result = db.query(SinglePromptStrategyResult).filter_by(
        strategy_id=strategy_id, result_version=strategy_result_version,
        output_hash=strategy_result_hash,
    ).one_or_none()
    strategy_output = loads(strategy_result.output_json, {}) if strategy_result else {}
    if (not strategy or not strategy_result or digest(strategy_output) != strategy_result_hash
            or strategy.diagnosis_result_version != ref["correction_result_version"]
            or strategy.diagnosis_result_hash != ref["correction_result_hash"]):
        raise HTTPException(409, "新策略身份、纠错版本或 hash 不一致")
    regeneration_plan = _affected_delivery_regeneration_plan(db, ref, strategy_output)
    expected_set_hash = digest(affected)
    if (manifest.get("affected_delivery_set_hash") != expected_set_hash
            or manifest.get("affected_delivery_regeneration_plan") != regeneration_plan):
        raise HTTPException(409, "策略重投影冻结的受影响稿件 hash 或生成映射不一致")
    direction_ids = [str(row.get("direction_id") or row.get("strategy_id") or "")
                     for row in strategy_output.get("directions") or []]
    if not direction_ids or any(not value for value in direction_ids) or len(set(direction_ids)) != len(direction_ids):
        raise HTTPException(409, "新策略没有完整且唯一的受影响方向集合")
    if not str(requested_by).strip():
        raise HTTPException(403, "缺少实际访问身份")
    fixed = copy.deepcopy(parent_fixed)
    fixed["source_fetch_authorized"] = False
    fixed["answer_relation_delivery_regeneration"] = {
        "contract_version": "answer_relation_delivery_regeneration.v1",
        "reprojection_task_id": parent.task_id,
        "reprojection_input_hash": parent.input_hash,
        "reprojection_revision": parent.revision,
        "correction_result_version": ref["correction_result_version"],
        "correction_result_hash": ref["correction_result_hash"],
        "strategy_id": strategy_id,
        "strategy_result_version": strategy_result_version,
        "strategy_result_hash": strategy_result_hash,
        "affected_delivery_set_hash": affected_delivery_set_hash,
        "affected_deliveries": affected,
        "unchanged_deliveries": unchanged,
        "delivery_regeneration_plan": regeneration_plan,
        "new_direction_ids": direction_ids,
        "requested_by": requested_by.strip(),
    }
    return parent, fixed, strategy_output


def create_delivery_regeneration_task(
    db, *, reprojection_task_id: str, project_id: int, prompt_id: int,
    expected_revision: int, strategy_result_version: str, strategy_result_hash: str,
    affected_delivery_set_hash: str, idempotency_key: str, requested_by: str,
):
    from .automatic_delivery import encode
    parent, fixed, _ = _delivery_regeneration_input(
        db, reprojection_task_id=reprojection_task_id, project_id=project_id, prompt_id=prompt_id,
        expected_revision=expected_revision, strategy_result_version=strategy_result_version,
        strategy_result_hash=strategy_result_hash, affected_delivery_set_hash=affected_delivery_set_hash,
        requested_by=requested_by,
    )
    fingerprint = digest(fixed)
    same_key = db.query(SinglePromptOptimizationTask).filter_by(
        project_id=project_id, idempotency_key=idempotency_key,
    ).one_or_none()
    if same_key and same_key.input_hash != fingerprint:
        raise HTTPException(409, "幂等键已绑定其他受影响稿件重新生成输入")
    existing = same_key or db.query(SinglePromptOptimizationTask).filter_by(
        analysis_id=parent.analysis_id, input_hash=fingerprint,
    ).one_or_none()
    if existing:
        return existing, False
    ref = fixed["answer_relation_delivery_regeneration"]
    initial_manifest = {
        "strategy_result_version": ref["strategy_result_version"],
        "strategy_result_hash": ref["strategy_result_hash"],
        "affected_deliveries": ref["affected_deliveries"],
        "regenerated_deliveries": [],
        "unchanged_deliveries": ref["unchanged_deliveries"],
        "pending_deliveries": ref["affected_deliveries"],
        "failed_deliveries": [],
        "deliveries_regenerated": False,
    }
    row = SinglePromptOptimizationTask(
        task_id=f"optimize-{uuid4()}", project_id=project_id, prompt_id=prompt_id,
        analysis_id=parent.analysis_id, context_id=parent.context_id,
        input_json=encode(fixed), input_hash=fingerprint, idempotency_key=idempotency_key,
        authorization_json=encode({"policy": "CACHE_ONLY", "max_requests": 0,
                                   "max_tokens": 0, "max_cost_cny": 0}),
        progress_json=encode({"stage": "DRAFT", "objects": {
            "answer_relation_delivery_regeneration": initial_manifest,
        }, "requests": [], "limitations": []}),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = db.query(SinglePromptOptimizationTask).filter_by(
            analysis_id=parent.analysis_id, input_hash=fingerprint,
        ).one_or_none()
        if concurrent:
            return concurrent, False
        raise
    return row, True


def validate_delivery_regeneration(db, task: SinglePromptOptimizationTask) -> tuple[dict, dict]:
    fixed = loads(task.input_json, {})
    ref = fixed.get("answer_relation_delivery_regeneration") or {}
    required = {
        "reprojection_task_id", "reprojection_revision", "strategy_result_version",
        "strategy_result_hash", "affected_delivery_set_hash", "requested_by",
    }
    if not required.issubset(ref):
        raise HTTPException(409, "受影响稿件重新生成缺少冻结身份")
    _, expected, strategy_output = _delivery_regeneration_input(
        db, reprojection_task_id=ref["reprojection_task_id"], project_id=task.project_id,
        prompt_id=task.prompt_id, expected_revision=ref["reprojection_revision"],
        strategy_result_version=ref["strategy_result_version"],
        strategy_result_hash=ref["strategy_result_hash"],
        affected_delivery_set_hash=ref["affected_delivery_set_hash"], requested_by=ref["requested_by"],
    )
    if fixed != expected or digest(expected) != task.input_hash:
        raise HTTPException(409, "受影响稿件重新生成输入、lineage 或冻结集合已变化")
    return ref, strategy_output


def execute_delivery_regeneration(db, task: SinglePromptOptimizationTask, fixed: dict) -> None:
    from .automatic_delivery import checkpoint, scoped_client
    from .execution import create_execution_proposal, generate_complete_execution_deliverable

    ref, strategy_output = validate_delivery_regeneration(db, task)
    regenerated = []
    context_version = (fixed.get("brand_context") or {}).get("context_version_id")
    plan = ref["delivery_regeneration_plan"]
    for index, item in enumerate(plan):
        direction_id = item["new_direction_id"]
        try:
            proposal, base, _ = create_execution_proposal(
                db, strategy_id=ref["strategy_id"],
                strategy_result_version=ref["strategy_result_version"],
                strategy_result_hash=ref["strategy_result_hash"], project_id=task.project_id,
                prompt_id=task.prompt_id, direction_id=direction_id,
                idempotency_key=f"{task.task_id}:answer-relation-delivery:{direction_id}",
                strategy_review_id=None, strategy_review_snapshot_hash="",
                input_authority_type="MACHINE_QUALIFICATION",
                input_authority_id=(strategy_output.get("authority") or {}).get("authority_id", ""),
                input_authority_hash=(strategy_output.get("authority") or {}).get("authority_hash", ""),
                brand_context_version_id=context_version,
                supplemental_source_refs=[{"source_id": source["snapshot_id"], "snapshot_hash": digest(source)}
                    for source in fixed.get("supplemental_sources") or []], commit=False,
                allow_frozen_strategy=True,
                answer_identity_override={
                    "answer_result_version": fixed["answer_relation_correction"]["parent_answer_result_version"],
                    "answer_result_hash": fixed["answer_relation_correction"]["parent_answer_result_hash"],
                },
            )
            result, _ = generate_complete_execution_deliverable(
                db, proposal_id=proposal.proposal_id, base_result_version=base.result_version,
                base_result_hash=base.output_hash, reviewable_set_hash=base.reviewable_set_hash,
                generation_client=scoped_client(db, task), allow_frozen_strategy=True,
            )
            output = loads(result.output_json, {})
            status = (output.get("validation") or {}).get("content_delivery_status")
            if status != "READY":
                raise HTTPException(409, "受影响稿件的新策略生成结果未通过正文检查")
            regenerated.append({
                "proposal_id": result.proposal_id, "strategy_id": direction_id,
                "result_version": result.result_version, "result_hash": result.output_hash,
                "content_delivery_status": status,
                "replaces_delivery": copy.deepcopy(item["affected_delivery"]),
            })
            partial = {
                "strategy_result_version": ref["strategy_result_version"],
                "strategy_result_hash": ref["strategy_result_hash"],
                "affected_deliveries": ref["affected_deliveries"],
                "regenerated_deliveries": copy.deepcopy(regenerated),
                "unchanged_deliveries": ref["unchanged_deliveries"],
                "pending_deliveries": [row["affected_delivery"] for row in plan[index + 1:]],
                "failed_deliveries": [], "deliveries_regenerated": False,
            }
            checkpoint(db, task, stage="DRAFT", objects={
                "answer_relation_delivery_regeneration": partial,
                "deliveries": copy.deepcopy(regenerated),
            })
        except Exception as exc:
            code = str(getattr(exc, "code", "") or exc)
            if code != "CACHE_MISS":
                failed = [{"delivery": copy.deepcopy(item["affected_delivery"]), "reason": code[:500]}]
                checkpoint(db, task, stage="DRAFT", objects={
                    "answer_relation_delivery_regeneration": {
                        "strategy_result_version": ref["strategy_result_version"],
                        "strategy_result_hash": ref["strategy_result_hash"],
                        "affected_deliveries": ref["affected_deliveries"],
                        "regenerated_deliveries": copy.deepcopy(regenerated),
                        "unchanged_deliveries": ref["unchanged_deliveries"],
                        "pending_deliveries": [row["affected_delivery"] for row in plan[index + 1:]],
                        "failed_deliveries": failed, "deliveries_regenerated": False,
                    }, "deliveries": copy.deepcopy(regenerated),
                })
            raise
    manifest = {
        "strategy_result_version": ref["strategy_result_version"],
        "strategy_result_hash": ref["strategy_result_hash"],
        "affected_deliveries": ref["affected_deliveries"],
        "regenerated_deliveries": regenerated,
        "unchanged_deliveries": ref["unchanged_deliveries"],
        "pending_deliveries": [], "failed_deliveries": [],
        "deliveries_regenerated": True,
    }
    checkpoint(db, task, stage="COMPLETE",
        objects={"answer_relation_delivery_regeneration": manifest, "deliveries": regenerated},
        status="COMPLETED")


def _canonical(value) -> str:
    from .automatic_delivery import encode
    return encode(value)
