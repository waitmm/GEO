"""Fifth-slice fixed retest and descriptive comparison for Single-Prompt V2."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import (
    BrowserMonitorRun,
    SinglePromptAnalysis,
    SinglePromptAnalysisContext,
    SinglePromptComparisonResult,
    SinglePromptDiagnosisResult,
    SinglePromptExecutionConfirmation,
    SinglePromptExecutionProposal,
    SinglePromptPublicationRecord,
    SinglePromptRetestExecution,
    SinglePromptStrategyExecution,
)
from app.modules.single_prompt_v2.diagnosis import _diagnose_answers
from app.modules.single_prompt_v2.llm_safety import V2AnswerSemanticJudge, V2_ANSWER_SCHEMA_VERSION
from app.modules.single_prompt_v2.service import (
    create_frozen_analysis,
    execute_analysis,
    finalize_analysis_with_recorded_failures,
    get_analysis_status,
    queue_frozen_analysis,
    retry_analysis,
)
from app.services.semantic_llm.deepseek import DeepSeekClient
from app.services.serialization import loads
from app.services.url_identity import CANONICALIZATION_VERSION, canonicalize_url


RETEST_CONTRACT_VERSION = "single_prompt_retest.v2_fifth_slice.v1"
RETEST_PLAN_VERSION = "single_prompt_retest_plan.v1"
MEASUREMENT_IDENTITY_VERSION = "single_prompt_measurement_identity.v1"
MEASUREMENT_CONTRACT_VERSION = "single_prompt_measurement.v2"
COMPARISON_CONTRACT_VERSION = "single_prompt_comparison.v1"
BRAND_IDENTITY_RULE_VERSION = "single_prompt_brand_identity.casefold_boundary.v1"
ACTIVE_RETEST_STATUSES = {"SAMPLING", "SEMANTIC_MEASURING"}
VALID_RUN_STATUSES = {"success", "partial_success"}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _text_hash(value: str) -> str:
    return _hash(str(value or ""))


def _iso(value: datetime | None) -> str | None:
    return f"{value.isoformat()}Z" if value else None


def _parse_aware(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _normalize_domain(value: str) -> str:
    raw = str(value or "").strip().lower()
    if "://" in raw:
        raw = urlparse(raw).hostname or ""
    raw = raw.split("/")[0].split(":")[0].strip(".")
    return raw[4:] if raw.startswith("www.") else raw


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result


def _exact_chain(
    db: Session,
    *,
    project_id: int,
    prompt_id: int,
    confirmation_id: str,
    publication_id: str,
) -> dict[str, Any]:
    publication = db.query(SinglePromptPublicationRecord).filter_by(publication_id=publication_id).one_or_none()
    if not publication:
        raise HTTPException(status_code=409, detail="缺少精确 PublicationRecord，不能创建发布后复测")
    confirmation = db.query(SinglePromptExecutionConfirmation).filter_by(confirmation_id=confirmation_id).one_or_none()
    if not confirmation or publication.confirmation_id != confirmation_id:
        raise HTTPException(status_code=409, detail="PublicationRecord 与 ExecutionConfirmation 不匹配")
    proposal = db.query(SinglePromptExecutionProposal).filter_by(proposal_id=confirmation.proposal_id).one_or_none()
    if not proposal or publication.proposal_id != proposal.proposal_id:
        raise HTTPException(status_code=409, detail="发布、确认与执行方案链不完整")
    if proposal.project_id != project_id or proposal.prompt_id != prompt_id:
        raise HTTPException(status_code=409, detail="发布复测输入跨 Project/Prompt")
    confirmed = loads(confirmation.confirmation_snapshot_json, {})
    report = loads(publication.report_json, {})
    if _hash(confirmed) != confirmation.confirmation_snapshot_hash:
        raise HTTPException(status_code=409, detail="ExecutionConfirmation 快照 Hash 不匹配")
    if _hash(report) != publication.report_hash:
        raise HTTPException(status_code=409, detail="PublicationRecord 报告 Hash 不匹配")
    baseline = confirmed.get("baseline") or {}
    baseline_analysis_id = str(baseline.get("analysis_id") or "")
    baseline_context_id = str(baseline.get("context_id") or "")
    analysis = db.query(SinglePromptAnalysis).filter_by(analysis_id=baseline_analysis_id).one_or_none()
    context = db.query(SinglePromptAnalysisContext).filter_by(context_id=baseline_context_id).one_or_none()
    if not analysis or not context or context.analysis_id != baseline_analysis_id:
        raise HTTPException(status_code=409, detail="确认记录引用的固定 Baseline 不完整")
    raw = loads(context.raw_output_json, {})
    run_scope = loads(context.run_scope_json, {})
    if (
        context.raw_output_hash != baseline.get("raw_output_hash")
        or context.result_version != baseline.get("raw_result_version")
        or analysis.sampling_plan_hash != baseline.get("sampling_plan_hash")
        or context.run_scope_hash != baseline.get("run_scope_hash")
        or _hash(raw) != context.raw_output_hash
        or _hash(run_scope) != context.run_scope_hash
    ):
        raise HTTPException(status_code=409, detail="固定 Baseline 版本或 Hash 已损坏")
    manifest = baseline.get("run_manifest") or {}
    valid_ids = [int(value) for value in manifest.get("valid_run_ids") or []]
    if valid_ids != [int(value) for value in baseline.get("baseline_run_ids") or []]:
        raise HTTPException(status_code=409, detail="固定 Baseline 有效 Run 清单不守恒")
    return {
        "publication": publication,
        "confirmation": confirmation,
        "proposal": proposal,
        "confirmed": confirmed,
        "report": report,
        "baseline": baseline,
        "baseline_analysis": analysis,
        "baseline_context": context,
        "baseline_raw": raw,
    }


def build_retest_readiness(
    db: Session,
    *,
    project_id: int,
    prompt_id: int,
    confirmation_id: str | None = None,
    publication_id: str | None = None,
) -> dict[str, Any]:
    if not confirmation_id or not publication_id:
        return {
            "contract_version": RETEST_CONTRACT_VERSION,
            "sampling_eligible": False,
            "blocker": {
                "code": "EXECUTION_CONFIRMATION_AND_PUBLICATION_REQUIRED",
                "detail": "需要明确选择一条执行确认及其人工发布记录，才能创建发布后复测。",
            },
            "allowed_actions": [],
        }
    chain = _exact_chain(
        db,
        project_id=project_id,
        prompt_id=prompt_id,
        confirmation_id=confirmation_id,
        publication_id=publication_id,
    )
    report = chain["report"]
    published = _parse_aware(report.get("published_at"))
    return {
        "contract_version": RETEST_CONTRACT_VERSION,
        "sampling_eligible": True,
        "comparison_eligible": {
            "temporal_order": published is not None,
            "status": "PENDING_RETEST",
        },
        "pre_post_temporal_order_verified": False,
        "publication": {
            "publication_id": publication_id,
            "confirmation_id": confirmation_id,
            "revision_number": chain["publication"].revision_number,
            "report_hash": chain["publication"].report_hash,
            "publication_status": chain["publication"].publication_status,
            "conformance": chain["publication"].conformance,
            "published_at": report.get("published_at"),
            "published_at_parse_status": "TIMEZONE_AWARE" if published else "TEMPORAL_ORDER_UNVERIFIED",
        },
        "baseline": chain["baseline"],
        "identity_default": {
            "canonical_brand_name": str((loads(chain["proposal"].input_snapshot_json, {}).get("brand_snapshot") or {}).get("brand_name") or ""),
            "accepted_aliases": [],
            "official_domains": [],
            "official_urls": [],
            "identity_source": "FROZEN_STRATEGY_BRAND_NAME_ONLY",
        },
        "allowed_actions": ["CREATE_RETEST_PLAN"],
        "boundary": {
            "publication_system_verified": False,
            "strategy_current_required": False,
            "external_sampling_started": False,
            "external_llm_calls": 0,
            "causal_conclusion": False,
        },
    }


def _measurement_identity(chain: dict[str, Any], supplied: dict[str, Any] | None) -> dict[str, Any]:
    strategy = chain["proposal"].strategy_id
    strategy_row = chain.get("strategy")
    if strategy_row is None:
        raise RuntimeError(f"strategy row missing for {strategy}")
    frozen_brand = loads(chain["proposal"].input_snapshot_json, {}).get("brand_snapshot") or {}
    supplied = supplied or {}
    canonical_name = str(supplied.get("canonical_brand_name") or frozen_brand.get("brand_name") or "").strip()
    if not canonical_name:
        raise HTTPException(status_code=409, detail="冻结策略输入缺少目标品牌名称")
    aliases = _dedupe(list(supplied.get("accepted_aliases") or []))
    official_domains = _dedupe([_normalize_domain(value) for value in supplied.get("official_domains") or []])
    official_urls = _dedupe([canonicalize_url(value) for value in supplied.get("official_urls") or [] if canonicalize_url(value)])
    explicit = bool(supplied.get("confirmed_by") or aliases or official_domains or official_urls)
    identity = {
        "contract_version": MEASUREMENT_IDENTITY_VERSION,
        "canonical_brand_name": canonical_name,
        "accepted_aliases": aliases,
        "official_domains": official_domains,
        "official_urls": official_urls,
        "identity_rule_version": BRAND_IDENTITY_RULE_VERSION,
        "identity_source": "USER_CONFIRMED_MEASUREMENT_IDENTITY" if explicit else "FROZEN_STRATEGY_BRAND_NAME_ONLY",
        "confirmed_by": str(supplied.get("confirmed_by") or ""),
        "source_brand_snapshot_hash": strategy_row.input_snapshot_hash,
    }
    identity["identity_snapshot_hash"] = _hash(identity)
    return identity


def _measurement_contract() -> dict[str, Any]:
    return {
        "contract_version": MEASUREMENT_CONTRACT_VERSION,
        "metrics": {
            "brand_mention_rate": "brand_mention.run_level.explicit_identity.v1",
            "brand_option_rate": f"brand_option.run_level.{V2_ANSWER_SCHEMA_VERSION}",
            "brand_recommendation_rate": f"brand_recommendation.run_level.{V2_ANSWER_SCHEMA_VERSION}",
            "target_brand_official_reference_rate": f"target_official_reference.run_level.{CANONICALIZATION_VERSION}",
            "published_url_reference_rate": f"published_url_reference.run_level.{CANONICALIZATION_VERSION}",
        },
        "counting_unit": "RUN",
        "zero_denominator": "NULL",
        "causal_conclusion": False,
    }


def create_retest(
    db: Session,
    *,
    project_id: int,
    prompt_id: int,
    confirmation_id: str,
    publication_id: str,
    publication_report_hash: str,
    confirmation_snapshot_hash: str,
    idempotency_key: str,
    sample_count: int | None,
    measurement_identity: dict[str, Any] | None,
) -> tuple[SinglePromptRetestExecution, bool]:
    chain = _exact_chain(
        db,
        project_id=project_id,
        prompt_id=prompt_id,
        confirmation_id=confirmation_id,
        publication_id=publication_id,
    )
    if chain["publication"].report_hash != publication_report_hash or chain["confirmation"].confirmation_snapshot_hash != confirmation_snapshot_hash:
        raise HTTPException(status_code=409, detail="确认或发布记录版本已变化，请重新加载精确版本")
    strategy_row = db.query(SinglePromptStrategyExecution).filter_by(strategy_id=chain["proposal"].strategy_id).one_or_none()
    if not strategy_row:
        raise HTTPException(status_code=409, detail="发布记录引用的历史策略身份缺失")
    chain["strategy"] = strategy_row
    identity = _measurement_identity(chain, measurement_identity)
    contract = _measurement_contract()
    baseline = chain["baseline"]
    baseline_plan = baseline.get("sampling_configuration") or {}
    raw = chain["baseline_raw"]
    prompt_text = str(raw.get("prompt_text") or "")
    planned_count = int(sample_count or baseline_plan.get("sample_count") or 0)
    if planned_count < 1 or planned_count > 10:
        raise HTTPException(status_code=422, detail="复测采样次数必须在 1-10 之间")
    required_plan = ["platform", "source_type", "adapter", "collection_mode"]
    if any(not baseline_plan.get(key) for key in required_plan):
        raise HTTPException(status_code=409, detail="Baseline 采样计划不完整，不能静默补当前配置")
    plan = {
        "contract_version": RETEST_PLAN_VERSION,
        "raw_output_contract_version": "single-prompt-retest-raw-output-v1",
        "project_id": project_id,
        "prompt_id": prompt_id,
        "prompt_text": prompt_text,
        "prompt_text_hash": _text_hash(prompt_text),
        "sample_count": planned_count,
        "platform": baseline_plan["platform"],
        "source_type": baseline_plan["source_type"],
        "adapter": baseline_plan["adapter"],
        "collection_mode": baseline_plan["collection_mode"],
        "baseline_sampling_plan_hash": baseline.get("sampling_plan_hash"),
    }
    planned_conditions = {
        key: {"value": plan[key], "source": "FROZEN_RETEST_PLAN"}
        for key in ("platform", "source_type", "adapter", "collection_mode", "prompt_text", "sample_count")
    }
    fingerprint = _hash({
        "confirmation_id": confirmation_id,
        "confirmation_snapshot_hash": confirmation_snapshot_hash,
        "publication_id": publication_id,
        "publication_report_hash": publication_report_hash,
        "baseline": baseline,
        "plan": plan,
        "measurement_identity": identity,
        "measurement_contract": contract,
    })
    existing = db.query(SinglePromptRetestExecution).filter_by(
        publication_id=publication_id, idempotency_key=idempotency_key
    ).one_or_none()
    if existing:
        if existing.input_fingerprint != fingerprint:
            raise HTTPException(status_code=409, detail="幂等键已用于不同复测输入")
        return existing, False

    retest_id = f"retest-{uuid4()}"
    analysis, _ = create_frozen_analysis(
        db,
        project_id=project_id,
        prompt_id=prompt_id,
        prompt_text=prompt_text,
        sampling_plan=plan,
        idempotency_key=f"{retest_id}:sampling",
        created_by=f"single_prompt_v2_retest:{retest_id}",
    )
    retest = SinglePromptRetestExecution(
        retest_id=retest_id,
        confirmation_id=confirmation_id,
        publication_id=publication_id,
        proposal_id=chain["proposal"].proposal_id,
        project_id=project_id,
        prompt_id=prompt_id,
        baseline_analysis_id=chain["baseline_analysis"].analysis_id,
        baseline_context_id=chain["baseline_context"].context_id,
        retest_analysis_id=analysis.analysis_id,
        idempotency_key=idempotency_key,
        input_fingerprint=fingerprint,
        confirmation_snapshot_hash=confirmation_snapshot_hash,
        publication_report_hash=publication_report_hash,
        baseline_snapshot_json=_canonical_json(baseline),
        baseline_snapshot_hash=_hash(baseline),
        retest_plan_json=_canonical_json(plan),
        retest_plan_hash=_hash(plan),
        measurement_identity_json=_canonical_json(identity),
        measurement_identity_hash=identity["identity_snapshot_hash"],
        measurement_contract_json=_canonical_json(contract),
        measurement_contract_hash=_hash(contract),
        planned_conditions_json=_canonical_json(planned_conditions),
        authorization_json=_canonical_json({"sampling": "NOT_AUTHORIZED", "semantic_measurement": "NOT_AUTHORIZED"}),
        status="PLANNED",
    )
    db.add(retest)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = db.query(SinglePromptRetestExecution).filter_by(
            publication_id=publication_id, idempotency_key=idempotency_key
        ).one_or_none()
        if concurrent and concurrent.input_fingerprint == fingerprint:
            return concurrent, False
        raise
    db.refresh(retest)
    return retest, True


def start_retest_sampling(db: Session, *, retest_id: str, project_id: int, prompt_id: int) -> SinglePromptRetestExecution:
    retest = db.query(SinglePromptRetestExecution).filter_by(retest_id=retest_id).one_or_none()
    if not retest:
        raise HTTPException(status_code=404, detail="V2 复测不存在")
    if retest.project_id != project_id or retest.prompt_id != prompt_id:
        raise HTTPException(status_code=409, detail="复测身份与 Project/Prompt 不匹配")
    queue_frozen_analysis(db, retest.retest_analysis_id)
    auth = loads(retest.authorization_json, {})
    auth["sampling"] = "EXPLICITLY_AUTHORIZED"
    auth["sampling_authorized_at"] = _iso(datetime.utcnow())
    retest.authorization_json = _canonical_json(auth)
    retest.status = "SAMPLING"
    retest.blocker_code = ""
    retest.blocker_detail = ""
    db.commit()
    db.refresh(retest)
    return retest


def _conditions_from_context(context: SinglePromptAnalysisContext) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw = loads(context.raw_output_json, {})
    rows = []
    unavailable: list[dict[str, Any]] = []
    for run in raw.get("runs") or []:
        observed = run.get("observed_conditions") or {}
        rows.append({"run_id": run.get("run_id"), **observed})
        for key, item in observed.items():
            if isinstance(item, dict) and item.get("source") == "PLATFORM_NOT_EXPOSED":
                unavailable.append({"run_id": run.get("run_id"), "condition": key, "reason": "PLATFORM_NOT_EXPOSED"})
    return {"source": "FROZEN_RETEST_CONTEXT", "runs": rows}, unavailable


def execute_retest_sampling(retest_id: str, *, session_factory: Any = SessionLocal) -> None:
    db = session_factory()
    try:
        retest = db.query(SinglePromptRetestExecution).filter_by(retest_id=retest_id).one_or_none()
        if not retest or retest.status != "SAMPLING":
            return
        analysis_id = retest.retest_analysis_id
    finally:
        db.close()
    execute_analysis(analysis_id, freeze_with_failures=False, session_factory=session_factory)
    db = session_factory()
    try:
        retest = db.query(SinglePromptRetestExecution).filter_by(retest_id=retest_id).one_or_none()
        analysis = db.query(SinglePromptAnalysis).filter_by(analysis_id=analysis_id).one_or_none()
        context = db.query(SinglePromptAnalysisContext).filter_by(analysis_id=analysis_id).one_or_none()
        if not retest or not analysis:
            return
        if context:
            observed, unavailable = _conditions_from_context(context)
            retest.observed_conditions_json = _canonical_json(observed)
            retest.unobservable_conditions_json = _canonical_json(unavailable)
            retest.status = "READY_FOR_MEASUREMENT"
        else:
            retest.status = analysis.status
            retest.blocker_code = analysis.blocker_code
            retest.blocker_detail = analysis.blocker_detail
        db.commit()
    finally:
        db.close()


def retry_retest_sampling(db: Session, *, retest_id: str, project_id: int, prompt_id: int) -> SinglePromptRetestExecution:
    retest = db.query(SinglePromptRetestExecution).filter_by(retest_id=retest_id).one_or_none()
    if not retest or retest.project_id != project_id or retest.prompt_id != prompt_id:
        raise HTTPException(status_code=404, detail="V2 复测不存在")
    analysis = retry_analysis(db, retest.retest_analysis_id)
    retest.status = "SAMPLING"
    retest.blocker_code = ""
    retest.blocker_detail = ""
    db.commit()
    db.refresh(retest)
    assert analysis.analysis_id == retest.retest_analysis_id
    return retest


def finalize_retest_with_failures(db: Session, *, retest_id: str, project_id: int, prompt_id: int) -> SinglePromptRetestExecution:
    retest = db.query(SinglePromptRetestExecution).filter_by(retest_id=retest_id).one_or_none()
    if not retest or retest.project_id != project_id or retest.prompt_id != prompt_id:
        raise HTTPException(status_code=404, detail="V2 复测不存在")
    context = finalize_analysis_with_recorded_failures(db, retest.retest_analysis_id)
    observed, unavailable = _conditions_from_context(context)
    retest.observed_conditions_json = _canonical_json(observed)
    retest.unobservable_conditions_json = _canonical_json(unavailable)
    retest.status = "READY_FOR_MEASUREMENT"
    retest.blocker_code = ""
    retest.blocker_detail = ""
    db.commit()
    db.refresh(retest)
    return retest


def start_semantic_measurement(
    db: Session,
    *,
    retest_id: str,
    project_id: int,
    prompt_id: int,
    authorize_external_llm: bool,
) -> SinglePromptRetestExecution:
    retest = db.query(SinglePromptRetestExecution).filter_by(retest_id=retest_id).one_or_none()
    if not retest or retest.project_id != project_id or retest.prompt_id != prompt_id:
        raise HTTPException(status_code=404, detail="V2 复测不存在")
    context = db.query(SinglePromptAnalysisContext).filter_by(analysis_id=retest.retest_analysis_id).one_or_none()
    if not context:
        raise HTTPException(status_code=409, detail="复测采样结果尚未冻结，不能启动推荐语义测量")
    if retest.status == "SEMANTIC_MEASURING":
        raise HTTPException(status_code=409, detail="推荐语义测量正在执行")
    auth = loads(retest.authorization_json, {})
    auth["semantic_measurement"] = "EXTERNAL_LLM_AUTHORIZED" if authorize_external_llm else "CACHE_ONLY"
    auth["semantic_authorized_at"] = _iso(datetime.utcnow())
    retest.authorization_json = _canonical_json(auth)
    retest.status = "SEMANTIC_MEASURING"
    db.commit()
    db.refresh(retest)
    return retest


def execute_semantic_measurement(
    retest_id: str,
    authorize_external_llm: bool,
    *,
    session_factory: Any = SessionLocal,
) -> None:
    db = session_factory()
    try:
        retest = db.query(SinglePromptRetestExecution).filter_by(retest_id=retest_id).one_or_none()
        if not retest or retest.status != "SEMANTIC_MEASURING":
            return
        context = db.query(SinglePromptAnalysisContext).filter_by(analysis_id=retest.retest_analysis_id).one()
        raw = loads(context.raw_output_json, {})
        identity = loads(retest.measurement_identity_json, {})
        client = DeepSeekClient(thinking_mode="disabled", max_attempts=1, cache_only=not authorize_external_llm)
        usage = {"external_llm_calls": 0, "llm_cache_hits": 0, "external_token_usage": 0}
        answer = _diagnose_answers(
            db,
            raw_output=raw,
            prompt_text=str(raw.get("prompt_text") or ""),
            brand_name=str(identity.get("canonical_brand_name") or ""),
            usage=usage,
            judge=V2AnswerSemanticJudge(client),
            thinking_mode="disabled",
        )
        jobs = answer.get("answer_jobs") or []
        done = [job for job in jobs if str(job.get("status") or "").startswith("DONE")]
        if done and len(done) == len(jobs):
            status = "COMPLETE"
        elif done:
            status = "PARTIAL"
        elif not authorize_external_llm:
            status = "AUTHORIZATION_REQUIRED"
        else:
            status = "FAILED"
        semantic = {
            "contract_version": MEASUREMENT_CONTRACT_VERSION,
            "answer_schema_version": V2_ANSWER_SCHEMA_VERSION,
            "policy": "ALLOW_EXTERNAL" if authorize_external_llm else "CACHE_ONLY",
            "status": status,
            "answer_diagnosis": answer,
            "usage": {
                **usage,
                "provider_external_calls": client.external_call_count,
                "provider_external_tokens": client.external_token_count,
            },
        }
        history = loads(retest.semantic_history_json, [])
        history.append({
            "recorded_at": _iso(datetime.utcnow()),
            "status": status,
            "semantic_result_hash": _hash(semantic),
            "policy": semantic["policy"],
            "external_llm_calls": client.external_call_count,
        })
        retest.semantic_result_json = _canonical_json(semantic)
        retest.semantic_result_hash = _hash(semantic)
        retest.semantic_history_json = _canonical_json(history)
        retest.status = "READY_FOR_COMPARISON"
        retest.blocker_code = "SEMANTIC_AUTHORIZATION_REQUIRED" if status == "AUTHORIZATION_REQUIRED" else ""
        retest.blocker_detail = "推荐率尚缺兼容缓存或单独外部 LLM 授权；其他指标仍可比较。" if status == "AUTHORIZATION_REQUIRED" else ""
        db.commit()
    except Exception as exc:
        db.rollback()
        retest = db.query(SinglePromptRetestExecution).filter_by(retest_id=retest_id).one_or_none()
        if retest:
            retest.status = "READY_FOR_COMPARISON"
            retest.blocker_code = "SEMANTIC_MEASUREMENT_FAILED"
            retest.blocker_detail = str(exc)[:1000]
            db.commit()
    finally:
        db.close()


def _valid_runs(raw: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row for row in raw.get("runs") or []
        if row.get("status") in VALID_RUN_STATUSES and str(row.get("answer_text") or "").strip()
    ]


def _identity_terms(identity: dict[str, Any]) -> list[str]:
    return _dedupe([identity.get("canonical_brand_name") or "", *(identity.get("accepted_aliases") or [])])


def _contains_identity(text: str, terms: list[str]) -> bool:
    for term in terms:
        if not term:
            continue
        if re.fullmatch(r"[A-Za-z0-9_.-]+", term):
            if re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", text, flags=re.IGNORECASE):
                return True
        elif term.casefold() in text.casefold():
            return True
    return False


def _metric_row(
    metric_key: str,
    raw: dict[str, Any],
    evaluable: list[int],
    hits: list[int],
    unevaluated: list[dict[str, Any]],
) -> dict[str, Any]:
    valid = _valid_runs(raw)
    unique_evaluable = sorted(set(evaluable))
    unique_hits = sorted(set(hits) & set(unique_evaluable))
    value = round(len(unique_hits) / len(unique_evaluable), 6) if unique_evaluable else None
    if not unique_evaluable:
        status = "NOT_COMPUTABLE"
    elif unevaluated:
        status = "PARTIAL"
    else:
        status = "COMPLETE"
    return {
        "metric_key": metric_key,
        "planned_count": len(raw.get("runs") or []),
        "valid_raw_count": len(valid),
        "evaluable_run_ids": unique_evaluable,
        "evaluable_count": len(unique_evaluable),
        "hit_run_ids": unique_hits,
        "hit_count": len(unique_hits),
        "unevaluated": unevaluated,
        "unevaluated_count": len(unevaluated),
        "value": value,
        "status": status,
        "counting_unit": "RUN",
    }


def _answer_job_by_hash(answer_diagnosis: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("answer_hash")): row
        for row in (answer_diagnosis or {}).get("answer_jobs") or []
        if row.get("answer_hash")
    }


def measure_frozen_runs(
    *,
    raw: dict[str, Any],
    identity: dict[str, Any],
    answer_diagnosis: dict[str, Any] | None,
    published_url: str,
) -> dict[str, Any]:
    runs = _valid_runs(raw)
    terms = _identity_terms(identity)
    mention_eval = [int(run["run_id"]) for run in runs]
    mention_hits = [int(run["run_id"]) for run in runs if _contains_identity(str(run.get("answer_text") or ""), terms)]

    jobs = _answer_job_by_hash(answer_diagnosis)
    events_by_run: dict[int, list[dict[str, Any]]] = {}
    for event in (answer_diagnosis or {}).get("events") or []:
        events_by_run.setdefault(int(event.get("run_id") or 0), []).append(event)
    recommendation_eval: list[int] = []
    recommendation_hits: list[int] = []
    recommendation_unknown: list[dict[str, Any]] = []
    option_eval: list[int] = []
    option_hits: list[int] = []
    option_unknown: list[dict[str, Any]] = []
    for run in runs:
        run_id = int(run["run_id"])
        answer_hash = hashlib.sha256(str(run.get("answer_text") or "").encode("utf-8")).hexdigest()
        job = jobs.get(answer_hash)
        eligible_events = [
            event for event in events_by_run.get(run_id, [])
            if event.get("fact_consumption_eligible") is True and _contains_identity(str(event.get("entity_text") or ""), terms)
        ]
        uncertain = any(event.get("fact_consumption_eligible") is not True
                        and _contains_identity(str(event.get("entity_text") or ""), terms)
                        for event in events_by_run.get(run_id, []))
        if any(event.get("effective_speech_act") in {"INCLUDE_AS_OPTION", "RECOMMEND"} for event in eligible_events):
            option_eval.append(run_id); option_hits.append(run_id)
        elif job and job.get("status") in {"DONE", "DONE_ZERO_EVENTS"} and not uncertain:
            option_eval.append(run_id)
        else:
            option_unknown.append({"run_id": run_id, "reason": "ANSWER_SEMANTIC_UNCERTAIN" if uncertain else "ANSWER_SEMANTIC_NOT_EVALUATED"})
        if any(event.get("effective_speech_act") == "RECOMMEND" for event in eligible_events):
            recommendation_eval.append(run_id)
            recommendation_hits.append(run_id)
        elif job and job.get("status") in {"DONE", "DONE_ZERO_EVENTS"} and not uncertain:
            recommendation_eval.append(run_id)
        else:
            recommendation_unknown.append({
                "run_id": run_id,
                "reason": "ANSWER_SEMANTIC_UNCERTAIN" if uncertain else "ANSWER_SEMANTIC_NOT_EVALUATED" if not job else str(job.get("status") or "ANSWER_SEMANTIC_UNCERTAIN"),
            })

    official_domains = set(identity.get("official_domains") or [])
    official_urls = set(identity.get("official_urls") or [])
    published_canonical = canonicalize_url(published_url)
    official_eval: list[int] = []
    official_hits: list[int] = []
    official_unknown: list[dict[str, Any]] = []
    published_eval: list[int] = []
    published_hits: list[int] = []
    published_unknown: list[dict[str, Any]] = []
    for run in runs:
        run_id = int(run["run_id"])
        refs = run.get("references") or []
        complete = run.get("reference_complete") is True
        canonical_refs = {canonicalize_url(str(ref.get("canonical_url") or ref.get("url") or "")) for ref in refs}
        domains = {
            _normalize_domain(str(ref.get("domain") or urlparse(
                canonicalize_url(str(ref.get("canonical_url") or ref.get("url") or ""))
            ).hostname or ""))
            for ref in refs
        }
        official_hit = bool(official_urls & canonical_refs or official_domains & domains)
        if not official_domains and not official_urls:
            official_unknown.append({"run_id": run_id, "reason": "OFFICIAL_IDENTITY_NOT_PROVIDED"})
        elif official_hit:
            official_eval.append(run_id); official_hits.append(run_id)
        elif complete:
            official_eval.append(run_id)
        else:
            official_unknown.append({"run_id": run_id, "reason": "REFERENCE_OBSERVATION_INCOMPLETE"})
        published_hit = bool(published_canonical and published_canonical in canonical_refs)
        if not published_canonical:
            published_unknown.append({"run_id": run_id, "reason": "PUBLISHED_URL_IDENTITY_UNAVAILABLE"})
        elif published_hit:
            published_eval.append(run_id); published_hits.append(run_id)
        elif complete:
            published_eval.append(run_id)
        else:
            published_unknown.append({"run_id": run_id, "reason": "REFERENCE_OBSERVATION_INCOMPLETE"})

    return {
        "contract_version": MEASUREMENT_CONTRACT_VERSION,
        "raw_output_hash": _hash(raw),
        "measurement_identity_hash": identity.get("identity_snapshot_hash"),
        "metrics": {
            "brand_mention_rate": _metric_row("brand_mention_rate", raw, mention_eval, mention_hits, []),
            "brand_option_rate": _metric_row("brand_option_rate", raw, option_eval, option_hits, option_unknown),
            "brand_recommendation_rate": _metric_row("brand_recommendation_rate", raw, recommendation_eval, recommendation_hits, recommendation_unknown),
            "target_brand_official_reference_rate": _metric_row("target_brand_official_reference_rate", raw, official_eval, official_hits, official_unknown),
            "published_url_reference_rate": _metric_row("published_url_reference_rate", raw, published_eval, published_hits, published_unknown),
        },
    }


def _baseline_semantics(db: Session, retest: SinglePromptRetestExecution) -> dict[str, Any] | None:
    proposal = db.query(SinglePromptExecutionProposal).filter_by(proposal_id=retest.proposal_id).one()
    strategy = db.query(SinglePromptStrategyExecution).filter_by(strategy_id=proposal.strategy_id).one()
    result = db.query(SinglePromptDiagnosisResult).filter_by(
        diagnosis_id=strategy.diagnosis_id,
        result_version=strategy.diagnosis_result_version,
    ).one_or_none()
    if not result or result.output_hash != strategy.diagnosis_result_hash:
        return None
    return (loads(result.output_json, {}).get("answer_diagnosis") or None)


def _planned_compatibility(baseline: dict[str, Any], plan: dict[str, Any]) -> tuple[bool, list[str]]:
    baseline_plan = baseline.get("sampling_configuration") or {}
    reasons = []
    for key in ("platform", "source_type", "adapter", "collection_mode", "prompt_text"):
        if baseline_plan.get(key) != plan.get(key):
            reasons.append(f"{key.upper()}_CHANGED")
    return not reasons, reasons


def _observed_retest_compatibility(plan: dict[str, Any], retest_raw: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    conflicts: set[str] = set()
    unknown: set[str] = set()
    expected = {
        "platform": plan.get("platform"),
        "source_type": plan.get("source_type"),
        "adapter": plan.get("adapter"),
        "collection_mode": plan.get("collection_mode"),
        "original_query": plan.get("prompt_text"),
    }
    for run in _valid_runs(retest_raw):
        observed = run.get("observed_conditions") or {}
        for key, expected_value in expected.items():
            item = observed.get(key)
            if not isinstance(item, dict) or item.get("source") != "RUN_CAPTURE":
                unknown.add(f"RETEST_{key.upper()}_NOT_OBSERVED")
                continue
            if item.get("value") != expected_value:
                conflicts.add(f"RETEST_{key.upper()}_MISMATCH")
        query_item = observed.get("original_query") or {}
        if query_item.get("source") == "RUN_CAPTURE" and _text_hash(str(query_item.get("value") or "")) != plan.get("prompt_text_hash"):
            conflicts.add("RETEST_PROMPT_HASH_MISMATCH")
    return not conflicts, sorted(conflicts), sorted(unknown)


def _temporal_order(chain: dict[str, Any], baseline_raw: dict[str, Any], retest_raw: dict[str, Any]) -> dict[str, Any]:
    published_raw = chain["report"].get("published_at")
    published = _parse_aware(published_raw)
    baseline_times = [_parse_aware(row.get("finished_at")) for row in _valid_runs(baseline_raw)]
    retest_times = [_parse_aware(row.get("started_at")) for row in _valid_runs(retest_raw)]
    if not published or not baseline_times or not retest_times or any(value is None for value in [*baseline_times, *retest_times]):
        return {"verified": False, "status": "TEMPORAL_ORDER_UNVERIFIED", "published_at": published_raw}
    verified = max(baseline_times) < published < min(retest_times)
    return {
        "verified": verified,
        "status": "VERIFIED" if verified else "TEMPORAL_ORDER_INVALID",
        "published_at": published_raw,
        "baseline_latest_at": max(baseline_times).isoformat(),
        "retest_earliest_at": min(retest_times).isoformat(),
    }


def create_comparison(db: Session, *, retest_id: str, project_id: int, prompt_id: int) -> tuple[SinglePromptComparisonResult, bool]:
    retest = db.query(SinglePromptRetestExecution).filter_by(retest_id=retest_id).one_or_none()
    if not retest or retest.project_id != project_id or retest.prompt_id != prompt_id:
        raise HTTPException(status_code=404, detail="V2 复测不存在")
    baseline_context = db.query(SinglePromptAnalysisContext).filter_by(context_id=retest.baseline_context_id).one()
    retest_context = db.query(SinglePromptAnalysisContext).filter_by(analysis_id=retest.retest_analysis_id).one_or_none()
    if not retest_context:
        raise HTTPException(status_code=409, detail="复测采样尚未形成不可变结果，不能比较")
    baseline_raw = loads(baseline_context.raw_output_json, {})
    retest_raw = loads(retest_context.raw_output_json, {})
    baseline_snapshot = loads(retest.baseline_snapshot_json, {})
    if _hash(baseline_snapshot) != retest.baseline_snapshot_hash or _hash(baseline_raw) != baseline_context.raw_output_hash:
        raise HTTPException(status_code=409, detail="固定 Baseline 快照或原始结果 Hash 不匹配")
    identity = loads(retest.measurement_identity_json, {})
    if _hash({key: value for key, value in identity.items() if key != "identity_snapshot_hash"}) != identity.get("identity_snapshot_hash"):
        raise HTTPException(status_code=409, detail="测量身份快照 Hash 不匹配")
    publication = db.query(SinglePromptPublicationRecord).filter_by(publication_id=retest.publication_id).one()
    chain = _exact_chain(
        db, project_id=project_id, prompt_id=prompt_id,
        confirmation_id=retest.confirmation_id, publication_id=retest.publication_id,
    )
    published_url = str(chain["report"].get("actual_url") or "")
    baseline_measurement = measure_frozen_runs(
        raw=baseline_raw,
        identity=identity,
        answer_diagnosis=_baseline_semantics(db, retest),
        published_url=published_url,
    )
    semantic = loads(retest.semantic_result_json, {})
    retest_measurement = measure_frozen_runs(
        raw=retest_raw,
        identity=identity,
        answer_diagnosis=(semantic.get("answer_diagnosis") or None),
        published_url=published_url,
    )
    plan = loads(retest.retest_plan_json, {})
    plan_ok, plan_reasons = _planned_compatibility(baseline_snapshot, plan)
    observed_ok, observed_conflicts, observed_unknown = _observed_retest_compatibility(plan, retest_raw)
    temporal = _temporal_order(chain, baseline_raw, retest_raw)
    comparisons: dict[str, Any] = {}
    limitations: list[dict[str, Any]] = []
    if not temporal["verified"]:
        limitations.append({"code": temporal["status"], "detail": "发布时间与两侧采样时间无法形成已验证的前后顺序。"})
    if publication.conformance in {"OUTSIDE_CONFIRMED_SCOPE", "NOT_EVALUABLE"}:
        limitations.append({"code": "PUBLICATION_NOT_CONFIRMED_PLAN_EQUIVALENT", "detail": publication.conformance})
    if observed_unknown:
        limitations.append({
            "code": "OBSERVED_CONDITIONS_INCOMPLETE",
            "detail": observed_unknown,
        })
    for code in observed_conflicts:
        limitations.append({"code": code, "detail": "复测实际捕获条件与冻结计划冲突。"})
    if any(not (run.get("observed_conditions") or {}) for run in _valid_runs(baseline_raw)):
        limitations.append({
            "code": "BASELINE_ACTUAL_CONDITIONS_PLAN_DECLARED_ONLY",
            "detail": "历史 Baseline 未保存完整逐 Run 实际条件，仅保留冻结计划声明。",
        })
    limitations.extend(loads(retest.unobservable_conditions_json, []))
    for metric_key, baseline_metric in baseline_measurement["metrics"].items():
        retest_metric = retest_measurement["metrics"][metric_key]
        comparable = plan_ok and observed_ok and baseline_metric["value"] is not None and retest_metric["value"] is not None
        reasons = [*plan_reasons, *observed_conflicts]
        if baseline_metric["value"] is None:
            reasons.append("BASELINE_NOT_COMPUTABLE")
        if retest_metric["value"] is None:
            reasons.append("RETEST_NOT_COMPUTABLE")
        delta = round((retest_metric["value"] - baseline_metric["value"]) * 100, 4) if comparable else None
        comparisons[metric_key] = {
            "comparison_eligible": comparable,
            "comparison_mode": "PRE_POST_DESCRIPTIVE" if comparable and temporal["verified"] else "TWO_SAMPLE_DESCRIPTIVE" if comparable else "NOT_COMPARABLE",
            "delta_percentage_points": delta,
            "reasons": reasons + ([] if temporal["verified"] else [temporal["status"]]),
            "causal_conclusion": None,
        }
    comparison = {
        "contract_version": COMPARISON_CONTRACT_VERSION,
        "retest_id": retest_id,
        "publication": {
            "publication_id": publication.publication_id,
            "report_hash": publication.report_hash,
            "publication_status": publication.publication_status,
            "conformance": publication.conformance,
            "system_verified": False,
        },
        "temporal_order": temporal,
        "planned_conditions_match": plan_ok,
        "planned_condition_differences": plan_reasons,
        "observed_retest_conditions_match": observed_ok,
        "observed_condition_conflicts": observed_conflicts,
        "observed_condition_unknown": observed_unknown,
        "metrics": comparisons,
        "limitations": limitations,
        "conclusion_policy": "OBSERVED_CHANGE_ONLY_NO_CAUSAL_OR_EFFECTIVENESS_CONCLUSION",
    }
    input_hash = _hash({
        "baseline_raw_hash": baseline_context.raw_output_hash,
        "retest_raw_hash": retest_context.raw_output_hash,
        "semantic_result_hash": retest.semantic_result_hash,
        "identity_hash": retest.measurement_identity_hash,
        "measurement_contract_hash": retest.measurement_contract_hash,
        "publication_report_hash": retest.publication_report_hash,
    })
    existing = db.query(SinglePromptComparisonResult).filter_by(retest_id=retest_id, input_hash=input_hash).one_or_none()
    if existing:
        return existing, False
    version_number = db.query(SinglePromptComparisonResult).filter_by(retest_id=retest_id).count() + 1
    output_hash = _hash({"baseline": baseline_measurement, "retest": retest_measurement, "comparison": comparison})
    result = SinglePromptComparisonResult(
        result_version=f"comparison-v{version_number}:{output_hash[:16]}",
        retest_id=retest_id,
        version_number=version_number,
        input_hash=input_hash,
        baseline_context_id=baseline_context.context_id,
        retest_context_id=retest_context.context_id,
        baseline_measurement_json=_canonical_json(baseline_measurement),
        retest_measurement_json=_canonical_json(retest_measurement),
        comparison_json=_canonical_json(comparison),
        output_hash=output_hash,
        limitations_json=_canonical_json(limitations),
    )
    db.add(result)
    db.flush()
    retest.active_comparison_version = result.result_version
    retest.status = "COMPARISON_READY"
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = db.query(SinglePromptComparisonResult).filter_by(retest_id=retest_id, input_hash=input_hash).one_or_none()
        if concurrent:
            return concurrent, False
        raise
    db.refresh(result)
    return result, True


def get_retest_status(db: Session, *, retest_id: str, project_id: int, prompt_id: int) -> dict[str, Any]:
    retest = db.query(SinglePromptRetestExecution).filter_by(retest_id=retest_id).one_or_none()
    if not retest:
        raise HTTPException(status_code=404, detail="V2 复测不存在")
    if retest.project_id != project_id or retest.prompt_id != prompt_id:
        raise HTTPException(status_code=409, detail="复测身份与 Project/Prompt 不匹配")
    analysis_status = get_analysis_status(db, retest.retest_analysis_id)
    effective_status = retest.status
    if retest.status == "SAMPLING" and analysis_status["sampling"]["status"] not in {"QUEUED", "COLLECTING"}:
        effective_status = analysis_status["sampling"]["status"]
    result = None
    if retest.active_comparison_version:
        row = db.query(SinglePromptComparisonResult).filter_by(result_version=retest.active_comparison_version).one_or_none()
        if row:
            result = {
                "result_version": row.result_version,
                "version_number": row.version_number,
                "output_hash": row.output_hash,
                "baseline_measurement": loads(row.baseline_measurement_json, {}),
                "retest_measurement": loads(row.retest_measurement_json, {}),
                "comparison": loads(row.comparison_json, {}),
                "limitations": loads(row.limitations_json, []),
                "created_at": _iso(row.created_at),
            }
    if effective_status == "PLANNED":
        actions = ["START_RETEST_SAMPLING"]
    elif effective_status == "INTERRUPTED" and (analysis_status.get("blocker") or {}).get("code") == "PARTIAL_RETEST_RETRY_AVAILABLE":
        actions = ["RETRY_RETEST_SAMPLING", "FINALIZE_RETEST_WITH_FAILURES"]
    elif effective_status in {"FAILED", "INTERRUPTED"}:
        actions = ["RETRY_RETEST_SAMPLING"]
    elif analysis_status.get("context_id"):
        actions = ["START_SEMANTIC_MEASUREMENT", "CREATE_COMPARISON"]
    else:
        actions = ["VIEW_STATUS"]
    return {
        "contract_version": RETEST_CONTRACT_VERSION,
        "retest": {
            "retest_id": retest.retest_id,
            "confirmation_id": retest.confirmation_id,
            "publication_id": retest.publication_id,
            "proposal_id": retest.proposal_id,
            "project_id": retest.project_id,
            "prompt_id": retest.prompt_id,
            "baseline_analysis_id": retest.baseline_analysis_id,
            "baseline_context_id": retest.baseline_context_id,
            "retest_analysis_id": retest.retest_analysis_id,
            "input_fingerprint": retest.input_fingerprint,
            "status": effective_status,
            "retest_plan_hash": retest.retest_plan_hash,
            "measurement_identity_hash": retest.measurement_identity_hash,
            "measurement_contract_hash": retest.measurement_contract_hash,
        },
        "baseline": loads(retest.baseline_snapshot_json, {}),
        "retest_plan": loads(retest.retest_plan_json, {}),
        "measurement_identity": loads(retest.measurement_identity_json, {}),
        "measurement_contract": loads(retest.measurement_contract_json, {}),
        "planned_conditions": loads(retest.planned_conditions_json, {}),
        "observed_conditions": loads(retest.observed_conditions_json, {}),
        "unobservable_conditions": loads(retest.unobservable_conditions_json, []),
        "authorization": loads(retest.authorization_json, {}),
        "semantic_measurement": loads(retest.semantic_result_json, {}),
        "sampling": analysis_status,
        "comparison_result": result,
        "blocker": {"code": retest.blocker_code, "detail": retest.blocker_detail} if retest.blocker_code else None,
        "allowed_actions": actions,
        "boundary": {
            "external_sampling_started": loads(retest.authorization_json, {}).get("sampling") == "EXPLICITLY_AUTHORIZED",
            "external_llm_calls": int((loads(retest.semantic_result_json, {}).get("usage") or {}).get("provider_external_calls") or 0),
            "publication_system_verified": False,
            "causal_conclusion": False,
            "strategy_current_required": False,
        },
    }
