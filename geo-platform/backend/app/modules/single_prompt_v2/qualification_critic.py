"""Bounded Model B shadow critic over an exact Qualification projection."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.models import (
    SinglePromptCitationContributionResult,
    SinglePromptDiagnosisResult,
    SinglePromptQualificationCriticExecution,
    SinglePromptQualificationCriticResult,
)
from app.modules.single_prompt_v2.qualification import build_qualification_projection
from app.services.semantic_llm.base import SemanticLLMError
from app.services.semantic_llm.model_b import create_model_b_client
from app.services.serialization import dumps, loads


QUALIFICATION_CRITIC_CONTRACT_VERSION = "single_prompt_v2.qualification_critic_shadow.v1"
QUALIFICATION_CRITIC_PROMPT_VERSION = "single_prompt_v2.qualification_critic.qwen.v1"
QUALIFICATION_CRITIC_SCHEMA_VERSION = "single_prompt_v2.qualification_critic.strict.v1"
QUALIFICATION_CRITIC_IMPLEMENTATION_VERSION = "single_prompt_v2.qualification_critic.impl.v1"

_ISSUES = {
    "SUBJECT_MISMATCH",
    "QUALIFIER_LOSS",
    "OVERSTATED_SUPPORT",
    "TRUTH_SCOPE_EXPANSION",
    "DECISION_ROLE_MISMATCH",
    "STRATEGY_GAP_MISMATCH",
    "CLAIM_OVERREACH",
    "OTHER",
}


class QualificationCriticResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    critic_verdict: Literal["AGREE", "DISAGREE", "INSUFFICIENT_CONTEXT"]
    issues: list[Literal[
        "SUBJECT_MISMATCH",
        "QUALIFIER_LOSS",
        "OVERSTATED_SUPPORT",
        "TRUTH_SCOPE_EXPANSION",
        "DECISION_ROLE_MISMATCH",
        "STRATEGY_GAP_MISMATCH",
        "CLAIM_OVERREACH",
        "OTHER",
    ]]
    counterexample: str | None
    rationale: str = Field(min_length=1, max_length=1200)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _require(condition: bool, code: str, detail: str) -> None:
    if not condition:
        raise HTTPException(status_code=409, detail={"code": code, "detail": detail})


def _write_response_artifact(
    *,
    critic_id: str,
    attempt_number: int,
    sequence: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    root = Path(get_settings().evidence_artifact_dir).resolve() / "qualification-critic" / critic_id
    root.mkdir(parents=True, exist_ok=True)
    input_hash = str((payload.get("request_identity") or {}).get("input_hash") or "unknown")
    path = root / f"attempt-{attempt_number:02d}-response-{sequence:03d}-{input_hash[:12]}.json"
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str).encode("utf-8")
    with path.open("xb") as handle:
        handle.write(encoded)
    path.chmod(0o600)
    return {
        "artifact_path": str(path),
        "artifact_hash": hashlib.sha256(encoded).hexdigest(),
        "size_bytes": len(encoded),
        "input_hash": input_hash,
        "response_source": str(payload.get("response_source") or ""),
        "validation_status": str(payload.get("validation_status") or ""),
        "raw_response_hash": str(payload.get("raw_response_hash") or ""),
        "token_usage": payload.get("token_usage") or {},
        "response_model": str(payload.get("response_model") or ""),
        "provider_trace_id": str(payload.get("provider_trace_id") or ""),
        "rejection_code": str(payload.get("rejection_code") or ""),
        "rejection_reason": str(payload.get("rejection_reason") or ""),
    }


def _load_contribution_output(db: Session, projection: dict[str, Any]) -> dict[str, Any] | None:
    identity = ((projection.get("evidence_scope") or {}).get("result") or {})
    result_version = str(identity.get("result_version") or "")
    result_hash = str(identity.get("result_hash") or "")
    if not result_version:
        return None
    row = db.query(SinglePromptCitationContributionResult).filter_by(result_version=result_version).one_or_none()
    _require(row is not None, "CRITIC_CONTRIBUTION_RESULT_MISSING", "资格投影绑定的 Citation Contribution 不存在")
    _require(row.output_hash == result_hash, "CRITIC_CONTRIBUTION_RESULT_HASH_MISMATCH", "Citation Contribution hash 不一致")
    return loads(row.output_json, {})


def _strategy_candidate(direction: dict[str, Any], draft: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "candidate_id": f"critic-strategy-{_hash(direction)[:20]}",
        "candidate_type": "STRATEGY_DIRECTION",
        "object_id": direction["strategy_id"],
        "impact_reasons": ["STRATEGY_DIRECTION_CONSUMABLE", "EXECUTION_DRAFT_DEPENDENCY"],
        "critic_input": {
            "model_a_judgment": {
                "mechanism_gap": direction.get("mechanism_gap"),
                "intervention_goal": direction.get("intervention_goal"),
                "strategy_direction_eligibility": direction.get("strategy_direction_eligibility"),
                "public_claim_eligibility": direction.get("public_claim_eligibility"),
            },
            "grounded_reason": {
                "reason_id": direction.get("reason_id"),
                "text": direction.get("reason_text"),
                "run_ids": direction.get("reason_run_ids") or [],
            },
            "truth_ids": direction.get("truth_ids") or [],
            "dependencies": direction.get("dependencies") or [],
            "scope_limitations": direction.get("scope_limitations") or [],
            "draft_claims": (draft or {}).get("claims") or [],
        },
    }


def _citation_candidates(contribution: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not contribution:
        return []
    units = {str(row.get("answer_unit_id")): row for row in contribution.get("answer_units") or []}
    evaluations = {str(row.get("evaluation_id")): row for row in contribution.get("evaluations") or []}
    result = []
    for binding in sorted(contribution.get("bindings") or [], key=lambda row: str(row.get("binding_id") or "")):
        if binding.get("evidence_relation") not in {"SUPPORTS_FULL", "SUPPORTS_PARTIAL"}:
            continue
        evaluation = evaluations.get(str(binding.get("evaluation_id") or ""))
        unit = units.get(str(binding.get("answer_unit_id") or ""))
        if not evaluation or not unit:
            continue
        result.append({
            "candidate_id": f"critic-citation-{_hash(binding)[:20]}",
            "candidate_type": "CITATION_RELATION",
            "object_id": binding["binding_id"],
            "impact_reasons": ["POSITIVE_EVIDENCE_RELATION", "DOWNSTREAM_MECHANISM_INPUT"],
            "critic_input": {
                "model_a_judgment": {
                    "correspondence_mode": binding.get("correspondence_mode"),
                    "evidence_relation": binding.get("evidence_relation"),
                    "answer_anchor": binding.get("answer_anchor"),
                    "generation_influence": binding.get("generation_influence"),
                    "rationale": binding.get("rationale"),
                },
                "answer_unit": {
                    "answer_unit_id": unit.get("answer_unit_id"),
                    "primary_type": unit.get("primary_type"),
                    "raw_text": unit.get("raw_text"),
                    "context_heading": unit.get("context_heading"),
                    "subject_markers": unit.get("subject_markers") or [],
                    "condition_markers": unit.get("condition_markers") or [],
                    "negation_markers": unit.get("negation_markers") or [],
                },
                "source_evidence": {
                    "citation_id": evaluation.get("citation_id"),
                    "citation_title": evaluation.get("citation_title"),
                    "answer_span": evaluation.get("answer_span"),
                    "source_span": evaluation.get("source_span"),
                    "source_passage_text": evaluation.get("source_passage_text"),
                    "validation_limitations": evaluation.get("validation_limitations") or [],
                },
            },
        })
    return result


def build_qualification_critic_plan(
    db: Session,
    *,
    analysis_id: str,
    diagnosis_id: str,
    result_version: str,
    project_id: int,
    prompt_id: int,
) -> dict[str, Any]:
    projection = build_qualification_projection(
        db,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        result_version=result_version,
        project_id=project_id,
        prompt_id=prompt_id,
    )
    drafts = {str(row.get("direction_id")): row for row in projection.get("execution_drafts") or []}
    candidates = [
        _strategy_candidate(row, drafts.get(str(row.get("strategy_id"))))
        for row in projection.get("directions") or []
        if row.get("strategy_direction_eligibility") == "CONSUMABLE"
    ]
    candidates.extend(_citation_candidates(_load_contribution_output(db, projection)))
    candidates = sorted(candidates, key=lambda row: (row["candidate_type"], row["object_id"]))
    settings = get_settings()
    _require(
        len(candidates) <= settings.model_b_shadow_max_calls,
        "CRITIC_SCOPE_EXCEEDS_CONFIGURED_LIMIT",
        f"高影响对象 {len(candidates)} 个，超过配置上限 {settings.model_b_shadow_max_calls}",
    )
    plan = {
        "contract_version": QUALIFICATION_CRITIC_CONTRACT_VERSION,
        "selection_policy": "HIGH_IMPACT_POSITIVE_RELATION_OR_CONSUMABLE_STRATEGY_V1",
        "baseline_projection_hash": projection["projection_hash"],
        "candidate_count": len(candidates),
        "candidates": candidates,
        "formal_qualification_effect": "SHADOW_ONLY",
    }
    plan["plan_hash"] = _hash(plan)
    return {"projection": projection, "plan": plan}


def queue_qualification_critic(
    db: Session,
    *,
    analysis_id: str,
    diagnosis_id: str,
    result_version: str,
    project_id: int,
    prompt_id: int,
    expected_projection_hash: str,
    idempotency_key: str,
    max_external_requests: int,
    max_total_tokens: int,
    authorized_by: str,
) -> tuple[SinglePromptQualificationCriticExecution, bool]:
    existing = db.query(SinglePromptQualificationCriticExecution).filter_by(
        analysis_id=analysis_id,
        idempotency_key=idempotency_key,
    ).one_or_none()
    if existing:
        _require(existing.diagnosis_result_version == result_version, "CRITIC_IDEMPOTENCY_CONFLICT", "幂等键已绑定其他结果版本")
        return existing, False

    settings = get_settings()
    _require(settings.model_b_enabled, "MODEL_B_DISABLED", "Model B 尚未在环境中启用")
    _require(max_external_requests <= settings.model_b_shadow_max_calls, "CRITIC_REQUEST_LIMIT_EXCEEDED", "请求数超过 Model B Shadow 上限")
    _require(max_total_tokens <= settings.model_b_shadow_max_tokens, "CRITIC_TOKEN_LIMIT_EXCEEDED", "token 上限超过 Model B Shadow 配置")
    built = build_qualification_critic_plan(
        db,
        analysis_id=analysis_id,
        diagnosis_id=diagnosis_id,
        result_version=result_version,
        project_id=project_id,
        prompt_id=prompt_id,
    )
    projection = built["projection"]
    plan = built["plan"]
    _require(projection["projection_hash"] == expected_projection_hash, "CRITIC_BASELINE_STALE", "资格投影已变化，请刷新后重新启动")
    _require(plan["candidate_count"] <= max_external_requests, "CRITIC_AUTHORIZATION_SCOPE_TOO_SMALL", "授权请求数不足以覆盖冻结计划")
    diagnosis_result = db.query(SinglePromptDiagnosisResult).filter_by(
        diagnosis_id=diagnosis_id,
        result_version=result_version,
    ).one_or_none()
    _require(diagnosis_result is not None, "CRITIC_DIAGNOSIS_RESULT_MISSING", "精确 DiagnosisResultVersion 不存在")
    input_snapshot = {
        "analysis_id": analysis_id,
        "context_id": projection["input_identity"]["context_id"],
        "project_id": project_id,
        "prompt_id": prompt_id,
        "diagnosis_id": diagnosis_id,
        "diagnosis_result_version": result_version,
        "diagnosis_result_hash": diagnosis_result.output_hash,
        "baseline_projection": projection,
        "baseline_projection_hash": projection["projection_hash"],
    }
    critic_id = f"qualification-critic-{uuid4()}"
    execution = SinglePromptQualificationCriticExecution(
        critic_id=critic_id,
        analysis_id=analysis_id,
        context_id=projection["input_identity"]["context_id"],
        project_id=project_id,
        prompt_id=prompt_id,
        diagnosis_id=diagnosis_id,
        diagnosis_result_version=result_version,
        diagnosis_result_hash=diagnosis_result.output_hash,
        baseline_projection_hash=projection["projection_hash"],
        idempotency_key=idempotency_key,
        input_snapshot_json=dumps(input_snapshot),
        input_snapshot_hash=_hash(input_snapshot),
        plan_json=dumps(plan),
        plan_hash=plan["plan_hash"],
        contract_version=QUALIFICATION_CRITIC_CONTRACT_VERSION,
        provider=settings.model_b_provider,
        requested_model=settings.siliconflow_model,
        authorization_json=dumps({
            "authorized_by": authorized_by,
            "max_external_requests": max_external_requests,
            "max_total_tokens": max_total_tokens,
            "automatic_retries": 0,
        }),
        status="QUEUED",
        progress_json=dumps({"completed": 0, "total": plan["candidate_count"], "stage": "QUEUED"}),
    )
    db.add(execution)
    db.commit()
    db.refresh(execution)
    return execution, True


def _prompt(candidate: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    system = """你是 Model B Critic，只复核一个已经冻结的高影响判断。
你不能重做主分析、不能生成新策略、不能改变任何 ID、事实、渠道、角色或资格。
只根据 supplied_object 判断 Model A 是否存在明显主体错位、限定丢失、支持强度夸大、Truth 范围扩张、决策角色错位、策略 Gap 错诊或 Claim 越界。
现实世界事实未包含在输入中时必须返回 INSUFFICIENT_CONTEXT，不能使用世界知识补齐。
counterexample 如非 null，必须逐字引用 supplied_object 中已有的连续文本；不得自由编写反例。
AGREE 时 issues 必须为空；DISAGREE 时 issues 至少一项。输出只能是符合 Schema 的 JSON。"""
    payload = {
        "task": "CRITIQUE_FROZEN_HIGH_IMPACT_OBJECT",
        "candidate_type": candidate["candidate_type"],
        "object_id": candidate["object_id"],
        "impact_reasons": candidate["impact_reasons"],
        "allowed_issue_types": sorted(_ISSUES),
        "supplied_object": candidate["critic_input"],
        "authority_boundary": {
            "shadow_only": True,
            "may_change_qualification": False,
            "may_create_facts": False,
            "may_create_strategy": False,
        },
    }
    return system, payload


def _validator(candidate: dict[str, Any]):
    searchable = _canonical_json(candidate.get("critic_input") or {})

    def validate(payload: Any) -> dict[str, Any]:
        row = QualificationCriticResponse.model_validate(payload).model_dump(mode="json")
        if row["critic_verdict"] == "AGREE" and row["issues"]:
            raise SemanticLLMError("AGREE 不得携带 issue")
        if row["critic_verdict"] == "DISAGREE" and not row["issues"]:
            raise SemanticLLMError("DISAGREE 必须携带至少一个 issue")
        counterexample = str(row.get("counterexample") or "").strip()
        if counterexample and counterexample not in searchable:
            raise SemanticLLMError("counterexample 未逐字出现在冻结输入中")
        return row

    return validate


def execute_qualification_critic(
    critic_id: str,
    *,
    session_factory: sessionmaker,
    client=None,
) -> None:
    db = session_factory()
    try:
        execution = db.query(SinglePromptQualificationCriticExecution).filter_by(critic_id=critic_id).one_or_none()
        if not execution or execution.status != "QUEUED":
            return
        execution.status = "RUNNING"
        execution.attempt_count += 1
        execution.started_at = datetime.utcnow()
        execution.progress_json = dumps({"completed": 0, "total": loads(execution.plan_json, {}).get("candidate_count", 0), "stage": "RUNNING"})
        db.commit()

        snapshot = loads(execution.input_snapshot_json, {})
        built = build_qualification_critic_plan(
            db,
            analysis_id=execution.analysis_id,
            diagnosis_id=execution.diagnosis_id,
            result_version=execution.diagnosis_result_version,
            project_id=execution.project_id,
            prompt_id=execution.prompt_id,
        )
        _require(built["projection"]["projection_hash"] == execution.baseline_projection_hash, "CRITIC_BASELINE_DRIFT", "worker 执行前 baseline 已变化")
        _require(built["plan"]["plan_hash"] == execution.plan_hash, "CRITIC_PLAN_DRIFT", "worker 执行前 plan 已变化")
        _require(_hash(snapshot) == execution.input_snapshot_hash, "CRITIC_INPUT_SNAPSHOT_DRIFT", "冻结输入 hash 不一致")
        plan = built["plan"]
        authorization = loads(execution.authorization_json, {})
        artifacts: list[dict[str, Any]] = []
        active_context: dict[str, Any] = {}

        def audit_sink(payload: dict[str, Any]) -> None:
            artifacts.append(_write_response_artifact(
                critic_id=critic_id,
                attempt_number=execution.attempt_count,
                sequence=len(artifacts) + 1,
                payload={
                    "critic_id": critic_id,
                    "plan_hash": execution.plan_hash,
                    "candidate_context": dict(active_context),
                    "contract_version": QUALIFICATION_CRITIC_CONTRACT_VERSION,
                    "prompt_version": QUALIFICATION_CRITIC_PROMPT_VERSION,
                    "schema_version": QUALIFICATION_CRITIC_SCHEMA_VERSION,
                    "implementation_version": QUALIFICATION_CRITIC_IMPLEMENTATION_VERSION,
                    **payload,
                },
            ))

        active_client = client or create_model_b_client(
            cache_only=False,
            max_attempts=1,
            response_audit_sink=audit_sink,
        )
        initial_external = int(getattr(active_client, "external_call_count", 0))
        initial_calls = int(getattr(active_client, "call_count", 0))
        initial_tokens = int(getattr(active_client, "external_token_count", 0))
        signals: list[dict[str, Any]] = []
        for index, candidate in enumerate(plan["candidates"], start=1):
            used_external = int(getattr(active_client, "external_call_count", 0)) - initial_external
            used_tokens = int(getattr(active_client, "external_token_count", 0)) - initial_tokens
            if used_external >= int(authorization["max_external_requests"]):
                signals.append({**candidate, "processing_status": "NOT_EVALUATED", "failure_code": "REQUEST_LIMIT_REACHED"})
                continue
            system_prompt, payload = _prompt(candidate)
            estimated_tokens = max(1, (len(system_prompt) + len(_canonical_json(payload))) // 3) + 1200
            if used_tokens + estimated_tokens > int(authorization["max_total_tokens"]):
                signals.append({**candidate, "processing_status": "NOT_EVALUATED", "failure_code": "TOKEN_LIMIT_WOULD_BE_EXCEEDED"})
                continue
            active_context.clear()
            active_context.update({
                "candidate_id": candidate["candidate_id"],
                "candidate_type": candidate["candidate_type"],
                "object_id": candidate["object_id"],
            })
            try:
                response = active_client.structured_generate_sync(
                    system_prompt=system_prompt,
                    user_payload=payload,
                    response_schema=QualificationCriticResponse,
                    prompt_version=QUALIFICATION_CRITIC_PROMPT_VERSION,
                    schema_version=QUALIFICATION_CRITIC_SCHEMA_VERSION,
                    max_tokens=1200,
                    db=db,
                    strict_json=True,
                    response_validator=_validator(candidate),
                )
                signals.append({
                    "candidate_id": candidate["candidate_id"],
                    "candidate_type": candidate["candidate_type"],
                    "object_id": candidate["object_id"],
                    "impact_reasons": candidate["impact_reasons"],
                    "processing_status": "DONE",
                    **response,
                })
            except Exception as exc:
                signals.append({
                    "candidate_id": candidate["candidate_id"],
                    "candidate_type": candidate["candidate_type"],
                    "object_id": candidate["object_id"],
                    "impact_reasons": candidate["impact_reasons"],
                    "processing_status": "FAILED",
                    "failure_code": str(getattr(exc, "code", exc.__class__.__name__)),
                    "failure_detail": str(exc)[:1000],
                })
            execution.progress_json = dumps({"completed": index, "total": plan["candidate_count"], "stage": "RUNNING"})
            db.commit()

        external_calls = int(getattr(active_client, "external_call_count", 0)) - initial_external
        admitted_calls = int(getattr(active_client, "call_count", 0)) - initial_calls
        token_usage = int(getattr(active_client, "external_token_count", 0)) - initial_tokens
        verdicts = Counter(row.get("critic_verdict") for row in signals if row.get("processing_status") == "DONE")
        issues = Counter(issue for row in signals for issue in row.get("issues") or [])
        statuses = Counter(str(row.get("processing_status")) for row in signals)
        output = {
            "contract_version": QUALIFICATION_CRITIC_CONTRACT_VERSION,
            "prompt_version": QUALIFICATION_CRITIC_PROMPT_VERSION,
            "schema_version": QUALIFICATION_CRITIC_SCHEMA_VERSION,
            "implementation_version": QUALIFICATION_CRITIC_IMPLEMENTATION_VERSION,
            "critic_id": critic_id,
            "input_identity": {
                "analysis_id": execution.analysis_id,
                "context_id": execution.context_id,
                "diagnosis_id": execution.diagnosis_id,
                "diagnosis_result_version": execution.diagnosis_result_version,
                "diagnosis_result_hash": execution.diagnosis_result_hash,
                "baseline_projection_hash": execution.baseline_projection_hash,
                "plan_hash": execution.plan_hash,
            },
            "model_identity": {
                "provider": execution.provider,
                "requested_model": execution.requested_model,
            },
            "single_model_baseline": snapshot["baseline_projection"],
            "signals": signals,
            "summary": {
                "candidate_count": plan["candidate_count"],
                "processing_status": dict(sorted(statuses.items())),
                "critic_verdict": dict(sorted((str(k), v) for k, v in verdicts.items())),
                "issues": dict(sorted(issues.items())),
                "external_calls": external_calls,
                "cache_hits": max(0, admitted_calls - external_calls),
                "external_tokens": token_usage,
            },
            "machine_output_artifacts": artifacts,
            "shadow_comparison": {
                "formal_qualification_changed": False,
                "formal_strategy_changed": False,
                "disagreement_count": verdicts.get("DISAGREE", 0),
                "insufficient_context_count": verdicts.get("INSUFFICIENT_CONTEXT", 0),
                "gain_against_human_gold": "NOT_MEASURABLE_UNTIL_P1_HUMAN_GOLD_EXISTS",
            },
            "boundary": {
                "shadow_only": True,
                "may_mutate_qualification": False,
                "may_mutate_strategy": False,
                "may_create_product_truth": False,
                "may_authorize_external_action": False,
            },
        }
        output_hash = _hash(output)
        result_version = f"critic-v1:{output_hash[:16]}"
        result = SinglePromptQualificationCriticResult(
            result_version=result_version,
            critic_id=critic_id,
            version_number=1,
            output_json=dumps(output),
            output_hash=output_hash,
            stats_json=dumps(output["summary"]),
        )
        db.add(result)
        execution.status = "SHADOW_COMPLETED" if not statuses.get("FAILED") and not statuses.get("NOT_EVALUATED") else "SHADOW_COMPLETED_WITH_LIMITATIONS"
        execution.active_result_version = result_version
        execution.external_llm_calls = external_calls
        execution.llm_cache_hits = max(0, admitted_calls - external_calls)
        execution.external_token_usage = token_usage
        execution.progress_json = dumps({"completed": len(signals), "total": plan["candidate_count"], "stage": execution.status})
        execution.finished_at = datetime.utcnow()
        db.commit()
    except Exception as exc:
        db.rollback()
        execution = db.query(SinglePromptQualificationCriticExecution).filter_by(critic_id=critic_id).one_or_none()
        if execution:
            execution.status = "FAILED"
            execution.blocker_code = str(getattr(exc, "code", exc.__class__.__name__))
            execution.blocker_detail = str(exc)[:2000]
            execution.finished_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


def get_qualification_critic_status(
    db: Session,
    *,
    analysis_id: str,
    critic_id: str,
    project_id: int,
    prompt_id: int,
) -> dict[str, Any]:
    execution = db.query(SinglePromptQualificationCriticExecution).filter_by(
        critic_id=critic_id,
        analysis_id=analysis_id,
        project_id=project_id,
        prompt_id=prompt_id,
    ).one_or_none()
    if not execution:
        raise HTTPException(status_code=404, detail="Qualification Critic 不存在")
    result = None
    if execution.active_result_version:
        row = db.query(SinglePromptQualificationCriticResult).filter_by(
            critic_id=critic_id,
            result_version=execution.active_result_version,
        ).one_or_none()
        if row:
            result = {
                "result_version": row.result_version,
                "result_hash": row.output_hash,
                "output": loads(row.output_json, {}),
                "created_at": _iso(row.created_at),
            }
    plan = loads(execution.plan_json, {})
    return {
        "execution": {
            "critic_id": execution.critic_id,
            "status": execution.status,
            "analysis_id": execution.analysis_id,
            "context_id": execution.context_id,
            "diagnosis_id": execution.diagnosis_id,
            "diagnosis_result_version": execution.diagnosis_result_version,
            "baseline_projection_hash": execution.baseline_projection_hash,
            "plan_hash": execution.plan_hash,
            "candidate_count": plan.get("candidate_count", 0),
            "provider": execution.provider,
            "requested_model": execution.requested_model,
            "progress": loads(execution.progress_json, {}),
            "external_llm_calls": execution.external_llm_calls,
            "llm_cache_hits": execution.llm_cache_hits,
            "external_token_usage": execution.external_token_usage,
            "blocker": ({"code": execution.blocker_code, "detail": execution.blocker_detail} if execution.blocker_code else None),
            "created_at": _iso(execution.created_at),
            "started_at": _iso(execution.started_at),
            "finished_at": _iso(execution.finished_at),
        },
        "result": result,
        "allowed_actions": [] if execution.status in {"QUEUED", "RUNNING"} else ["VIEW_SHADOW_COMPARISON"],
    }


def recover_interrupted_qualification_critics(db: Session) -> int:
    rows = db.query(SinglePromptQualificationCriticExecution).filter_by(status="RUNNING").all()
    for row in rows:
        row.status = "FAILED"
        row.blocker_code = "WORKER_INTERRUPTED"
        row.blocker_detail = "Model B Shadow worker 中断；不会自动重试或追加调用"
        row.finished_at = datetime.utcnow()
    if rows:
        db.commit()
    return len(rows)
