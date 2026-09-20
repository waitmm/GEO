from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from types import SimpleNamespace

from app.models import (
    AnswerDecisionBinding,
    AnswerEvidenceShadowRun,
    AnswerUnit,
    Base,
    EvidenceAlignment,
    EvidenceAlignmentMaterialization,
    LLMCallCache,
    Project,
    RecommendationEvent,
    ReferenceSource,
    SourceClaim,
    SourceDocument,
)
from app.modules.optimization.evidence_alignment import (
    ALIGNMENT_MATERIALIZATION_CONTRACT,
    ALIGNMENT_PROMPT_VERSION,
    ALIGNMENT_SCHEMA_VERSION,
    _dedupe_source_claims_for_alignment,
    alignment_llm_input_hash,
    build_alignment_materialization_key,
    decision_support_level_from_relation,
    entity_scope_precheck,
    resolve_alignment_materialization_compatibility,
    run_evidence_alignment,
)
from app.modules.optimization.passage_retrieval import SHADOW_INPUT_PIPELINE_VERSION
from app.modules.optimization import evidence_alignment as evidence_alignment_module
from app.services.serialization import dumps


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _claim(subject: str, owner: str) -> SourceClaim:
    return SourceClaim(
        project_id=1, source_document_id=1, passage_id="p0",
        source_owner_entity=owner, source_role="UNKNOWN",
        subject_entity=subject, normalized_claim="x",
        claim_type="CAPABILITY", polarity="POSITIVE",
        source_span="x", raw_start=0, raw_end=1,
    )


def _project() -> Project:
    return Project(id=1, organization_id=1, name="P", brand_name="爱短链", website_url="https://aifabu.com")


def _event(run_id: int, entity: str = "爱短链", reason: str = "支持点击统计", prompt_id: int = 1) -> RecommendationEvent:
    return RecommendationEvent(
        id=run_id,
        project_id=1,
        prompt_id=prompt_id,
        run_id=run_id,
        entity_text=entity,
        speech_act="RECOMMEND",
        review_status="HUMAN_CONFIRMED",
        reasons_json=dumps([{"normalized_reason": reason, "reason_scope": "ENTITY_SPECIFIC"}]),
    )


def _source_claim(
    claim_id: int = 1,
    *,
    subject: str = "爱短链",
    owner: str = "爱短链",
    text: str = "爱短链支持点击统计",
    polarity: str = "POSITIVE",
    doc_id: int = 1,
) -> SourceClaim:
    return SourceClaim(
        id=claim_id,
        project_id=1,
        source_document_id=doc_id,
        passage_id=f"doc{doc_id}:b1",
        source_owner_entity=owner,
        source_role="TARGET_FIRST_PARTY",
        subject_entity=subject,
        normalized_claim=text,
        predicate="支持",
        object_text="点击统计",
        claim_type="CAPABILITY",
        polarity=polarity,
        source_span=text,
        raw_start=0,
        raw_end=len(text),
        review_status="MACHINE_GROUNDED",
        prompt_version="source_claim.v1",
        schema_version="v1",
    )


def _fake_alignment_judge(monkeypatch, relation: str = "SUPPORTS"):
    calls = []

    class FakeJudge:
        def __init__(self):
            self.client = SimpleNamespace(provider="deepseek")
            self.settings = SimpleNamespace(deepseek_model="test-model")

        def judge(self, reason_text, source_claim_text, db=None):
            calls.append((reason_text, source_claim_text))
            return {
                "relation": relation,
                "rationale": f"{relation} rationale",
                "confidence_raw": 0.9,
            }

    monkeypatch.setattr(evidence_alignment_module, "EvidenceAlignmentJudge", FakeJudge)
    return calls


def test_entity_specific_same_entity_passes():
    """Reason=爱短链支持X，Claim 主体=爱短链 → PASS。"""
    claim = _claim("爱短链", "爱短链")
    assert entity_scope_precheck("ENTITY_SPECIFIC", "爱短链", claim) == "PASS"


def test_entity_specific_competitor_is_competitor_context():
    """Reason=爱短链支持X，Claim 主体=商加加 → COMPETITOR_CONTEXT（不得 SUPPORT）。"""
    claim = _claim("商加加", "商加加")
    assert entity_scope_precheck("ENTITY_SPECIFIC", "爱短链", claim) == "COMPETITOR_CONTEXT"


def test_market_criterion_allows_competitor_claim():
    """MARKET_CRITERION Reason 允许竞品 Claim 参与（验证市场标准存在性）。"""
    claim = _claim("商加加", "商加加")
    assert entity_scope_precheck("MARKET_CRITERION", "", claim) == "PASS_MARKET"


def test_unknown_subject_falls_back_to_owner():
    """主体未识别时用 owner 弱匹配。"""
    claim = _claim("UNKNOWN", "爱短链")
    assert entity_scope_precheck("ENTITY_SPECIFIC", "爱短链", claim) == "PASS"


def test_unknown_subject_wrong_owner_is_competitor_context():
    claim = _claim("UNKNOWN", "商加加")
    assert entity_scope_precheck("ENTITY_SPECIFIC", "爱短链", claim) == "COMPETITOR_CONTEXT"


def test_alignment_system_prompt_has_relation_constraints():
    from app.modules.optimization.evidence_alignment import ALIGNMENT_SYSTEM
    assert "RELATED" in ALIGNMENT_SYSTEM
    assert "把 RELATED 当成 SUPPORTS" in ALIGNMENT_SYSTEM
    assert "JSON" in ALIGNMENT_SYSTEM


def test_legacy_related_is_not_partial_support():
    assert decision_support_level_from_relation("SUPPORTS") == "SUPPORTS"
    assert decision_support_level_from_relation("CONTRADICTS") == "CONTRADICTS"
    assert decision_support_level_from_relation("NONE") == "NO_SUPPORT"
    assert decision_support_level_from_relation("RELATED") == "LEGACY_RELATED"


def test_alignment_consumes_one_source_claim_per_semantic_fact():
    claim_a = _claim("小码短链接", "小码短链接")
    claim_a.id = 10
    claim_a.source_document_id = 3
    claim_a.passage_id = "doc3:b1"
    claim_a.normalized_claim = "小码短链接支持点击统计"
    claim_a.source_span = "小码短链接支持点击统计"
    claim_b = _claim("小码短链接", "小码短链接")
    claim_b.id = 11
    claim_b.source_document_id = 3
    claim_b.passage_id = "doc3:b1"
    claim_b.normalized_claim = "小码短链接支持点击统计"
    claim_b.source_span = "小码短链接支持点击统计"

    deduped, duplicate_count = _dedupe_source_claims_for_alignment([claim_b, claim_a])

    assert [claim.id for claim in deduped] == [10]
    assert duplicate_count == 1


def test_empty_doc_filter_does_not_expand_alignment_to_all_source_claims(db):
    project = Project(id=1, organization_id=1, name="P", brand_name="B", website_url="https://b.com")
    event = RecommendationEvent(
        id=1,
        project_id=1,
        prompt_id=1,
        run_id=1,
        entity_text="小码短链接",
        speech_act="RECOMMEND",
        review_status="HUMAN_CONFIRMED",
        reasons_json=dumps([{"normalized_reason": "点击统计", "reason_scope": "ENTITY_SPECIFIC"}]),
    )
    claim = SourceClaim(
        id=1,
        project_id=1,
        source_document_id=99,
        passage_id="doc99:b1",
        source_owner_entity="小码短链接",
        source_role="COMPETITOR_FIRST_PARTY",
        subject_entity="小码短链接",
        normalized_claim="小码短链接支持点击统计",
        claim_type="CAPABILITY",
        polarity="POSITIVE",
        source_span="小码短链接支持点击统计",
        review_status="MACHINE_GROUNDED",
    )
    db.add_all([project, event, claim])
    db.commit()

    result = run_evidence_alignment(
        db,
        project,
        prompt_id=1,
        run_ids=[1],
        doc_id_filter=[],
    )

    assert result["unique_reasons"] == 1
    assert result["alignments_created"] == 0
    assert result["judge_calls"] == 0


def test_binding_aware_dry_run_keeps_explicit_l0_candidates_without_topk_pruning(db):
    project = _project()
    event = _event(1, reason="")
    event.reasons_json = dumps([])
    shadow = AnswerEvidenceShadowRun(
        id=90,
        project_id=1,
        prompt_id=1,
        source_run_ids_json=dumps([1]),
        pipeline_version=SHADOW_INPUT_PIPELINE_VERSION,
        status="completed",
        formal_output_impact="NONE",
    )
    unit = AnswerUnit(
        id=91,
        shadow_run_id=90,
        project_id=1,
        prompt_id=1,
        run_id=1,
        answer_claim_id=1,
        unit_text_original="支持点击统计",
        unit_text_normalized="支持点击统计",
        source_span="支持点击统计",
        entity_hint="爱短链",
        review_status="MACHINE_GROUNDED",
    )
    binding = AnswerDecisionBinding(
        id=92,
        shadow_run_id=90,
        project_id=1,
        prompt_id=1,
        run_id=1,
        recommendation_event_id=1,
        answer_unit_id=91,
        decision_role="SUPPORTING_REASON",
        binding_strength="HIGH",
        pipeline_version=SHADOW_INPUT_PIPELINE_VERSION,
        review_status="MACHINE_GROUNDED",
    )
    docs = [
        SourceDocument(
            id=doc_id,
            url=f"https://aifabu.com/l0/{doc_id}",
            canonical_url=f"https://aifabu.com/l0/{doc_id}",
            domain="aifabu.com",
            fetch_status="SUCCESS",
            clean_text=f"爱短链支持点击统计能力 {doc_id}",
        )
        for doc_id in range(10, 16)
    ]
    refs = [
        ReferenceSource(
            id=doc_id + 100,
            run_id=1,
            reference_index=doc_id,
            url=f"https://aifabu.com/l0/{doc_id}",
            canonical_url=f"https://aifabu.com/l0/{doc_id}",
            domain="aifabu.com",
        )
        for doc_id in range(10, 16)
    ]
    claims = [
        _source_claim(
            claim_id=doc_id + 200,
            doc_id=doc_id,
            text=f"爱短链支持点击统计能力 {doc_id}",
        )
        for doc_id in range(10, 16)
    ]
    db.add_all([project, event, shadow, unit, binding, *docs, *refs, *claims])
    db.commit()

    result = run_evidence_alignment(
        db,
        project,
        prompt_id=1,
        run_ids=[1],
        include_answer_binding_reasons=True,
        doc_id_filter=[doc.id for doc in docs],
        candidate_dry_run=True,
    )

    assert result["candidate_builder_mode"] == "BINDING_AWARE_V1_1"
    assert result["candidate_policy"] == "POLICY_D_TOPK_WITH_BOUNDARY_TIES"
    assert result["production_candidate_keys"] == 6
    assert result["recall_layer_counts"]["L0_EXPLICIT"] == 6
    assert result["recall_layer_counts"]["L2_RUN_SCOPE"] == 0
    assert result["recall_layer_counts"]["L3_PROMPT_SCOPE"] == 0
    assert db.query(EvidenceAlignment).count() == 0


@pytest.mark.parametrize("relation", ["SUPPORTS", "NO_SUPPORT", "CONTRADICTS"])
def test_alignment_materialization_verdict_second_run_skips_llm(db, monkeypatch, relation):
    project = _project()
    event = _event(1)
    claim = _source_claim()
    db.add_all([project, event, claim])
    db.commit()
    calls = _fake_alignment_judge(monkeypatch, relation)

    first = run_evidence_alignment(db, project, prompt_id=1, run_ids=[1])
    second = run_evidence_alignment(db, project, prompt_id=1, run_ids=[1])

    materialization = db.query(EvidenceAlignmentMaterialization).one()
    assert len(calls) == 1
    assert first["actual_alignment_llm_calls"] == 1
    assert second["actual_alignment_llm_calls"] == 0
    assert second["materialization_hit_count"] == 1
    assert second["llm_call_cache_hit_count"] == 0
    assert materialization.status == "DONE"
    assert materialization.verdict == relation


def test_alignment_progress_callback_reports_running_and_hit_states(db, monkeypatch):
    project = _project()
    event = _event(1)
    claim = _source_claim()
    db.add_all([project, event, claim])
    db.commit()
    calls = _fake_alignment_judge(monkeypatch, "SUPPORTS")
    first_progress: list[dict] = []
    second_progress: list[dict] = []

    first = run_evidence_alignment(
        db,
        project,
        prompt_id=1,
        run_ids=[1],
        progress_callback=first_progress.append,
    )
    second = run_evidence_alignment(
        db,
        project,
        prompt_id=1,
        run_ids=[1],
        progress_callback=second_progress.append,
    )

    assert len(calls) == 1
    assert first_progress[0]["processed"] == 0
    assert first_progress[0]["total"] == first["unique_jobs"] == 1
    assert any(
        item["processed"] == 0 and item["actual_alignment_llm_calls"] == 1
        for item in first_progress
    )
    assert first_progress[-1]["processed"] == first_progress[-1]["total"] == 1
    assert second["actual_alignment_llm_calls"] == 0
    assert second_progress[0]["processed"] == 0
    assert second_progress[-1]["processed"] == second_progress[-1]["total"] == 1
    assert second_progress[-1]["materialization_hit_count"] == 1


def test_same_semantic_answer_unit_across_runs_uses_one_alignment_materialization(db, monkeypatch):
    project = _project()
    claim = _source_claim()
    db.add_all([project, _event(1), _event(2), claim])
    db.commit()
    calls = _fake_alignment_judge(monkeypatch, "SUPPORTS")

    result = run_evidence_alignment(db, project, prompt_id=1, run_ids=[1, 2])

    assert len(calls) == 1
    assert result["actual_alignment_llm_calls"] == 1
    assert result["alignments_created"] == 2
    assert db.query(EvidenceAlignmentMaterialization).count() == 1


def test_same_semantic_source_claim_across_observations_uses_one_alignment_materialization(db, monkeypatch):
    project = _project()
    claim_a = _source_claim(claim_id=1, doc_id=1)
    claim_b = _source_claim(claim_id=2, doc_id=2)
    db.add_all([project, _event(1), claim_a, claim_b])
    db.commit()
    calls = _fake_alignment_judge(monkeypatch, "SUPPORTS")

    result = run_evidence_alignment(db, project, prompt_id=1, run_ids=[1])

    assert len(calls) == 1
    assert result["actual_alignment_llm_calls"] == 1
    assert result["materialization_hit_count"] == 1
    assert result["alignments_created"] == 2
    assert db.query(EvidenceAlignmentMaterialization).count() == 1


def test_alignment_materialization_key_changes_for_entity_and_polarity():
    claim = _source_claim()
    other_entity_claim = _source_claim(claim_id=2, subject="商加加", owner="商加加", text="商加加支持点击统计")
    negative_claim = _source_claim(claim_id=3, polarity="NEGATIVE")

    base = build_alignment_materialization_key("支持点击统计", "ENTITY_SPECIFIC", "爱短链", claim)
    different_entity = build_alignment_materialization_key("支持点击统计", "ENTITY_SPECIFIC", "商加加", claim)
    different_claim_entity = build_alignment_materialization_key(
        "支持点击统计",
        "ENTITY_SPECIFIC",
        "商加加",
        other_entity_claim,
    )
    different_polarity = build_alignment_materialization_key(
        "支持点击统计",
        "ENTITY_SPECIFIC",
        "爱短链",
        negative_claim,
    )

    assert base != different_entity
    assert base != different_claim_entity
    assert base != different_polarity


def test_alignment_impl_upgrade_keeps_same_contract_compatible(db, monkeypatch):
    project = _project()
    event = _event(1)
    claim = _source_claim()
    key = build_alignment_materialization_key("支持点击统计", "ENTITY_SPECIFIC", "爱短链", claim)
    materialization = EvidenceAlignmentMaterialization(
        materialization_key=key,
        answer_unit_semantic_hash="answer",
        source_claim_semantic_hash="claim",
        contract_version=ALIGNMENT_MATERIALIZATION_CONTRACT,
        status="DONE",
        verdict="SUPPORTS",
        output_payload_json=dumps({"relation": "SUPPORTS", "rationale": "cached", "confidence_raw": 0.8}),
        judge_impl_version="evidence_alignment_judge.impl.2.0",
        prompt_version=ALIGNMENT_PROMPT_VERSION,
        schema_version=ALIGNMENT_SCHEMA_VERSION,
        provider="deepseek",
        model="test-model",
    )
    db.add_all([project, event, claim, materialization])
    db.commit()
    calls = _fake_alignment_judge(monkeypatch, "CONTRADICTS")

    result = run_evidence_alignment(db, project, prompt_id=1, run_ids=[1])

    assert calls == []
    assert result["actual_alignment_llm_calls"] == 0
    assert result["materialization_hit_count"] == 1
    assert resolve_alignment_materialization_compatibility(materialization) == "COMPATIBLE"


def test_alignment_breaking_contract_is_stale_schema():
    materialization = EvidenceAlignmentMaterialization(
        materialization_key="k",
        answer_unit_semantic_hash="a",
        source_claim_semantic_hash="c",
        contract_version=ALIGNMENT_MATERIALIZATION_CONTRACT,
        status="DONE",
    )

    assert resolve_alignment_materialization_compatibility(materialization, "ALIGNMENT_V2") == "STALE_SCHEMA"


def test_alignment_llm_call_cache_recovery_writes_ledger_then_hits_ledger(db, monkeypatch):
    project = _project()
    event = _event(1)
    claim = _source_claim()
    cache = LLMCallCache(
        provider="deepseek",
        model="test-model",
        prompt_version=ALIGNMENT_PROMPT_VERSION,
        schema_version=ALIGNMENT_SCHEMA_VERSION,
        input_hash=alignment_llm_input_hash("支持点击统计", "爱短链支持点击统计"),
        parsed_payload_json=dumps({"relation": "SUPPORTS", "rationale": "cache", "confidence_raw": 0.7}),
    )
    db.add_all([project, event, claim, cache])
    db.commit()
    calls = _fake_alignment_judge(monkeypatch, "CONTRADICTS")

    first = run_evidence_alignment(db, project, prompt_id=1, run_ids=[1])
    second = run_evidence_alignment(db, project, prompt_id=1, run_ids=[1])

    assert calls == []
    assert first["actual_alignment_llm_calls"] == 0
    assert first["llm_call_cache_hit_count"] == 1
    assert first["materializations_created"] == 1
    assert second["materialization_hit_count"] == 1
    assert second["llm_call_cache_hit_count"] == 0
    assert second["actual_alignment_llm_calls"] == 0
    assert db.query(EvidenceAlignmentMaterialization).one().status == "DONE"


def test_legacy_alignment_recovery_writes_materialization_without_llm(db, monkeypatch):
    project = _project()
    event = _event(1)
    claim = _source_claim()
    legacy = EvidenceAlignment(
        project_id=1,
        prompt_id=1,
        run_id=1,
        recommendation_event_id=1,
        recommendation_reason_id="reason:支持点击统计",
        source_document_id=1,
        source_claim_id=1,
        relation="SUPPORTS",
        scope_relation="PASS",
        provider="deepseek",
        model="test-model",
        prompt_version=ALIGNMENT_PROMPT_VERSION,
        schema_version=ALIGNMENT_SCHEMA_VERSION,
        machine_payload_json=dumps({
            "relation": "SUPPORTS",
            "rationale": "legacy",
            "confidence_raw": 0.8,
            "semantic_reason_key": "支持点击统计|ENTITY_SPECIFIC|爱短链",
        }),
        review_status="MACHINE_GROUNDED",
    )
    db.add_all([project, event, claim, legacy])
    db.commit()
    calls = _fake_alignment_judge(monkeypatch, "CONTRADICTS")

    result = run_evidence_alignment(db, project, prompt_id=1, run_ids=[1])

    assert calls == []
    assert result["legacy_reuse_count"] == 1
    assert result["actual_alignment_llm_calls"] == 0
    assert db.query(EvidenceAlignmentMaterialization).one().status == "DONE"
    assert db.query(EvidenceAlignment).count() == 1


def test_historical_materialization_does_not_create_current_membership_without_candidate_scope(db, monkeypatch):
    project = _project()
    claim = _source_claim()
    key = build_alignment_materialization_key("支持点击统计", "ENTITY_SPECIFIC", "爱短链", claim)
    materialization = EvidenceAlignmentMaterialization(
        materialization_key=key,
        answer_unit_semantic_hash="answer",
        source_claim_semantic_hash="claim",
        contract_version=ALIGNMENT_MATERIALIZATION_CONTRACT,
        status="DONE",
        verdict="SUPPORTS",
        output_payload_json=dumps({"relation": "SUPPORTS", "rationale": "cached", "confidence_raw": 0.8}),
        prompt_version=ALIGNMENT_PROMPT_VERSION,
        schema_version=ALIGNMENT_SCHEMA_VERSION,
        provider="deepseek",
        model="test-model",
    )
    db.add_all([project, _event(40, prompt_id=40), claim, materialization])
    db.commit()
    calls = _fake_alignment_judge(monkeypatch, "SUPPORTS")

    result = run_evidence_alignment(db, project, prompt_id=40, run_ids=[40], doc_id_filter=[])

    assert calls == []
    assert result["materialization_hit_count"] == 0
    assert result["alignments_created"] == 0
    assert db.query(EvidenceAlignment).count() == 0
