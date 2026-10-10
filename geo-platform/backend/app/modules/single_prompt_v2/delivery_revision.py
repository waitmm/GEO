"""Explicit edited manuscript tasks on the existing V2 queue and budget ledger."""
from __future__ import annotations

from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.models import SinglePromptExecutionProposal, SinglePromptExecutionProposalResult, SinglePromptOptimizationTask
from app.services.serialization import loads
from .automatic_delivery import checkpoint, encode, require_task, scoped_client
from .delivery_generation import admit_draft, generation_input, editable_draft, GENERATION_VERSION, QA_VERSION
from .delivery_text import digest
from .execution import _generated_qa, _proposal_applicability, generate_complete_execution_deliverable


REVISION_CONTRACT = "delivery_text_revision.v1"
REGENERATION_CONTRACT = "delivery_text_regeneration.v1"


def revision_computation_contracts(*, regenerate: bool = False) -> dict:
    return {"revision": REGENERATION_CONTRACT if regenerate else REVISION_CONTRACT,
        "generation": GENERATION_VERSION, "text_qa": QA_VERSION}


def create_revision_task(db, *, parent_task_id: str, project_id: int, prompt_id: int,
                         proposal_id: str, result_version: str, result_hash: str,
                         draft: dict | None = None, idempotency_key: str, editor: str,
                         regenerate: bool = False):
    if (regenerate and draft is not None) or (not regenerate and draft is None):
        raise HTTPException(422, "重新生成和修改原文必须使用各自明确的输入")
    parent = require_task(db, parent_task_id, project_id, prompt_id)
    progress = loads(parent.progress_json, {})
    binding = next((item for item in progress.get("objects", {}).get("deliveries", [])
        if item["proposal_id"] == proposal_id and item["result_version"] == result_version
        and item["result_hash"] == result_hash), None)
    if not binding:
        raise HTTPException(409, "待编辑稿件不是所选任务的准确交付版本")
    proposal = db.query(SinglePromptExecutionProposal).filter_by(proposal_id=proposal_id,
        project_id=project_id, prompt_id=prompt_id, context_id=parent.context_id, analysis_id=parent.analysis_id).one_or_none()
    base = db.query(SinglePromptExecutionProposalResult).filter_by(proposal_id=proposal_id,
        result_version=result_version, output_hash=result_hash).one_or_none()
    if not proposal or not base or digest(loads(base.output_json, {})) != result_hash:
        raise HTTPException(409, "待编辑稿件归属或 hash 不匹配")
    output = loads(base.output_json, {})
    frozen = output.get("delivery_input")
    if not frozen or digest(frozen) != output.get("delivery_input_hash") or not output.get("generation_receipt"):
        raise HTTPException(409, "当前稿件缺少可复检的生成记录，不能继承其文本资格")
    _generated_qa(output, frozen)
    if not regenerate:
        try:
            draft = admit_draft(draft, generation_input(frozen, output['generation_receipt'].get('official_facts')))
        except ValueError as error:
            raise HTTPException(422, "修改内容的段落或证据绑定不合法") from error
    fixed = loads(parent.input_json, {})
    fixed['computation_contracts'] = revision_computation_contracts(regenerate=regenerate)
    fixed["source_fetch_authorized"] = False
    fixed["delivery_revision"] = {"contract_version": REGENERATION_CONTRACT if regenerate else REVISION_CONTRACT, "parent_task_id": parent_task_id,
        "proposal_id": proposal_id, "base_result_version": result_version, "base_result_hash": result_hash,
        "reviewable_set_hash": base.reviewable_set_hash, "delivery_input_hash": output["delivery_input_hash"],
        "draft": draft, "editor": editor}
    fingerprint = digest(fixed)
    same_key = db.query(SinglePromptOptimizationTask).filter_by(project_id=project_id, idempotency_key=idempotency_key).one_or_none()
    if same_key:
        if same_key.input_hash != fingerprint:
            raise HTTPException(409, "幂等键已用于不同的正文修改")
        return same_key, False
    if not regenerate and draft == editable_draft(output["generation_receipt"]):
        return parent, False
    existing = db.query(SinglePromptOptimizationTask).filter_by(analysis_id=parent.analysis_id, input_hash=fingerprint).one_or_none()
    if existing:
        return existing, False
    if proposal.active_result_version != result_version or not _proposal_applicability(db, proposal)["is_current_input"]:
        raise HTTPException(409, "稿件或策略输入已变化，请读取准确版本后再编辑")
    objects = {key: value for key, value in progress.get("objects", {}).items() if key not in {"deliveries", "draft_in_progress"}}
    row = SinglePromptOptimizationTask(task_id=f"optimize-{uuid4()}", project_id=project_id, prompt_id=prompt_id,
        analysis_id=parent.analysis_id, context_id=parent.context_id, idempotency_key=idempotency_key,
        input_json=encode(fixed), input_hash=fingerprint,
        authorization_json=encode({"policy": "CACHE_ONLY", "max_requests": 0, "max_tokens": 0, "max_cost_cny": 0}),
        progress_json=encode({"stage": "DRAFT" if regenerate else "TEXT_QA", "objects": objects, "requests": [],
            "limitations": progress.get("limitations", [])}))
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(SinglePromptOptimizationTask).filter_by(analysis_id=parent.analysis_id, input_hash=fingerprint).one_or_none()
        if existing:
            return existing, False
        raise
    return row, True


def execute_revision(db, row, fixed):
    revision = fixed["delivery_revision"]
    regenerate = revision["contract_version"] == REGENERATION_CONTRACT
    if revision["contract_version"] not in {REVISION_CONTRACT, REGENERATION_CONTRACT}:
        raise HTTPException(409, "正文复检契约已变化")
    parent = require_task(db, revision["parent_task_id"], row.project_id, row.prompt_id)
    if parent.context_id != row.context_id or parent.analysis_id != row.analysis_id:
        raise HTTPException(409, "正文复检上下文不一致")
    binding = {"proposal_id": revision["proposal_id"], "result_version": revision["base_result_version"],
        "result_hash": revision["base_result_hash"]}
    if not any(all(item.get(key) == value for key, value in binding.items())
            for item in loads(parent.progress_json, {}).get("objects", {}).get("deliveries", [])):
        raise HTTPException(409, "正文复检的原任务绑定已变化")
    checkpoint(db, row, stage="DRAFT" if regenerate else "TEXT_QA")
    identity = {"task_id": row.task_id, "input_hash": row.input_hash, "editor": revision["editor"]}
    result, _ = generate_complete_execution_deliverable(db,
        proposal_id=revision["proposal_id"], base_result_version=revision["base_result_version"],
        base_result_hash=revision["base_result_hash"], reviewable_set_hash=revision["reviewable_set_hash"],
        generation_client=scoped_client(db, row), submitted_draft=revision["draft"],
        generation_progress=lambda stage: checkpoint(db, row, stage=stage),
        revision_identity=None if regenerate else identity,
        regeneration_identity=identity if regenerate else None)
    output = loads(result.output_json, {})
    ready = output["validation"]["content_delivery_status"] == "READY"
    checkpoint(db, row, stage="COMPLETE" if ready else "TEXT_QA",
        objects={"deliveries": [{"proposal_id": result.proposal_id, "result_version": result.result_version,
            "result_hash": result.output_hash, "content_delivery_status": output["validation"]["content_delivery_status"]}]},
        status=("COMPLETED_WITH_LIMITATIONS" if loads(row.progress_json, {}).get("limitations") else "COMPLETED") if ready else "BLOCKED",
        code="" if ready else "TEXT_QA_NO_DELIVERABLE",
        detail="" if ready else "修改后的正文未形成可用内容；旧稿保留，不能继承旧检查结果。")
