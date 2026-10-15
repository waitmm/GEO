"""V2-owned finite Optimize handoff using the existing computation stages."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session

from app.core.config import get_settings
from app.models import (Project, ProjectConfigurationVersion, SinglePromptAnalysisContext, SinglePromptOptimizationTask)
from app.services.serialization import loads
from app.services.semantic_llm.base import SemanticLLMError
from app.services.semantic_llm.deepseek import DeepSeekClient, resolve_deepseek_request_model
from .context_provider import select_context
from .delivery_text import digest


CONTRACT_VERSION = "single_prompt_automatic_delivery.v1"
STAGES = ("SOURCES", "ANSWER", "CITATION", "STRATEGY", "TRUTH", "DRAFT", "TEXT_QA")
TERMINAL = {"COMPLETED", "COMPLETED_WITH_LIMITATIONS", "CANCELLED"}


def computation_contracts() -> dict:
    from .diagnosis import _contract_config
    from .citation_contribution import CITATION_CONTRIBUTION_CONTRACT_VERSION, CITATION_CONTRIBUTION_PROMPT_VERSION, CITATION_CONTRIBUTION_SCHEMA_VERSION
    from .delivery_generation import GENERATION_VERSION, QA_VERSION
    from .qualification import QUALIFICATION_CONTRACT_VERSION
    from .delivery_facts import CONTRACT as FACT_CONTRACT
    from .llm_safety import V2_SOURCE_CLAIM_PROMPT_VERSION, V2_SOURCE_CLAIM_SCHEMA_VERSION
    return {"answer": _contract_config(diagnosis_mode="ANSWER_ONLY", source_snapshot_policy="SOURCE_PREPARATION_ONLY",
        answer_llm_policy="CACHE_ONLY", evidence_llm_policy="CACHE_ONLY"),
        "citation_contract": CITATION_CONTRIBUTION_CONTRACT_VERSION, "citation_prompt": CITATION_CONTRIBUTION_PROMPT_VERSION,
        "citation_schema": CITATION_CONTRIBUTION_SCHEMA_VERSION, "generation": GENERATION_VERSION,
        "text_qa": QA_VERSION, "qualification": QUALIFICATION_CONTRACT_VERSION,
        "official_fact": FACT_CONTRACT, "official_claim_prompt": V2_SOURCE_CLAIM_PROMPT_VERSION,
        "official_claim_schema": V2_SOURCE_CLAIM_SCHEMA_VERSION}


def _validated_project_configuration(
    db: Session, project_id: int, binding: dict | None = None,
) -> tuple[ProjectConfigurationVersion | None, dict | None]:
    if binding is None:
        # Tasks created before project configuration version binding retain their
        # own hashed input. They never acquire a synthetic/latest version later.
        return None, None
    if not isinstance(binding, dict) or set(binding) != {
        "configuration_version_id", "version_number", "snapshot_hash",
    }:
        raise HTTPException(409, "自动优化绑定的项目配置版本格式无效")
    version_id = binding.get("configuration_version_id")
    version_number = binding.get("version_number")
    snapshot_hash = binding.get("snapshot_hash")
    if (not isinstance(version_id, str) or not version_id
            or not isinstance(version_number, int) or isinstance(version_number, bool)
            or version_number < 1 or not isinstance(snapshot_hash, str) or len(snapshot_hash) != 64):
        raise HTTPException(409, "自动优化绑定的项目配置版本身份不完整")
    row = db.query(ProjectConfigurationVersion).filter_by(
        project_id=project_id, configuration_version_id=version_id,
        version_number=version_number,
    ).one_or_none()
    if not row:
        raise HTTPException(409, "自动优化绑定的项目配置版本不存在或不属于当前项目")
    actual_hash = hashlib.sha256(row.snapshot_json.encode("utf-8")).hexdigest()
    snapshot = loads(row.snapshot_json, None)
    if (snapshot_hash != row.snapshot_hash or actual_hash != row.snapshot_hash
            or not isinstance(snapshot, dict) or snapshot.get("project_id") != project_id):
        raise HTTPException(409, "自动优化绑定的项目配置版本内容或 hash 已变化")
    return row, snapshot


def _current_project_configuration(db: Session, project_id: int) -> tuple[dict, dict]:
    row = db.query(ProjectConfigurationVersion).filter_by(project_id=project_id).order_by(
        ProjectConfigurationVersion.version_number.desc()).first()
    if not row:
        raise HTTPException(409, "项目尚无可绑定的配置版本，请先通过项目配置入口保存")
    binding = {"configuration_version_id": row.configuration_version_id,
        "version_number": row.version_number, "snapshot_hash": row.snapshot_hash}
    _, snapshot = _validated_project_configuration(db, project_id, binding)
    return binding, snapshot or {}


def _validate_task_project_configuration(db: Session, project_id: int, inputs: dict) -> None:
    binding = inputs.get("project_configuration_version")
    _, snapshot = _validated_project_configuration(db, project_id, binding)
    if snapshot is None:
        return
    brand = inputs.get("brand") or {}
    expected = {"project_id": project_id, "brand_name": snapshot.get("brand_name"),
        "brand_aliases": snapshot.get("brand_aliases"), "website_url": snapshot.get("website_url")}
    if any(brand.get(key) != value for key, value in expected.items()):
        raise HTTPException(409, "自动优化冻结品牌配置与绑定版本不一致")


def configuration_snapshot(db: Session, project_id: int, prompt_text: str, context_version_id: str | None) -> dict:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    configuration_version, project_snapshot = _current_project_configuration(db, project_id)
    from .truth_corrections import project_truths
    model = get_settings().deepseek_model
    return {"computation_contracts": computation_contracts(),
        "project_configuration_version": configuration_version,
        "brand": {"project_id": project_id, "brand_name": project_snapshot["brand_name"],
            "brand_aliases": project_snapshot["brand_aliases"], "website_url": project_snapshot["website_url"],
            "project_updated_at": project.updated_at.isoformat() if project.updated_at else None},
        "truth_snapshot": project_truths(db, project_id),
        "brand_context": select_context(db, project_id=project_id, context_version_id=context_version_id, query=prompt_text),
        "provider": "deepseek", "requested_model": model,
        "effective_request_model": resolve_deepseek_request_model(model, "JSON_SCHEMA")}


def checkpoint(db: Session, row: SinglePromptOptimizationTask, *, stage: str | None = None,
               objects: dict | None = None, limitations: list | None = None,
               status: str = "RUNNING", code: str = "", detail: str = "") -> None:
    db.refresh(row)
    if row.status != "RUNNING":
        raise SemanticLLMError("OPTIMIZATION_NOT_RUNNING")
    progress = loads(row.progress_json, {})
    if stage:
        progress["stage"] = stage
    if objects:
        progress.setdefault("objects", {}).update(objects)
    if limitations:
        progress.setdefault("limitations", []).extend(limitations)
    changed = db.execute(update(SinglePromptOptimizationTask).where(
        SinglePromptOptimizationTask.id == row.id, SinglePromptOptimizationTask.revision == row.revision,
        SinglePromptOptimizationTask.status == "RUNNING",
    ).values(progress_json=encode(progress), revision=row.revision + 1, status=status,
        blocker_code=code, blocker_detail=detail,
        finished_at=datetime.utcnow() if status in TERMINAL else None))
    db.commit()
    if changed.rowcount != 1:
        raise SemanticLLMError("OPTIMIZATION_CHECKPOINT_CONFLICT")
    db.refresh(row)


def recover_interrupted_tasks(db: Session) -> int:
    result = db.execute(update(SinglePromptOptimizationTask).where(SinglePromptOptimizationTask.status == "RUNNING").values(
        status="INTERRUPTED", revision=SinglePromptOptimizationTask.revision + 1,
        blocker_code="WORKER_INTERRUPTED", blocker_detail="保留已完成对象与累计预算；核对调用审计后恢复，不自动补调。"))
    db.commit()
    return result.rowcount


def resume_task(db: Session, row: SinglePromptOptimizationTask, expected_revision: int) -> SinglePromptOptimizationTask:
    if row.status not in {"INTERRUPTED", "BLOCKED"}:
        raise HTTPException(409, "当前任务不是可恢复的工程阻断状态")
    if task_view(row)["usage"]["unsettled_requests"]:
        raise HTTPException(409, "有未核实用量的外部请求，不能自动补调或重置预算")
    changed = db.execute(update(SinglePromptOptimizationTask).where(
        SinglePromptOptimizationTask.id == row.id, SinglePromptOptimizationTask.revision == expected_revision,
        SinglePromptOptimizationTask.status.in_(["INTERRUPTED", "BLOCKED"]),
    ).values(status="QUEUED", revision=expected_revision + 1, blocker_code="", blocker_detail=""))
    db.commit()
    if changed.rowcount != 1:
        raise HTTPException(409, "任务状态已变化")
    db.refresh(row)
    return row


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def task_view(row: SinglePromptOptimizationTask) -> dict:
    inputs = loads(row.input_json, {})
    db = object_session(row)
    if db is not None:
        _validate_task_project_configuration(db, row.project_id, inputs)
    progress = loads(row.progress_json, {})
    requests = progress.get("requests") or []
    return {"task_id": row.task_id, "project_id": row.project_id, "prompt_id": row.prompt_id,
        "task_kind": ("ANSWER_RELATION_DELIVERY_REGENERATION" if inputs.get("answer_relation_delivery_regeneration")
            else "TEXT_REGENERATION" if (inputs.get("delivery_revision") or {}).get("contract_version") == "delivery_text_regeneration.v1"
            else "TEXT_REVISION" if inputs.get("delivery_revision")
            else "ANSWER_RELATION_REPROJECTION" if inputs.get("answer_relation_correction")
            else "TRUTH_REPROJECTION" if inputs.get("truth_correction") else "AUTOMATIC_OPTIMIZE"),
        "pending_draft": (inputs.get("delivery_revision") or {}).get("draft"),
        "analysis_id": row.analysis_id, "context_id": row.context_id, "input_hash": row.input_hash,
        "status": row.status, "revision": row.revision, "stage": progress.get("stage"),
        "objects": progress.get("objects") or {}, "limitations": progress.get("limitations") or [],
        "blocker_code": row.blocker_code, "blocker_detail": row.blocker_detail,
        "scope": inputs.get("run_ids"), "brand_context_version_id": (inputs.get("brand_context") or {}).get("context_version_id"),
        "project_configuration_version": inputs.get("project_configuration_version") or {"binding_status": "LEGACY_UNBOUND"},
        "brand_context_label": ((inputs.get('brand_context') or {}).get('title') or '未选择') +
            (f" · 版本 {(inputs.get('brand_context') or {})['version_number']}" if (inputs.get('brand_context') or {}).get('version_number') else ''),
        "supplemental_source_count": len(inputs.get('supplemental_sources') or []),
        "source_input": inputs.get("source_input"),
        "provider": inputs.get("provider"), "requested_model": inputs.get("requested_model"),
        "effective_request_model": inputs.get("effective_request_model"),
        "authorization": loads(row.authorization_json, {}),
        "usage": {"external_requests": len(requests), "cache_hits": progress.get("cache_hits", 0),
            "reserved_tokens": sum(r["token_ceiling"] for r in requests),
            "reserved_cost_cny": round(sum(r["reserved_cost_cny"] for r in requests), 6),
            "actual_tokens": sum(int(r.get("actual_tokens") or 0) for r in requests),
            "unsettled_requests": sum(r.get("status") in {"RESERVED", "USAGE_UNKNOWN"} for r in requests)},
        "created_at": row.created_at.isoformat(), "finished_at": row.finished_at.isoformat() if row.finished_at else None}


def require_task(db: Session, task_id: str, project_id: int, prompt_id: int) -> SinglePromptOptimizationTask:
    row = db.query(SinglePromptOptimizationTask).filter_by(task_id=task_id, project_id=project_id, prompt_id=prompt_id).one_or_none()
    if not row:
        raise HTTPException(404, "自动优化任务不存在或不属于当前项目/问题")
    inputs = loads(row.input_json, {})
    if digest(inputs) != row.input_hash:
        raise HTTPException(409, "自动优化冻结输入 hash 不匹配")
    _validate_task_project_configuration(db, project_id, inputs)
    return row


def create_task(db: Session, *, analysis_id: str, project_id: int, prompt_id: int,
                raw_output_hash: str, idempotency_key: str, brand_context_version_id: str | None = None,
                source_fetch_authorized: bool = False, completion_manifest_id: str | None = None,
                completion_manifest_hash: str | None = None,
                supplemental_source_ids: list[str] | None = None) -> tuple[SinglePromptOptimizationTask, bool]:
    context = db.query(SinglePromptAnalysisContext).filter_by(analysis_id=analysis_id, project_id=project_id, prompt_id=prompt_id).one_or_none()
    if not context or context.raw_output_hash != raw_output_hash:
        raise HTTPException(409, "自动优化必须选择已冻结的准确分析范围与原始版本")
    raw = loads(context.raw_output_json, {})
    if digest(raw) != raw_output_hash or not context.valid_run_count:
        raise HTTPException(409, "原始内容校验失败或没有有效回答")
    source_input = None
    if bool(completion_manifest_id) != bool(completion_manifest_hash):
        raise HTTPException(422, "正文版本 ID 与 hash 必须同时提供")
    if completion_manifest_id:
        from app.models import SinglePromptSourceCompletionManifest
        from .source_preparation import validate_completion_for_evidence
        completion = db.query(SinglePromptSourceCompletionManifest).filter_by(manifest_id=completion_manifest_id).one_or_none()
        if not completion or source_fetch_authorized:
            raise HTTPException(409, "指定正文版本不存在，或不能同时授权重新抓取固定版本")
        source_input = {"completion_manifest_id": completion_manifest_id, "completion_manifest_hash": completion_manifest_hash,
            "citation_manifest_id": completion.citation_manifest_id, "citation_manifest_hash": completion.citation_manifest_hash}
        validate_completion_for_evidence(db, analysis_id=analysis_id, context_id=context.context_id,
            **source_input, allow_partial=True)
    inputs = {"contract_version": CONTRACT_VERSION, "analysis_id": analysis_id, "context_id": context.context_id,
        **configuration_snapshot(db, project_id, raw["prompt_text"], brand_context_version_id),
        "raw_result_version": context.result_version, "raw_output_hash": raw_output_hash,
        "run_ids": [row["run_id"] for row in raw["runs"]], "prompt_text": raw["prompt_text"],
        "source_input": source_input,
        "source_fetch_authorized": source_fetch_authorized, "source_attempts_per_url": 2, "automatic_retry": 0}
    if supplemental_source_ids:
        from .supplemental_sources import frozen_sources
        inputs['supplemental_sources'] = frozen_sources(db, project_id=project_id, source_ids=supplemental_source_ids)
    fingerprint = digest(inputs)
    existing = db.query(SinglePromptOptimizationTask).filter_by(project_id=project_id, idempotency_key=idempotency_key).one_or_none()
    if existing:
        if existing.input_hash != fingerprint:
            raise HTTPException(409, "幂等键已经绑定其他优化输入")
        return existing, False
    existing = db.query(SinglePromptOptimizationTask).filter_by(analysis_id=analysis_id, input_hash=fingerprint).one_or_none()
    if existing:
        return existing, False
    row = SinglePromptOptimizationTask(task_id=f"optimize-{uuid4()}", project_id=project_id, prompt_id=prompt_id,
        analysis_id=analysis_id, context_id=context.context_id, input_json=encode(inputs), input_hash=fingerprint,
        idempotency_key=idempotency_key, authorization_json=encode({"policy": "CACHE_ONLY", "max_requests": 0,
            "max_tokens": 0, "max_cost_cny": 0}),
        progress_json=encode({"stage": "SOURCES", "objects": {}, "requests": [], "limitations": []}))
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(SinglePromptOptimizationTask).filter_by(analysis_id=analysis_id, input_hash=fingerprint).one_or_none()
        if existing:
            return existing, False
        raise
    return row, True


def cancel_task(db: Session, row: SinglePromptOptimizationTask, expected_revision: int) -> SinglePromptOptimizationTask:
    if row.status in TERMINAL:
        return row
    changed = db.execute(update(SinglePromptOptimizationTask).where(
        SinglePromptOptimizationTask.id == row.id, SinglePromptOptimizationTask.revision == expected_revision
    ).values(status="CANCELLED", revision=expected_revision + 1, finished_at=datetime.utcnow()))
    db.commit()
    if changed.rowcount != 1:
        raise HTTPException(409, "任务状态已变化，请刷新")
    db.refresh(row)
    return row


def validate_authorization(*, max_requests: int, max_tokens: int, max_cost_cny: float,
                           conservative_cny_per_million_tokens: float, pricing_source: str,
                           pricing_checked_at: str, authorized_by: str) -> None:
    if not (0 < max_requests <= 1000 and 0 < max_tokens <= 10000000 and 0 < max_cost_cny <= 1000
            and 0 < conservative_cny_per_million_tokens <= 1000 and pricing_source.strip() and authorized_by.strip()):
        raise HTTPException(422, "必须给出有限的调用、token、费用上限及可核对的保守单价依据")
    try:
        checked = datetime.fromisoformat(pricing_checked_at).date()
    except ValueError:
        raise HTTPException(422, "计费核对日期无效")
    if not 0 <= (datetime.utcnow().date() - checked).days <= 7:
        raise HTTPException(409, "计费依据超出本次核对有效期，不能自动沿用")


def authorize_task(db: Session, row: SinglePromptOptimizationTask, *, expected_revision: int, input_hash: str,
                   max_requests: int, max_tokens: int, max_cost_cny: float,
                   conservative_cny_per_million_tokens: float, pricing_source: str, pricing_checked_at: str,
                   authorized_by: str) -> SinglePromptOptimizationTask:
    inputs = loads(row.input_json, {})
    if inputs.get("answer_relation_correction") and not inputs.get("answer_relation_delivery_regeneration"):
        raise HTTPException(409, "答案与关系策略重投影固定为 CACHE_ONLY，不接受外部调用授权")
    if row.status in TERMINAL or row.status == "RUNNING" or row.input_hash != input_hash:
        raise HTTPException(409, "任务不可授权或输入已变化")
    regeneration = inputs.get("answer_relation_delivery_regeneration")
    if regeneration:
        affected = regeneration.get("affected_deliveries")
        plan = regeneration.get("delivery_regeneration_plan")
        if (not isinstance(affected, list) or not affected or not isinstance(plan, list)
                or len(plan) != len(affected)):
            raise HTTPException(409, "受影响稿件重新生成的冻结稿件集合或生成映射无效")
        if max_requests > 2 * len(affected):
            raise HTTPException(422, "受影响稿件重新生成每稿最多授权一次生成和一次文本复检请求")
    revision = loads(row.input_json, {}).get("delivery_revision")
    if revision:
        regenerate = revision.get("contract_version") == "delivery_text_regeneration.v1"
        if (regenerate and max_requests > 2) or (not regenerate and max_requests != 1):
            raise HTTPException(422, "重新生成最多两次请求；正文修改只允许一次文本复检请求，不自动重试")
    validate_authorization(max_requests=max_requests, max_tokens=max_tokens, max_cost_cny=max_cost_cny,
        conservative_cny_per_million_tokens=conservative_cny_per_million_tokens, pricing_source=pricing_source,
        pricing_checked_at=pricing_checked_at, authorized_by=authorized_by)
    previous = loads(row.authorization_json, {})
    if previous.get("policy") == "ALLOW_EXTERNAL":
        raise HTTPException(409, "本任务已有独立累计授权，重启或重试不能重置额度")
    authorization = {"policy": "ALLOW_EXTERNAL", "input_hash": input_hash, "max_requests": max_requests,
        "max_tokens": max_tokens, "max_cost_cny": max_cost_cny,
        "conservative_cny_per_million_tokens": conservative_cny_per_million_tokens,
        "pricing_source": pricing_source, "pricing_checked_at": pricing_checked_at,
        "pricing_verification": "OPERATOR_ATTESTED_NOT_PROVIDER_BILL", "authorized_by": authorized_by,
        "authorized_at": datetime.utcnow().isoformat(), "automatic_retry": 0}
    changed = db.execute(update(SinglePromptOptimizationTask).where(
        SinglePromptOptimizationTask.id == row.id, SinglePromptOptimizationTask.revision == expected_revision
    ).values(authorization_json=encode(authorization), status="QUEUED", revision=expected_revision + 1,
             blocker_code="", blocker_detail=""))
    db.commit()
    if changed.rowcount != 1:
        raise HTTPException(409, "授权期间任务状态已变化")
    db.refresh(row)
    return row


def scoped_client(db: Session, row: SinglePromptOptimizationTask) -> DeepSeekClient:
    inputs = loads(row.input_json, {})
    task_id = row.task_id

    def current():
        db.expire_all()
        active = db.query(SinglePromptOptimizationTask).filter_by(task_id=task_id).one()
        if active.status != "RUNNING" or digest(loads(active.input_json, {})) != active.input_hash:
            raise SemanticLLMError("OPTIMIZATION_NOT_RUNNING")
        return active

    def reserve(identity: dict):
        active = current()
        authorization = loads(active.authorization_json, {})
        progress = loads(active.progress_json, {})
        requests = progress.setdefault("requests", [])
        if inputs.get("answer_relation_correction") and not inputs.get("answer_relation_delivery_regeneration"):
            raise SemanticLLMError("ANSWER_RELATION_REPROJECTION_FORBIDS_EXTERNAL_CALL")
        if inputs.get("answer_relation_delivery_regeneration"):
            from .delivery_generation import GENERATION_VERSION, QA_VERSION
            from .delivery_facts import CONTRACT as FACT_CONTRACT
            if identity.get("prompt_version") not in {FACT_CONTRACT, GENERATION_VERSION, QA_VERSION}:
                raise SemanticLLMError("ANSWER_RELATION_DELIVERY_REGENERATION_FORBIDS_UPSTREAM_EXTERNAL_CALL")
        if inputs.get("truth_correction"):
            from .delivery_generation import GENERATION_VERSION, QA_VERSION
            allowed = {GENERATION_VERSION: 'DRAFT', QA_VERSION: 'TEXT_QA'}
            if identity.get('prompt_version') not in allowed or progress.get('stage') != allowed[identity['prompt_version']]:
                raise SemanticLLMError('TRUTH_REPROJECTION_FORBIDS_UPSTREAM_EXTERNAL_CALL')
        if inputs.get("delivery_revision"):
            from .delivery_generation import GENERATION_VERSION, QA_VERSION
            regenerate = inputs["delivery_revision"].get("contract_version") == "delivery_text_regeneration.v1"
            allowed = {QA_VERSION: "TEXT_QA", **({GENERATION_VERSION: "DRAFT"} if regenerate else {})}
            if (identity.get("prompt_version") not in allowed
                    or progress.get("stage") != allowed[identity["prompt_version"]]
                    or any(r.get("prompt_version") == identity.get("prompt_version") for r in requests)):
                raise SemanticLLMError("TEXT_TASK_ONLY_ONE_REQUEST_PER_ALLOWED_STAGE")
        if any(r.get("provider_payload_hash") == identity.get("provider_payload_hash") for r in requests):
            raise SemanticLLMError("OPTIMIZATION_INPUT_ALREADY_REQUESTED_NO_AUTOMATIC_RETRY")
        if (identity["provider"] != inputs["provider"] or identity["requested_model_alias"] != inputs["requested_model"]
                or (identity["structured_output_mode"] == "JSON_SCHEMA" and identity["effective_request_model"] != inputs["effective_request_model"])):
            raise SemanticLLMError("OPTIMIZATION_MODEL_IDENTITY_CHANGED")
        tokens = identity["input_token_upper_bound"] + identity["max_output_tokens"]
        cost = tokens * float(authorization.get("conservative_cny_per_million_tokens") or 0) / 1_000_000
        if (authorization.get("policy") != "ALLOW_EXTERNAL" or authorization.get("input_hash") != active.input_hash
                or len(requests) + 1 > authorization["max_requests"]
                or sum(r["token_ceiling"] for r in requests) + tokens > authorization["max_tokens"]
                or sum(r["reserved_cost_cny"] for r in requests) + cost > authorization["max_cost_cny"]):
            error = SemanticLLMError("OPTIMIZATION_EXTERNAL_BUDGET_EXHAUSTED")
            error.code = "EXTERNAL_BUDGET_EXHAUSTED"
            raise error
        requests.append({**identity, "request_id": f"{task_id}:{len(requests) + 1}", "stage": progress["stage"],
            "token_ceiling": tokens, "reserved_cost_cny": cost, "status": "RESERVED"})
        changed = db.execute(update(SinglePromptOptimizationTask).where(SinglePromptOptimizationTask.id == active.id,
            SinglePromptOptimizationTask.revision == active.revision, SinglePromptOptimizationTask.status == "RUNNING"
        ).values(progress_json=encode(progress), revision=active.revision + 1))
        db.commit()
        if changed.rowcount != 1:
            raise SemanticLLMError("OPTIMIZATION_REQUEST_RESERVATION_CONFLICT")

    def audit(payload: dict):
        root = Path(get_settings().evidence_artifact_dir).resolve() / "automatic-delivery" / task_id
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        body = encode({"task_id": task_id, "input_hash": row.input_hash, **payload})
        path = root / f"{uuid4().hex}.json"
        with path.open("x", encoding="utf-8") as out:
            out.write(body)
        path.chmod(0o600)
        from hashlib import sha256
        artifact = {"path": str(path), "sha256": sha256(body.encode()).hexdigest(),
                    "response_source": payload.get("response_source"), "validation_status": payload.get("validation_status")}
        # Cancellation may arrive while a provider response is in flight. Preserve its
        # state, but still attach the response and usage to the already reserved request.
        for _ in range(3):
            active = db.query(SinglePromptOptimizationTask).filter_by(task_id=task_id).populate_existing().one()
            progress = loads(active.progress_json, {})
            progress.setdefault("artifacts", []).append(artifact)
            if payload.get("response_source") == "LLM_CALL_CACHE":
                progress["cache_hits"] = progress.get("cache_hits", 0) + 1
            else:
                identity = payload.get("request_identity") or {}
                request = next((r for r in reversed(progress.get("requests") or [])
                    if r.get("input_hash") == identity.get("input_hash") and r["status"] == "RESERVED"), None)
                if request:
                    usage = payload.get("token_usage")
                    total = usage.get("total_tokens") if isinstance(usage, dict) else None
                    known = isinstance(total, int) and not isinstance(total, bool) and total >= 0
                    request.update(status="RECORDED" if known else "USAGE_UNKNOWN",
                        actual_tokens=total if known else None, token_usage=usage, artifact=artifact)
            changed = db.execute(update(SinglePromptOptimizationTask).where(
                SinglePromptOptimizationTask.id == active.id,
                SinglePromptOptimizationTask.revision == active.revision,
            ).values(progress_json=encode(progress), revision=active.revision + 1))
            db.commit()
            if changed.rowcount == 1:
                return
        raise SemanticLLMError("OPTIMIZATION_AUDIT_CONFLICT_ARTIFACT_PRESERVED")

    upstream_reprojection = bool((inputs.get("answer_relation_correction") and not inputs.get("answer_relation_delivery_regeneration")) or (inputs.get('truth_correction') and
        loads(row.progress_json, {}).get('stage') not in {'DRAFT', 'TEXT_QA'})
    )
    return DeepSeekClient(thinking_mode="disabled", max_attempts=1,
        cache_only=upstream_reprojection or loads(row.authorization_json, {}).get("policy") != "ALLOW_EXTERNAL",
        request_guard=reserve, response_audit_sink=audit)


def execute_task(task_id: str, *, session_factory) -> None:
    """One release-worker owner, bounded existing stages, no human-review fabrication."""
    from app.models import (SinglePromptCitationManifest, SinglePromptSourcePreparation,
        SinglePromptSourceCompletionManifest, SinglePromptSourceDisposition,
        SinglePromptDiagnosisExecution, SinglePromptDiagnosisResult,
        SinglePromptCitationContributionExecution, SinglePromptCitationContributionResult,
        SinglePromptExecutionProposal, SinglePromptExecutionProposalResult)
    from .source_preparation import create_source_preparation, queue_auto_fetch, execute_auto_fetch, freeze_completion_manifest
    from .diagnosis import create_answer_diagnosis, claim_diagnosis, compute_answer_diagnosis
    from .coverage import compute_coverage
    from .llm_safety import V2AnswerSemanticJudge
    from .citation_contribution import create_citation_contribution_plan, execute_citation_contribution
    from .qualification import build_qualification_projection
    from .strategy import create_automatic_strategy_candidate
    from .execution import create_execution_proposal, generate_complete_execution_deliverable

    db = session_factory()
    row = None
    try:
        claimed = db.execute(update(SinglePromptOptimizationTask).where(
            SinglePromptOptimizationTask.task_id == task_id, SinglePromptOptimizationTask.status == "QUEUED",
        ).values(status="RUNNING", started_at=datetime.utcnow(), revision=SinglePromptOptimizationTask.revision + 1))
        db.commit()
        if claimed.rowcount != 1:
            return
        row = db.query(SinglePromptOptimizationTask).filter_by(task_id=task_id).one()
        require_task(db, task_id, row.project_id, row.prompt_id)
        fixed = loads(row.input_json, {})
        from .delivery_revision import revision_computation_contracts, REGENERATION_CONTRACT
        expected_contracts = (revision_computation_contracts(regenerate=fixed['delivery_revision']['contract_version'] == REGENERATION_CONTRACT)
            if fixed.get('delivery_revision') else computation_contracts())
        if fixed.get("computation_contracts") != expected_contracts:
            raise HTTPException(409, "模型或计算契约已变化，需要针对新身份显式建立任务；旧任务不会偷偷换规则")
        context = db.query(SinglePromptAnalysisContext).filter_by(context_id=row.context_id).one()
        raw = loads(context.raw_output_json, {})
        if digest(raw) != fixed["raw_output_hash"] or context.analysis_id != row.analysis_id:
            raise HTTPException(409, "自动任务冻结原文发生变化")
        scope = {"analysis_id": row.analysis_id, "project_id": row.project_id, "prompt_id": row.prompt_id}
        if fixed.get("delivery_revision"):
            from .delivery_revision import execute_revision
            execute_revision(db, row, fixed)
            return
        if fixed.get("answer_relation_delivery_regeneration"):
            from .answer_relation_corrections import execute_delivery_regeneration
            execute_delivery_regeneration(db, row, fixed)
            return
        if fixed.get("answer_relation_correction"):
            from .answer_relation_corrections import execute_reprojection
            execute_reprojection(db, row, fixed)
            return
        if fixed.get('truth_correction'):
            from .truth_corrections import validate_reprojection
            validate_reprojection(db, row)
        policy = loads(row.authorization_json, {}).get("policy", "CACHE_ONLY")
        key = f"{task_id}:{policy}"
        objects = loads(row.progress_json, {}).get("objects") or {}

        checkpoint(db, row, stage="SOURCES")
        preparation, _ = create_source_preparation(db, **scope, idempotency_key=task_id, created_by="automatic-optimize")
        manifest = db.query(SinglePromptCitationManifest).filter_by(manifest_id=preparation.citation_manifest_id).one()
        checkpoint(db, row, objects={"preparation_id": preparation.preparation_id,
            "citation_manifest_id": manifest.manifest_id, "citation_manifest_hash": manifest.payload_hash})
        if fixed["source_fetch_authorized"] and not objects.get("source_fetch_started"):
            pending = db.query(SinglePromptSourceDisposition).filter(
                SinglePromptSourceDisposition.preparation_id == preparation.preparation_id,
                SinglePromptSourceDisposition.state.notin_(["READY", "WAIVED_WITH_LIMITATION"]),
            ).count()
            if pending:
                checkpoint(db, row, objects={"source_fetch_started": True})
                queue_auto_fetch(db, preparation_id=preparation.preparation_id, project_id=row.project_id, prompt_id=row.prompt_id)
                db.rollback()
                execute_auto_fetch(preparation.preparation_id, session_factory=session_factory)
                db.expire_all()
        if fixed.get("source_input"):
            from .source_preparation import validate_completion_for_evidence
            completion, _, _ = validate_completion_for_evidence(db, analysis_id=row.analysis_id,
                context_id=row.context_id, **fixed["source_input"], allow_partial=True)
        elif objects.get("completion_manifest_id"):
            completion = db.query(SinglePromptSourceCompletionManifest).filter_by(
                manifest_id=objects["completion_manifest_id"], payload_hash=objects["completion_manifest_hash"],
                preparation_id=preparation.preparation_id).one()
        else:
            completion = freeze_completion_manifest(db, preparation_id=preparation.preparation_id,
                created_by="automatic-optimize", allow_partial=True)
        checkpoint(db, row, objects={"completion_manifest_id": completion.manifest_id,
            "completion_manifest_hash": completion.payload_hash, "source_status": completion.status})

        checkpoint(db, row, stage="ANSWER")
        diagnosis, _ = create_answer_diagnosis(db, **scope, citation_manifest_id=manifest.manifest_id,
            citation_manifest_hash=manifest.payload_hash, answer_llm_policy=policy, idempotency_key=key,
            automatic_task_id=task_id)
        checkpoint(db, row, objects={"diagnosis_id": diagnosis.diagnosis_id})
        if diagnosis.status == "OPTIMIZE_OWNED":
            token = claim_diagnosis(db, diagnosis.diagnosis_id, automatic_task_id=task_id)
            if not token:
                raise HTTPException(409, "Answer 任务已被其他执行占用")
            result = compute_answer_diagnosis(db, diagnosis, token, answer_judge=V2AnswerSemanticJudge(scoped_client(db, row)))
        else:
            result = db.query(SinglePromptDiagnosisResult).filter_by(diagnosis_id=diagnosis.diagnosis_id,
                result_version=diagnosis.active_result_version).one_or_none()
            if not result:
                raise HTTPException(409, "Answer 中断后缺少完整结果，禁止静默重试")
        answer = loads(result.output_json, {})
        if digest(answer) != result.output_hash:
            raise HTTPException(409, "Answer 保存结果 hash 不匹配")
        coverage = compute_coverage(raw, answer.get("answer_diagnosis") or {})
        checkpoint(db, row, objects={"answer_result_version": result.result_version,
            "answer_result_hash": result.output_hash, "answer_coverage": coverage})
        if not coverage["valid_compute_run_ids"]:
            if fixed.get('truth_correction'):
                checkpoint(db, row, status='BLOCKED', code='TRUTH_REPROJECTION_UPSTREAM_UNAVAILABLE',
                    detail='原回答缺少合格兼容缓存，本次纠错不授权重新调用回答模型；旧结果保留。')
                return
            pending_authority = bool(coverage["pending_external_authorization_run_ids"])
            checkpoint(db, row, status="WAITING_AUTHORIZATION" if policy == "CACHE_ONLY" else "BLOCKED",
                code="ANSWER_AUTHORIZATION_INSUFFICIENT" if pending_authority else "NO_CONSUMABLE_ANSWER",
                detail="回答请求未发出：需要核实授权或剩余预算，不会自动扩大额度。" if pending_authority else "没有合格回答；待授权、失败与合法零事件保持分别记录。")
            return

        checkpoint(db, row, stage="CITATION")
        contributions = {}
        citation_results = []
        limits = []
        for run_id in coverage["valid_compute_run_ids"]:
            try:
                contribution, _ = create_citation_contribution_plan(db, **scope,
                    answer_result_version=result.result_version, answer_result_hash=result.output_hash,
                    answer_review_id=None, input_authority="MACHINE_ADMISSION", selected_run_id=run_id,
                    citation_manifest_id=manifest.manifest_id, citation_manifest_hash=manifest.payload_hash,
                    completion_manifest_id=completion.manifest_id, completion_manifest_hash=completion.payload_hash,
                    fixed_run_ids=fixed["run_ids"], idempotency_key=f"{key}:run{run_id}")
            except HTTPException as exc:
                if not isinstance(exc.detail, dict) or exc.detail.get("code") != "NO_TECHNICALLY_ELIGIBLE_P1_RUN":
                    raise
                limits.append({"code": "CITATION_NOT_EVALUATED", "run_id": run_id, "reason": exc.detail})
                continue
            contributions[str(run_id)] = {"contribution_id": contribution.contribution_id, "plan_hash": contribution.plan_hash}
            checkpoint(db, row, objects={"contributions": contributions})
            if contribution.status == "AWAITING_EXTERNAL_AUTHORIZATION":
                db.rollback()
                execute_citation_contribution(contribution.contribution_id,
                    session_factory=session_factory, automatic_task_id=task_id)
                db.expire_all()
            current = db.query(SinglePromptCitationContributionExecution).filter_by(contribution_id=contribution.contribution_id).one()
            value = db.query(SinglePromptCitationContributionResult).filter_by(contribution_id=current.contribution_id,
                result_version=current.active_result_version).one_or_none()
            if value:
                evaluated = loads(value.output_json, {})
                if digest(evaluated) != value.output_hash:
                    raise HTTPException(409, "引用贡献结果 hash 不匹配")
                unavailable = [c for c in evaluated.get("citations") or [] if c.get("processing_status") != "DONE"]
                if unavailable:
                    limits.append({"code": "CITATION_PARTIAL_EVALUATION", "run_id": run_id,
                        "items": [{"citation_id": c["citation_id"], "status": c["processing_status"],
                            "reason": c.get("failure_code") or c.get("disposition")} for c in unavailable]})
                citation_results.append({"contribution_id": current.contribution_id, "result_version": value.result_version,
                    "result_hash": value.output_hash, "run_id": run_id})
            else:
                limits.append({"code": "CITATION_NO_RESULT", "run_id": run_id, "status": current.status})
        checkpoint(db, row, objects={"citation_results": citation_results}, limitations=limits)

        checkpoint(db, row, stage="STRATEGY")
        context_version = (fixed.get("brand_context") or {}).get("context_version_id")
        arguments = {**scope, "diagnosis_id": diagnosis.diagnosis_id, "result_version": result.result_version,
            "brand_context_version_id": context_version,
            "contribution_result_versions": [r["result_version"] for r in citation_results]}
        projection = build_qualification_projection(db, **arguments)
        strategy, strategy_result, _ = create_automatic_strategy_candidate(db, **arguments,
            idempotency_key=key, expected_projection_hash=projection["projection_hash"])
        checkpoint(db, row, objects={"strategy_id": strategy.strategy_id,
            "strategy_result_version": strategy_result.result_version, "strategy_result_hash": strategy_result.output_hash})

        checkpoint(db, row, stage="DRAFT")
        drafts = []
        directions = loads(strategy_result.output_json, {})['directions']
        if fixed.get('truth_correction'):
            from .truth_corrections import affected_directions
            directions = affected_directions(directions, fixed['truth_correction'])
            checkpoint(db, row, objects={'truth_reprojection': {
                **fixed['truth_correction'], 'new_affected_direction_ids': [d['strategy_id'] for d in directions],
                'unchanged_deliveries_location': 'PARENT_TASK'}})
            if not directions:
                checkpoint(db, row, stage='COMPLETE', status='COMPLETED_WITH_LIMITATIONS',
                    detail='纠错已应用，本次没有需要生成的新稿件；原稿作为历史版本保留，未受影响内容无需重写。')
                return
        for direction in directions:
            proposal, base, _ = create_execution_proposal(db, strategy_id=strategy.strategy_id,
                strategy_result_version=strategy_result.result_version, strategy_result_hash=strategy_result.output_hash,
                project_id=row.project_id, prompt_id=row.prompt_id, direction_id=direction["strategy_id"],
                idempotency_key=f"{key}:{direction['strategy_id']}", strategy_review_id=None, strategy_review_snapshot_hash="",
                input_authority_type="MACHINE_QUALIFICATION", input_authority_id=strategy.input_authority_id,
                input_authority_hash=strategy.input_authority_hash, brand_context_version_id=context_version,
                supplemental_source_refs=[{'source_id': s['snapshot_id'], 'snapshot_hash': digest(s)}
                    for s in fixed.get('supplemental_sources') or []])
            checkpoint(db, row, objects={"draft_in_progress": {"proposal_id": proposal.proposal_id,
                "result_version": base.result_version, "result_hash": base.output_hash}})
            delivered, _ = generate_complete_execution_deliverable(db, proposal_id=proposal.proposal_id,
                base_result_version=base.result_version, base_result_hash=base.output_hash,
                reviewable_set_hash=base.reviewable_set_hash, generation_client=scoped_client(db, row),
                generation_progress=lambda stage: checkpoint(db, row, stage=stage))
            payload = loads(delivered.output_json, {})
            drafts.append({"proposal_id": proposal.proposal_id, "result_version": delivered.result_version,
                "result_hash": delivered.output_hash, "content_delivery_status": payload["validation"]["content_delivery_status"]})
            checkpoint(db, row, objects={"deliveries": drafts})
        if not drafts or any(d["content_delivery_status"] != "READY" for d in drafts):
            checkpoint(db, row, status="BLOCKED", code="TEXT_QA_NO_DELIVERABLE", detail="正文未通过实际检查；保留问题与修改记录，不包装成完成。")
        else:
            limited = bool(limits or completion.status != "FROZEN" or len(coverage["valid_compute_run_ids"]) != len(fixed["run_ids"]))
            checkpoint(db, row, stage="COMPLETE", status="COMPLETED_WITH_LIMITATIONS" if limited else "COMPLETED")
    except Exception as exc:
        db.rollback()
        if row is not None:
            db.refresh(row)
            if row.status == "RUNNING":
                code = str(getattr(exc, "code", "") or "OPTIMIZATION_STAGE_FAILED")
                waiting = code in {"CACHE_MISS", "EXTERNAL_BUDGET_EXHAUSTED"}
                checkpoint(db, row, status="WAITING_AUTHORIZATION" if waiting else "BLOCKED", code=code,
                    detail=str(exc.detail if isinstance(exc, HTTPException) else exc)[:1000])
        else:
            raise
    finally:
        db.close()
