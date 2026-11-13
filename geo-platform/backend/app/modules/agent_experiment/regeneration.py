"""Bounded worker execution for one immutable draft-artifact regeneration."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.models import (
    AgentDraftArtifactRegeneration, AgentDraftArtifactVersion,
    AgentExperimentRun, AgentResultVersion,
)
from app.modules.single_prompt_v2.delivery_text import digest
from app.services.serialization import loads

from .evidence_pack import (
    EVIDENCE_PACK_EXECUTION_CONTRACT, EVIDENCE_PACK_PROMPT_VERSION,
    build_evidence_pack, render_evidence_pack_prompt,
    validate_markdown_result,
)
from .scope import revalidate_frozen_scope
from .service import complete_draft_artifact_regeneration


class RegenerationClient(Protocol):
    def generate(self, *, db: Session, system_prompt: str, evidence_pack: dict[str, Any],
                 max_tokens: int) -> tuple[str, dict[str, Any]]: ...


class RegenerationCancelled(RuntimeError):
    pass


class RegenerationContractError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


_CURRENT_REGENERATION_VALIDATION_CONTRACT = "geo.evidence-pack.validation.v6"


def _frozen_generation_profile(policy: dict[str, Any]) -> dict[str, str]:
    profile = policy.get("generation_profile")
    if not isinstance(profile, dict):
        raise RegenerationContractError("DRAFT_REGENERATION_GENERATION_PROFILE_MISSING")
    expected = {
        "execution_contract": EVIDENCE_PACK_EXECUTION_CONTRACT,
        "prompt_version": EVIDENCE_PACK_PROMPT_VERSION,
        "validation_contract": _CURRENT_REGENERATION_VALIDATION_CONTRACT,
    }
    if any(profile.get(key) != value for key, value in expected.items()):
        raise RegenerationContractError("DRAFT_REGENERATION_GENERATION_PROFILE_UNSUPPORTED")
    return expected


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def recover_interrupted_draft_regenerations(db: Session) -> int:
    rows = db.query(AgentDraftArtifactRegeneration).filter_by(status="RUNNING").order_by(
        AgentDraftArtifactRegeneration.id).all()
    for row in rows:
        audit = loads(row.audit_json, {})
        state = audit.get("external_request_state", "NOT_STARTED")
        if row.cancel_requested_at and state == "NOT_STARTED":
            row.status = "CANCELLED"
            row.failure_code = ""
            row.failure_detail = ""
        elif state == "NOT_STARTED":
            row.status = "QUEUED"
            row.failure_code = ""
            row.failure_detail = ""
        elif state in {"RESERVATION_PENDING", "RESERVED_IN_FLIGHT"}:
            row.status = "FAILED"
            row.failure_code = "DRAFT_REGENERATION_DELIVERY_UNKNOWN"
            row.failure_detail = "Worker 在外部请求边界中断；送达或用量未知，未自动重试。"
            row.audit_json = _canonical({**audit, "external_request_state": "DELIVERY_UNKNOWN"})
        else:
            row.status = "FAILED"
            row.failure_code = "DRAFT_REGENERATION_RESPONSE_NOT_MATERIALIZED"
            row.failure_detail = "Provider 已返回或结算，但子稿未完成持久化；未回滚费用且未自动重试。"
        if row.status != "QUEUED":
            row.finished_at = datetime.utcnow()
    if rows:
        db.commit()
    return len(rows)


def execute_draft_artifact_regeneration(
    request_id: str, *, session_factory, client: RegenerationClient | None = None,
) -> None:
    db: Session = session_factory()
    request: AgentDraftArtifactRegeneration | None = None
    try:
        request = db.query(AgentDraftArtifactRegeneration).filter_by(
            request_id=request_id).one_or_none()
        if not request or request.status != "QUEUED":
            return
        if request.cancel_requested_at:
            request.status = "CANCELLED"
            request.finished_at = datetime.utcnow()
            request.audit_json = _canonical({"external_request_state": "NOT_SENT",
                                             "cancelled_before_provider": True})
            db.commit()
            return
        source = db.query(AgentDraftArtifactVersion).filter_by(
            artifact_version=request.source_artifact_version,
            project_id=request.project_id, prompt_id=request.prompt_id).one()
        parent = db.query(AgentResultVersion).filter_by(
            result_version=request.parent_result_version,
            agent_run_id=request.agent_run_id).one()
        run = db.query(AgentExperimentRun).filter_by(
            run_id=request.agent_run_id, project_id=request.project_id,
            prompt_id=request.prompt_id).one()
        if parent.result_version != source.parent_result_version:
            raise RuntimeError("DRAFT_REGENERATION_PARENT_SCOPE_MISMATCH")
        scope = revalidate_frozen_scope(db, run)
        if digest(scope) != run.input_scope_hash:
            raise RuntimeError("DRAFT_REGENERATION_SCOPE_HASH_MISMATCH")
        policy = loads(request.server_policy_json, {})
        frozen_profile = policy.get("generation_profile")
        generation_profile = _frozen_generation_profile(policy)
        pack = build_evidence_pack(
            scope, execution_contract=generation_profile["execution_contract"],
        )
        request.status = "RUNNING"
        request.started_at = request.started_at or datetime.utcnow()
        request.attempt_count += 1
        request.audit_json = _canonical({
            "contract_version": "geo.draft-artifact.regeneration-audit.v1",
            "external_request_state": "NOT_STARTED",
            "source_artifact_hash": source.artifact_hash,
            "parent_result_hash": parent.result_hash,
            "input_scope_hash": run.input_scope_hash,
            "evidence_pack_hash": pack["evidence_pack_hash"],
            "artifact_type": source.artifact_type,
            "generation_profile": frozen_profile if isinstance(frozen_profile, dict) else {},
        })
        db.commit()

        if client is None:
            raise RuntimeError("DRAFT_REGENERATION_PROVIDER_NOT_AUTHORIZED")
        active_client = client
        db.refresh(request)
        if request.cancel_requested_at:
            raise RegenerationCancelled("DRAFT_REGENERATION_CANCELLED_BEFORE_PROVIDER")
        markdown, usage = active_client.generate(
            db=db,
            system_prompt=render_evidence_pack_prompt(
                prompt_version=generation_profile["prompt_version"],
                requested_artifact_types=[source.artifact_type]),
            evidence_pack=pack,
            max_tokens=min(16_384, int(policy.get("max_total_tokens", 16_384))),
        )
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        if not all(isinstance(value, int) and not isinstance(value, bool) and value >= 0
                   for value in (input_tokens, output_tokens)):
            raise RuntimeError("DRAFT_REGENERATION_USAGE_UNKNOWN")
        total_tokens = input_tokens + output_tokens
        cost_cny = float(usage.get("cost_cny", 0.0))
        if total_tokens > int(policy.get("max_total_tokens", 0)):
            raise RuntimeError("DRAFT_REGENERATION_ACTUAL_TOKENS_EXCEED_POLICY")
        if cost_cny < 0 or cost_cny > float(policy.get("max_cost_cny", 0.0)):
            raise RuntimeError("DRAFT_REGENERATION_ACTUAL_COST_EXCEEDS_POLICY")
        request.usage_json = _canonical({
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "total_tokens": total_tokens, "cost_cny": cost_cny,
            "accounting_persisted": bool(usage.get("accounting_persisted")),
            "response_source": usage.get("response_source", "UNKNOWN"),
            "request_identity_hash": digest(usage.get("request_identity") or {}),
        })
        request.audit_json = _canonical({**loads(request.audit_json, {}),
                                          "external_request_state": "PROVIDER_RETURNED",
                                          "usage_state": "KNOWN"})
        db.commit()
        checked, _eligibility = validate_markdown_result(
            markdown, pack, requested_artifact_types=[source.artifact_type],
            execution_contract=generation_profile["execution_contract"])
        if checked.get("validation", {}).get("contract_version") != \
                generation_profile["validation_contract"]:
            raise RegenerationContractError("DRAFT_REGENERATION_VALIDATION_PROFILE_MISMATCH")
        deliverables = checked["result"].get("deliverables") or []
        if len(deliverables) != 1 or deliverables[0].get("asset_type") != source.artifact_type:
            raise RuntimeError("DRAFT_REGENERATION_ASSET_TYPE_MISMATCH")
        # Cancellation after the provider boundary is intentionally audit-only:
        # generated content and settled usage are never rolled back.
        if request.cancel_requested_at:
            request.audit_json = _canonical({**loads(request.audit_json, {}),
                                              "cancel_after_provider_ignored": True})
            db.commit()
        complete_draft_artifact_regeneration(
            db, request_id=request.request_id, generated=deliverables[0], completed_by="worker")
    except RegenerationCancelled:
        db.rollback()
        request = db.query(AgentDraftArtifactRegeneration).filter_by(request_id=request_id).one_or_none()
        if request and request.status in {"QUEUED", "RUNNING"}:
            request.status = "CANCELLED"
            request.finished_at = datetime.utcnow()
            request.audit_json = _canonical({**loads(request.audit_json, {}),
                                              "external_request_state": "NOT_SENT",
                                              "cancelled_before_provider": True})
            db.commit()
    except Exception as exc:
        db.rollback()
        request = db.query(AgentDraftArtifactRegeneration).filter_by(request_id=request_id).one_or_none()
        if request and request.status in {"QUEUED", "RUNNING"}:
            audit = loads(request.audit_json, {})
            state = audit.get("external_request_state", "NOT_STARTED")
            request.status = "FAILED"
            request.failure_code = str(getattr(exc, "code", "") or exc.__class__.__name__).upper()
            request.failure_detail = str(exc)[:4000]
            request.finished_at = datetime.utcnow()
            request.audit_json = _canonical({**audit, "external_request_state": state})
            if state in {"RESERVATION_PENDING", "RESERVED_IN_FLIGHT"}:
                request.audit_json = _canonical({**audit, "external_request_state": "DELIVERY_UNKNOWN",
                                                  "usage_state": "UNKNOWN"})
            db.commit()
    finally:
        db.close()
