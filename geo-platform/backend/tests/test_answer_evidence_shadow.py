from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    AnswerClaim,
    AnswerDecisionBinding,
    AnswerEvidenceShadowResult,
    AnswerEvidenceShadowRun,
    AnswerUnit,
    Base,
    BrowserMonitorRun,
    BrowserMonitorTask,
    EvidenceAlignment,
    OptimizationEvidencePackage,
    Project,
    Prompt,
    RecommendationEvent,
    ReferenceSource,
    SourceClaim,
    SourceDocument,
    SourceQuality,
)
from app.modules.optimization.answer_evidence_shadow import (
    SHADOW_PIPELINE_VERSION,
    _split_claim_units,
    run_answer_evidence_shadow_chain,
)
from app.modules.optimization.passage_retrieval import run_reason_driven_retrieval
from app.modules.optimization.evidence_alignment import run_evidence_alignment
from app.services.serialization import dumps, loads


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


class FakeSourceClaimJudge:
    def judge_passage(self, passage_text: str, db=None) -> dict:
        if "点击统计" not in passage_text:
            return {"claims": []}
        return {
            "claims": [
                {
                    "normalized_claim": "小码短链接支持点击统计",
                    "subject_text": "小码短链接",
                    "predicate": "支持",
                    "object_text": "点击统计",
                    "claim_type": "CAPABILITY",
                    "polarity": "POSITIVE",
                    "source_span": "小码短链接支持点击统计",
                }
            ]
        }


class FakeAlignmentJudge:
    def judge(self, reason_text: str, source_claim_text: str, db=None) -> dict:
        if ("点击统计" in reason_text and "点击统计" in source_claim_text) or (
            "粘贴长链接" in reason_text and "粘贴长链接" in source_claim_text
        ):
            return {"relation": "SUPPORTS", "rationale": "来源主张支撑答案能力描述", "confidence_raw": 0.9}
        return {"relation": "NONE", "rationale": "未形成支撑", "confidence_raw": 0.2}


class FakeFormalAlignmentJudge:
    def __init__(self) -> None:
        self.client = type("Client", (), {"provider": "fake"})()
        self.settings = type("Settings", (), {"deepseek_model": "fake-model"})()

    def judge(self, reason_text: str, source_claim_text: str, db=None) -> dict:
        if "点击统计" in reason_text and "点击统计" in source_claim_text:
            return {"relation": "SUPPORTS", "rationale": "来源主张支撑答案能力描述", "confidence_raw": 0.9}
        return {"relation": "NONE", "rationale": "未形成支撑", "confidence_raw": 0.2}


class FakeProcedureSourceClaimJudge:
    def judge_passage(self, passage_text: str, db=None) -> dict:
        return {
            "claims": [
                {
                    "normalized_claim": "小码短链接支持粘贴长链接后生成短链",
                    "subject_text": "小码短链接",
                    "predicate": "支持",
                    "object_text": "粘贴长链接后生成短链",
                    "claim_type": "USAGE",
                    "polarity": "POSITIVE",
                    "source_span": "粘贴长链接，然后保存生成短链",
                }
            ]
        }


def _seed_project_prompt(db):
    project = Project(id=3, organization_id=1, name="爱短链品牌监测", brand_name="爱短链", website_url="https://aifabu.com")
    prompt = Prompt(id=40, project_id=3, prompt_text="长链接缩短工具哪个好？", title="长链接缩短")
    task = BrowserMonitorTask(id=10, project_id=3, status="done")
    run = BrowserMonitorRun(
        id=238,
        task_id=10,
        project_id=3,
        prompt_id=40,
        status="success",
        answer_text="小码短链接：支持长链接快速缩短，自带点击统计、二维码生成、自定义分享标题等功能，适合营销场景使用。",
    )
    package = OptimizationEvidencePackage(
        id=15,
        project_id=3,
        prompt_id=40,
        version=1,
        source_run_ids_json=dumps([238]),
        package_hash="shadow-fixture",
        status="active",
    )
    db.add_all([project, prompt, task, run, package])
    db.commit()
    return project, prompt, run, package


def _seed_xiaoma_claim_event_and_source(db):
    db.add(AnswerClaim(
        id=501,
        run_id=238,
        claim_index=1,
        raw_text="小码短链接：支持长链接快速缩短，自带点击统计、二维码生成、自定义分享标题等功能，适合营销场景使用",
        provenance="RULE_DERIVED",
        review_status="PENDING",
    ))
    db.add(RecommendationEvent(
        id=601,
        project_id=3,
        prompt_id=40,
        run_id=238,
        entity_text="小码短链接",
        entity_type="BRAND",
        speech_act="RECOMMEND",
        recommendation_strength="HIGH",
        answer_span="小码短链接：支持长链接快速缩短，自带点击统计、二维码生成、自定义分享标题等功能，适合营销场景使用。",
        reasons_json=dumps([]),
        review_status="HUMAN_CONFIRMED",
    ))
    db.add(ReferenceSource(
        id=701,
        run_id=238,
        reference_index=1,
        display_title="如何将长链接缩短-小码至营",
        url="https://zhuanlan.zhihu.com/p/938392385",
        canonical_url="https://zhuanlan.zhihu.com/p/938392385",
        domain="zhuanlan.zhihu.com",
    ))
    passage = "小码短链接支持点击统计，也支持二维码生成和自定义分享标题，适合营销推广场景。"
    db.add(SourceDocument(
        id=345,
        url="https://zhuanlan.zhihu.com/p/938392385",
        original_url="https://zhuanlan.zhihu.com/p/938392385",
        canonical_url="https://zhuanlan.zhihu.com/p/938392385",
        domain="zhuanlan.zhihu.com",
        fetch_status="SUCCESS",
        title="如何将长链接缩短-小码至营",
        clean_text=passage,
        content_blocks_json=dumps([{"block_index": 1, "block_type": "PARAGRAPH", "text": passage}]),
    ))
    db.add(SourceQuality(
        source_document_id=345,
        content_quality_status="CONTENT_VALID",
        quality_reason="fixture",
    ))
    db.commit()


def test_answer_claim_atomicization_extracts_entity_capabilities():
    claim = AnswerClaim(
        raw_text="小码短链接：支持长链接快速缩短，自带点击统计、二维码生成、自定义分享标题等功能，适合营销场景使用",
    )

    units = _split_claim_units(claim)
    normalized = [item["unit_text_normalized"] for item in units]

    assert "小码短链接支持长链接快速缩短" in normalized
    assert "小码短链接自带点击统计" in normalized
    assert "小码短链接自带二维码生成" in normalized
    assert "小码短链接自带自定义分享标题" in normalized
    assert "小码短链接适合营销场景使用" in normalized


def test_shadow_chain_creates_support_without_writing_formal_tables(db):
    _seed_project_prompt(db)
    _seed_xiaoma_claim_event_and_source(db)

    result = run_answer_evidence_shadow_chain(
        db,
        3,
        40,
        evidence_package_id=15,
        top_k=3,
        use_llm_binding=False,
        source_claim_judge=FakeSourceClaimJudge(),
        alignment_judge=FakeAlignmentJudge(),
    )

    summary = result["summary"]
    assert result["pipeline_version"] == SHADOW_PIPELINE_VERSION
    assert result["formal_output_impact"] == "NONE"
    assert summary["binding_count"] >= 1
    assert summary["supports_count"] >= 1
    assert summary["recommendation_evidence_eligible_count"] >= 1
    assert summary["supporting_reason_count"] >= 1
    assert summary["formal_source_claim_count_before"] == summary["formal_source_claim_count_after"] == 0
    assert summary["formal_evidence_alignment_count_before"] == summary["formal_evidence_alignment_count_after"] == 0
    assert db.query(SourceClaim).count() == 0
    assert db.query(EvidenceAlignment).count() == 0
    assert db.query(AnswerUnit).count() >= 5
    assert db.query(AnswerDecisionBinding).count() >= 1
    assert db.query(AnswerEvidenceShadowResult).count() >= 1


def test_phase1_retrieval_uses_answer_binding_only_when_enabled(db):
    project, _, _, _ = _seed_project_prompt(db)
    _seed_xiaoma_claim_event_and_source(db)
    run_answer_evidence_shadow_chain(
        db,
        3,
        40,
        evidence_package_id=15,
        top_k=3,
        use_llm_binding=False,
        source_claim_judge=FakeSourceClaimJudge(),
        alignment_judge=FakeAlignmentJudge(),
    )

    disabled = run_reason_driven_retrieval(db, project, 40, [238], include_answer_binding_reasons=False)
    enabled = run_reason_driven_retrieval(db, project, 40, [238], include_answer_binding_reasons=True)

    assert disabled["answer_binding_reasons"] == 0
    assert disabled["unique_reasons"] == 0
    assert enabled["answer_binding_reasons"] >= 1
    assert enabled["passages_retrieved"] >= 1
    assert any(
        "点击统计" in row["reason_text"]
        for row in enabled["by_reason"].values()
        if row.get("reason_source") == "ANSWER_DECISION_BINDING"
    )


def test_reason_retrieval_respects_doc_id_filter(db):
    project, _, _, _ = _seed_project_prompt(db)
    _seed_xiaoma_claim_event_and_source(db)
    event = db.get(RecommendationEvent, 601)
    event.reasons_json = dumps([{"normalized_reason": "点击统计"}])
    db.add(SourceDocument(
        id=346,
        url="https://zhuanlan.zhihu.com/p/other",
        original_url="https://zhuanlan.zhihu.com/p/other",
        canonical_url="https://zhuanlan.zhihu.com/p/other",
        domain="zhuanlan.zhihu.com",
        fetch_status="SUCCESS",
        title="其他短链文章",
        clean_text="另一篇文章也提到了点击统计能力，并说明可以查看链接访问量和点击次数。",
        content_blocks_json=dumps([{"block_index": 1, "block_type": "PARAGRAPH", "text": "另一篇文章也提到了点击统计能力，并说明可以查看链接访问量和点击次数。"}]),
    ))
    db.add(SourceQuality(
        source_document_id=346,
        content_quality_status="CONTENT_VALID",
        quality_reason="fixture",
    ))
    db.commit()

    result = run_reason_driven_retrieval(db, project, 40, [238], doc_id_filter=[346])

    assert result["doc_id_filter"] == [346]
    passages = [
        passage
        for item in result["by_reason"].values()
        for passage in item.get("passages", [])
    ]
    assert passages
    assert {passage["doc_id"] for passage in passages} == {346}


def test_phase1_alignment_writes_formal_rows_with_binding_provenance(db, monkeypatch):
    import app.modules.optimization.evidence_alignment as evidence_alignment_module

    project, _, _, _ = _seed_project_prompt(db)
    _seed_xiaoma_claim_event_and_source(db)
    run_answer_evidence_shadow_chain(
        db,
        3,
        40,
        evidence_package_id=15,
        top_k=3,
        use_llm_binding=False,
        source_claim_judge=FakeSourceClaimJudge(),
        alignment_judge=FakeAlignmentJudge(),
    )
    db.add(SourceClaim(
        project_id=3,
        source_document_id=345,
        passage_id="doc345:b1",
        source_owner_entity="小码短链接",
        source_role="COMPETITOR_FIRST_PARTY",
        subject_entity="小码短链接",
        normalized_claim="小码短链接支持点击统计",
        subject_text="小码短链接",
        predicate="支持",
        object_text="点击统计",
        claim_type="CAPABILITY",
        polarity="POSITIVE",
        source_span="小码短链接支持点击统计",
        raw_start=0,
        raw_end=10,
        review_status="MACHINE_GROUNDED",
    ))
    db.commit()
    monkeypatch.setattr(evidence_alignment_module, "EvidenceAlignmentJudge", FakeFormalAlignmentJudge)

    result = run_evidence_alignment(db, project, 40, [238], include_answer_binding_reasons=True)

    assert result["answer_binding_reasons"] >= 1
    supports = db.query(EvidenceAlignment).filter(EvidenceAlignment.relation == "SUPPORTS").all()
    assert supports
    payload = loads(supports[0].machine_payload_json, {})
    assert payload["reason_source"] == "ANSWER_DECISION_BINDING"
    assert payload["formal_input_version"] == "citation_decision_v1_1_formal_input.v1"
    assert payload["answer_unit_id"]
    assert payload["decision_binding_id"]


def test_phase1_alignment_preserves_run_observations_for_semantic_dedupe(db, monkeypatch):
    import app.modules.optimization.evidence_alignment as evidence_alignment_module

    project, _, _, package = _seed_project_prompt(db)
    package.source_run_ids_json = dumps([238, 239])
    _seed_xiaoma_claim_event_and_source(db)
    db.add(BrowserMonitorRun(
        id=239,
        task_id=10,
        project_id=3,
        prompt_id=40,
        status="success",
        answer_text="小码短链接：自带点击统计。",
    ))
    db.add(AnswerClaim(
        id=502,
        run_id=239,
        claim_index=1,
        raw_text="小码短链接：自带点击统计",
        provenance="RULE_DERIVED",
        review_status="PENDING",
    ))
    db.add(RecommendationEvent(
        id=602,
        project_id=3,
        prompt_id=40,
        run_id=239,
        entity_text="小码短链接",
        entity_type="BRAND",
        speech_act="RECOMMEND",
        recommendation_strength="HIGH",
        answer_span="小码短链接：自带点击统计。",
        reasons_json=dumps([]),
        review_status="HUMAN_CONFIRMED",
    ))
    db.add(AnswerEvidenceShadowRun(
        id=901,
        project_id=3,
        prompt_id=40,
        evidence_package_id=15,
        source_run_ids_json=dumps([238, 239]),
        pipeline_version=SHADOW_PIPELINE_VERSION,
        status="completed",
        formal_output_impact="NONE",
    ))
    db.add_all([
        AnswerUnit(
            id=801,
            shadow_run_id=901,
            project_id=3,
            prompt_id=40,
            run_id=238,
            answer_claim_id=501,
            unit_text_original="小码短链接自带点击统计",
            unit_text_normalized="小码短链接自带点击统计",
            source_span="小码短链接自带点击统计",
            entity_hint="小码短链接",
        ),
        AnswerUnit(
            id=802,
            shadow_run_id=901,
            project_id=3,
            prompt_id=40,
            run_id=239,
            answer_claim_id=502,
            unit_text_original="小码短链接自带点击统计",
            unit_text_normalized="小码短链接自带点击统计",
            source_span="小码短链接自带点击统计",
            entity_hint="小码短链接",
        ),
        AnswerDecisionBinding(
            id=811,
            shadow_run_id=901,
            project_id=3,
            prompt_id=40,
            run_id=238,
            recommendation_event_id=601,
            answer_unit_id=801,
            decision_role="SUPPORTING_REASON",
            pipeline_version=SHADOW_PIPELINE_VERSION,
            review_status="MACHINE_GROUNDED",
        ),
        AnswerDecisionBinding(
            id=812,
            shadow_run_id=901,
            project_id=3,
            prompt_id=40,
            run_id=239,
            recommendation_event_id=602,
            answer_unit_id=802,
            decision_role="SUPPORTING_REASON",
            pipeline_version=SHADOW_PIPELINE_VERSION,
            review_status="MACHINE_GROUNDED",
        ),
        SourceClaim(
            project_id=3,
            source_document_id=345,
            passage_id="doc345:b1",
            source_owner_entity="小码短链接",
            source_role="COMPETITOR_FIRST_PARTY",
            subject_entity="小码短链接",
            normalized_claim="小码短链接支持点击统计",
            subject_text="小码短链接",
            predicate="支持",
            object_text="点击统计",
            claim_type="CAPABILITY",
            polarity="POSITIVE",
            source_span="小码短链接支持点击统计",
            raw_start=0,
            raw_end=10,
            review_status="MACHINE_GROUNDED",
        ),
    ])
    db.commit()
    monkeypatch.setattr(evidence_alignment_module, "EvidenceAlignmentJudge", FakeFormalAlignmentJudge)

    result = run_evidence_alignment(
        db,
        project,
        40,
        [238, 239],
        include_answer_binding_reasons=True,
        doc_id_filter=[345],
    )

    supports = db.query(EvidenceAlignment).filter(EvidenceAlignment.relation == "SUPPORTS").all()
    assert result["judge_calls"] == 1
    assert {alignment.run_id for alignment in supports} == {238, 239}
    for alignment in supports:
        payload = loads(alignment.machine_payload_json, {})
        assert payload["observed_run_ids"] == [238, 239]
        assert payload["run_coverage_count"] == 2
        assert payload["run_coverage_denominator"] == 2
        assert payload["reason_source"] == "ANSWER_DECISION_BINDING"


def test_recommended_brand_feature_defaults_to_supporting_reason(db):
    _seed_project_prompt(db)
    _seed_xiaoma_claim_event_and_source(db)

    result = run_answer_evidence_shadow_chain(
        db,
        3,
        40,
        evidence_package_id=15,
        use_llm_binding=False,
        entity_filter="小码短链接",
        source_claim_judge=FakeSourceClaimJudge(),
        alignment_judge=FakeAlignmentJudge(),
    )

    bindings = db.query(AnswerDecisionBinding).all()
    assert result["summary"]["binding_count"] >= 1
    assert {binding.decision_role for binding in bindings} == {"SUPPORTING_REASON"}
    assert {binding.scope_type for binding in bindings} <= {"SAME_SENTENCE", "ENTITY_HEADING_SCOPE"}


def test_procedure_answer_unit_does_not_bind_as_recommendation_reason(db):
    _seed_project_prompt(db)
    db.add(AnswerClaim(
        id=502,
        run_id=238,
        claim_index=1,
        raw_text="小码短链接：点击输入框粘贴长链接，然后保存生成短链",
        provenance="RULE_DERIVED",
        review_status="PENDING",
    ))
    db.add(RecommendationEvent(
        id=602,
        project_id=3,
        prompt_id=40,
        run_id=238,
        entity_text="小码短链接",
        entity_type="BRAND",
        speech_act="RECOMMEND",
        answer_span="小码短链接：点击输入框粘贴长链接，然后保存生成短链",
        reasons_json=dumps([]),
        review_status="HUMAN_CONFIRMED",
    ))
    db.commit()

    result = run_answer_evidence_shadow_chain(
        db,
        3,
        40,
        evidence_package_id=15,
        use_llm_binding=False,
        source_claim_judge=FakeSourceClaimJudge(),
        alignment_judge=FakeAlignmentJudge(),
    )

    assert result["summary"]["answer_unit_count"] >= 1
    assert result["summary"]["binding_count"] == 0
    assert result["summary"]["shadow_result_count"] == 0


def test_procedure_context_can_record_procedural_evidence_without_recommendation_eligibility(db):
    _, _, run, _ = _seed_project_prompt(db)
    run.answer_text = "小码短链接：点击输入框粘贴长链接，然后保存生成短链"
    db.add(AnswerClaim(
        id=506,
        run_id=238,
        claim_index=1,
        raw_text="小码短链接：点击输入框粘贴长链接，然后保存生成短链",
        provenance="RULE_DERIVED",
        review_status="PENDING",
    ))
    db.add(RecommendationEvent(
        id=606,
        project_id=3,
        prompt_id=40,
        run_id=238,
        entity_text="小码短链接",
        entity_type="BRAND",
        speech_act="RECOMMEND",
        answer_span="小码短链接：点击输入框粘贴长链接，然后保存生成短链",
        reasons_json=dumps([]),
        review_status="HUMAN_CONFIRMED",
    ))
    db.add(ReferenceSource(
        id=702,
        run_id=238,
        reference_index=1,
        display_title="小码短链接使用教程",
        url="https://zhuanlan.zhihu.com/p/procedure",
        canonical_url="https://zhuanlan.zhihu.com/p/procedure",
        domain="zhuanlan.zhihu.com",
    ))
    passage = "打开小码短链接后台，在输入框粘贴长链接，然后保存生成短链。"
    db.add(SourceDocument(
        id=346,
        url="https://zhuanlan.zhihu.com/p/procedure",
        original_url="https://zhuanlan.zhihu.com/p/procedure",
        canonical_url="https://zhuanlan.zhihu.com/p/procedure",
        domain="zhuanlan.zhihu.com",
        fetch_status="SUCCESS",
        title="小码短链接使用教程",
        clean_text=passage,
        content_blocks_json=dumps([{"block_index": 1, "block_type": "PARAGRAPH", "text": passage}]),
    ))
    db.add(SourceQuality(
        source_document_id=346,
        content_quality_status="CONTENT_VALID",
        quality_reason="fixture",
    ))
    db.commit()

    result = run_answer_evidence_shadow_chain(
        db,
        3,
        40,
        evidence_package_id=15,
        top_k=1,
        use_llm_binding=False,
        include_procedural_context=True,
        source_claim_judge=FakeProcedureSourceClaimJudge(),
        alignment_judge=FakeAlignmentJudge(),
    )

    summary = result["summary"]
    assert summary["binding_count"] == 0
    assert summary["context_binding_count"] >= 1
    assert summary["supports_count"] >= 1
    assert summary["recommendation_evidence_eligible_count"] == 0
    assert summary["evidence_classification_counts"]["PROCEDURAL_EVIDENCE"] >= 1


def test_mention_feature_does_not_bind_without_recommendation_event(db):
    _seed_project_prompt(db)
    db.add(AnswerClaim(
        id=503,
        run_id=238,
        claim_index=1,
        raw_text="小码短链接：提供短链管理和访问统计能力",
        provenance="RULE_DERIVED",
        review_status="PENDING",
    ))
    db.add(RecommendationEvent(
        id=603,
        project_id=3,
        prompt_id=40,
        run_id=238,
        entity_text="小码短链接",
        entity_type="BRAND",
        speech_act="MENTION",
        answer_span="小码短链接：提供短链管理和访问统计能力",
        reasons_json=dumps([]),
        review_status="HUMAN_CONFIRMED",
    ))
    db.commit()

    result = run_answer_evidence_shadow_chain(
        db,
        3,
        40,
        evidence_package_id=15,
        use_llm_binding=False,
        source_claim_judge=FakeSourceClaimJudge(),
        alignment_judge=FakeAlignmentJudge(),
    )

    assert result["summary"]["answer_unit_count"] >= 1
    assert result["summary"]["binding_count"] == 0


def test_other_brand_feature_does_not_bind_to_current_recommendation_scope(db):
    _seed_project_prompt(db)
    db.add(AnswerClaim(
        id=503,
        run_id=238,
        claim_index=1,
        raw_text="Bitly：支持链接缩短和点击统计能力",
        provenance="RULE_DERIVED",
        review_status="PENDING",
    ))
    db.add(RecommendationEvent(
        id=603,
        project_id=3,
        prompt_id=40,
        run_id=238,
        entity_text="小码短链接",
        entity_type="BRAND",
        speech_act="RECOMMEND",
        answer_span="推荐小码短链接，适合营销场景使用。",
        reasons_json=dumps([]),
        review_status="HUMAN_CONFIRMED",
    ))
    db.commit()

    result = run_answer_evidence_shadow_chain(
        db,
        3,
        40,
        evidence_package_id=15,
        use_llm_binding=False,
        source_claim_judge=FakeSourceClaimJudge(),
        alignment_judge=FakeAlignmentJudge(),
    )

    assert result["summary"]["answer_unit_count"] >= 1
    assert result["summary"]["binding_count"] == 0


def test_limitation_binds_as_counter_reason_not_positive_supporting_reason(db):
    _, _, run, _ = _seed_project_prompt(db)
    run.answer_text = "推荐小码短链接，但它不支持自定义域名，存在使用限制。"
    db.add(AnswerClaim(
        id=508,
        run_id=238,
        claim_index=1,
        raw_text="小码短链接：不支持自定义域名，存在使用限制",
        provenance="RULE_DERIVED",
        review_status="PENDING",
    ))
    db.add(RecommendationEvent(
        id=608,
        project_id=3,
        prompt_id=40,
        run_id=238,
        entity_text="小码短链接",
        entity_type="BRAND",
        speech_act="RECOMMEND",
        answer_span="推荐小码短链接，但它不支持自定义域名，存在使用限制。",
        reasons_json=dumps([]),
        review_status="HUMAN_CONFIRMED",
    ))
    db.commit()

    result = run_answer_evidence_shadow_chain(
        db,
        3,
        40,
        evidence_package_id=15,
        use_llm_binding=False,
        source_claim_judge=FakeSourceClaimJudge(),
        alignment_judge=FakeAlignmentJudge(),
    )

    bindings = db.query(AnswerDecisionBinding).all()
    assert result["summary"]["binding_count"] == 2
    assert result["summary"]["counter_reason_count"] == 2
    assert {binding.decision_role for binding in bindings} == {"COUNTER_REASON"}
    assert result["summary"]["supporting_reason_count"] == 0
    assert result["summary"]["direct_reason_count"] == 0


def test_brand_directed_feature_without_recommendation_event_records_capability_evidence(db):
    _, _, run, _ = _seed_project_prompt(db)
    run.answer_text = "小码短链接支持点击统计。"
    db.add(AnswerClaim(
        id=507,
        run_id=238,
        claim_index=1,
        raw_text="小码短链接：支持点击统计",
        provenance="RULE_DERIVED",
        review_status="PENDING",
    ))
    db.add(ReferenceSource(
        id=703,
        run_id=238,
        reference_index=1,
        display_title="小码短链接功能说明",
        url="https://zhuanlan.zhihu.com/p/capability",
        canonical_url="https://zhuanlan.zhihu.com/p/capability",
        domain="zhuanlan.zhihu.com",
    ))
    passage = "小码短链接支持点击统计，可以查看每个链接的访问量和点击次数。"
    db.add(SourceDocument(
        id=347,
        url="https://zhuanlan.zhihu.com/p/capability",
        original_url="https://zhuanlan.zhihu.com/p/capability",
        canonical_url="https://zhuanlan.zhihu.com/p/capability",
        domain="zhuanlan.zhihu.com",
        fetch_status="SUCCESS",
        title="小码短链接功能说明",
        clean_text=passage,
        content_blocks_json=dumps([{"block_index": 1, "block_type": "PARAGRAPH", "text": passage}]),
    ))
    db.add(SourceQuality(
        source_document_id=347,
        content_quality_status="CONTENT_VALID",
        quality_reason="fixture",
    ))
    db.commit()

    result = run_answer_evidence_shadow_chain(
        db,
        3,
        40,
        evidence_package_id=15,
        top_k=1,
        use_llm_binding=False,
        include_unbound_answer_units=True,
        source_claim_judge=FakeSourceClaimJudge(),
        alignment_judge=FakeAlignmentJudge(),
    )

    summary = result["summary"]
    assert summary["binding_count"] == 0
    assert summary["brand_capability_evidence_count"] >= 1
    assert summary["recommendation_evidence_eligible_count"] == 0


def test_implicit_use_case_reason_can_bind_to_recommendation_event(db):
    _seed_project_prompt(db)
    db.add(AnswerClaim(
        id=504,
        run_id=238,
        claim_index=1,
        raw_text="小码短链接：适合营销场景使用",
        provenance="RULE_DERIVED",
        review_status="PENDING",
    ))
    db.add(RecommendationEvent(
        id=604,
        project_id=3,
        prompt_id=40,
        run_id=238,
        entity_text="小码短链接",
        entity_type="BRAND",
        speech_act="RECOMMEND",
        answer_span="综合功能完整性和使用场景看，小码短链接更适合营销团队。",
        reasons_json=dumps([]),
        review_status="HUMAN_CONFIRMED",
    ))
    db.commit()

    result = run_answer_evidence_shadow_chain(
        db,
        3,
        40,
        evidence_package_id=15,
        use_llm_binding=False,
        source_claim_judge=FakeSourceClaimJudge(),
        alignment_judge=FakeAlignmentJudge(),
    )

    assert result["summary"]["binding_count"] == 1
    assert result["summary"]["supporting_reason_count"] == 1


def test_shadow_entity_filter_limits_decision_bindings(db):
    _seed_project_prompt(db)
    _seed_xiaoma_claim_event_and_source(db)
    db.add(AnswerClaim(
        id=505,
        run_id=238,
        claim_index=2,
        raw_text="Bitly：支持链接缩短和点击统计",
        provenance="RULE_DERIVED",
        review_status="PENDING",
    ))
    db.add(RecommendationEvent(
        id=605,
        project_id=3,
        prompt_id=40,
        run_id=238,
        entity_text="Bitly",
        entity_type="BRAND",
        speech_act="RECOMMEND",
        answer_span="Bitly：支持链接缩短和点击统计",
        reasons_json=dumps([]),
        review_status="HUMAN_CONFIRMED",
    ))
    db.commit()

    result = run_answer_evidence_shadow_chain(
        db,
        3,
        40,
        evidence_package_id=15,
        use_llm_binding=False,
        entity_filter="小码短链接",
        source_claim_judge=FakeSourceClaimJudge(),
        alignment_judge=FakeAlignmentJudge(),
    )

    bindings = db.query(AnswerDecisionBinding).all()
    event_ids = {binding.recommendation_event_id for binding in bindings}
    assert result["summary"]["entity_filter"] == "小码短链接"
    assert event_ids == {601}
