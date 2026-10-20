from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import sessionmaker

from app.models import AgentResultFeedback
from app.modules.agent_experiment.api import (
    AgentAuthorization,
    authorize_agent_experiment,
    read_agent_capabilities,
)
from app.modules.agent_experiment.evidence_pack import build_evidence_pack
from app.modules.agent_experiment.runner import execute_agent_run
from app.modules.agent_experiment.service import (
    add_result_feedback,
    create_agent_run,
    list_agent_results,
    list_result_feedback,
)
from app.services.serialization import loads
from test_agent_experiment import ScriptedEvidencePackClient, _evidence_markdown
from test_release_first_slice import _migrated_session, _seed_citation_contribution_fixture


def _successful_evidence_run(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run, _ = create_agent_run(
        db, project_id=1, prompt_id=44, analysis_id=fixture["analysis"].analysis_id,
        context_id=fixture["context"].context_id,
        citation_manifest_id=fixture["manifest"].manifest_id,
        citation_manifest_hash=fixture["manifest"].payload_hash,
        completion_manifest_id=fixture["completion"].manifest_id,
        completion_manifest_hash=fixture["completion"].payload_hash,
        idempotency_key="internal-beta-result-0001", requested_by="employee-one",
        execution_mode="EVIDENCE_PACK",
    )
    pack = build_evidence_pack(loads(run.input_scope_json, {}))
    execute_agent_run(
        run.run_id, session_factory=sessionmaker(bind=engine, expire_on_commit=False),
        client=ScriptedEvidencePackClient(_evidence_markdown(pack)),
    )
    db.expire_all()
    return db, run


def test_feedback_is_append_only_and_bound_to_exact_result_scope(tmp_path, monkeypatch):
    db, run = _successful_evidence_run(tmp_path, monkeypatch)
    results = list_agent_results(
        db, run_id=run.run_id, project_id=1, prompt_id=44)
    assert len(results) == 1
    result_version = results[0]["result_version"]

    first = add_result_feedback(
        db, run_id=run.run_id, project_id=1, prompt_id=44,
        result_version=result_version, submitted_by="employee-one",
        rating="NEEDS_CHANGES", reason_tags=["BRAND_ASSOCIATION", "DRAFT_QUALITY"],
        suggestion="品牌关联需要更具体，但不能补写未经核实的能力。",
        adoption_status="PARTIALLY_ADOPTED", modification_level="MEDIUM",
        modification_summary="重写品牌段并保留事实提醒。",
    )
    second = add_result_feedback(
        db, run_id=run.run_id, project_id=1, prompt_id=44,
        result_version=result_version, submitted_by="employee-two",
        rating="USABLE", reason_tags=[], suggestion="可作为编辑底稿。",
        adoption_status="ADOPTED", modification_level="LIGHT", modification_summary="调整标题。",
    )
    rows = list_result_feedback(
        db, run_id=run.run_id, project_id=1, prompt_id=44,
        result_version=result_version)
    assert {row["feedback_id"] for row in rows} == {first.feedback_id, second.feedback_id}
    assert all(row["result_version"] == result_version for row in rows)
    assert rows[0]["payload_hash"]

    with pytest.raises(HTTPException) as foreign:
        list_result_feedback(db, run_id=run.run_id, project_id=2, prompt_id=44)
    assert foreign.value.status_code == 404
    with pytest.raises(HTTPException) as wrong_version:
        add_result_feedback(
            db, run_id=run.run_id, project_id=1, prompt_id=44,
            result_version="agent-result-v1:foreign:1", submitted_by="employee-one",
            rating="USABLE", reason_tags=[], suggestion="", adoption_status="UNKNOWN",
            modification_level="NOT_RECORDED", modification_summary="",
        )
    assert wrong_version.value.status_code == 404

    with pytest.raises(DatabaseError):
        db.execute(text("UPDATE agent_result_feedback SET suggestion='overwrite' WHERE id=:id"), {"id": first.id})
        db.commit()
    db.rollback()
    assert db.get(AgentResultFeedback, first.id).suggestion.startswith("品牌关联")


def test_daily_model_calls_fail_closed_without_deployment_authorization(monkeypatch):
    monkeypatch.delenv("GEO_AGENT_BETA_DAILY_MODEL_CALLS", raising=False)
    assert read_agent_capabilities(1) == {
        "project_id": 1, "execution_mode": "EVIDENCE_PACK",
        "new_generation_enabled": False, "authorization_scope": "HISTORY_ONLY",
        "message": "当前没有日常模型调用授权；可查看历史结果并准备任务，但不能产生付费请求。",
    }
    payload = AgentAuthorization(
        project_id=1, prompt_id=44, revision=1, max_requests=1,
        max_total_tokens=300000, max_cost_cny=3,
        conservative_cny_per_million_tokens=10,
        pricing_source="provider pricing page", pricing_checked_at="2026-10-20",
    )
    with pytest.raises(HTTPException) as blocked:
        authorize_agent_experiment("agent-run-not-used", payload, actor="admin", db=None)
    assert blocked.value.status_code == 409
    assert blocked.value.detail["code"] == "BETA_DAILY_MODEL_AUTHORIZATION_REQUIRED"

    monkeypatch.setenv("GEO_AGENT_BETA_DAILY_MODEL_CALLS", "1")
    assert read_agent_capabilities(1)["new_generation_enabled"] is True
