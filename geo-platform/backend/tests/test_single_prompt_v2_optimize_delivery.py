from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models import Base, Project, Prompt, SinglePromptExecutionProposal, SinglePromptExecutionProposalResult
from app.modules.single_prompt_v2 import execution
from app.modules.single_prompt_v2.delivery_text import (
    INPUT_VERSION, audit_draft, build_sections, digest, quote_text, render_draft, text_digest,
)


@pytest.fixture
def frozen():
    passage = "仅在电源断开时，甲厂过滤器可以拆卸清洗。清洗后需完全晾干再安装；不支持带电清洗。"
    return {
        "contract_version": INPUT_VERSION,
        "identity": {"project_id": 1, "prompt_id": 1, "analysis_id": "analysis", "context_id": "context", "input_authority_type": "MACHINE_QUALIFICATION"},
        "brand": {"brand_name": "乙厂"}, "brand_hash": digest({"brand_name": "乙厂"}),
        "prompt_text": "空气过滤器如何清洗", "prompt_hash": text_digest("空气过滤器如何清洗"),
        "answers": [{"run_id": 1, "text": "甲厂过滤器可以清洗。"}],
        "subjects": ["甲厂", "乙厂"], "contribution_result_version": "contribution:fixture",
        "asset_observations": [], "historical_failures": [],
        "selected_evidence": [{
            "section_id": "section-1", "proposed_text": "乙厂过滤器可带电清洗，效率提升99%。",
            "binding_id": "binding-1", "citation_id": "citation-1", "answer_unit_id": "unit-1",
            "snapshot_id": "snapshot-1", "title": "甲厂过滤器维护说明", "url": "https://example.com/filter",
            "passage_id": "passage-1", "passage_text": passage, "passage_hash": text_digest(passage),
            "evidence_relation": "SUPPORTS_PARTIAL", "answer_anchor": "UNPROVEN", "generation_influence": "UNAVAILABLE",
        }],
    }


def snapshot(frozen):
    return {"identity": frozen["identity"], "delivery_input": frozen, "delivery_input_hash": digest(frozen),
            "direction": {"direction_id": "direction", "direction_type": "DISCOVERY", "channel_key": None,
                          "channel_label": None, "channel_role": None},
            "baseline": {"baseline_run_ids": [1], "run_manifest": {"valid_run_ids": [1]}},
            "boundary": {}, "limitations": [], "advisories": []}


def test_different_topic_generates_complete_text_without_scenario_templates(frozen):
    output = execution._compile_machine_delivery("proposal", snapshot(frozen))
    body = output["publication_draft"]["body_markdown"]
    assert "空气过滤器如何清洗" in body and "电源断开" in body and "晾干" in body
    assert not any(word in body for word in ["抖音", "短链", "私信", "直播", "三种"])
    assert "乙厂过滤器可带电清洗" not in body and "99%" not in body
    assert output["automatic_qa"]["status"] == "READY"
    assert output["validation"]["status"] == "READY_FOR_BUSINESS_INPUT"
    assert output["strategy_channel"]["channel_role"] is None


def test_wrong_subject_number_and_condition_are_reported_then_locally_repaired(frozen):
    sections, findings, repairs = build_sections(frozen)
    assert {f["code"] for f in findings} >= {"SUBJECT_NOT_SUPPORTED", "NUMBER_NOT_SUPPORTED", "QUALIFIER_NOT_PRESERVED"}
    assert len(repairs) == 1
    repair = repairs[0]
    assert repair["before"] != repair["after"] and repair["before_hash"] != repair["after_hash"]
    assert repair["recheck"] == "PASS"
    qa = audit_draft(frozen, render_draft(frozen, sections), findings=findings, repairs=repairs)
    assert qa["status"] == "READY" and qa["findings"] and not qa["issues"]
    assert sections[0]["truth_ids"] == [] and sections[0]["answer_anchor"] == "UNPROVEN"


def test_no_problem_has_no_repair_record(frozen):
    item = frozen["selected_evidence"][0]
    item["proposed_text"] = quote_text(item)
    _, findings, repairs = build_sections(frozen)
    assert findings == [] and repairs == []


@pytest.mark.parametrize("change", ["subject", "number", "qualifier", "unbound_body", "title"])
def test_qa_rechecks_actual_text_not_just_existing_citation(frozen, change):
    sections, _, _ = build_sections(frozen)
    if change == "subject":
        sections[0]["draft_text"] = sections[0]["draft_text"].replace("甲厂", "乙厂")
    elif change == "number":
        sections[0]["draft_text"] += "效率提升99%。"
    elif change == "qualifier":
        sections[0]["draft_text"] = sections[0]["draft_text"].replace("仅在电源断开时，", "")
    draft = render_draft(frozen, sections)
    if change == "unbound_body":
        draft["body_markdown"] += "\n乙厂适用于所有环境。"
    if change == "title":
        draft["title"] = "乙厂效率提升99%"
    draft["content_hash"] = text_digest(draft["body_markdown"])
    assert audit_draft(frozen, draft)["status"] == "NEEDS_REPAIR"


def test_frozen_configuration_and_compiler_have_no_database_read(tmp_path, frozen):
    engine = create_engine(f"sqlite:///{tmp_path / 'isolated.db'}")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        db.add(Project(id=1, organization_id=1, name="乙厂", brand_name="乙厂"))
        db.add(Prompt(id=1, project_id=1, title=frozen["prompt_text"], prompt_text=frozen["prompt_text"]))
        db.commit()
        before = execution._compile_machine_delivery("proposal", snapshot(frozen))
        db.get(Project, 1).brand_name = "另一个品牌"
        db.get(Prompt, 1).prompt_text = "另一个问题"
        db.commit()
        def reject_sql(*args):
            raise AssertionError("compiler must not read current configuration")
        event.listen(engine, "before_cursor_execute", reject_sql)
        try:
            assert execution._compile_machine_delivery("proposal", snapshot(frozen)) == before
        finally:
            event.remove(engine, "before_cursor_execute", reject_sql)
    engine.dispose()


def test_frozen_hash_tampering_is_rejected(frozen):
    value = snapshot(frozen)
    value["delivery_input"]["prompt_text"] = "篡改"
    with pytest.raises(HTTPException) as exc:
        execution._compile_machine_delivery("proposal", value)
    assert exc.value.status_code == 409


def test_confirmation_validator_does_not_trust_forged_ready(frozen):
    data = snapshot(frozen)
    output = execution._compile_machine_delivery("proposal", data)
    output["publication_draft"]["body_markdown"] += "乙厂永久支持100万人。"
    output["automatic_qa"]["status"] = "READY"
    assert "AUTOMATIC_QA_NOT_READY" in execution.validate_execution_output(output, data)["errors"]


def test_regeneration_preserves_prior_version_and_is_idempotent(tmp_path, frozen, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'versions.db'}")
    Base.metadata.create_all(engine)
    data = snapshot(frozen)
    old_output = {"delivery_input": frozen, "delivery_input_hash": digest(frozen)}
    with sessionmaker(bind=engine, expire_on_commit=False)() as db:
        db.add(SinglePromptExecutionProposal(
            proposal_id="proposal", strategy_id="strategy", analysis_id="analysis", context_id="context",
            diagnosis_id="diagnosis", project_id=1, prompt_id=1, direction_id="direction",
            idempotency_key="original", input_fingerprint=digest(data), strategy_result_version="strategy:v1",
            strategy_result_hash="a"*64, strategy_review_snapshot_hash="", input_authority_type="MACHINE_QUALIFICATION",
            input_authority_id="authority", input_authority_hash="b"*64, validation_contract_version="fixture",
            input_snapshot_json=json.dumps(data), input_snapshot_hash=digest(data), status="READY_FOR_BUSINESS_INPUT",
            active_result_version="execution-v5:fixture",
        ))
        old = SinglePromptExecutionProposalResult(
            proposal_id="proposal", result_version="execution-v5:fixture", version_number=5,
            output_json=json.dumps(old_output), output_hash=digest(old_output), reviewable_set_hash="c"*64,
            limitations_json="[]",
        )
        db.add(old); db.commit()
        monkeypatch.setattr(execution, "_proposal_applicability", lambda *args: {"is_current_input": True})
        args = dict(proposal_id="proposal", base_result_version=old.result_version,
                    base_result_hash=old.output_hash, reviewable_set_hash=old.reviewable_set_hash)
        new, created = execution.generate_complete_execution_deliverable(db, **args)
        assert created and new.version_number == 6 and new.parent_result_version == old.result_version
        assert db.get(SinglePromptExecutionProposalResult, old.id).output_json == json.dumps(old_output)
        again, created = execution.generate_complete_execution_deliverable(db, proposal_id="proposal",
            base_result_version=new.result_version, base_result_hash=new.output_hash, reviewable_set_hash=new.reviewable_set_hash)
        assert not created and again.result_version == new.result_version
        with pytest.raises(HTTPException) as exc:
            execution.generate_complete_execution_deliverable(db, **args)
        assert exc.value.status_code == 409
        assert db.query(SinglePromptExecutionProposalResult).count() == 2
        revised = execution.revise_execution_proposal(
            db, proposal_id="proposal", base_result_version=new.result_version,
            base_result_hash=new.output_hash, reviewable_set_hash=new.reviewable_set_hash,
            editor="isolated-test", edit={"execution_note": "核对发布账号"},
        )
        edited = json.loads(revised.output_json)
        assert revised.parent_result_version == new.result_version
        assert edited["automatic_qa"]["status"] == "READY"
        assert edited["repair_history"] == [] and edited["automatic_qa"]["repairs"] == []
        assert json.loads(new.output_json)["repair_history"]
    engine.dispose()
