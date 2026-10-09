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


@pytest.mark.parametrize('intent,qualified,expected', [
    ('supplier_recommendation', True, 'FEATURE_PAGE'),
    ('supplier_recommendation', False, 'HELP_DOC'),
    ('usage_instruction', True, 'HELP_DOC'),
])
def test_asset_choice_uses_intent_and_fact_eligibility_not_empty_inventory(frozen, intent, qualified, expected):
    frozen['prompt_configuration'] = {'intent_type': intent}
    frozen['truths'] = [{'public_use_eligibility': 'CONSUMABLE' if qualified else 'VERIFY_FIRST'}]
    result = execution._compile_machine_delivery('proposal', snapshot(frozen))
    assert result['asset_resolution']['recommended_asset_type'] == expected
    assert frozen['prompt_text'] in result['asset_resolution']['selection_reason']
    assert result['asset_operation'] == 'CONDITIONAL'
    assert result['asset_resolution']['inventory_state'] == 'UNKNOWN'
    assert not result['channel_resolution']['upstream_channel_resolver_reused']


def test_no_problem_has_no_repair_record(frozen):
    item = frozen["selected_evidence"][0]
    item["proposed_text"] = quote_text(item)
    _, findings, repairs = build_sections(frozen)
    assert findings == [] and repairs == []


def test_no_source_has_scoped_research_material_not_factual_ready(frozen):
    from app.modules.single_prompt_v2.citation_contribution import build_answer_units
    frozen['selected_evidence'] = []
    frozen['contribution_result_version'] = None
    frozen['question_topics'] = build_answer_units(frozen['answers'][0]['text'], 1, [])
    output = execution._compile_machine_delivery('proposal', snapshot(frozen))
    assert output['publication_draft']['deliverable_type'] == 'SCOPED_RESEARCH_GUIDE'
    assert '甲厂过滤器可以清洗' in output['publication_draft']['body_markdown']
    assert '不直接把它当作事实' in output['publication_draft']['body_markdown']
    assert output['automatic_qa']['status'] == 'READY_INTERNAL'
    assert output['automatic_qa']['repairs'] == []
    assert output['validation']['content_delivery_status'] == 'INCOMPLETE'
    changed = output['publication_draft']
    changed['sections'][0]['draft_text'] += '乙厂支持带电清洗。'
    assert audit_draft(frozen, changed)['status'] == 'NEEDS_REPAIR'


def test_brand_context_informs_execution_without_public_fact_promotion(frozen):
    frozen['brand_context'] = {'context_version_id': 'context:1', 'passages': [
        {'text': '乙厂希望说明过滤器维护；效率提升99%的说法待核实。', 'source_reference': '用户内部资料'}]}
    output = execution._compile_machine_delivery('proposal', snapshot(frozen))
    item = next(x for x in output['internal_checklist'] if x['code'] == 'SUPPLEMENTAL_CONTEXT_NOT_VERIFIED')
    assert item['context_version_id'] == 'context:1' and item['public_claim_eligible'] is False
    assert '效率提升99%' not in output['publication_draft']['body_markdown']


def test_reader_guide_and_brand_lookup_do_not_promote_marketing_to_claim(frozen):
    frozen["asset_observations"] = [{"candidate_id": "observed:fixture", "url": "https://example.com/product", "title": "乙厂产品说明"}]
    frozen["selected_evidence"].append({
        **frozen["selected_evidence"][0], "section_id": "brand-observation",
        "material_use": "ATTRIBUTED_BRAND_PAGE_OBSERVATION_NOT_TRUTH", "binding_id": None,
        "passage_text": "乙厂效率提升99.99%，适用所有环境。",
    })
    result = execution._compile_machine_delivery("proposal", snapshot(frozen))
    body = result["publication_draft"]["body_markdown"]
    assert "先对照自己的需求" in body and "选择后，按这个顺序检查" in body
    assert "https://example.com/product" in body and "向服务方核对" in body
    assert "99.99%" not in body and "适用所有环境" not in body
    assert len(result["selected_public_content"]) == 1
    assert result["strategy_channel"]["channel_role"] is None
    assert result["automatic_qa"]["status"] == "READY"


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


def test_generated_actual_text_and_qa_project_into_formal_result(frozen):
    from app.modules.single_prompt_v2.delivery_generation import finish_draft, generation_input, segments_of
    data = snapshot(frozen)
    generated = {"sections": [{"heading": "先识别型号与维护条件", "blocks": [{"kind": "INSTRUCTION",
        "text": "先记录过滤器铭牌型号，再与维护手册的适用型号逐项核对；找不到对应说明时先联系供应方。",
        "evidence_ids": []}]}]}
    qa = {"checks": [{"segment_id": r["segment_id"], "verdict": "PASS", "rationale": "限定为查证步骤。"}
        for r in segments_of(generated)]}
    receipt = finish_draft(generated, qa, generation_input(frozen))
    output = execution._attach_generated_delivery(execution._compile_machine_delivery('proposal', data), receipt, data)
    assert output['validation']['content_delivery_status'] == 'READY'
    assert output['validation']['status'] == 'READY_FOR_BUSINESS_INPUT'
    assert output['publication_draft']['body_markdown'] == receipt['body_markdown']
    assert output['repair_history'] == []
    output['publication_draft']['body_markdown'] += '\n乙厂适用全部过滤器。'
    result = execution.validate_execution_output(output, data)
    assert 'AUTOMATIC_QA_NOT_READY' in result['errors']
    assert result['content_delivery_status'] == 'INCOMPLETE'


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
