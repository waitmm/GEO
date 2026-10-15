"""Task-scoped answer/relation corrections backed by append-only diagnosis revisions."""
from __future__ import annotations

from fastapi import HTTPException

from app.models import (
    SinglePromptDiagnosisExecution,
    SinglePromptDiagnosisResult,
    SinglePromptExecutionProposal,
    SinglePromptExecutionProposalResult,
    SinglePromptStrategyResult,
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
    if fixed.get("delivery_revision") or fixed.get("truth_correction"):
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
