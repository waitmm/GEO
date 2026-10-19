"""Server-side freeze and revalidation of the exact Agent input scope."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (
    BrowserMonitorRun,
    SinglePromptAnalysis,
    SinglePromptAnalysisContext,
    SinglePromptCitationManifest,
    SinglePromptPreparedSourceSnapshot,
    SinglePromptSourceCompletionManifest,
    SinglePromptSourceDisposition,
    SinglePromptSourcePreparation,
)
from app.modules.single_prompt_v2.context_provider import select_context
from app.modules.single_prompt_v2.delivery_text import digest, text_digest
from app.modules.single_prompt_v2.service import (
    _run_input_fingerprint,
    _snapshot_run_rows,
    _validate_analysis_configuration,
    _validate_analysis_prompt_version,
)
from app.modules.single_prompt_v2.truth_corrections import project_truths
from app.services.serialization import loads


VALID_ANSWER_STATUSES = frozenset({"success", "completed"})


def _conflict(code: str, message: str) -> None:
    raise HTTPException(status_code=409, detail={"code": code, "message": message})


def _matches_frozen_run(frozen: dict[str, Any], live: dict[str, Any]) -> bool:
    """Compare at the immutable snapshot's schema version.

    Later migrations may add live Run fields, but can neither remove nor change
    a field that the historical snapshot actually froze.
    """
    if not set(frozen).issubset(live):
        return False
    return _run_input_fingerprint(frozen) == _run_input_fingerprint(
        {key: live[key] for key in frozen}
    )


def _exact_citation_manifest(
    db: Session, *, analysis: SinglePromptAnalysis, context: SinglePromptAnalysisContext,
    manifest_id: str | None, manifest_hash: str | None,
) -> SinglePromptCitationManifest | None:
    query = db.query(SinglePromptCitationManifest).filter_by(
        analysis_id=analysis.analysis_id, context_id=context.context_id,
        project_id=analysis.project_id, prompt_id=analysis.prompt_id,
    )
    if manifest_id:
        row = query.filter_by(manifest_id=manifest_id).one_or_none()
        if not row:
            _conflict("CITATION_MANIFEST_SCOPE_MISMATCH", "Citation manifest 不属于冻结 Analysis scope")
        if manifest_hash != row.payload_hash:
            _conflict("CITATION_MANIFEST_HASH_MISMATCH", "Citation manifest hash 不匹配")
        return row
    rows = query.all()
    if len(rows) > 1:
        _conflict("CITATION_MANIFEST_AMBIGUOUS", "存在多个 Citation manifest，必须显式选择版本")
    return rows[0] if rows else None


def _exact_completion(
    db: Session, *, citation: SinglePromptCitationManifest | None,
    manifest_id: str | None, manifest_hash: str | None,
) -> SinglePromptSourceCompletionManifest | None:
    if not manifest_id:
        return None
    if not citation:
        _conflict("COMPLETION_WITHOUT_CITATION_MANIFEST", "Source completion 缺少 Citation manifest 锚点")
    row = db.query(SinglePromptSourceCompletionManifest).filter_by(
        manifest_id=manifest_id, citation_manifest_id=citation.manifest_id,
        analysis_id=citation.analysis_id, context_id=citation.context_id,
    ).one_or_none()
    if not row:
        _conflict("SOURCE_COMPLETION_SCOPE_MISMATCH", "Source completion 不属于冻结 Citation scope")
    if manifest_hash != row.payload_hash:
        _conflict("SOURCE_COMPLETION_HASH_MISMATCH", "Source completion hash 不匹配")
    return row


def freeze_scope(
    db: Session, *, project_id: int, prompt_id: int, analysis_id: str, context_id: str,
    citation_manifest_id: str | None = None, citation_manifest_hash: str | None = None,
    completion_manifest_id: str | None = None, completion_manifest_hash: str | None = None,
    brand_context_version_id: str | None = None,
) -> tuple[dict[str, Any], str]:
    analysis = db.query(SinglePromptAnalysis).filter_by(analysis_id=analysis_id).one_or_none()
    if not analysis:
        raise HTTPException(404, "Analysis 不存在")
    if analysis.project_id != project_id or analysis.prompt_id != prompt_id:
        _conflict("ANALYSIS_SCOPE_MISMATCH", "Analysis 与 Project/Prompt 不匹配")
    context = db.query(SinglePromptAnalysisContext).filter_by(
        context_id=context_id, analysis_id=analysis_id,
        project_id=project_id, prompt_id=prompt_id,
    ).one_or_none()
    if not context:
        _conflict("ANALYSIS_CONTEXT_SCOPE_MISMATCH", "Analysis Context 身份不匹配")

    plan = loads(analysis.sampling_plan_json, {})
    configuration = _validate_analysis_configuration(db, analysis, plan)
    prompt_version = _validate_analysis_prompt_version(db, analysis, plan)
    run_scope = loads(context.run_scope_json, {})
    raw = loads(context.raw_output_json, {})
    if digest(run_scope) != context.run_scope_hash or digest(raw) != context.raw_output_hash:
        _conflict("FROZEN_CONTEXT_HASH_MISMATCH", "冻结 Context 内容 hash 不匹配")
    if raw.get("analysis_id") != analysis_id or raw.get("project_id") != project_id or raw.get("prompt_id") != prompt_id:
        _conflict("RAW_OUTPUT_SCOPE_MISMATCH", "冻结 raw output 身份不匹配")
    if raw.get("prompt_text") != analysis.prompt_text_snapshot or raw.get("sampling_plan") != plan:
        _conflict("RAW_OUTPUT_BINDING_MISMATCH", "冻结 raw output 与 Prompt/Plan 绑定不匹配")

    runs = raw.get("runs") if isinstance(raw.get("runs"), list) else []
    run_ids = [int(row.get("run_id")) for row in runs]
    if run_ids != [int(value) for value in run_scope.get("run_ids", [])] or len(run_ids) != len(set(run_ids)):
        _conflict("RUN_SCOPE_MISMATCH", "冻结 run_ids 与 Context scope 不一致")
    rows = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.id.in_(run_ids)).all() if run_ids else []
    by_id = {row.id: row for row in rows}
    if set(by_id) != set(run_ids) or any(row.project_id != project_id or row.prompt_id != prompt_id for row in rows):
        _conflict("RUN_OWNERSHIP_MISMATCH", "Run 不存在或跨越 Project/Prompt")
    live_snapshots = _snapshot_run_rows(db, [by_id[value] for value in run_ids]) if run_ids else []
    if len(live_snapshots) != len(runs):
        _conflict("RUN_SNAPSHOT_MISMATCH", "Run 快照数量变化")
    expected_fingerprints = plan.get("run_fingerprints") or run_scope.get("run_fingerprints") or {}
    for frozen, live in zip(runs, live_snapshots):
        if int(frozen["run_id"]) != int(live["run_id"]):
            _conflict("RUN_SNAPSHOT_ORDER_MISMATCH", "Run 快照顺序变化")
        # Historical immutable contexts cannot contain additive runtime fields
        # introduced by later migrations (for example physical-attempt lineage).
        # Revalidate every field owned by that frozen schema while ignoring only
        # fields absent from the historical snapshot.  Missing or changed frozen
        # fields still fail closed.
        if not set(frozen).issubset(live):
            _conflict("RUN_SNAPSHOT_SCHEMA_MISMATCH", f"Run {frozen['run_id']} 缺少冻结字段")
        if not _matches_frozen_run(frozen, live):
            _conflict("RUN_SNAPSHOT_DRIFT", f"Run {frozen['run_id']} 已偏离冻结快照")
        expected = expected_fingerprints.get(str(frozen["run_id"]), expected_fingerprints.get(int(frozen["run_id"])))
        if expected and _run_input_fingerprint(frozen) != expected:
            _conflict("RUN_FINGERPRINT_MISMATCH", "冻结 Run fingerprint 不匹配")

    citation = _exact_citation_manifest(
        db, analysis=analysis, context=context, manifest_id=citation_manifest_id,
        manifest_hash=citation_manifest_hash,
    )
    citation_payload = loads(citation.payload_json, {}) if citation else {}
    if citation and (digest(citation_payload) != citation.payload_hash or citation.raw_output_hash != context.raw_output_hash):
        _conflict("CITATION_MANIFEST_CONTENT_MISMATCH", "Citation manifest 内容或 raw hash 不匹配")
    completion = _exact_completion(
        db, citation=citation, manifest_id=completion_manifest_id, manifest_hash=completion_manifest_hash,
    )
    completion_payload = loads(completion.payload_json, {}) if completion else {}
    if completion and digest(completion_payload) != completion.payload_hash:
        _conflict("SOURCE_COMPLETION_CONTENT_MISMATCH", "Source completion 内容 hash 不匹配")

    preparation = None
    if citation:
        preparation = db.query(SinglePromptSourcePreparation).filter_by(
            citation_manifest_id=citation.manifest_id, analysis_id=analysis_id, context_id=context_id,
        ).one_or_none()
    dispositions = []
    snapshots = []
    if preparation:
        for row in db.query(SinglePromptSourceDisposition).filter_by(
                preparation_id=preparation.preparation_id).order_by(SinglePromptSourceDisposition.source_key):
            dispositions.append({
                "source_key": row.source_key, "canonical_url": row.canonical_url,
                "state": row.state, "active_snapshot_id": row.active_snapshot_id,
                "failure_code": row.failure_code, "failure_detail": row.failure_detail,
                "waiver_reason": row.waiver_reason,
            })
        for row in db.query(SinglePromptPreparedSourceSnapshot).filter_by(
                preparation_id=preparation.preparation_id,
                citation_manifest_id=citation.manifest_id).order_by(SinglePromptPreparedSourceSnapshot.snapshot_id):
            passages = loads(row.passages_json, [])
            if digest(passages) != row.passages_hash or text_digest(row.clean_text) != row.content_hash:
                _conflict("SOURCE_SNAPSHOT_HASH_MISMATCH", f"Source snapshot {row.snapshot_id} hash 不匹配")
            snapshots.append({
                "snapshot_id": row.snapshot_id, "source_key": row.source_key,
                "canonical_url": row.canonical_url, "title": row.title,
                "content_hash": row.content_hash, "clean_text": row.clean_text,
                "passages": passages, "passages_hash": row.passages_hash,
                "coverage_scope": row.coverage_scope, "acquisition_method": row.acquisition_method,
            })

    brand_context = select_context(
        db, project_id=project_id, context_version_id=brand_context_version_id,
        query=analysis.prompt_text_snapshot,
    )
    truths = project_truths(db, project_id)
    valid_answers = [row for row in runs if row.get("status") in VALID_ANSWER_STATUSES and str(row.get("answer_text") or "").strip()]
    failed_answers = [row for row in runs if row not in valid_answers]
    input_scope = {
        "contract_version": "geo.agent.input-scope.v1",
        "identity": {
            "project_id": project_id, "prompt_id": prompt_id, "analysis_id": analysis_id,
            "context_id": context_id, "raw_output_hash": context.raw_output_hash,
            "run_scope_hash": context.run_scope_hash, "sampling_plan_hash": analysis.sampling_plan_hash,
        },
        "prompt": {"text": analysis.prompt_text_snapshot, "version": prompt_version},
        "project_configuration": configuration,
        "run_scope": run_scope,
        "runs": runs,
        "citation_manifest": ({"manifest_id": citation.manifest_id, "payload_hash": citation.payload_hash,
                               "payload": citation_payload} if citation else None),
        "source_completion": ({"manifest_id": completion.manifest_id, "payload_hash": completion.payload_hash,
                               "status": completion.status, "payload": completion_payload} if completion else None),
        "source_dispositions": dispositions,
        "source_snapshots": snapshots,
        "brand_context": brand_context,
        "product_truth": {"facts": truths, "set_hash": digest(truths)},
        "monitor_metrics": {
            "run_count": len(runs), "valid_answer_count": len(valid_answers),
            "failed_answer_count": len(failed_answers),
            "citation_occurrence_count": sum(len(row.get("references") or []) for row in runs),
            "brand_mentioned_count": sum(bool(row.get("brand_mentioned")) for row in runs),
        },
    }
    if snapshots or truths:
        planned_level = "L2_PARTIALLY_GROUNDED"
        evidence_qualification = "PARTIALLY_GROUNDED_FOR_SELECTED_BLOCKS"
        delivery_type = "BOUNDED_DRAFT"
        public_claim_eligibility = "VERIFY_FIRST"
    elif valid_answers:
        planned_level = "L3_ACTIONABLE_WITHOUT_FACT_CLAIMS"
        evidence_qualification = "SOURCE_UNAVAILABLE" if dispositions else "NOT_EVALUATED"
        delivery_type = "INSTRUCTION_ONLY_DRAFT"
        public_claim_eligibility = "NOT_CONSUMABLE"
    else:
        planned_level = "L4_RECOVERY_PACKAGE"
        evidence_qualification = "INPUT_UNAVAILABLE"
        delivery_type = "RECOVERY_ACTIONS"
        public_claim_eligibility = "NOT_CONSUMABLE"
    qualification = {
        "contract_version": "SC-GRADED-DELIVERY-001@1.0.0",
        "valid_answer_count": len(valid_answers),
        "source_snapshot_count": len(snapshots),
        "truth_fact_count": len(truths),
        "brand_context_mode": brand_context.get("mode", "EMPTY"),
        "planned_delivery_level": planned_level,
        "product_outcome": "NONE",
        "delivery_type": delivery_type,
        "evidence_qualification": evidence_qualification,
        "public_claim_eligibility": public_claim_eligibility,
        "publication_eligibility": (
            "NOT_CONSUMABLE" if planned_level == "L4_RECOVERY_PACKAGE" else "VERIFY_FIRST"
        ),
    }
    input_scope["qualification"] = qualification
    return input_scope, digest(qualification)


def revalidate_frozen_scope(db: Session, run) -> dict[str, Any]:
    scope = loads(run.input_scope_json, {})
    execution = loads(run.agent_execution_json, {})
    if digest(scope) != run.input_scope_hash or digest(execution) != run.agent_execution_hash:
        _conflict("AGENT_FROZEN_IDENTITY_MISMATCH", "Agent 冻结输入或执行契约 hash 不匹配")
    if digest(scope.get("qualification")) != run.qualification_hash:
        _conflict("AGENT_QUALIFICATION_HASH_MISMATCH", "Agent qualification hash 不匹配")
    identity = scope.get("identity") or {}
    if identity != {
        "project_id": run.project_id, "prompt_id": run.prompt_id, "analysis_id": run.analysis_id,
        "context_id": run.context_id, "raw_output_hash": identity.get("raw_output_hash"),
        "run_scope_hash": identity.get("run_scope_hash"), "sampling_plan_hash": identity.get("sampling_plan_hash"),
    }:
        _conflict("AGENT_RUN_SCOPE_MISMATCH", "Agent Run 行与冻结输入 scope 不匹配")
    context = db.query(SinglePromptAnalysisContext).filter_by(
        context_id=run.context_id, analysis_id=run.analysis_id,
        project_id=run.project_id, prompt_id=run.prompt_id,
        raw_output_hash=identity.get("raw_output_hash"), run_scope_hash=identity.get("run_scope_hash"),
    ).one_or_none()
    if not context or digest(loads(context.raw_output_json, {})) != context.raw_output_hash:
        _conflict("AGENT_CONTEXT_DRIFT", "Agent 冻结 Context 已失配")
    raw = loads(context.raw_output_json, {})
    run_scope = loads(context.run_scope_json, {})
    if scope.get("runs") != raw.get("runs") or scope.get("run_scope") != run_scope:
        _conflict("AGENT_SCOPE_CONTENT_DRIFT", "Agent scope 中的 Run 快照已偏离冻结 Context")
    if identity.get("sampling_plan_hash") != db.query(SinglePromptAnalysis).filter_by(
            analysis_id=run.analysis_id, project_id=run.project_id, prompt_id=run.prompt_id).one().sampling_plan_hash:
        _conflict("AGENT_SAMPLING_PLAN_DRIFT", "Agent scope 的采样计划 hash 已偏离 Analysis")
    return scope
