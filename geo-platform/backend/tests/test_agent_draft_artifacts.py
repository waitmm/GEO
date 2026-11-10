from __future__ import annotations

import json
from pathlib import Path
import re

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException, Response
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import sessionmaker

from app.models import (
    AgentDraftArtifactRegeneration, AgentDraftArtifactVersion,
    AgentExperimentRun, AgentResultVersion,
)
from app.modules.agent_experiment.evidence_pack import (
    _draft_similarity_metrics, _has_sufficient_faq_structure,
    _has_unsupported_numeric_claim, _help_doc_structure_metrics, build_evidence_pack,
    validate_markdown_result,
)
from app.modules.agent_experiment.api import (
    AgentDraftArtifactRegenerate, read_agent_capabilities, regenerate_draft_artifact,
)
from app.modules.agent_experiment.runner import _save_result, execute_agent_run
from app.modules.agent_experiment.regeneration import (
    execute_draft_artifact_regeneration, recover_interrupted_draft_regenerations,
)
from app.modules.agent_experiment.service import (
    add_draft_artifact_feedback,
    complete_draft_artifact_regeneration,
    cancel_draft_artifact_regeneration,
    create_agent_run,
    draft_artifact_export,
    list_agent_results,
    list_draft_artifact_feedback,
    list_draft_artifacts,
    queue_draft_artifact_regeneration,
)
from app.services.serialization import loads
from test_agent_experiment import (
    CURRENT_PRICING_DATE, ScriptedEvidencePackClient, _artifact, _evidence_markdown,
)
from test_release_first_slice import _migrated_session, _seed_citation_contribution_fixture


ELIGIBILITY = {
    "evidence_grade": "L3_ACTIONABLE_WITHOUT_FACT_CLAIMS",
    "public_claim_eligibility": "NOT_CONSUMABLE",
    "publication_eligibility": "VERIFY_FIRST",
}
ROOT = Path(__file__).resolve().parents[1]
REGENERATION_AUDIT_COLUMNS = {
    "attempt_count", "usage_json", "audit_json", "cancel_requested_at",
    "started_at", "finished_at", "updated_at",
}


def _run(db, fixture, key="multi-content-run-0001"):
    row, _ = create_agent_run(
        db, project_id=1, prompt_id=44, analysis_id=fixture["analysis"].analysis_id,
        context_id=fixture["context"].context_id,
        citation_manifest_id=fixture["manifest"].manifest_id,
        citation_manifest_hash=fixture["manifest"].payload_hash,
        completion_manifest_id=fixture["completion"].manifest_id,
        completion_manifest_hash=fixture["completion"].payload_hash,
        idempotency_key=key, requested_by="qa", execution_mode="TOOL_LOOP")
    return row


def _multi_result():
    result = _artifact(run_id=1, answer_end=20)
    result["deliverables"][0]["artifact_validation"] = {"status": "PASS", "issues": []}
    result["deliverables"].append({
        "id": "faq-1", "action_ids": ["action-1"], "asset_type": "FAQ",
        "title": "短链接常见问题", "body_markdown": "",
        "editorial_notes": ["缺失正文应独立失败，不影响帮助文档"],
        "artifact_validation": {
            "status": "FAIL",
            "issues": [{"code": "DELIVERABLE_INCOMPLETE", "detail": "FAQ 正文为空"}],
        },
    })
    return result


def _help_doc_body():
    return (
        "这是一份面向当前搜索问题的可编辑操作说明，所有品牌能力在发布前都必须依据冻结事实核验。\n\n"
        "### 步骤一：确认使用条件\n\n"
        "先核对账号权限、目标页面、输入范围与失败回退方式，记录当前平台和设备环境。"
        "不要把竞品能力或未知第三方描述写成目标品牌承诺。\n\n"
        "### 步骤二：执行小范围测试\n\n"
        "选择一组可复现样例，保存原始输入后执行操作，并逐项记录跳转结果、异常现象和实际限制。"
        "如果页面无法打开，应停止扩大范围，返回官方配置与权限检查。\n\n"
        "### 步骤三：检查并交付\n\n"
        "核对正文中的适用条件、失败处理和隐私边界，确认每项品牌事实都有已核实资料或权威来源。"
        "完成内容后保存版本，再用同一问题版本、采样配置和样本范围验证结果。"
    )


def test_quality_gate_boundaries_ignore_short_shared_facts_and_accept_ordered_steps():
    shared = "爱短链相关能力必须依据已核实品牌资料，不能把竞品能力迁移成品牌事实。"
    assert _draft_similarity_metrics(shared * 2, shared * 2)["triggered"] is False
    help_body = shared * 3 + "选择样例并记录输入输出，检查失败回退和权限。" * 6
    faq_body = shared * 3 + "用户常问适用条件与限制，回答必须保留待核实事项。" * 6
    metrics = _draft_similarity_metrics(help_body, faq_body)
    assert metrics["left_normalized_chars"] >= 180
    assert metrics["right_normalized_chars"] >= 180
    assert metrics["triggered"] is False
    ordered = (
        "1. 选择一组可复现样例并保存输入。\n"
        "2. 执行小范围测试并记录错误。\n"
        "3. 检查结果，确认限制后保存版本。"
    )
    assert _help_doc_structure_metrics(ordered)["passed"] is True


def test_help_doc_structure_does_not_count_action_words_in_headings():
    narrative_filler = (
        "这一部分主要介绍相关背景、适用范围、风险边界和编辑原则。"
        "内容用于说明上下文，不包含面向使用者的具体动作指令。"
    ) * 8
    headings_only = (
        f"### 配置\n\n{narrative_filler}\n\n"
        f"### 执行\n\n{narrative_filler}"
    )
    metrics = _help_doc_structure_metrics(headings_only)
    assert metrics["step_heading_count"] == 2
    assert metrics["operation_verb_count"] == 0
    assert metrics["actionable_unit_count"] == 0
    assert metrics["passed"] is False

    real_steps = _help_doc_structure_metrics(_help_doc_body())
    assert real_steps["operation_verb_count"] >= 2
    assert real_steps["actionable_unit_count"] >= 2
    assert real_steps["passed"] is True


def test_faq_structure_accepts_numbered_bold_questions_but_rejects_plain_copy():
    faq = (
        "**Q1：使用前需要确认什么？**\nA：确认真实权限与限制。\n\n"
        "**Q2: 结果异常怎么办？**\nA：停止扩大范围并复测。"
    )
    assert _has_sufficient_faq_structure(faq) is True
    assert _has_sufficient_faq_structure("只有两段说明，没有明确问题与回答。") is False
    assert _has_sufficient_faq_structure("**Q1：问题一？**\n\n**Q2：问题二？**") is False
    assert _has_sufficient_faq_structure("**Q1：问题一？**\nA：\n\n**Q2：问题二？**\n答：") is False
    assert _has_sufficient_faq_structure(
        "**Q1：问题一？**\n**A：**\n\n**Q2：问题二？**\n**答：**"
    ) is False
    assert _has_sufficient_faq_structure(
        "**Q1：问题一？**\nA1：\n\n**Q2：问题二？**\nA2："
    ) is False
    assert _has_sufficient_faq_structure(
        "```markdown\n**Q1：示例一？**\nA：示例。\n**Q2：示例二？**\nA：示例。\n```"
    ) is False
    assert _has_sufficient_faq_structure(
        "~~~markdown\n**Q1：示例一？**\nA：示例。\n**Q2：示例二？**\nA：示例。\n~~~"
    ) is False


def test_numeric_claim_gate_ignores_explicit_prohibition_but_blocks_real_claim():
    assert _has_unsupported_numeric_claim(
        "全文搜索敏感词：免费、永久、100%、保证。命中即删或改。"
    ) is True
    assert _has_unsupported_numeric_claim("不得写100%的成功率承诺。") is True
    assert _has_unsupported_numeric_claim("实测成功率可达100%。") is True
    assert _has_unsupported_numeric_claim("套餐价格为99元。") is True
    assert _has_unsupported_numeric_claim("不要错过20%的折扣。") is True
    assert _has_unsupported_numeric_claim("套餐价格不得低于99元。") is True
    assert _has_unsupported_numeric_claim("为避免风险，回报20%。") is True
    assert _has_unsupported_numeric_claim(
        "敏感词命中即删或改，但本产品成功率达到100%。"
    ) is True
    assert _has_unsupported_numeric_claim(
        "敏感词清单：保证。我们产品成功率达到100%。命中即删或改。"
    ) is True
    assert _has_unsupported_numeric_claim(
        "敏感词清单：保证，但我们实测成功率达到100%，命中即删或改。"
    ) is True


def _multi_markdown(pack, *, valid_faq=True):
    markdown = _evidence_markdown(pack).replace("## 完整正文", "## 帮助文档")
    before, remainder = markdown.split("## 帮助文档", 1)
    _old_help, after = remainder.split("## QA 与事实限制", 1)
    markdown = f"{before}## 帮助文档\n{_help_doc_body()}\n\n## QA 与事实限制{after}"
    faq = ("### 批量处理前需要确认什么？\n\n需要确认账号权限、处理数量、失败回退和可核验资料，"
           "不能把尚未确认的品牌能力写成承诺。编辑应保存测试条件、输入样例与失败记录。\n\n"
           "### 结果异常时如何处理？\n\n先停止扩大范围，核对输入、平台限制和真实错误，再用小样本复测。"
           "如果证据不足，明确标记待核实并补充官方资料，不根据竞品页面反推目标品牌能力。\n\n"
           "### 哪些信息可以写进对外稿件？\n\n只写冻结证据能够支持的操作步骤、适用条件和限制。"
           "价格、效果承诺、平台兼容性等事实必须能够定位到已核实品牌资料或权威来源；"
           "无法核实的内容应明确列入待核验清单，核验后再发布。")
    if not valid_faq:
        faq = "只有一个尚未完成的问题。"
    return markdown.replace("## QA 与事实限制", f"## 常见问题\n{faq}\n\n## QA 与事实限制")


def _faq_markdown(pack, *, valid=True):
    markdown = _evidence_markdown(pack)
    before, remainder = markdown.split("## 完整正文", 1)
    _old_body, after = remainder.split("## QA 与事实限制", 1)
    faq = ("### 使用前需要核对什么？\n\n核对真实账号权限、输入范围、失败回退与官方资料，"
           "不要把竞品能力写成目标品牌事实。保存测试条件和原始错误，确保编辑可以复核。\n\n"
           "### 结果不符合预期怎么办？\n\n先缩小处理范围，核对平台限制与真实错误，再用小样本复测。"
           "证据不足时必须标记待核实，并在发布前补充已核实品牌资料或权威来源。\n\n"
           "### 哪些事实可以对外使用？\n\n只有冻结证据明确支持的适用条件、操作步骤和限制可以使用。"
           "价格、效果和兼容性等表述必须逐项核验，无法核验的内容继续保留在待确认清单中。")
    if not valid:
        faq = "只有一条未完成的回答。"
    return f"{before}## 常见问题\n{faq}\n\n## QA 与事实限制{after}"


def test_internal_authoring_leak_fails_only_affected_draft_asset(tmp_path, monkeypatch):
    db, _engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run = _run(db, fixture, "multi-content-internal-leak-0001")
    pack = build_evidence_pack(loads(run.input_scope_json, {}))
    markdown = _multi_markdown(pack).replace(
        "### 批量处理前需要确认什么？",
        "### 批量处理前需要确认什么？\n\n"
        "请编辑打开 Evidence Pack，核查 product_truth 后删除未经证实的表述。",
    )
    checked, _ = validate_markdown_result(
        markdown, pack, requested_artifact_types=["HELP_DOC", "FAQ"],
    )
    by_type = {
        row["asset_type"]: row for row in checked["result"]["deliverables"]
    }
    assert checked["validation"]["status"] == "PARTIAL"
    assert by_type["HELP_DOC"]["artifact_validation"]["status"] == "PASS"
    assert by_type["FAQ"]["artifact_validation"]["status"] == "FAIL"
    assert "INTERNAL_AUTHORING_INSTRUCTION_LEAK" in {
        row["code"] for row in by_type["FAQ"]["artifact_validation"]["issues"]
    }


def test_evidence_pack_selection_freezes_and_generates_two_distinct_assets(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run, _ = create_agent_run(
        db, project_id=1, prompt_id=44, analysis_id=fixture["analysis"].analysis_id,
        context_id=fixture["context"].context_id,
        citation_manifest_id=fixture["manifest"].manifest_id,
        citation_manifest_hash=fixture["manifest"].payload_hash,
        completion_manifest_id=fixture["completion"].manifest_id,
        completion_manifest_hash=fixture["completion"].payload_hash,
        idempotency_key="multi-content-evidence-0001", requested_by="qa",
        execution_mode="EVIDENCE_PACK", requested_artifact_types=["FAQ", "HELP_DOC"])
    scope = loads(run.input_scope_json, {})
    execution = loads(run.agent_execution_json, {})
    assert scope["requested_artifact_types"] == ["HELP_DOC", "FAQ"]
    assert execution["requested_artifact_types"] == ["HELP_DOC", "FAQ"]
    pack = build_evidence_pack(scope)
    execute_agent_run(
        run.run_id, session_factory=sessionmaker(bind=engine, expire_on_commit=False),
        client=ScriptedEvidencePackClient(_multi_markdown(pack)))
    db.expire_all()
    stored = db.query(AgentExperimentRun).filter_by(run_id=run.run_id).one()
    artifacts = list_draft_artifacts(db, run_id=run.run_id, project_id=1, prompt_id=44)
    assert stored.status == "SUCCEEDED", (stored.blocker_code, stored.blocker_detail)
    assert {row["artifact_type"] for row in artifacts} == {"HELP_DOC", "FAQ"}
    assert all(row["status"] == "SUCCESS" for row in artifacts)
    assert len({row["body_markdown"] for row in artifacts}) == 2
    for row in artifacts:
        metrics = row["qa"]["artifact_validation"]["quality_metrics"]
        assert metrics["cross_asset_similarity"]["triggered"] is False
    help_doc = next(row for row in artifacts if row["artifact_type"] == "HELP_DOC")
    assert help_doc["qa"]["artifact_validation"]["quality_metrics"][
        "operation_structure"]["passed"] is True


def test_dual_asset_unstructured_help_fails_only_help_and_keeps_faq(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run, _ = create_agent_run(
        db, project_id=1, prompt_id=44, analysis_id=fixture["analysis"].analysis_id,
        context_id=fixture["context"].context_id,
        citation_manifest_id=fixture["manifest"].manifest_id,
        citation_manifest_hash=fixture["manifest"].payload_hash,
        completion_manifest_id=fixture["completion"].manifest_id,
        completion_manifest_hash=fixture["completion"].payload_hash,
        idempotency_key="multi-content-unstructured-help", requested_by="qa",
        execution_mode="EVIDENCE_PACK", requested_artifact_types=["HELP_DOC", "FAQ"])
    pack = build_evidence_pack(loads(run.input_scope_json, {}))
    markdown = _multi_markdown(pack)
    before, remainder = markdown.split("## 帮助文档", 1)
    _help, after = remainder.split("## 常见问题", 1)
    unstructured = (
        "当前问题需要先理解使用环境、账号权限、目标页面和失败风险。编辑应当核对真实资料，"
        "保留适用条件与限制，不把竞品能力迁移成目标品牌事实。为了提高内容可读性，还需要"
        "说明输入范围、异常现象、隐私边界和复测条件。\n\n"
        "本文建议使用小样本观察结果，保存原始输入与实际错误，并在发现异常时停止扩大范围。"
        "所有价格、效果、平台兼容性和品牌能力都必须由已核实品牌资料或权威来源支持。"
        "内容交付后应使用同一问题版本、采样配置与样本范围复测，但不能宣称变化存在因果。"
    )
    markdown = f"{before}## 帮助文档\n{unstructured}\n\n## 常见问题{after}"
    execute_agent_run(
        run.run_id, session_factory=sessionmaker(bind=engine, expire_on_commit=False),
        client=ScriptedEvidencePackClient(markdown))
    db.expire_all()
    artifacts = list_draft_artifacts(db, run_id=run.run_id, project_id=1, prompt_id=44)
    assert {(row["artifact_type"], row["status"]) for row in artifacts} == {
        ("HELP_DOC", "FAILED"), ("FAQ", "SUCCESS")}
    help_doc = next(row for row in artifacts if row["artifact_type"] == "HELP_DOC")
    assert "HELP_DOC_OPERATION_STRUCTURE_REQUIRED" in {
        issue["code"] for issue in help_doc["qa"]["artifact_validation"]["issues"]}
    assert help_doc["qa"]["artifact_validation"]["quality_metrics"][
        "operation_structure"]["passed"] is False


def test_dual_asset_substantive_copy_fails_both_with_auditable_metrics(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run, _ = create_agent_run(
        db, project_id=1, prompt_id=44, analysis_id=fixture["analysis"].analysis_id,
        context_id=fixture["context"].context_id,
        citation_manifest_id=fixture["manifest"].manifest_id,
        citation_manifest_hash=fixture["manifest"].payload_hash,
        completion_manifest_id=fixture["completion"].manifest_id,
        completion_manifest_hash=fixture["completion"].payload_hash,
        idempotency_key="multi-content-substantive-copy", requested_by="qa",
        execution_mode="EVIDENCE_PACK", requested_artifact_types=["HELP_DOC", "FAQ"])
    pack = build_evidence_pack(loads(run.input_scope_json, {}))
    markdown = _multi_markdown(pack)
    before_faq, faq_and_after = markdown.split("## 常见问题", 1)
    _faq, after_faq = faq_and_after.split("## QA 与事实限制", 1)
    markdown = f"{before_faq}## 常见问题\n{_help_doc_body()}\n\n## QA 与事实限制{after_faq}"
    execute_agent_run(
        run.run_id, session_factory=sessionmaker(bind=engine, expire_on_commit=False),
        client=ScriptedEvidencePackClient(markdown))
    db.expire_all()
    stored = db.query(AgentExperimentRun).filter_by(run_id=run.run_id).one()
    artifacts = list_draft_artifacts(db, run_id=run.run_id, project_id=1, prompt_id=44)
    assert stored.status == "FAILED"
    assert {row["status"] for row in artifacts} == {"FAILED"}
    for row in artifacts:
        validation = row["qa"]["artifact_validation"]
        assert "ARTIFACT_CONTENT_TOO_SIMILAR" in {
            issue["code"] for issue in validation["issues"]}
        metrics = validation["quality_metrics"]["cross_asset_similarity"]
        assert metrics["algorithm"] == "geo.draft-content-similarity.v1"
        assert metrics["triggered"] is True
        assert metrics["jaccard"] == 1.0 and metrics["containment"] == 1.0


def test_evidence_pack_two_asset_partial_success_keeps_good_sibling(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run, _ = create_agent_run(
        db, project_id=1, prompt_id=44, analysis_id=fixture["analysis"].analysis_id,
        context_id=fixture["context"].context_id,
        citation_manifest_id=fixture["manifest"].manifest_id,
        citation_manifest_hash=fixture["manifest"].payload_hash,
        completion_manifest_id=fixture["completion"].manifest_id,
        completion_manifest_hash=fixture["completion"].payload_hash,
        idempotency_key="multi-content-evidence-0002", requested_by="qa",
        execution_mode="EVIDENCE_PACK", requested_artifact_types=["HELP_DOC", "FAQ"])
    pack = build_evidence_pack(loads(run.input_scope_json, {}))
    execute_agent_run(
        run.run_id, session_factory=sessionmaker(bind=engine, expire_on_commit=False),
        client=ScriptedEvidencePackClient(_multi_markdown(pack, valid_faq=False)))
    db.expire_all()
    stored = db.query(AgentExperimentRun).filter_by(run_id=run.run_id).one()
    artifacts = list_draft_artifacts(db, run_id=run.run_id, project_id=1, prompt_id=44)
    assert stored.status == "PARTIAL", (stored.blocker_code, stored.blocker_detail)
    assert {(row["artifact_type"], row["status"]) for row in artifacts} == {
        ("HELP_DOC", "SUCCESS"), ("FAQ", "FAILED")}
    failed = next(row for row in artifacts if row["artifact_type"] == "FAQ")
    assert failed["failure"]["code"] == "ARTIFACT_VALIDATION_FAILED"
    assert {issue["code"] for issue in failed["qa"]["artifact_validation"]["issues"]} == {
        "DELIVERABLE_INCOMPLETE", "FAQ_STRUCTURE_REQUIRED"}
    assert list_agent_results(db, run_id=run.run_id, project_id=1, prompt_id=44)[0][
        "draft_delivery_status"] == "PARTIAL_SUCCESS"


def test_asset_scoped_invalid_reference_fails_only_faq_and_keeps_help_exportable(
    tmp_path, monkeypatch,
):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run, _ = create_agent_run(
        db, project_id=1, prompt_id=44, analysis_id=fixture["analysis"].analysis_id,
        context_id=fixture["context"].context_id,
        citation_manifest_id=fixture["manifest"].manifest_id,
        citation_manifest_hash=fixture["manifest"].payload_hash,
        completion_manifest_id=fixture["completion"].manifest_id,
        completion_manifest_hash=fixture["completion"].payload_hash,
        idempotency_key="multi-content-asset-invalid-ref", requested_by="qa",
        execution_mode="EVIDENCE_PACK", requested_artifact_types=["HELP_DOC", "FAQ"])
    pack = build_evidence_pack(loads(run.input_scope_json, {}))
    markdown = _multi_markdown(pack).replace(
        "### 批量处理前需要确认什么？",
        "[[answer:999999:0:999]]\n\n### 批量处理前需要确认什么？", 1)
    execute_agent_run(
        run.run_id, session_factory=sessionmaker(bind=engine, expire_on_commit=False),
        client=ScriptedEvidencePackClient(markdown))
    db.expire_all()
    stored = db.query(AgentExperimentRun).filter_by(run_id=run.run_id).one()
    result = list_agent_results(db, run_id=run.run_id, project_id=1, prompt_id=44)[0]
    artifacts = result["draft_artifacts"]
    help_doc = next(row for row in artifacts if row["artifact_type"] == "HELP_DOC")
    faq = next(row for row in artifacts if row["artifact_type"] == "FAQ")
    assert stored.status == "PARTIAL"
    assert result["validation"]["status"] == "PARTIAL"
    assert result["draft_delivery_status"] == "PARTIAL_SUCCESS"
    assert help_doc["status"] == "SUCCESS"
    assert faq["status"] == "FAILED"
    assert all(reference.get("locator") != "999999:0:999"
               for reference in help_doc["evidence"]["result_evidence_references"])
    assert any(reference.get("locator") == "999999:0:999"
               for reference in faq["evidence"]["result_evidence_references"])
    assert "ANSWER_REF_OUT_OF_SCOPE" in {
        issue["code"] for issue in faq["qa"]["artifact_validation"]["issues"]}
    assert draft_artifact_export(
        db, artifact_version=help_doc["artifact_version"], project_id=1,
        prompt_id=44)["content"] == help_doc["body_markdown"]
    with pytest.raises(HTTPException) as blocked:
        draft_artifact_export(
            db, artifact_version=faq["artifact_version"], project_id=1, prompt_id=44)
    assert blocked.value.status_code == 409


def test_shared_section_invalid_reference_fails_all_children_and_parent(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run, _ = create_agent_run(
        db, project_id=1, prompt_id=44, analysis_id=fixture["analysis"].analysis_id,
        context_id=fixture["context"].context_id,
        citation_manifest_id=fixture["manifest"].manifest_id,
        citation_manifest_hash=fixture["manifest"].payload_hash,
        completion_manifest_id=fixture["completion"].manifest_id,
        completion_manifest_hash=fixture["completion"].payload_hash,
        idempotency_key="multi-content-shared-invalid-ref", requested_by="qa",
        execution_mode="EVIDENCE_PACK", requested_artifact_types=["HELP_DOC", "FAQ"])
    pack = build_evidence_pack(loads(run.input_scope_json, {}))
    markdown = re.sub(
        r"\[\[answer:[^\]]+\]\]", "[[answer:999999:0:999]]",
        _multi_markdown(pack), count=1)
    execute_agent_run(
        run.run_id, session_factory=sessionmaker(bind=engine, expire_on_commit=False),
        client=ScriptedEvidencePackClient(markdown))
    db.expire_all()
    stored = db.query(AgentExperimentRun).filter_by(run_id=run.run_id).one()
    result = list_agent_results(db, run_id=run.run_id, project_id=1, prompt_id=44)[0]
    artifacts = result["draft_artifacts"]
    assert stored.status == "FAILED"
    assert result["validation"]["status"] == "FAIL"
    assert result["validation"]["shared_issue_count"] >= 1
    assert result["draft_delivery_status"] == "FAILED"
    assert {row["status"] for row in artifacts} == {"FAILED"}
    for artifact in artifacts:
        assert "ANSWER_REF_OUT_OF_SCOPE" in {
            issue["code"] for issue in artifact["qa"]["artifact_validation"]["issues"]}
        with pytest.raises(HTTPException) as blocked:
            draft_artifact_export(
                db, artifact_version=artifact["artifact_version"], project_id=1,
                prompt_id=44)
        assert blocked.value.status_code == 409


def test_parent_is_frozen_optimize_and_child_failures_are_independent(tmp_path, monkeypatch):
    db, _engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run = _run(db, fixture)
    parent = _save_result(
        db, run, _multi_result(), {"status": "PASS", "issues": []},
        ELIGIBILITY, status="SUCCEEDED")

    artifacts = list_draft_artifacts(
        db, run_id=run.run_id, project_id=1, prompt_id=44,
        result_version=parent.result_version)
    assert {(row["artifact_type"], row["status"]) for row in artifacts} == {
        ("HELP_DOC", "SUCCESS"), ("FAQ", "FAILED")}
    result = list_agent_results(db, run_id=run.run_id, project_id=1, prompt_id=44)[0]
    assert result["result_version"] == parent.result_version
    assert result["draft_delivery_status"] == "PARTIAL_SUCCESS"
    assert result["result"]["deliverables"][0]["body_markdown"]
    assert next(row for row in artifacts if row["artifact_type"] == "FAQ")["failure"]["code"] == \
        "ARTIFACT_BODY_REQUIRED"


def test_asset_feedback_export_and_cross_scope_are_exact(tmp_path, monkeypatch):
    db, _engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run = _run(db, fixture, "multi-content-run-0002")
    _save_result(db, run, _multi_result(), {"status": "PASS"}, ELIGIBILITY, status="SUCCEEDED")
    help_doc = next(row for row in list_draft_artifacts(
        db, run_id=run.run_id, project_id=1, prompt_id=44) if row["artifact_type"] == "HELP_DOC")

    feedback = add_draft_artifact_feedback(
        db, artifact_version=help_doc["artifact_version"], project_id=1, prompt_id=44,
        submitted_by="employee", rating="USABLE", reason_tags=[], suggestion="可采用",
        adoption_status="ADOPTED", modification_level="LIGHT", modification_summary="调整标题")
    assert list_draft_artifact_feedback(
        db, artifact_version=help_doc["artifact_version"], project_id=1, prompt_id=44
    )[0]["feedback_id"] == feedback.feedback_id
    exported = draft_artifact_export(
        db, artifact_version=help_doc["artifact_version"], project_id=1, prompt_id=44)
    assert exported["artifact_hash"] == help_doc["artifact_hash"]
    assert exported["content"].startswith("# 短链工具")
    with pytest.raises(HTTPException) as foreign:
        draft_artifact_export(
            db, artifact_version=help_doc["artifact_version"], project_id=2, prompt_id=44)
    assert foreign.value.status_code == 404


def test_single_asset_regeneration_is_idempotent_and_preserves_parent_and_sibling(tmp_path, monkeypatch):
    db, _engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run = _run(db, fixture, "multi-content-run-0003")
    parent = _save_result(db, run, _multi_result(), {"status": "PASS"}, ELIGIBILITY, status="SUCCEEDED")
    before = list_draft_artifacts(db, run_id=run.run_id, project_id=1, prompt_id=44)
    faq = next(row for row in before if row["artifact_type"] == "FAQ")
    sibling = next(row for row in before if row["artifact_type"] == "HELP_DOC")

    policy = {"max_requests": 1, "max_total_tokens": 300_000, "max_cost_cny": 5.0,
              "pricing_source": "server-test", "pricing_checked_at": CURRENT_PRICING_DATE}
    request, created = queue_draft_artifact_regeneration(
        db, artifact_version=faq["artifact_version"], project_id=1, prompt_id=44,
        idempotency_key="faq-regeneration-0001", requested_by="employee", server_policy=policy)
    same, created_again = queue_draft_artifact_regeneration(
        db, artifact_version=faq["artifact_version"], project_id=1, prompt_id=44,
        idempotency_key="faq-regeneration-0001", requested_by="employee", server_policy=policy)
    assert created is True and created_again is False and same.request_id == request.request_id

    regenerated = complete_draft_artifact_regeneration(db, request_id=request.request_id, generated={
        "asset_type": "FAQ", "title": "短链接常见问题",
        "body_markdown": "# 常见问题\n\n## 批量处理前要核对什么？\n\n核对权限、数量、失败回退和事实来源。",
        "action_ids": ["action-1"], "editorial_notes": ["发布前核实品牌能力"],
        "qa": {"status": "PASS", "verify_first": True},
        "artifact_validation": {"status": "PASS", "issues": []},
    })
    repeat = complete_draft_artifact_regeneration(
        db, request_id=request.request_id, generated={"asset_type": "FAQ"})
    assert regenerated.artifact_version == repeat.artifact_version
    assert regenerated.previous_artifact_version == faq["artifact_version"]
    assert regenerated.status == "SUCCESS"
    assert db.query(AgentResultVersion).filter_by(result_version=parent.result_version).one().result_hash == \
        parent.result_hash
    assert db.query(AgentDraftArtifactVersion).filter_by(
        artifact_version=sibling["artifact_version"]).one().artifact_hash == sibling["artifact_hash"]
    assert list_agent_results(db, run_id=run.run_id, project_id=1, prompt_id=44)[0][
        "draft_delivery_status"] == "SUCCESS"


def test_legacy_single_draft_remains_readable_without_child_backfill(tmp_path, monkeypatch):
    db, _engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run = _run(db, fixture, "multi-content-run-legacy")
    result = _artifact(run_id=1, answer_end=20)
    result["deliverables"][0].pop("asset_type")
    _save_result(db, run, result, {"status": "PASS"}, ELIGIBILITY, status="SUCCEEDED")
    view = list_agent_results(db, run_id=run.run_id, project_id=1, prompt_id=44)[0]
    assert view["legacy_single_draft"] is True
    assert view["draft_delivery_status"] == "LEGACY_SINGLE_DRAFT"
    assert view["draft_artifacts"] == []
    assert view["deliverable_markdown"]


def test_child_versions_and_feedback_are_append_only(tmp_path, monkeypatch):
    db, _engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run = _run(db, fixture, "multi-content-run-0004")
    _save_result(db, run, _multi_result(), {"status": "PASS"}, ELIGIBILITY, status="SUCCEEDED")
    child = db.query(AgentDraftArtifactVersion).first()
    with pytest.raises(DatabaseError):
        db.execute(text("UPDATE agent_draft_artifact_versions SET title='overwrite' WHERE id=:id"),
                   {"id": child.id})
        db.commit()
    db.rollback()
    assert db.get(AgentDraftArtifactVersion, child.id).title != "overwrite"


def _queued_failed_faq(db, fixture, key):
    run = _run(db, fixture, key)
    _save_result(db, run, _multi_result(), {"status": "PASS"}, ELIGIBILITY, status="SUCCEEDED")
    faq = next(row for row in list_draft_artifacts(
        db, run_id=run.run_id, project_id=1, prompt_id=44) if row["artifact_type"] == "FAQ")
    policy = {"max_requests": 1, "max_total_tokens": 300_000, "max_cost_cny": 5.0,
              "conservative_cny_per_million_tokens": 10.0,
              "pricing_source": "server-test", "pricing_checked_at": CURRENT_PRICING_DATE}
    request, _ = queue_draft_artifact_regeneration(
        db, artifact_version=faq["artifact_version"], project_id=1, prompt_id=44,
        idempotency_key=f"{key}-regen", requested_by="employee", server_policy=policy)
    return run, faq, request


def test_regeneration_executor_claims_and_appends_only_target_asset(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run, faq, request = _queued_failed_faq(db, fixture, "regen-worker-success")
    pack = build_evidence_pack(loads(run.input_scope_json, {}))
    client = ScriptedEvidencePackClient(_faq_markdown(pack))
    execute_draft_artifact_regeneration(
        request.request_id, session_factory=sessionmaker(bind=engine, expire_on_commit=False),
        client=client)
    db.expire_all()
    stored = db.query(type(request)).filter_by(request_id=request.request_id).one()
    versions = db.query(AgentDraftArtifactVersion).filter_by(artifact_id=faq["artifact_id"]).order_by(
        AgentDraftArtifactVersion.version_number).all()
    assert client.calls == 1
    assert stored.status == "COMPLETED"
    assert stored.attempt_count == 1
    assert loads(stored.usage_json, {})["total_tokens"] == 200
    audit = loads(stored.audit_json, {})
    assert audit["external_request_state"] == "PROVIDER_RETURNED"
    assert audit["generation_profile"] == {
        "execution_contract": "geo.evidence-pack.execution.v12",
        "prompt_version": "geo-evidence-pack-synthesis.v10",
        "validation_contract": "geo.evidence-pack.validation.v5",
    }
    assert "面向最终使用者" in client.payloads[0]["system_prompt"]
    assert [row.version_number for row in versions] == [1, 2]
    assert versions[-1].status == "SUCCESS"
    assert versions[-1].artifact_type == "FAQ"


def test_historical_regeneration_without_frozen_generation_profile_fails_before_provider(
        tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run, _faq, request = _queued_failed_faq(db, fixture, "regen-profile-missing")
    policy = loads(request.server_policy_json, {})
    policy.pop("generation_profile", None)
    historical = AgentDraftArtifactRegeneration(
        request_id="historical-regeneration-without-profile",
        idempotency_key="historical-regeneration-without-profile",
        source_artifact_version=request.source_artifact_version,
        parent_result_version=request.parent_result_version,
        agent_run_id=request.agent_run_id,
        project_id=request.project_id,
        prompt_id=request.prompt_id,
        requested_by="historical-worker",
        request_hash="0" * 64,
        server_policy_json=json.dumps(policy, ensure_ascii=False, sort_keys=True),
        status="QUEUED",
    )
    db.add(historical)
    db.commit()
    pack = build_evidence_pack(loads(run.input_scope_json, {}))
    client = ScriptedEvidencePackClient(_faq_markdown(pack))

    execute_draft_artifact_regeneration(
        historical.request_id, session_factory=sessionmaker(bind=engine, expire_on_commit=False),
        client=client)

    db.expire_all()
    stored = db.query(AgentDraftArtifactRegeneration).filter_by(
        request_id=historical.request_id).one()
    assert client.calls == 0
    assert stored.status == "FAILED"
    assert stored.failure_code == "DRAFT_REGENERATION_GENERATION_PROFILE_MISSING"
    assert loads(stored.audit_json, {})["external_request_state"] == "NOT_STARTED"


def test_regeneration_cancel_before_provider_makes_zero_calls(tmp_path, monkeypatch):
    db, engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    run, _faq, request = _queued_failed_faq(db, fixture, "regen-worker-cancel")
    pack = build_evidence_pack(loads(run.input_scope_json, {}))
    client = ScriptedEvidencePackClient(_faq_markdown(pack))
    cancelled = cancel_draft_artifact_regeneration(
        db, request_id=request.request_id, project_id=1, prompt_id=44)
    execute_draft_artifact_regeneration(
        request.request_id, session_factory=sessionmaker(bind=engine, expire_on_commit=False),
        client=client)
    assert cancelled.status == "CANCELLED"
    assert client.calls == 0
    assert loads(cancelled.audit_json, {})["cancelled_before_provider"] is True


def test_regeneration_recovery_never_replays_uncertain_provider_boundary(tmp_path, monkeypatch):
    db, _engine = _migrated_session(tmp_path, monkeypatch)
    fixture = _seed_citation_contribution_fixture(db, monkeypatch, tmp_path)
    _run_row, _faq, request = _queued_failed_faq(db, fixture, "regen-worker-recover")
    request.status = "RUNNING"
    request.attempt_count = 1
    request.audit_json = '{"external_request_state":"RESERVED_IN_FLIGHT"}'
    db.commit()
    assert recover_interrupted_draft_regenerations(db) == 1
    db.refresh(request)
    assert request.status == "FAILED"
    assert request.failure_code == "DRAFT_REGENERATION_DELIVERY_UNKNOWN"
    assert loads(request.audit_json, {})["external_request_state"] == "DELIVERY_UNKNOWN"


def test_regeneration_capability_is_fail_closed_and_post_creates_nothing(tmp_path, monkeypatch):
    db, _engine = _migrated_session(tmp_path, monkeypatch)
    capability = read_agent_capabilities(project_id=1)
    assert capability["draft_regeneration_enabled"] is False
    assert capability["draft_regeneration_blocker"] == \
        "DRAFT_REGENERATION_EXTERNAL_CALL_NOT_AUTHORIZED"
    with pytest.raises(HTTPException) as denied:
        regenerate_draft_artifact(
            "draft-does-not-matter:v1",
            AgentDraftArtifactRegenerate(
                project_id=1, prompt_id=44, idempotency_key="no-external-call"),
            Response(), actor="employee", db=db)
    assert denied.value.status_code == 409
    assert db.query(AgentDraftArtifactRegeneration).count() == 0


def test_regeneration_audit_migration_is_present_on_fresh_head(tmp_path, monkeypatch):
    _db, engine = _migrated_session(tmp_path, monkeypatch)
    columns = {row["name"] for row in inspect(engine).get_columns(
        "agent_draft_artifact_regenerations")}
    assert REGENERATION_AUDIT_COLUMNS <= columns


def test_regeneration_audit_migration_upgrades_historical_01_shape(tmp_path, monkeypatch):
    path = tmp_path / "historical-01.db"
    monkeypatch.setenv("GEO_RELEASE_DATABASE_URL", f"sqlite:///{path.as_posix()}")
    config = Config(str(ROOT / "alembic.release.ini"))
    command.upgrade(config, "20261030_01")
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    # Revision 01 historically predated these columns. The dynamic table
    # metadata used by its fresh-DB path now includes them, so remove them to
    # reproduce the already-deployed 01 shape before exercising 01 -> 02.
    with engine.begin() as connection:
        for name in REGENERATION_AUDIT_COLUMNS:
            connection.execute(text(
                f"ALTER TABLE agent_draft_artifact_regenerations DROP COLUMN {name}"))
    command.upgrade(config, "head")
    columns = {row["name"] for row in inspect(engine).get_columns(
        "agent_draft_artifact_regenerations")}
    assert REGENERATION_AUDIT_COLUMNS <= columns
