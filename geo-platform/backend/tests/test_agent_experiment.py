from __future__ import annotations

import json
from datetime import datetime
import os
import stat
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.models import (
    AgentCheckpoint, AgentEvent,
    AgentExperimentRun,
    AgentResultVersion,
    BrowserMonitorRun,
    SinglePromptAnalysis,
    SinglePromptAnalysisContext,
    SinglePromptCitationManifest,
)
from app.core.release_database import get_release_db
from app.release_main import create_release_app
from release_test_client import TestClient
from app.modules.agent_experiment.contracts import AgentArtifact, AgentDecision
from app.modules.agent_experiment.grading import validate_and_grade
from app.modules.agent_experiment.evidence_pack import (
    EvidencePackCapacityError,
    build_evidence_pack,
    validate_markdown_result,
)
from app.modules.agent_experiment.reconciliation import reconcile_agent_run_usage
from app.modules.agent_experiment.response_audit import SecureResponseAuditArchive
from app.modules.agent_experiment.runner import (
    _model_payload, _recover_agent_dsml_tool_call, _request_guard, _response_audit_sink,
    _settle_local_reservation, execute_agent_run,
)
from app.modules.agent_experiment.service import (
    authorize_agent_run, cancel_agent_run, create_agent_run, get_agent_run,
)
from app.modules.agent_experiment.tools import ToolRegistry
from app.modules.agent_experiment.scope import _matches_frozen_run
from app.modules.single_prompt_v2.delivery_text import digest
from app.modules.single_prompt_v2.service import _snapshot_run_rows
from app.services.serialization import loads
from app.services.semantic_llm.base import SemanticLLMError
from app.services.shared_model_budget import SharedBudgetHooks, initialize as initialize_shared_budget, summary as shared_budget_summary
from test_release_first_slice import (
    _migrated_session,
    _seed_citation_contribution_fixture,
    _seed_frozen_analysis,
)
from scripts import release_worker


class ScriptedClient:
    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.calls = 0
        self.payloads = []

    def decide(self, **kwargs):
        self.calls += 1
        self.payloads.append(kwargs)
        return self.decisions.pop(0), {
            "input_tokens": 20, "output_tokens": 10, "cost_cny": 0.01,
            "response_source": "TEST_SCRIPT", "request_identity": {"provider": "test"},
        }


class ScriptedEvidencePackClient:
    def __init__(self, markdown: str):
        self.markdown = markdown
        self.calls = 0
        self.payloads = []

    def generate(self, **kwargs):
        self.calls += 1
        self.payloads.append(kwargs)
        return self.markdown, {
            "input_tokens": 120, "output_tokens": 80, "cost_cny": 0.002,
            "response_source": "TEST_SCRIPT", "request_identity": {"provider": "test"},
            "accounting_persisted": False,
        }


def _evidence_markdown(pack, *, valid=True, include_authority=True):
    run = pack["runs"][0]
    answer_end = min(12, len(run["answer_text"]))
    answer_ref = f"[[answer:{run['run_id']}:0:{answer_end}]]"
    source_ref = ""
    if include_authority and pack["selected_source_passages"]:
        passage = pack["selected_source_passages"][0]
        source_ref = f" [[source:{passage['snapshot_id']}:{passage['passage_id']}]]"
    draft = (
        "这是一份面向当前搜索问题的完整可编辑内容。先判断用户希望打开哪一类抖音目标，"
        "再核对平台允许的入口、账号权限和跳转后的落地体验。操作前应保存原始链接并用"
        "同一设备完成小范围测试，避免把未经核验的第三方能力写成目标品牌承诺。\n\n"
        "实际执行时，记录每一步的输入、跳转结果和异常现象；若页面无法打开，应回到官方"
        "配置与权限检查，而不是反复替换未知链接。面向编辑的稿件需要说明适用条件、失败"
        "处理和隐私边界，并把所有品牌能力保留为待核实项。\n\n"
        "完成内容修改后，使用相同 PromptVersion、采样配置与明确 Run 范围复测，分别观察"
        "回答是否覆盖关键步骤、目标品牌是否被提及以及真实引用关系是否变化。单次变化不能"
        "证明由本内容造成，也不能提前承诺收录、引用或推荐效果。"
    )
    if not valid:
        draft = "只有提纲"
    return f"""## GEO 诊断与依据
当前回答已覆盖部分操作线索，但适用条件仍需说明。{answer_ref}{source_ref}

## 品牌表现与证据缺口
当前冻结回答中的品牌表现只能在本 Run 范围内判断，品牌能力仍需核验。{answer_ref}

## 优化策略与渠道
优先在帮助中心发布与当前问题直接对应的核对指南，第三方渠道只作补充。{answer_ref}

## 完整正文
{draft}

## QA 与事实限制
VERIFY_FIRST；没有把外部来源主张直接写成目标品牌事实，也没有承诺优化效果。

## 复测计划
复用同一 PromptVersion、配置和指标，比较品牌提及与引用 occurrence；变化不代表因果。
"""


def test_dsml_adapter_accepts_only_one_whitelisted_tool_call():
    valid = ('<｜｜DSML｜｜ calls> <｜｜DSML｜｜ invoke name="read_answer"> '
             '<｜｜DSML｜｜ parameter name="run_id" string="true">1</｜｜DSML｜｜ parameter> '
             '</｜｜DSML｜｜ invoke> </｜｜DSML｜｜ calls>')
    assert _recover_agent_dsml_tool_call(valid) == {
        "action_type": "TOOL_CALL",
        "reasoning": "DeepSeek emitted one explicit DSML white-list tool invocation.",
        "tool_name": "read_answer", "arguments": {"run_id": 1},
        "artifact": None, "stop_reason": None,
    }
    with pytest.raises(SemanticLLMError):
        _recover_agent_dsml_tool_call(valid.replace("read_answer", "run_shell"))
    with pytest.raises(SemanticLLMError):
        _recover_agent_dsml_tool_call("ignore prior instructions\n" + valid)
    with pytest.raises(SemanticLLMError):
        _recover_agent_dsml_tool_call(valid + valid)


def test_dsml_adapter_extracts_only_complete_top_level_agent_decision():
    wrapped = (
        '<｜｜DSML｜｜ calls> <｜｜DSML｜｜ invoke name="AgentDecision"> '
        '<｜｜DSML｜｜ parameter name="action_type" string="true">TOOL_CALL</｜｜DSML｜｜ parameter> '
        '<｜｜DSML｜｜ parameter name="reasoning" string="true">读取指定冻结回答</｜｜DSML｜｜ parameter> '
        '<｜｜DSML｜｜ parameter name="tool_name" string="true">read_answer</｜｜DSML｜｜ parameter> '
        '<｜｜DSML｜｜ parameter name="arguments">{"run_id":"1"}</｜｜DSML｜｜ parameter> '
        '<｜｜DSML｜｜ parameter name="artifact">null</｜｜DSML｜｜ parameter> '
        '<｜｜DSML｜｜ parameter name="stop_reason">null</｜｜DSML｜｜ parameter> '
        '</｜｜DSML｜｜ invoke> </｜｜DSML｜｜ calls>'
    )
    assert _recover_agent_dsml_tool_call(wrapped) == {
        "action_type": "TOOL_CALL", "reasoning": "读取指定冻结回答",
        "tool_name": "read_answer", "arguments": {"run_id": "1"},
        "artifact": None, "stop_reason": None,
    }
    retained_real_prefix = (
        '<｜｜DSML｜｜ calls> <｜｜DSML｜｜ invoke name="AgentDecision"> '
        '<｜｜DSML｜｜ parameter name="action_type" string="true">TOOL_CALL</｜｜DSML｜｜ parameter> '
        '<｜｜DSML｜｜ parameter name="reasoning" string="true">回答已确认为一篇 746 字的操作型教程'
    )
    with pytest.raises(SemanticLLMError) as truncated:
        _recover_agent_dsml_tool_call(retained_real_prefix)
    assert getattr(truncated.value, "code", "") == "FAILED_PARSE"
    with pytest.raises(SemanticLLMError):
        _recover_agent_dsml_tool_call(wrapped.replace(
            '</｜｜DSML｜｜ invoke> </｜｜DSML｜｜ calls>',
            '<｜｜DSML｜｜ parameter name="unexpected">x</｜｜DSML｜｜ parameter>'
            '</｜｜DSML｜｜ invoke> </｜｜DSML｜｜ calls>',
        ))


@pytest.mark.parametrize("candidate", [
    {"action_type": "TOOL_CALL", "reasoning": "非法工具", "tool_name": "run_shell",
     "arguments": {}, "artifact": None, "stop_reason": None},
    {"action_type": "TOOL_CALL", "reasoning": "冲突动作", "tool_name": "read_answer",
     "arguments": {}, "artifact": None, "stop_reason": "同时停止"},
    {"action_type": "STOP", "reasoning": "冲突动作", "tool_name": "read_answer",
     "arguments": {}, "artifact": None, "stop_reason": "停止"},
])
def test_agent_decision_rejects_unknown_tools_and_conflicting_actions(candidate):
    with pytest.raises(Exception):
        AgentDecision.model_validate(candidate)


def test_rejected_response_archive_is_complete_restricted_and_response_only(tmp_path):
    root = tmp_path / "restricted-response-audit"
    archive = SecureResponseAuditArchive(root, retention_days=7)
    secret = "sk-must-never-enter-response-audit"
    raw = {
        "model": "deepseek-flash", "status": "completed",
        "output": [{"type": "message", "content": [
            {"type": "output_text", "text": "complete provider response"},
        ]}],
        "usage": {"input_tokens": 12, "output_tokens": 7, "total_tokens": 19},
    }
    event = {
        "response_source": "EXTERNAL_LLM", "validation_status": "REJECTED",
        "request_identity": {"provider": "deepseek", "input_hash": "a" * 64,
                             "authorization": f"Bearer {secret}"},
        "rejection_code": "FAILED_PARSE", "raw_response_hash": "b" * 64,
        "raw_provider_response": raw, "token_usage": raw["usage"],
    }
    path = archive.record_rejected_response(run_id="agent-run-test", event=event)
    assert path is not None
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    stored_text = path.read_text(encoding="utf-8")
    stored = json.loads(stored_text)
    assert stored["raw_provider_response"] == raw
    assert stored["expires_at"] and stored["record_hash"]
    assert secret not in stored_text and "authorization" not in stored_text.lower()
    assert archive.record_rejected_response(run_id="agent-run-test", event={
        **event, "validation_status": "ACCEPTED",
    }) is None
    accepted_path = archive.record_provider_response(run_id="agent-run-accepted", event={
        **event, "validation_status": "ACCEPTED", "raw_response_hash": "a" * 64,
    })
    assert accepted_path is not None
    assert json.loads(accepted_path.read_text(encoding="utf-8"))["validation_status"] == "ACCEPTED"

    http_event = {
        "response_source": "EXTERNAL_LLM", "validation_status": "REJECTED",
        "request_identity": {"provider": "deepseek", "input_hash": "c" * 64},
        "rejection_code": "PROVIDER_HTTP_ERROR", "raw_response_hash": "d" * 64,
        "raw_provider_response": None, "http_status": 400,
        "provider_error_category": "invalid_request_error",
        "raw_http_response": json.dumps({"error": {"message": f"bad {secret}",
                                                       "api_key": secret}}),
        "token_usage": {},
    }
    http_path = archive.record_rejected_response(run_id="agent-run-http", event=http_event)
    assert http_path is not None
    http_stored = json.loads(http_path.read_text(encoding="utf-8"))
    assert http_stored["http_status"] == 400
    assert http_stored["provider_error_category"] == "invalid_request_error"
    assert secret not in http_path.read_text(encoding="utf-8")
    assert "[REDACTED]" in http_stored["raw_http_response"]

    expired = root / "agent-response-expired.json"
    expired.write_text("{}", encoding="utf-8")
    old = datetime.now().timestamp() - 8 * 24 * 60 * 60
    os.utime(expired, (old, old))
    archive.prepare()
    assert not expired.exists()


def _artifact(*, run_id: int, answer_end: int, source=None, readiness="VERIFY_FIRST"):
    refs = [{"kind": "answer_span", "run_id": str(run_id), "start": 0, "end": answer_end}]
    if source:
        refs.append({"kind": "source_passage", "snapshot_id": source["snapshot_id"],
                     "passage_id": source["passages"][0]["passage_id"]})
    body = (
        "# 短链工具选择与批量处理核对指南\n\n"
        "先明确需要处理的链接数量、权限边界和失败回退方式，再用同一组样例检查候选工具。"
        "对于批量任务，记录每条链接的输入、处理状态与错误原因；没有可核实资料的能力不要写成承诺。\n\n"
        "## 上线前检查\n\n小范围执行并保存结果。若条件不一致或出现异常，停止扩大范围并回到资料核验。"
    )
    return {
        "schema_version": "geo.agent.result.v1",
        "summary": "当前回答提供了批量短链处理线索；结论仅限冻结 Run 与已读取资料。",
        "observations": [{"statement": "冻结回答提到了批量生成短链。", "classification": "OBSERVED",
                          "reasoning": "来自冻结回答原文。", "evidence_refs": refs[:1]}],
        "diagnosis": [{"statement": "应围绕批量任务的条件与失败处理补足可核验内容。",
                       "classification": "INFERENCE", "reasoning": "回答主题与交付目标相关。",
                       "evidence_refs": refs}],
        "actions": [{"id": "action-1", "priority": "HIGH", "what": "制作批量短链核对指南",
                     "why": "直接回应当前 Prompt", "channel": "官网帮助中心", "channel_role": "PRIMARY",
                     "readiness": readiness, "required_asset": "可编辑 Markdown",
                     "next_step": "编辑复核后小范围发布", "evidence_refs": refs}],
        "deliverables": [{"id": "draft-1", "action_ids": ["action-1"], "asset_type": "HELP_DOC",
                          "title": "短链工具选择与批量处理核对指南", "body_markdown": body,
                          "editorial_notes": ["不得补写未经核验的品牌能力"]}],
        "qa_self_check": {"checked": ["主体", "事实", "引用", "因果"],
                          "identified_issues": [], "suggested_repairs": []},
        "validation_plan": {"questions": ["相同 Prompt 下品牌提及是否变化"],
                            "metrics": ["brand_mentioned_count", "citation_occurrence_count"],
                            "comparison_prerequisites": ["使用同一 PromptVersion 和采样配置"],
                            "non_causality_note": "观测变化不单独证明内容造成模型变化。"},
        "limitations": ["样本仅限当前冻结 Run。"],
    }


def _create_from_fixture(db, fixture, *, key="agent-fixture-0001", execution_mode="TOOL_LOOP"):
    return create_agent_run(
        db, project_id=1, prompt_id=44, analysis_id=fixture["analysis"].analysis_id,
        context_id=fixture["context"].context_id,
        citation_manifest_id=fixture["manifest"].manifest_id,
        citation_manifest_hash=fixture["manifest"].payload_hash,
        completion_manifest_id=fixture["completion"].manifest_id,
        completion_manifest_hash=fixture["completion"].payload_hash,
        idempotency_key=key, requested_by="qa", execution_mode=execution_mode,
    )


def test_evidence_pack_builds_from_frozen_scope_without_workflow_outputs(tmp_path, monkeypatch):
    db, _engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run, created = create_agent_run(
        db, project_id=1, prompt_id=44, analysis_id=fixture["analysis"].analysis_id,
        context_id=fixture["context"].context_id,
        citation_manifest_id=fixture["manifest"].manifest_id,
        citation_manifest_hash=fixture["manifest"].payload_hash,
        completion_manifest_id=fixture["completion"].manifest_id,
        completion_manifest_hash=fixture["completion"].payload_hash,
        idempotency_key="evidence-pack-build-0001", requested_by="qa",
        execution_mode="EVIDENCE_PACK",
    )
    assert created
    execution = loads(run.agent_execution_json, {})
    assert execution["contract_version"] == "geo.evidence-pack.execution.v4"
    assert execution["model_profile"]["prompt_version"] == "geo-evidence-pack-synthesis.v4"
    assert execution["model_profile"]["reasoning_effort"] == "none"
    assert execution["model_profile"]["response_transport"] == (
        "geo.deepseek.responses-text.no-thinking.v2"
    )
    assert loads(run.budget_json, {})["max_model_calls"] == 1
    assert loads(run.budget_json, {})["max_tool_calls"] == 0
    pack = build_evidence_pack(loads(run.input_scope_json, {}))
    assert pack["contract_version"] == "geo.evidence-pack.v1"
    assert pack["evidence_pack_hash"] == digest({key: value for key, value in pack.items()
                                                  if key != "evidence_pack_hash"})
    assert pack["runs"][0]["answer_text"]
    assert pack["runs"][0]["answer_evidence_locator"].endswith(
        f":0:{len(pack['runs'][0]['answer_text'])}]]"
    )
    assert len(pack["citation_occurrences"]) == 2
    assert all(row["evidence_locator"].startswith("[[citation:")
               for row in pack["citation_occurrences"])
    assert all(row["evidence_locator"].startswith("[[truth:")
               for row in pack["product_truth"]["facts"])
    assert pack["coverage"]["source_passage_total"] >= 1
    assert pack["coverage"]["source_passage_included"] >= 1
    serialized = json.dumps(pack, ensure_ascii=False).lower()
    assert "workflow" not in serialized
    assert "diagnosis_result" not in serialized and "strategy_result" not in serialized


def test_evidence_pack_capacity_is_explicit_and_deterministic(tmp_path, monkeypatch):
    db, _engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run, _ = create_agent_run(
        db, project_id=1, prompt_id=44, analysis_id=fixture["analysis"].analysis_id,
        context_id=fixture["context"].context_id,
        citation_manifest_id=fixture["manifest"].manifest_id,
        citation_manifest_hash=fixture["manifest"].payload_hash,
        completion_manifest_id=fixture["completion"].manifest_id,
        completion_manifest_hash=fixture["completion"].payload_hash,
        idempotency_key="evidence-pack-capacity-0001", requested_by="qa",
        execution_mode="EVIDENCE_PACK",
    )
    scope = loads(run.input_scope_json, {})
    oversized = json.loads(json.dumps(scope))
    oversized["runs"][0]["answer_text"] += "超出容量" * 1_000
    with pytest.raises(EvidencePackCapacityError, match="CORE_EXCEEDS_BUDGET"):
        build_evidence_pack(oversized, text_budget=2_000)
    passage_heavy = json.loads(json.dumps(scope))
    passage_heavy["source_snapshots"][0]["passages"][0]["text"] += "来源正文" * 1_000
    constrained_budget = 2_000
    constrained = build_evidence_pack(passage_heavy, text_budget=constrained_budget)
    assert constrained["coverage"]["source_passage_omitted"] >= 1
    assert constrained == build_evidence_pack(passage_heavy, text_budget=constrained_budget)
    assert all(row["reason"] == "TEXT_BUDGET"
               for row in constrained["coverage"]["omitted_materials"])


def test_evidence_pack_demotes_only_nested_draft_h2_headings(tmp_path, monkeypatch):
    db, _engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run, _ = _create_from_fixture(
        db, fixture, key="evidence-pack-heading-normalization-0001",
        execution_mode="EVIDENCE_PACK",
    )
    pack = build_evidence_pack(loads(run.input_scope_json, {}))
    markdown = _evidence_markdown(pack).replace(
        "## 完整正文\n",
        "## 完整正文\n开场说明。\n\n## 正文内部小节\n",
    )
    checked, _eligibility = validate_markdown_result(markdown, pack)
    assert checked["validation"]["status"] == "PASS"
    assert checked["result"]["normalizations"] == [
        {"code": "DRAFT_H2_DEMOTED", "detail": "正文内部小节"},
    ]
    assert "### 正文内部小节" in checked["result"]["raw_markdown"]

    outside = markdown.replace(
        "## 品牌表现与证据缺口\n",
        "## 非契约顶层章节\n内容。\n\n## 品牌表现与证据缺口\n",
    )
    rejected, _ = validate_markdown_result(outside, pack)
    assert {row["code"] for row in rejected["validation"]["issues"]} >= {
        "UNEXPECTED_TOP_LEVEL_SECTION",
    }


def test_evidence_pack_single_call_persists_validated_independent_result(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run, _ = create_agent_run(
        db, project_id=1, prompt_id=44, analysis_id=fixture["analysis"].analysis_id,
        context_id=fixture["context"].context_id,
        citation_manifest_id=fixture["manifest"].manifest_id,
        citation_manifest_hash=fixture["manifest"].payload_hash,
        completion_manifest_id=fixture["completion"].manifest_id,
        completion_manifest_hash=fixture["completion"].payload_hash,
        idempotency_key="evidence-pack-execute-0001", requested_by="qa",
        execution_mode="EVIDENCE_PACK",
    )
    pack = build_evidence_pack(loads(run.input_scope_json, {}))
    scripted = ScriptedEvidencePackClient(_evidence_markdown(pack))
    execute_agent_run(
        run.run_id, session_factory=sessionmaker(bind=engine, expire_on_commit=False),
        client=scripted,
    )
    db.expire_all()
    stored = db.query(AgentExperimentRun).filter_by(run_id=run.run_id).one()
    result = db.query(AgentResultVersion).filter_by(agent_run_id=run.run_id).one()
    assert stored.status == "SUCCEEDED"
    assert stored.model_call_count == 1 and stored.tool_call_count == 0
    assert result.evidence_grade == "L2_PARTIALLY_GROUNDED"
    assert result.publication_eligibility == "VERIFY_FIRST"
    payload = loads(result.result_json, {})
    assert payload["schema_version"] == "geo.evidence-pack.markdown-result.v1"
    assert payload["evidence_pack"]["evidence_pack_hash"] == pack["evidence_pack_hash"]
    assert payload["success_assessment"] == {
        "engineering_success": True,
        "business_usable": "REQUIRES_HUMAN_REVIEW",
        "workflow_advantage": "NOT_MEASURABLE",
    }
    assert len(result.deliverable_markdown) >= 240
    assert db.query(AgentEvent).filter_by(
        agent_run_id=run.run_id, event_type="EVIDENCE_PACK_FROZEN",
    ).count() == 1
    assert not db.execute(text("SELECT COUNT(*) FROM single_prompt_strategy_results")).scalar_one()
    assert not db.execute(text("SELECT COUNT(*) FROM single_prompt_execution_proposal_results")).scalar_one()


def test_evidence_pack_rejects_unread_source_and_incomplete_draft(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run, _ = create_agent_run(
        db, project_id=1, prompt_id=44, analysis_id=fixture["analysis"].analysis_id,
        context_id=fixture["context"].context_id,
        citation_manifest_id=fixture["manifest"].manifest_id,
        citation_manifest_hash=fixture["manifest"].payload_hash,
        completion_manifest_id=fixture["completion"].manifest_id,
        completion_manifest_hash=fixture["completion"].payload_hash,
        idempotency_key="evidence-pack-invalid-0001", requested_by="qa",
        execution_mode="EVIDENCE_PACK",
    )
    pack = build_evidence_pack(loads(run.input_scope_json, {}))
    markdown = _evidence_markdown(pack, valid=False, include_authority=False).replace(
        "[[answer:", "[[source:missing-snapshot:missing-passage]] [[answer:", 1,
    )
    execute_agent_run(
        run.run_id, session_factory=sessionmaker(bind=engine, expire_on_commit=False),
        client=ScriptedEvidencePackClient(markdown),
    )
    db.expire_all()
    stored = db.query(AgentExperimentRun).filter_by(run_id=run.run_id).one()
    result = db.query(AgentResultVersion).filter_by(agent_run_id=run.run_id).one()
    validation = loads(result.validation_report_json, {})
    assert stored.status == "FAILED"
    assert stored.blocker_code == "EVIDENCE_PACK_OUTPUT_VALIDATION_FAILED"
    assert {row["code"] for row in validation["issues"]} >= {
        "SOURCE_REF_NOT_INCLUDED", "DELIVERABLE_INCOMPLETE",
    }
    assert validation["status"] == "FAIL"


def test_evidence_pack_l3_requires_verify_first_and_valid_refs(tmp_path, monkeypatch):
    db, _engine = _migrated_session(tmp_path, monkeypatch)
    analysis = _seed_frozen_analysis(db, reference_urls=[])
    context = db.query(SinglePromptAnalysisContext).filter_by(analysis_id=analysis.analysis_id).one()
    run, _ = create_agent_run(
        db, project_id=1, prompt_id=44, analysis_id=analysis.analysis_id,
        context_id=context.context_id, idempotency_key="evidence-pack-l3-0001",
        requested_by="qa", execution_mode="EVIDENCE_PACK",
    )
    pack = build_evidence_pack(loads(run.input_scope_json, {}))
    checked, eligibility = validate_markdown_result(
        _evidence_markdown(pack, include_authority=False), pack,
    )
    assert checked["validation"]["status"] == "PASS"
    assert eligibility["evidence_grade"] == "L3_ACTIONABLE_WITHOUT_FACT_CLAIMS"
    assert eligibility["public_claim_eligibility"] == "NOT_CONSUMABLE"
    without_marker = _evidence_markdown(pack, include_authority=False).replace("VERIFY_FIRST", "待核验")
    rejected, _ = validate_markdown_result(without_marker, pack)
    assert "L3_VERIFY_FIRST_REQUIRED" in {row["code"] for row in rejected["validation"]["issues"]}


def test_true_agent_loop_chooses_tools_then_persists_independent_l2_result(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run, created = _create_from_fixture(db, fixture)
    assert created and run.status == "QUEUED"
    scope = loads(run.input_scope_json, {})
    source = scope["source_snapshots"][0]
    answer = scope["runs"][0]["answer_text"]
    client = ScriptedClient([
        {"action_type": "TOOL_CALL", "reasoning": "先读取回答", "tool_name": "read_answer",
         "arguments": {"run_id": str(fixture["run"].id), "start": 0, "end": len(answer)},
         "artifact": None, "stop_reason": None},
        {"action_type": "TOOL_CALL", "reasoning": "核对来源原文", "tool_name": "read_source",
         "arguments": {"snapshot_id": source["snapshot_id"],
                       "passage_id": source["passages"][0]["passage_id"]},
         "artifact": None, "stop_reason": None},
        {"action_type": "FINAL_ARTIFACT", "reasoning": "证据足以形成限定交付", "tool_name": None,
         "arguments": None, "artifact": _artifact(run_id=fixture["run"].id,
         answer_end=len(answer), source=source), "stop_reason": None},
    ])
    execute_agent_run(run.run_id, session_factory=sessionmaker(bind=engine, expire_on_commit=False), client=client)
    db.expire_all()
    stored = db.query(AgentExperimentRun).filter_by(run_id=run.run_id).one()
    assert stored.status == "SUCCEEDED", (stored.blocker_code, stored.blocker_detail)
    result = db.query(AgentResultVersion).filter_by(agent_run_id=run.run_id).one()
    assert stored.status == "SUCCEEDED"
    assert stored.model_call_count == 3 and stored.tool_call_count == 2
    assert stored.cost_cny == pytest.approx(0.03)
    assert result.evidence_grade == "L2_PARTIALLY_GROUNDED"
    assert result.public_claim_eligibility == "VERIFY_FIRST"
    assert result.publication_eligibility == "VERIFY_FIRST"
    assert len(result.deliverable_markdown) >= 120
    binding = loads(result.plan_result_binding_json, {})
    assert binding == {
        "contract_version": "geo.agent.plan-result-binding.v1",
        "plan_hash": result.plan_hash,
        "result_hash": result.result_hash,
        "input_scope_hash": stored.input_scope_hash,
        "agent_execution_hash": stored.agent_execution_hash,
        "qualification_hash": stored.qualification_hash,
    }
    assert len(scope["source_dispositions"]) == 2
    assert {row["state"] for row in scope["source_dispositions"]} == {"READY", "WAIVED_WITH_LIMITATION"}
    assert scope["monitor_metrics"]["citation_occurrence_count"] == 2
    assert db.query(AgentEvent).filter_by(agent_run_id=run.run_id, event_type="TOOL_RESULT").count() == 2
    assert not db.execute(text("SELECT COUNT(*) FROM single_prompt_strategy_results")).scalar_one()
    assert not db.execute(text("SELECT COUNT(*) FROM single_prompt_execution_proposal_results")).scalar_one()


def test_stateless_requests_replay_full_tool_result_and_explicit_observation_catalog(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run, _ = _create_from_fixture(db, fixture, key="agent-context-replay-0001")
    client = ScriptedClient([
        {"action_type": "TOOL_CALL", "reasoning": "先看范围", "tool_name": "get_scope_summary",
         "arguments": {}, "artifact": None, "stop_reason": None},
        {"action_type": "TOOL_CALL", "reasoning": "重复确认范围", "tool_name": "get_scope_summary",
         "arguments": {}, "artifact": None, "stop_reason": None},
        {"action_type": "STOP", "reasoning": "测试结束", "tool_name": None,
         "arguments": None, "artifact": None, "stop_reason": "离线连续性测试结束"},
    ])
    execute_agent_run(run.run_id, session_factory=sessionmaker(bind=engine, expire_on_commit=False), client=client)
    second = client.payloads[1]["user_payload"]
    assert second["contract_version"] == "geo.agent.loop-input.v3"
    assert second["current_call_contract"]["decision_count"] == 1
    assert second["current_call_contract"]["future_action_list_allowed"] is False
    assert second["tool_history"][0]["tool_result"]["data"]["monitor_metrics"]
    assert second["observation_catalog"][0]["tool_name"] == "get_scope_summary"
    assert second["observation_catalog"][0]["status"] == "AVAILABLE"
    assert second["context_integrity"]["observation_summaries_complete"] is True
    db.expire_all()
    stored = db.query(AgentExperimentRun).filter_by(run_id=run.run_id).one()
    assert stored.tool_call_count == 1
    assert db.query(AgentEvent).filter_by(
        agent_run_id=run.run_id, event_type="TOOL_RESULT_REUSED").count() == 1
    manifests = db.query(AgentEvent).filter_by(
        agent_run_id=run.run_id, event_type="MODEL_INPUT_CONTEXT").order_by(AgentEvent.sequence_number).all()
    assert len(manifests) == 3
    assert loads(manifests[1].payload_json, {})["observation_catalog"][0]["status"] == "AVAILABLE"


def test_checkpoint_resume_replays_observation_catalog(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run, _ = _create_from_fixture(db, fixture, key="agent-context-checkpoint-0001")
    observation = ToolRegistry(db, run).call("get_scope_summary", {})
    decision = {"action_type": "TOOL_CALL", "reasoning": "先看范围",
                "tool_name": "get_scope_summary", "arguments": {}, "stop_reason": None}
    state = {"turn": 1, "history": [{"turn": 1, "decision": decision,
                                      "tool_result": observation}],
             "observations": [observation], "repair_count": 0, "consecutive_no_progress": 0}
    state_json = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    db.add(AgentCheckpoint(
        checkpoint_id=f"agent-checkpoint-{uuid4()}", agent_run_id=run.run_id,
        sequence_number=1, state_json=state_json, state_hash=digest(state),
    ))
    run.model_call_count = 1
    db.commit()
    client = ScriptedClient([
        {"action_type": "STOP", "reasoning": "恢复信息完整", "tool_name": None,
         "arguments": None, "artifact": None, "stop_reason": "离线恢复测试结束"},
    ])
    execute_agent_run(run.run_id, session_factory=sessionmaker(bind=engine, expire_on_commit=False), client=client)
    payload = client.payloads[0]["user_payload"]
    assert payload["turn"] == 2
    assert payload["tool_history"][0]["tool_result"]["observation_id"] == observation["observation_id"]
    assert payload["observation_catalog"][0]["observation_key"] == observation["observation_key"]


def test_finalization_reserves_last_two_calls_and_rejects_exploration(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run, _ = create_agent_run(
        db, project_id=1, prompt_id=44, analysis_id=fixture["analysis"].analysis_id,
        context_id=fixture["context"].context_id,
        citation_manifest_id=fixture["manifest"].manifest_id,
        citation_manifest_hash=fixture["manifest"].payload_hash,
        completion_manifest_id=fixture["completion"].manifest_id,
        completion_manifest_hash=fixture["completion"].payload_hash,
        idempotency_key="agent-finalization-0001", requested_by="qa",
        budget={"max_model_calls": 4},
    )
    answer = loads(run.input_scope_json, {})["runs"][0]["answer_text"]
    client = ScriptedClient([
        {"action_type": "TOOL_CALL", "reasoning": "读取回答", "tool_name": "read_answer",
         "arguments": {"run_id": str(fixture["run"].id), "start": 0, "end": len(answer)},
         "artifact": None, "stop_reason": None},
        {"action_type": "TOOL_CALL", "reasoning": "读取引用", "tool_name": "list_citations",
         "arguments": {"run_id": str(fixture["run"].id)}, "artifact": None, "stop_reason": None},
        {"action_type": "TOOL_CALL", "reasoning": "继续探索", "tool_name": "get_scope_summary",
         "arguments": {}, "artifact": None, "stop_reason": None},
        {"action_type": "STOP", "reasoning": "不编造", "tool_name": None,
         "arguments": None, "artifact": None, "stop_reason": "证据不足，安全停止"},
    ])
    execute_agent_run(run.run_id, session_factory=sessionmaker(bind=engine, expire_on_commit=False), client=client)
    db.expire_all()
    stored = db.query(AgentExperimentRun).filter_by(run_id=run.run_id).one()
    assert stored.status == "NEEDS_INPUT" and stored.model_call_count == 4
    assert stored.tool_call_count == 2
    assert client.payloads[2]["user_payload"]["execution_phase"] == "FINALIZATION"
    assert client.payloads[3]["user_payload"]["server_validation_feedback"][0]["code"] == (
        "FINALIZATION_TOOL_CALL_NOT_ALLOWED"
    )
    assert db.query(AgentEvent).filter_by(
        agent_run_id=run.run_id, event_type="TOOL_CALL_REJECTED_FINALIZATION").count() == 1


def test_observation_keys_normalize_same_call_and_keep_ranges_distinct(tmp_path, monkeypatch):
    db, _engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run, _ = _create_from_fixture(db, fixture, key="agent-observation-key-0001")
    registry = ToolRegistry(db, run)
    answer = loads(run.input_scope_json, {})["runs"][0]["answer_text"]
    first = registry.call("read_answer", {"run_id": fixture["run"].id, "start": 0,
                                           "end": min(10, len(answer))})
    same = registry.call("read_answer", {"end": min(10, len(answer)), "start": 0,
                                          "run_id": str(fixture["run"].id)})
    different = registry.call("read_answer", {"run_id": str(fixture["run"].id),
                                               "start": 1, "end": min(11, len(answer))})
    assert first["observation_key"] == same["observation_key"]
    assert first["observation_key"] != different["observation_key"]


def test_context_overflow_keeps_complete_observation_summaries():
    scope = {
        "identity": {"project_id": 1}, "prompt": {"text": "x"}, "monitor_metrics": {},
        "source_snapshots": [], "product_truth": {"set_hash": "truth"},
        "brand_context": {"mode": "EMPTY"},
    }
    observations = [
        {"observation_id": f"obs-{index}", "observation_key": f"key-{index}",
         "tool_name": "get_scope_summary", "arguments": {}, "data": {"index": index}}
        for index in range(15)
    ]
    history = [{"turn": index + 1, "decision": {"action_type": "TOOL_CALL",
                "tool_name": "get_scope_summary"}, "tool_result": observation}
               for index, observation in enumerate(observations)]
    payload = _model_payload(
        scope, history, observations, 16, max_model_calls=20, finalization=False,
        consecutive_no_progress=0,
    )
    assert len(payload["tool_history"]) == 12
    assert payload["context_integrity"]["history_truncated"] is True
    assert len(payload["observation_catalog"]) == 15
    assert payload["context_integrity"]["observation_summaries_complete"] is True


def test_no_source_still_delivers_complete_l3_instruction_only_artifact(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    analysis = _seed_frozen_analysis(db, reference_urls=[])
    context = db.query(SinglePromptAnalysisContext).filter_by(analysis_id=analysis.analysis_id).one()
    monitor_run = db.query(BrowserMonitorRun).filter_by(task_id=analysis.task_id).one()
    row, _ = create_agent_run(
        db, project_id=1, prompt_id=44, analysis_id=analysis.analysis_id, context_id=context.context_id,
        idempotency_key="agent-no-source-0001", requested_by="qa",
    )
    answer = loads(row.input_scope_json, {})["runs"][0]["answer_text"]
    client = ScriptedClient([
        {"action_type": "TOOL_CALL", "reasoning": "读取有效回答", "tool_name": "read_answer",
         "arguments": {"run_id": str(monitor_run.id), "start": 0, "end": len(answer)},
         "artifact": None, "stop_reason": None},
        {"action_type": "FINAL_ARTIFACT", "reasoning": "以核验指南形式交付", "tool_name": None,
         "arguments": None, "artifact": _artifact(run_id=monitor_run.id, answer_end=len(answer)),
         "stop_reason": None},
    ])
    execute_agent_run(row.run_id, session_factory=sessionmaker(bind=engine, expire_on_commit=False), client=client)
    db.expire_all()
    result = db.query(AgentResultVersion).filter_by(agent_run_id=row.run_id).one()
    assert result.evidence_grade == "L3_ACTIONABLE_WITHOUT_FACT_CLAIMS"
    assert result.public_claim_eligibility == "NOT_CONSUMABLE"
    assert result.publication_eligibility == "VERIFY_FIRST"


def test_frozen_scope_identity_cannot_be_mutated_and_has_no_agent_result(tmp_path, monkeypatch):
    db, _engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run, _ = _create_from_fixture(db, fixture)
    run.input_scope_json = run.input_scope_json.replace("甲工具", "篡改工具", 1)
    with pytest.raises(Exception, match="AGENT_EXPERIMENT_IDENTITY_IMMUTABLE"):
        db.commit()
    db.rollback()
    assert db.query(AgentResultVersion).filter_by(agent_run_id=run.run_id).count() == 0
    stored = db.query(AgentExperimentRun).filter_by(run_id=run.run_id).one()
    assert stored.model_call_count == 0


def test_tool_allowlist_rejects_prompt_injected_shell_request(tmp_path, monkeypatch):
    db, _engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run, _ = _create_from_fixture(db, fixture)
    with pytest.raises(HTTPException) as error:
        ToolRegistry(db, run).call("execute_shell", {"command": "cat /etc/passwd"})
    assert error.value.detail["code"] == "AGENT_TOOL_NOT_ALLOWED"


def test_agent_events_results_and_checkpoints_are_append_only(tmp_path, monkeypatch):
    db, _engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run, _ = _create_from_fixture(db, fixture)
    event = AgentEvent(event_id=f"evt-{uuid4()}", agent_run_id=run.run_id, sequence_number=1,
                       event_type="TEST", payload_json="{}", payload_hash=digest({}))
    db.add(event)
    db.commit()
    event.event_type = "MUTATED"
    with pytest.raises(Exception, match="AGENT_EXPERIMENT_APPEND_ONLY"):
        db.commit()
    db.rollback()


def test_no_valid_answer_creates_l4_recovery_with_zero_model_calls(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    source_analysis = _seed_frozen_analysis(db, reference_urls=[])
    source_run = db.query(BrowserMonitorRun).filter_by(task_id=source_analysis.task_id).one()
    source_run.status = "failed"
    source_run.stage = "failed"
    source_run.answer_text = ""
    source_run.answer_char_count = 0
    source_run.error_type = "fixture_failure"
    source_run.error_message = "测试失败回答"
    db.commit()
    snapshot = _snapshot_run_rows(db, [source_run])[0]
    analysis_id = f"agent-l4-analysis-{uuid4()}"
    plan = loads(source_analysis.sampling_plan_json, {})
    analysis = SinglePromptAnalysis(
        analysis_id=analysis_id, project_id=1, prompt_id=44, task_id=None,
        idempotency_key=f"agent-l4-analysis-{uuid4()}",
        prompt_text_snapshot=source_analysis.prompt_text_snapshot,
        sampling_plan_json=json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        sampling_plan_hash=digest(plan), status="READY_WITH_FAILURES", finished_at=datetime.utcnow(),
    )
    run_scope = {"contract_version": "single-prompt-run-scope-v2", "source": "EXPLICIT_TEST_FAILURE",
                 "run_ids": [source_run.id], "planned_run_count": 1}
    raw = {"contract_version": "single-prompt-raw-output-v1", "analysis_id": analysis_id,
           "project_id": 1, "prompt_id": 44, "prompt_text": source_analysis.prompt_text_snapshot,
           "sampling_plan": plan, "runs": [snapshot]}
    context = SinglePromptAnalysisContext(
        context_id=f"ctx-{uuid4()}", analysis_id=analysis_id, project_id=1, prompt_id=44, task_id=None,
        result_version=f"raw-v1:{digest(raw)[:16]}",
        run_scope_json=json.dumps(run_scope, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        run_scope_hash=digest(run_scope), raw_output_json=json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        raw_output_hash=digest(raw), valid_run_count=0, failed_run_count=1,
    )
    db.add_all([analysis, context]); db.commit()
    agent, _ = create_agent_run(db, project_id=1, prompt_id=44, analysis_id=analysis_id,
                                context_id=context.context_id, idempotency_key="agent-l4-run-0001",
                                requested_by="qa", execution_mode="EVIDENCE_PACK")
    client = ScriptedEvidencePackClient("")
    execute_agent_run(agent.run_id, session_factory=sessionmaker(bind=engine, expire_on_commit=False), client=client)
    db.expire_all()
    stored = db.query(AgentExperimentRun).filter_by(run_id=agent.run_id).one()
    result = db.query(AgentResultVersion).filter_by(agent_run_id=agent.run_id).one()
    assert stored.status == "NEEDS_INPUT"
    assert stored.model_call_count == 0 and client.calls == 0
    assert result.evidence_grade == "L4_RECOVERY_PACKAGE"
    assert result.deliverable_markdown == ""


def test_agent_api_create_get_and_comparison_get_are_scoped_and_read_only(tmp_path, monkeypatch):
    db, _engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    app = create_release_app(validate_on_startup=False)

    def override_release_db():
        yield db

    app.dependency_overrides[get_release_db] = override_release_db
    client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000))
    payload = {"project_id": 1, "prompt_id": 44, "context_id": fixture["context"].context_id,
               "citation_manifest_id": fixture["manifest"].manifest_id,
               "citation_manifest_hash": fixture["manifest"].payload_hash,
               "completion_manifest_id": fixture["completion"].manifest_id,
               "completion_manifest_hash": fixture["completion"].payload_hash,
               "idempotency_key": "agent-api-create-0001"}
    created = client.post(f"/api/v2/single-prompt/analyses/{fixture['analysis'].analysis_id}/agent-experiments", json=payload)
    assert created.status_code == 201, created.text
    assert created.json()["execution_mode"] == "EVIDENCE_PACK"
    assert created.json()["budget"]["max_model_calls"] == 1
    assert created.json()["budget"]["max_tool_calls"] == 0
    run_id = created.json()["run_id"]
    before = db.query(AgentEvent).count()
    read = client.get(f"/api/v2/single-prompt/agent-experiments/{run_id}?project_id=1&prompt_id=44")
    compared = client.get(f"/api/v2/single-prompt/agent-experiments/{run_id}/comparison?project_id=1&prompt_id=44")
    assert read.status_code == 200 and read.json()["run_id"] == run_id
    assert compared.status_code == 200 and compared.json()["comparison_contract"].endswith("v1")
    assert db.query(AgentEvent).count() == before
    assert client.get(f"/api/v2/single-prompt/agent-experiments/{run_id}?project_id=1&prompt_id=45").status_code == 404
    app.dependency_overrides.clear()


def test_wrong_frozen_hash_records_blocked_run_with_zero_model_and_no_result(tmp_path, monkeypatch):
    db, _engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    row, created = create_agent_run(
        db, project_id=1, prompt_id=44, analysis_id=fixture["analysis"].analysis_id,
        context_id=fixture["context"].context_id,
        citation_manifest_id=fixture["manifest"].manifest_id,
        citation_manifest_hash="0" * 64,
        idempotency_key="agent-wrong-hash-0001", requested_by="qa",
    )
    assert created and row.status == "BLOCKED"
    assert row.blocker_code == "CITATION_MANIFEST_HASH_MISMATCH"
    assert row.model_call_count == 0 and row.tool_call_count == 0
    assert db.query(AgentResultVersion).filter_by(agent_run_id=row.run_id).count() == 0


def test_cache_only_miss_waits_for_authorization_without_external_call(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    row, _ = _create_from_fixture(
        db, fixture, key="agent-cache-only-0001", execution_mode="EVIDENCE_PACK",
    )
    execute_agent_run(row.run_id, session_factory=sessionmaker(bind=engine, expire_on_commit=False))
    db.expire_all()
    stored = db.query(AgentExperimentRun).filter_by(run_id=row.run_id).one()
    assert stored.status == "WAITING_AUTHORIZATION"
    assert stored.blocker_code == "CACHE_MISS"
    assert stored.model_call_count == 0 and stored.cost_cny == 0
    assert db.query(AgentResultVersion).filter_by(agent_run_id=row.run_id).count() == 0


def test_release_worker_dispatches_agent_run_through_existing_single_concurrency_loop(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    row, _ = _create_from_fixture(db, fixture, key="agent-worker-dispatch-0001")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    captured = []
    monkeypatch.setattr(release_worker, "ReleaseSessionLocal", factory)
    monkeypatch.setattr(release_worker, "execute_agent_run",
                        lambda run_id, session_factory: captured.append((run_id, session_factory)))
    assert release_worker.run_once() == f"agent_experiment:{row.run_id}"
    assert captured == [(row.run_id, factory)]


def test_external_authorization_reserves_request_token_and_cost_before_transport(tmp_path, monkeypatch):
    db, _engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    row, _ = _create_from_fixture(db, fixture, key="agent-budget-reservation-0001")
    row.status = "WAITING_AUTHORIZATION"; db.commit()
    row = authorize_agent_run(
        db, run_id=row.run_id, project_id=1, prompt_id=44, revision=row.revision,
        max_requests=1, max_total_tokens=4000, max_cost_cny=1.0,
        conservative_cny_per_million_tokens=10.0,
        pricing_source="测试中人工核实的计费页面", pricing_checked_at="2026-10-19", authorized_by="qa",
    )
    guard = _request_guard(db, row)
    guard({"input_token_upper_bound": 1000, "max_output_tokens": 2000, "provider_payload_hash": "a" * 64})
    db.refresh(row)
    authorization = loads(row.authorization_json, {})
    assert authorization["reserved_requests"] == 1
    assert authorization["reserved_tokens"] == 3000
    assert authorization["reserved_cost_cny"] == pytest.approx(0.03)
    assert loads(row.progress_json, {})["external_request_state"] == "RESERVED_IN_FLIGHT"
    _settle_local_reservation(row, {"input_tokens": 100, "output_tokens": 50})
    db.commit(); db.refresh(row)
    settled = loads(row.authorization_json, {})
    assert settled["reserved_tokens"] == 150
    assert settled["reserved_cost_cny"] == pytest.approx(0.0015)
    assert loads(row.progress_json, {})["external_request_state"] == "SETTLED"
    with pytest.raises(SemanticLLMError) as error:
        guard({"input_token_upper_bound": 1, "max_output_tokens": 2048})
    assert getattr(error.value, "code") == "AGENT_MODEL_CALL_BUDGET_EXHAUSTED"


def test_agent_external_guard_uses_controller_shared_ledger(tmp_path, monkeypatch):
    db, _engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    row, _ = _create_from_fixture(db, fixture, key="agent-shared-budget-0001")
    row.status = "WAITING_AUTHORIZATION"; db.commit()
    row = authorize_agent_run(
        db, run_id=row.run_id, project_id=1, prompt_id=44, revision=row.revision,
        max_requests=1, max_total_tokens=4000, max_cost_cny=1.0,
        conservative_cny_per_million_tokens=10.0,
        pricing_source="https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
        pricing_checked_at="2026-10-19", authorized_by="qa",
    )
    ledger = tmp_path / "shared-budget.sqlite3"
    initialize_shared_budget(ledger, batch_id="agent-workflow-comparison-20261019",
                             pricing_checked_at="2026-10-19")
    hooks = SharedBudgetHooks(ledger, lane="AGENT_EXPERIMENT", operation_id=row.run_id)
    request = {
        "provider": "deepseek", "requested_model_alias": "deepseek-flash",
        "effective_request_model": "deepseek-flash",
        "endpoint": "https://api.deepseek.com/responses", "endpoint_path": "/responses",
        "transport_kind": "RESPONSES_JSON_SCHEMA", "attempt": 1,
        "input_token_upper_bound": 1000, "max_output_tokens": 2000,
        "input_hash": "a" * 64, "provider_payload_hash": "b" * 64,
    }
    _request_guard(db, row, shared_budget_hooks=hooks)(request)
    hooks.audit_sink({"request_identity": request, "response_source": "EXTERNAL_LLM",
                      "validation_status": "ACCEPTED",
                      "token_usage": {"prompt_tokens": 100, "completion_tokens": 50,
                                      "total_tokens": 150}})
    state = shared_budget_summary(ledger)
    assert state["by_lane"]["AGENT_EXPERIMENT"] == 1
    assert state["used_tokens"] == 150
    result = reconcile_agent_run_usage(db, ledger_path=ledger, run_id=row.run_id)
    assert result["changed"] is True
    db.refresh(row)
    assert row.model_call_count == 1 and row.input_tokens == 100 and row.output_tokens == 50
    assert row.cost_cny == pytest.approx(0.0015)
    assert loads(row.progress_json, {})["external_request_state"] == "SETTLED"
    assert reconcile_agent_run_usage(db, ledger_path=ledger, run_id=row.run_id)["changed"] is False
    assert db.query(AgentEvent).filter_by(
        agent_run_id=row.run_id, event_type="MODEL_USAGE_RECONCILED",
    ).count() == 1


def test_rejected_provider_response_settles_local_usage_before_decision_parse(tmp_path, monkeypatch):
    db, _engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    row, _ = _create_from_fixture(db, fixture, key="agent-rejected-usage-0001")
    row.status = "WAITING_AUTHORIZATION"; db.commit()
    row = authorize_agent_run(
        db, run_id=row.run_id, project_id=1, prompt_id=44, revision=row.revision,
        max_requests=1, max_total_tokens=4000, max_cost_cny=1.0,
        conservative_cny_per_million_tokens=10.0,
        pricing_source="https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
        pricing_checked_at="2026-10-19", authorized_by="qa",
    )
    ledger = tmp_path / "shared-budget-rejected.sqlite3"
    initialize_shared_budget(ledger, batch_id="agent-rejected-response-accounting",
                             pricing_checked_at="2026-10-19")
    hooks = SharedBudgetHooks(ledger, lane="AGENT_EXPERIMENT", operation_id=row.run_id)
    request = {
        "provider": "deepseek", "requested_model_alias": "deepseek-flash",
        "effective_request_model": "deepseek-flash",
        "endpoint": "https://api.deepseek.com/responses", "endpoint_path": "/responses",
        "transport_kind": "RESPONSES_JSON_SCHEMA", "attempt": 1,
        "input_token_upper_bound": 1000, "max_output_tokens": 2000,
        "input_hash": "c" * 64, "provider_payload_hash": "d" * 64,
    }
    _request_guard(db, row, shared_budget_hooks=hooks)(request)
    event = {
        "request_identity": request, "response_source": "EXTERNAL_LLM",
        "validation_status": "REJECTED", "response_model": "deepseek-flash",
        "raw_response_hash": "e" * 64, "rejection_code": "FAILED_PARSE",
        "raw_provider_response": {"model": "deepseek-flash", "output": []},
        "token_usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
    }
    archive = SecureResponseAuditArchive(tmp_path / "response-audit")
    sink = _response_audit_sink(db, row, hooks, archive)
    sink(event)
    sink(event)  # repeated reads/restarts cannot double-account a settled request
    db.refresh(row)
    state = shared_budget_summary(ledger)
    assert state["used_requests"] == 1 and state["used_tokens"] == 150
    assert row.model_call_count == 1
    assert row.input_tokens == 100 and row.output_tokens == 50
    assert row.cost_cny == pytest.approx(0.0015)
    assert loads(row.progress_json, {})["external_request_state"] == "SETTLED"
    assert loads(row.authorization_json, {})["reserved_tokens"] == 150
    assert db.query(AgentEvent).filter_by(
        agent_run_id=row.run_id, event_type="MODEL_REQUEST_ACCOUNTED",
    ).count() == 1
    assert len(list(archive.root.glob("agent-response-*.json"))) == 1


def test_incomplete_provider_response_settles_usage_and_archives_partial_output(tmp_path, monkeypatch):
    db, _engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    row, _ = _create_from_fixture(db, fixture, key="agent-incomplete-usage-0001")
    row.status = "WAITING_AUTHORIZATION"; db.commit()
    row = authorize_agent_run(
        db, run_id=row.run_id, project_id=1, prompt_id=44, revision=row.revision,
        max_requests=1, max_total_tokens=4000, max_cost_cny=1.0,
        conservative_cny_per_million_tokens=10.0,
        pricing_source="https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
        pricing_checked_at="2026-10-19", authorized_by="qa",
    )
    ledger = tmp_path / "shared-budget-incomplete.sqlite3"
    initialize_shared_budget(ledger, batch_id="agent-incomplete-accounting",
                             pricing_checked_at="2026-10-19")
    hooks = SharedBudgetHooks(ledger, lane="AGENT_EXPERIMENT", operation_id=row.run_id)
    request = {
        "provider": "deepseek", "requested_model_alias": "deepseek-flash",
        "effective_request_model": "deepseek-flash",
        "endpoint": "https://api.deepseek.com/responses", "endpoint_path": "/responses",
        "transport_kind": "RESPONSES_JSON_SCHEMA", "attempt": 1,
        "input_token_upper_bound": 1000, "max_output_tokens": 2000,
        "input_hash": "4" * 64, "provider_payload_hash": "5" * 64,
    }
    _request_guard(db, row, shared_budget_hooks=hooks)(request)
    partial = "## GEO 诊断与依据\n未完成正文，不得交付。"
    raw = {
        "id": "resp-incomplete", "model": "deepseek-flash", "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
        "output": [{"type": "message", "status": "incomplete", "content": [
            {"type": "output_text", "text": partial},
        ]}],
        "usage": {"input_tokens": 100, "output_tokens": 50,
                  "output_tokens_details": {"reasoning_tokens": 40}, "total_tokens": 150},
    }
    event = {
        "request_identity": request, "response_source": "EXTERNAL_LLM",
        "validation_status": "REJECTED", "finish_reason": "incomplete",
        "response_model": "deepseek-flash", "provider_response_id": "resp-incomplete",
        "provider_response_status": "incomplete", "incomplete_reason": "max_output_tokens",
        "provider_output_summary": [{"type": "message", "status": "incomplete"}],
        "partial_output_text": partial, "raw_response_hash": "6" * 64,
        "rejection_code": "PROVIDER_INCOMPLETE", "raw_provider_response": raw,
        "token_usage": raw["usage"],
    }
    archive = SecureResponseAuditArchive(tmp_path / "incomplete-response-audit")
    sink = _response_audit_sink(db, row, hooks, archive)
    sink(event)
    sink(event)
    db.refresh(row)
    state = shared_budget_summary(ledger)
    assert state["used_requests"] == 1 and state["used_tokens"] == 150
    assert state["requests"][0]["status"] == "FAILED"
    ledger_outcome = json.loads(state["requests"][0]["outcome_json"])
    assert "response_excerpt" not in ledger_outcome
    assert ledger_outcome["partial_output_length"] == len(partial)
    assert row.model_call_count == 1 and row.input_tokens == 100 and row.output_tokens == 50
    assert row.cost_cny == pytest.approx(0.0015)
    progress = loads(row.progress_json, {})
    assert progress["external_request_state"] == "PROVIDER_INCOMPLETE_SETTLED"
    assert progress["provider_incomplete_reason"] == "max_output_tokens"
    assert db.query(AgentResultVersion).filter_by(agent_run_id=row.run_id).count() == 0
    paths = list(archive.root.glob("agent-response-*.json"))
    assert len(paths) == 1
    stored = json.loads(paths[0].read_text(encoding="utf-8"))
    assert stored["partial_output_text"] == partial
    assert stored["raw_provider_response"] == raw


@pytest.mark.parametrize(("provider_status", "reason", "rejection_code", "expected_state"), [
    ("incomplete", "content_filter", "PROVIDER_INCOMPLETE",
     "PROVIDER_INCOMPLETE_USAGE_UNKNOWN"),
    ("completed", "UNKNOWN", "FAILED_PARSE", "PROVIDER_RESPONSE_USAGE_UNKNOWN"),
])
def test_provider_response_without_usage_keeps_conservative_hold(
    tmp_path, monkeypatch, provider_status, reason, rejection_code, expected_state,
):
    db, _engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    row, _ = _create_from_fixture(db, fixture, key="agent-incomplete-unknown-usage-0001")
    row.status = "WAITING_AUTHORIZATION"; db.commit()
    row = authorize_agent_run(
        db, run_id=row.run_id, project_id=1, prompt_id=44, revision=row.revision,
        max_requests=1, max_total_tokens=4000, max_cost_cny=1.0,
        conservative_cny_per_million_tokens=10.0,
        pricing_source="https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
        pricing_checked_at="2026-10-19", authorized_by="qa",
    )
    ledger = tmp_path / "shared-budget-incomplete-unknown.sqlite3"
    initialize_shared_budget(ledger, batch_id="agent-incomplete-unknown-accounting",
                             pricing_checked_at="2026-10-19")
    hooks = SharedBudgetHooks(ledger, lane="AGENT_EXPERIMENT", operation_id=row.run_id)
    request = {
        "provider": "deepseek", "requested_model_alias": "deepseek-flash",
        "effective_request_model": "deepseek-flash",
        "endpoint": "https://api.deepseek.com/responses", "endpoint_path": "/responses",
        "transport_kind": "RESPONSES_JSON_SCHEMA", "attempt": 1,
        "input_token_upper_bound": 1000, "max_output_tokens": 2000,
        "input_hash": "7" * 64, "provider_payload_hash": "8" * 64,
    }
    _request_guard(db, row, shared_budget_hooks=hooks)(request)
    archive = SecureResponseAuditArchive(tmp_path / "incomplete-unknown-response-audit")
    _response_audit_sink(db, row, hooks, archive)({
        "request_identity": request, "response_source": "EXTERNAL_LLM",
        "validation_status": "REJECTED", "finish_reason": provider_status,
        "response_model": "deepseek-flash", "provider_response_id": "resp-no-usage",
        "provider_response_status": provider_status, "incomplete_reason": reason,
        "partial_output_text": "", "raw_response_hash": "9" * 64,
        "rejection_code": rejection_code,
        "raw_provider_response": {
            "id": "resp-no-usage", "model": "deepseek-flash", "status": provider_status,
            "incomplete_details": ({"reason": reason} if provider_status == "incomplete" else None),
            "output": [],
        },
        "token_usage": {},
    })
    db.refresh(row)
    state = shared_budget_summary(ledger)
    assert state["used_requests"] == 1 and state["used_tokens"] == 3000
    assert state["requests"][0]["status"] == "FAILED"
    assert state["requests"][0]["actual_total_tokens"] is None
    assert row.model_call_count == 1 and row.input_tokens == row.output_tokens == 0
    progress = loads(row.progress_json, {})
    assert progress["external_request_state"] == expected_state
    assert progress["provider_incomplete_reason"] == reason
    event = db.query(AgentEvent).filter_by(
        agent_run_id=row.run_id, event_type="MODEL_REQUEST_ACCOUNTED",
    ).one()
    assert loads(event.payload_json, {})["usage_audit_state"] == "USAGE_UNKNOWN"
    assert len(list(archive.root.glob("agent-response-*.json"))) == 1


def test_provider_http_error_preserves_original_status_without_fake_usage(tmp_path, monkeypatch):
    db, _engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    row, _ = _create_from_fixture(db, fixture, key="agent-http-rejected-usage-0001")
    row.status = "WAITING_AUTHORIZATION"; db.commit()
    row = authorize_agent_run(
        db, run_id=row.run_id, project_id=1, prompt_id=44, revision=row.revision,
        max_requests=1, max_total_tokens=4000, max_cost_cny=1.0,
        conservative_cny_per_million_tokens=10.0,
        pricing_source="https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
        pricing_checked_at="2026-10-19", authorized_by="qa",
    )
    ledger = tmp_path / "shared-budget-http-rejected.sqlite3"
    initialize_shared_budget(ledger, batch_id="agent-http-rejected-accounting",
                             pricing_checked_at="2026-10-19")
    hooks = SharedBudgetHooks(ledger, lane="AGENT_EXPERIMENT", operation_id=row.run_id)
    request = {
        "provider": "deepseek", "requested_model_alias": "deepseek-flash",
        "effective_request_model": "deepseek-flash",
        "endpoint": "https://api.deepseek.com/responses", "endpoint_path": "/responses",
        "transport_kind": "RESPONSES_JSON_SCHEMA", "attempt": 1,
        "input_token_upper_bound": 1000, "max_output_tokens": 2000,
        "input_hash": "1" * 64, "provider_payload_hash": "2" * 64,
    }
    _request_guard(db, row, shared_budget_hooks=hooks)(request)
    archive = SecureResponseAuditArchive(tmp_path / "http-response-audit")
    _response_audit_sink(db, row, hooks, archive)({
        "request_identity": request, "response_source": "EXTERNAL_LLM",
        "validation_status": "REJECTED", "response_model": "",
        "raw_response_hash": "3" * 64, "rejection_code": "PROVIDER_HTTP_ERROR",
        "rejection_reason": "DeepSeek HTTP 400", "raw_provider_response": None,
        "raw_http_response": '{"error":{"type":"invalid_request_error"}}',
        "http_status": 400, "provider_error_category": "invalid_request_error",
        "token_usage": {},
    })
    db.refresh(row)
    progress = loads(row.progress_json, {})
    state = shared_budget_summary(ledger)
    assert row.model_call_count == 1
    assert row.input_tokens == row.output_tokens == 0 and row.cost_cny == 0
    assert progress["external_request_state"] == "PROVIDER_REJECTED_USAGE_UNKNOWN"
    assert progress["provider_http_status"] == 400
    assert state["used_requests"] == 1 and state["used_tokens"] == 3000
    assert state["in_flight"] == 0
    assert state["requests"][0]["actual_total_tokens"] is None
    assert json.loads(state["requests"][0]["outcome_json"])["http_status"] == 400
    assert len(list(archive.root.glob("agent-response-*.json"))) == 1


def test_external_agent_execution_without_shared_guard_fails_before_model(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    row, _ = _create_from_fixture(db, fixture, key="agent-unmetered-denied-0001")
    row.status = "WAITING_AUTHORIZATION"; db.commit()
    row = authorize_agent_run(
        db, run_id=row.run_id, project_id=1, prompt_id=44, revision=row.revision,
        max_requests=1, max_total_tokens=4000, max_cost_cny=1.0,
        conservative_cny_per_million_tokens=10.0,
        pricing_source="https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
        pricing_checked_at="2026-10-19", authorized_by="qa",
    )
    client = ScriptedClient([])
    execute_agent_run(row.run_id, session_factory=sessionmaker(bind=engine, expire_on_commit=False),
                      client=client)
    db.expire_all()
    stored = db.query(AgentExperimentRun).filter_by(run_id=row.run_id).one()
    assert stored.status == "FAILED"
    assert stored.blocker_code == "SHARED_BUDGET_GUARD_REQUIRED"
    assert client.calls == 0


def test_historical_scope_ignores_only_additive_live_run_lineage():
    frozen = {"run_id": 1, "status": "success", "answer_text": "frozen"}
    assert _matches_frozen_run(frozen, {
        **frozen, "attempt_id": "attempt-added-later", "attempt_no": 1,
        "logical_run_id": "logical-added-later", "retry_of_run_id": None,
    })
    assert not _matches_frozen_run(frozen, {**frozen, "answer_text": "changed"})
    assert not _matches_frozen_run(frozen, {"run_id": 1, "status": "success"})


def test_idempotent_retry_reuses_run_and_explicit_regenerate_preserves_old_version(tmp_path, monkeypatch):
    db, _engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    first, created = _create_from_fixture(db, fixture, key="agent-idempotent-0001")
    retried, retried_created = _create_from_fixture(db, fixture, key="agent-idempotent-0001")
    assert created is True and retried_created is False and retried.run_id == first.run_id
    regenerated, regenerated_created = create_agent_run(
        db, project_id=1, prompt_id=44, analysis_id=fixture["analysis"].analysis_id,
        context_id=fixture["context"].context_id,
        citation_manifest_id=fixture["manifest"].manifest_id,
        citation_manifest_hash=fixture["manifest"].payload_hash,
        completion_manifest_id=fixture["completion"].manifest_id,
        completion_manifest_hash=fixture["completion"].payload_hash,
        idempotency_key="agent-regenerate-0001", requested_by="qa", regenerate_nonce="manual-2",
    )
    assert regenerated_created is True and regenerated.run_id != first.run_id
    assert regenerated.input_scope_hash == first.input_scope_hash
    assert regenerated.agent_execution_hash != first.agent_execution_hash
    assert db.query(AgentExperimentRun).count() == 2


def test_output_validation_rejects_unread_passage_then_accepts_bounded_repair(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run, _ = _create_from_fixture(db, fixture, key="agent-repair-0001")
    scope = loads(run.input_scope_json, {})
    source = scope["source_snapshots"][0]
    answer = scope["runs"][0]["answer_text"]
    client = ScriptedClient([
        {"action_type": "TOOL_CALL", "reasoning": "读取回答", "tool_name": "read_answer",
         "arguments": {"run_id": str(fixture["run"].id), "start": 0, "end": len(answer)},
         "artifact": None, "stop_reason": None},
        {"action_type": "FINAL_ARTIFACT", "reasoning": "第一次候选错误引用未读取来源", "tool_name": None,
         "arguments": None, "artifact": _artifact(run_id=fixture["run"].id,
         answer_end=len(answer), source=source), "stop_reason": None},
        {"action_type": "FINAL_ARTIFACT", "reasoning": "删除未准入事实并降为核验型内容", "tool_name": None,
         "arguments": None, "artifact": _artifact(run_id=fixture["run"].id,
         answer_end=len(answer)), "stop_reason": None},
    ])
    execute_agent_run(run.run_id, session_factory=sessionmaker(bind=engine, expire_on_commit=False), client=client)
    db.expire_all()
    stored = db.query(AgentExperimentRun).filter_by(run_id=run.run_id).one()
    result = db.query(AgentResultVersion).filter_by(agent_run_id=run.run_id).one()
    assert stored.status == "SUCCEEDED" and stored.model_call_count == 3
    assert result.evidence_grade == "L3_ACTIONABLE_WITHOUT_FACT_CLAIMS"
    assert db.query(AgentEvent).filter_by(agent_run_id=run.run_id, event_type="OUTPUT_REJECTED").count() == 1


def test_cancelled_queued_run_never_calls_model_or_creates_result(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run, _ = _create_from_fixture(db, fixture, key="agent-cancel-0001")
    cancelled = cancel_agent_run(db, run_id=run.run_id, project_id=1, prompt_id=44)
    client = ScriptedClient([])
    execute_agent_run(run.run_id, session_factory=sessionmaker(bind=engine, expire_on_commit=False), client=client)
    db.refresh(cancelled)
    assert cancelled.status == "CANCELLED" and client.calls == 0
    assert db.query(AgentResultVersion).filter_by(agent_run_id=run.run_id).count() == 0


def test_l3_server_rejects_model_claim_that_answer_only_fact_is_verified(tmp_path, monkeypatch):
    db, _engine = _migrated_session(tmp_path, monkeypatch)
    analysis = _seed_frozen_analysis(db, reference_urls=[])
    context = db.query(SinglePromptAnalysisContext).filter_by(analysis_id=analysis.analysis_id).one()
    run, _ = create_agent_run(
        db, project_id=1, prompt_id=44, analysis_id=analysis.analysis_id, context_id=context.context_id,
        idempotency_key="agent-l3-fact-reject-0001", requested_by="qa",
    )
    scope = loads(run.input_scope_json, {})
    answer = scope["runs"][0]["answer_text"]
    observation = ToolRegistry(db, run).call(
        "read_answer", {"run_id": str(scope["runs"][0]["run_id"]), "start": 0, "end": len(answer)},
    )
    payload = _artifact(run_id=scope["runs"][0]["run_id"], answer_end=len(answer))
    payload["observations"][0]["classification"] = "VERIFIED_FACT"
    validation, eligibility = validate_and_grade(AgentArtifact.model_validate(payload), scope, [observation])
    assert eligibility["evidence_grade"] == "L3_ACTIONABLE_WITHOUT_FACT_CLAIMS"
    assert validation["status"] == "FAIL"
    assert "L3_VERIFIED_FACT_NOT_ALLOWED" in {row["code"] for row in validation["issues"]}
