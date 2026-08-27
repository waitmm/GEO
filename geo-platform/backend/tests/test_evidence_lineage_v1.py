from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    AnswerDecisionBinding,
    AnswerUnit,
    Base,
    BrowserMonitorRun,
    BrowserMonitorTask,
    EvidenceAlignment,
    Organization,
    Project,
    Prompt,
    RecommendationEvent,
    ReferenceSource,
    SourceClaim,
    SourceDocument,
)
from app.modules.optimization.evidence_lineage import evaluate_evidence_alignment_v1_eligibility
from app.modules.optimization.passage_retrieval import ANSWER_BINDING_REASON_SOURCE, FORMAL_V1_1_INPUT_VERSION
from app.modules.optimization.service import _decision_support_by_doc_id
from app.services.serialization import dumps


def _db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed_base(db):
    db.add_all([
        Organization(id=1, name="测试组织"),
        Project(id=1, organization_id=1, name="测试项目", brand_name="测试品牌"),
        Prompt(id=10, project_id=1, prompt_text="短链工具推荐", title="短链工具推荐"),
        BrowserMonitorTask(id=1, project_id=1, status="completed"),
    ])
    db.commit()


def _run(db, run_id: int) -> BrowserMonitorRun:
    run = BrowserMonitorRun(
        id=run_id,
        task_id=1,
        project_id=1,
        prompt_id=10,
        status="success",
        answer_text="推荐 ToolX，因为它支持点击统计。",
    )
    db.add(run)
    return run


def _reference(db, ref_id: int, run_id: int, url: str = "https://www.example.com/a") -> ReferenceSource:
    ref = ReferenceSource(
        id=ref_id,
        run_id=run_id,
        reference_index=1,
        display_title="ToolX 功能说明",
        url=url,
        canonical_url=url,
        domain="example.com",
    )
    db.add(ref)
    return ref


def _document_and_claim(db) -> tuple[SourceDocument, SourceClaim]:
    doc = SourceDocument(
        id=100,
        url="https://example.com/a",
        original_url="https://example.com/a",
        canonical_url="https://example.com/a",
        domain="example.com",
        fetch_status="SUCCESS",
        title="ToolX 功能说明",
        clean_text="ToolX 支持点击统计。",
    )
    claim = SourceClaim(
        id=200,
        project_id=1,
        source_document_id=100,
        subject_entity="ToolX",
        normalized_claim="ToolX 支持点击统计。",
        predicate="支持",
        object_text="点击统计",
        source_span="ToolX 支持点击统计。",
        review_status="MACHINE_GROUNDED",
    )
    db.add_all([doc, claim])
    return doc, claim


def _lineaged_alignment(db, *, run_id: int, event_id: int, unit_id: int, binding_id: int, alignment_id: int) -> EvidenceAlignment:
    event = RecommendationEvent(
        id=event_id,
        project_id=1,
        prompt_id=10,
        run_id=run_id,
        entity_text="ToolX",
        speech_act="RECOMMEND",
        recommendation_strength="STRONG",
        polarity="POSITIVE",
        answer_span="推荐 ToolX，因为它支持点击统计。",
        reasons_json=dumps([]),
        review_status="MACHINE_GROUNDED",
    )
    unit = AnswerUnit(
        id=unit_id,
        project_id=1,
        prompt_id=10,
        run_id=run_id,
        answer_claim_id=unit_id,
        unit_text_original="ToolX 支持点击统计",
        unit_text_normalized="ToolX 支持点击统计",
        source_span="ToolX 支持点击统计",
        entity_hint="ToolX",
    )
    binding = AnswerDecisionBinding(
        id=binding_id,
        project_id=1,
        prompt_id=10,
        run_id=run_id,
        recommendation_event_id=event_id,
        answer_unit_id=unit_id,
        decision_role="SUPPORTING_REASON",
        binding_strength="MEDIUM",
        scope_type="SAME_PARAGRAPH",
        pipeline_version="citation_decision_v1_1_shadow",
        review_status="MACHINE_GROUNDED",
    )
    alignment = EvidenceAlignment(
        id=alignment_id,
        project_id=1,
        prompt_id=10,
        run_id=run_id,
        recommendation_event_id=event_id,
        recommendation_reason_id=f"answer_unit:{unit_id}:binding:{binding_id}",
        source_document_id=100,
        source_claim_id=200,
        relation="SUPPORTS",
        scope_relation="PASS",
        review_status="MACHINE_GROUNDED",
        machine_payload_json=dumps({
            "reason_source": ANSWER_BINDING_REASON_SOURCE,
            "formal_input_version": FORMAL_V1_1_INPUT_VERSION,
            "answer_unit_id": unit_id,
            "decision_binding_id": binding_id,
        }),
    )
    db.add_all([event, unit, binding, alignment])
    return alignment


def test_same_source_document_two_runs_reuses_source_claim_and_derives_run_coverage():
    db = _db()
    try:
        _seed_base(db)
        _run(db, 1)
        _run(db, 2)
        _run(db, 3)
        _reference(db, 11, 1)
        _reference(db, 12, 2)
        _document_and_claim(db)
        _lineaged_alignment(db, run_id=1, event_id=301, unit_id=401, binding_id=501, alignment_id=601)
        _lineaged_alignment(db, run_id=2, event_id=302, unit_id=402, binding_id=502, alignment_id=602)
        db.commit()

        payload = _decision_support_by_doc_id(
            db,
            1,
            10,
            {100},
            allowed_run_ids={1, 2, 3},
            include_answer_binding_v1_1=True,
        )[100]

        assert payload["decision_support_level"] == "RECOMMENDATION_REASON"
        assert payload["supporting_alignment_ids"] == [601, 602]
        assert payload["evidence_observed_run_ids"] == [1, 2]
        assert payload["evidence_run_coverage_count"] == 2
        assert db.query(SourceClaim).filter(SourceClaim.source_document_id == 100).count() == 1
    finally:
        db.close()


def test_source_document_not_referenced_by_current_run_is_ineligible():
    db = _db()
    try:
        _seed_base(db)
        _run(db, 1)
        _document_and_claim(db)
        alignment = _lineaged_alignment(db, run_id=1, event_id=301, unit_id=401, binding_id=501, alignment_id=601)
        db.commit()

        result = evaluate_evidence_alignment_v1_eligibility(
            db,
            alignment,
            allowed_run_ids={1},
            include_answer_binding_v1_1=True,
        )

        assert result.eligible_for_v1 is False
        assert "SOURCE_NOT_REFERENCED_IN_RUN" in result.ineligibility_reasons
        assert _decision_support_by_doc_id(db, 1, 10, {100}, allowed_run_ids={1}, include_answer_binding_v1_1=True)[100][
            "decision_support_level"
        ] == "NONE"
    finally:
        db.close()


def test_answer_unit_recommendation_event_cross_run_mismatch_is_ineligible():
    db = _db()
    try:
        _seed_base(db)
        _run(db, 1)
        _run(db, 2)
        _reference(db, 11, 1)
        _document_and_claim(db)
        alignment = _lineaged_alignment(db, run_id=1, event_id=301, unit_id=401, binding_id=501, alignment_id=601)
        unit = db.get(AnswerUnit, 401)
        unit.run_id = 2
        db.commit()

        result = evaluate_evidence_alignment_v1_eligibility(
            db,
            alignment,
            allowed_run_ids={1, 2},
            include_answer_binding_v1_1=True,
        )

        assert result.eligible_for_v1 is False
        assert "RUN_MISMATCH" in result.ineligibility_reasons
    finally:
        db.close()


def test_alignment_run_id_alone_does_not_pass_when_reference_belongs_to_other_run():
    db = _db()
    try:
        _seed_base(db)
        _run(db, 1)
        _run(db, 2)
        _reference(db, 12, 2)
        _document_and_claim(db)
        alignment = _lineaged_alignment(db, run_id=1, event_id=301, unit_id=401, binding_id=501, alignment_id=601)
        db.commit()

        result = evaluate_evidence_alignment_v1_eligibility(
            db,
            alignment,
            allowed_run_ids={1, 2},
            include_answer_binding_v1_1=True,
        )

        assert result.eligible_for_v1 is False
        assert "SOURCE_NOT_REFERENCED_IN_RUN" in result.ineligibility_reasons
    finally:
        db.close()


def test_legacy_alignment_without_full_lineage_is_kept_but_not_consumed():
    db = _db()
    try:
        _seed_base(db)
        _run(db, 1)
        _reference(db, 11, 1)
        _document_and_claim(db)
        event = RecommendationEvent(
            id=301,
            project_id=1,
            prompt_id=10,
            run_id=1,
            entity_text="ToolX",
            speech_act="RECOMMEND",
            recommendation_strength="STRONG",
            polarity="POSITIVE",
            review_status="MACHINE_GROUNDED",
        )
        alignment = EvidenceAlignment(
            id=601,
            project_id=1,
            prompt_id=10,
            run_id=1,
            recommendation_event_id=301,
            source_document_id=100,
            source_claim_id=200,
            relation="SUPPORTS",
            scope_relation="PASS",
            review_status="MACHINE_GROUNDED",
        )
        db.add_all([event, alignment])
        db.commit()

        result = evaluate_evidence_alignment_v1_eligibility(
            db,
            alignment,
            allowed_run_ids={1},
            include_answer_binding_v1_1=True,
        )
        payload = _decision_support_by_doc_id(db, 1, 10, {100}, allowed_run_ids={1}, include_answer_binding_v1_1=True)[100]

        assert result.eligible_for_v1 is False
        assert "LEGACY_RELATION_ONLY" in result.ineligibility_reasons
        assert "MISSING_ANSWER_UNIT" in result.ineligibility_reasons
        assert "MISSING_DECISION_BINDING" in result.ineligibility_reasons
        assert payload["decision_support_level"] == "NONE"
        assert db.get(EvidenceAlignment, 601) is not None
    finally:
        db.close()


def test_observed_run_ids_are_derived_only_from_real_eligible_alignments():
    db = _db()
    try:
        _seed_base(db)
        for run_id in [1, 2, 3]:
            _run(db, run_id)
            _reference(db, 10 + run_id, run_id)
        _document_and_claim(db)
        _lineaged_alignment(db, run_id=1, event_id=301, unit_id=401, binding_id=501, alignment_id=601)
        fake = _lineaged_alignment(db, run_id=2, event_id=302, unit_id=402, binding_id=502, alignment_id=602)
        fake.machine_payload_json = dumps({
            "reason_source": ANSWER_BINDING_REASON_SOURCE,
            "formal_input_version": FORMAL_V1_1_INPUT_VERSION,
            "answer_unit_id": 402,
            "decision_binding_id": 502,
            "observed_run_ids": [1, 2, 3],
        })
        db.commit()

        payload = _decision_support_by_doc_id(
            db,
            1,
            10,
            {100},
            allowed_run_ids={1, 2, 3},
            include_answer_binding_v1_1=True,
        )[100]

        assert payload["evidence_observed_run_ids"] == [1, 2]
        assert 3 not in payload["evidence_observed_run_ids"]
    finally:
        db.close()
