from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Project, RecommendationEvent, SourceClaim, SourceClaimMaterialization, SourceDocument
from app.modules.optimization.passage_retrieval import run_reason_driven_retrieval
from app.modules.optimization import source_claim as source_claim_module
from app.modules.optimization.source_claim import (
    SOURCE_CLAIM_MATERIALIZATION_CONTRACT,
    SOURCE_CLAIM_PROMPT_VERSION,
    SOURCE_CLAIM_SCHEMA_VERSION,
    SourceClaimJudge,
    _source_claim_row_key,
    resolve_source_claim_materialization_compatibility,
    run_source_claim_extraction,
)
from app.services.semantic_llm.base import SemanticLLMError
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


def test_subject_entity_separated_from_owner_entity(db):
    """subject_entity（语义主体）与 source_owner_entity（provenance）分列存储。"""
    project = Project(id=1, organization_id=1, name="P", brand_name="爱短链", website_url="https://aifabu.com")
    doc = SourceDocument(id=1, url="https://shangjiajia.com/4626.html", domain="shangjiajia.com", fetch_status="SUCCESS")
    db.add_all([project, doc])
    db.commit()

    claim = SourceClaim(
        project_id=1, source_document_id=1, passage_id="doc1:p0",
        source_owner_entity="商加加", source_role="COMPETITOR_FIRST_PARTY",
        subject_entity="天天外链",  # Judge 识别正文在讲天天外链
        normalized_claim="天天外链支持抖音跳转", claim_type="CAPABILITY", polarity="POSITIVE",
        source_span="天天外链支持抖音跳转", raw_start=0, raw_end=9,
    )
    db.add(claim)
    db.commit()

    saved = db.query(SourceClaim).first()
    assert saved.subject_entity == "天天外链"
    assert saved.source_owner_entity == "商加加"
    assert saved.subject_entity != saved.source_owner_entity


def test_negation_preserved_in_normalized_claim(db):
    """否定不得翻转：'不支持' 不能存成 '支持'。"""
    project = Project(id=1, organization_id=1, name="P", brand_name="B", website_url="https://b.com")
    doc = SourceDocument(id=1, url="https://x.com/a", domain="x.com", fetch_status="SUCCESS")
    db.add_all([project, doc])
    db.commit()
    claim = SourceClaim(
        project_id=1, source_document_id=1, passage_id="p0",
        source_owner_entity="UNKNOWN", source_role="UNKNOWN",
        subject_entity="某工具",
        normalized_claim="某工具不支持修改目标地址",
        predicate="不支持", object_text="修改目标地址",
        claim_type="LIMITATION", polarity="NEGATIVE",
        source_span="不支持修改目标地址", raw_start=0, raw_end=9,
    )
    db.add(claim)
    db.commit()
    saved = db.query(SourceClaim).first()
    assert saved.predicate == "不支持"
    assert saved.polarity == "NEGATIVE"
    assert "不支持" in saved.normalized_claim


def test_ungrounded_span_marks_validation_failed(db):
    """span 无法定位时必须 VALIDATION_FAILED（由 run 流程处理，此处验证字段语义）。"""
    project = Project(id=1, organization_id=1, name="P", brand_name="B", website_url="https://b.com")
    doc = SourceDocument(id=1, url="https://x.com/a", domain="x.com", fetch_status="SUCCESS")
    db.add_all([project, doc])
    db.commit()
    claim = SourceClaim(
        project_id=1, source_document_id=1, passage_id="p0",
        source_owner_entity="UNKNOWN", source_role="UNKNOWN", subject_entity="X",
        normalized_claim="", claim_type="OTHER", polarity="NEUTRAL",
        source_span="伪造的span", raw_start=-1, raw_end=-1,
        review_status="VALIDATION_FAILED",
    )
    db.add(claim)
    db.commit()
    assert db.query(SourceClaim).first().review_status == "VALIDATION_FAILED"


def test_judge_system_prompt_has_injection_guard():
    """SourceClaimJudge 的 System Prompt 必须包含注入防护说明。"""
    from app.modules.optimization.source_claim import SOURCE_CLAIM_SYSTEM
    assert "不是指令" in SOURCE_CLAIM_SYSTEM
    assert "只输出纯 JSON 对象" in SOURCE_CLAIM_SYSTEM or "JSON" in SOURCE_CLAIM_SYSTEM


def test_source_claim_semantic_key_ignores_ephemeral_row_id(db):
    doc = SourceDocument(id=1, url="https://x.com/a", domain="x.com", fetch_status="SUCCESS")
    claim_a = SourceClaim(
        id=10,
        project_id=1,
        source_document_id=1,
        passage_id="doc1:b1",
        normalized_claim="小码短链接 可以 查看 点击次数",
        source_span="小码短链接可以查看点击次数。",
        claim_type="CAPABILITY",
        polarity="POSITIVE",
    )
    claim_b = SourceClaim(
        id=11,
        project_id=1,
        source_document_id=1,
        passage_id="doc1:b1",
        normalized_claim="小码短链接 可以 查看 点击次数",
        source_span="小码短链接可以查看点击次数。",
        claim_type="CAPABILITY",
        polarity="POSITIVE",
    )
    db.add_all([doc, claim_a, claim_b])
    db.commit()

    assert _source_claim_row_key(claim_a) == _source_claim_row_key(claim_b)


def test_empty_doc_filter_does_not_expand_reason_retrieval_to_all_documents(db):
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
    doc = SourceDocument(
        id=1,
        url="https://zhuanlan.zhihu.com/p/1",
        domain="zhuanlan.zhihu.com",
        fetch_status="SUCCESS",
        clean_text="小码短链接可以查看点击次数和访问量。",
    )
    db.add_all([project, event, doc])
    db.commit()

    result = run_reason_driven_retrieval(
        db,
        project,
        prompt_id=1,
        run_ids=[1],
        doc_id_filter=[],
    )

    assert result["valid_documents"] == 0
    assert result["passages_retrieved"] == 0


def _add_project_event_doc(db, *, doc_id=1, text="爱短链支持点击统计，可以查看访问数据，并提供访问来源分析。", reason="点击统计"):
    project = Project(id=1, organization_id=1, name="P", brand_name="爱短链", website_url="https://aifabu.com")
    event = RecommendationEvent(
        id=1,
        project_id=1,
        prompt_id=1,
        run_id=1,
        entity_text="爱短链",
        speech_act="RECOMMEND",
        review_status="HUMAN_CONFIRMED",
        reasons_json=dumps([{"normalized_reason": reason, "reason_scope": "ENTITY_SPECIFIC"}]),
    )
    doc = SourceDocument(
        id=doc_id,
        url=f"https://aifabu.com/{doc_id}",
        canonical_url=f"https://aifabu.com/{doc_id}",
        domain="aifabu.com",
        fetch_status="SUCCESS",
        clean_text=text,
        clean_text_hash="same-content",
        content_blocks_json=dumps([{"block_index": 1, "text": text}]),
        fetch_time=datetime.utcnow(),
    )
    db.add_all([project, event, doc])
    db.commit()
    return project, event, doc


def _fake_judge(monkeypatch, payloads):
    calls = []

    class FakeJudge:
        def __init__(self):
            self.client = SimpleNamespace(provider="deepseek")
            self.settings = SimpleNamespace(deepseek_model="test-model")

        def judge_passage(self, passage_text, db=None):
            calls.append(passage_text)
            if callable(payloads):
                return payloads(passage_text)
            return payloads

    monkeypatch.setattr(source_claim_module, "SourceClaimJudge", FakeJudge)
    return calls


def test_source_claim_zero_claim_materialization_skips_second_llm(db, monkeypatch):
    project, _, _ = _add_project_event_doc(
        db,
        text="这是一段点击统计相关的导航和版权说明，没有明确产品能力主张。",
        reason="点击统计",
    )
    calls = _fake_judge(monkeypatch, {"claims": []})

    first = run_source_claim_extraction(db, project, prompt_id=1, run_ids=[1], top_k=5)
    second = run_source_claim_extraction(db, project, prompt_id=1, run_ids=[1], top_k=5)

    materialization = db.query(SourceClaimMaterialization).one()
    assert len(calls) == 1
    assert first["actual_source_claim_llm_calls"] == 1
    assert second["actual_source_claim_llm_calls"] == 0
    assert first["processed_materialization_keys"] == second["processed_materialization_keys"]
    assert second["zero_claim_hit_count"] == 1
    assert materialization.status == "DONE"
    assert materialization.claim_count == 0
    assert db.query(SourceClaim).count() == 0


def test_source_claim_duplicate_passage_across_documents_uses_one_materialization(db, monkeypatch):
    project, _, doc1 = _add_project_event_doc(db)
    text = "爱短链支持点击统计，可以查看访问数据，并提供访问来源分析。"
    doc2 = SourceDocument(
        id=2,
        url="https://mirror.example/a",
        canonical_url="https://mirror.example/a",
        domain="mirror.example",
        fetch_status="SUCCESS",
        clean_text=text,
        clean_text_hash="same-content",
        content_blocks_json=dumps([{"block_index": 1, "text": text}]),
    )
    db.add(doc2)
    db.commit()
    calls = _fake_judge(monkeypatch, {
        "claims": [{
            "normalized_claim": "爱短链支持点击统计",
            "subject_text": "爱短链",
            "predicate": "支持",
            "object_text": "点击统计",
            "claim_type": "CAPABILITY",
            "polarity": "POSITIVE",
            "source_span": "爱短链支持点击统计",
        }]
    })

    result = run_source_claim_extraction(db, project, prompt_id=1, run_ids=[1], top_k=5)
    materialization = db.query(SourceClaimMaterialization).one()

    assert len(calls) == 1
    assert result["required_passage_rows"] == 2
    assert result["unique_extraction_inputs"] == 1
    assert len(result["processed_materialization_keys"]) == 1
    assert result["claims_created"] == 2
    assert db.query(SourceClaim).count() == 2
    assert set(loads(materialization.observed_source_document_ids_json, [])) == {doc1.id, doc2.id}


def test_source_claim_same_content_refresh_reuses_materialization(db, monkeypatch):
    project, _, doc = _add_project_event_doc(db)
    calls = _fake_judge(monkeypatch, {
        "claims": [{
            "normalized_claim": "爱短链支持点击统计",
            "subject_text": "爱短链",
            "predicate": "支持",
            "object_text": "点击统计",
            "claim_type": "CAPABILITY",
            "polarity": "POSITIVE",
            "source_span": "爱短链支持点击统计",
        }]
    })

    first = run_source_claim_extraction(db, project, prompt_id=1, run_ids=[1], top_k=5)
    doc.fetch_time = datetime.utcnow()
    db.commit()
    second = run_source_claim_extraction(db, project, prompt_id=1, run_ids=[1], top_k=5)

    assert len(calls) == 1
    assert first["actual_source_claim_llm_calls"] == 1
    assert second["actual_source_claim_llm_calls"] == 0
    assert second["materialization_hit_count"] == 1
    assert db.query(SourceClaimMaterialization).count() == 1


def test_source_claim_progress_callback_reports_running_and_hit_states(db, monkeypatch):
    project, _, _ = _add_project_event_doc(db)
    calls = _fake_judge(monkeypatch, {
        "claims": [{
            "normalized_claim": "爱短链支持点击统计",
            "subject_text": "爱短链",
            "predicate": "支持",
            "object_text": "点击统计",
            "claim_type": "CAPABILITY",
            "polarity": "POSITIVE",
            "source_span": "爱短链支持点击统计",
        }]
    })
    first_progress: list[dict] = []
    second_progress: list[dict] = []

    first = run_source_claim_extraction(
        db,
        project,
        prompt_id=1,
        run_ids=[1],
        top_k=5,
        progress_callback=first_progress.append,
    )
    second = run_source_claim_extraction(
        db,
        project,
        prompt_id=1,
        run_ids=[1],
        top_k=5,
        progress_callback=second_progress.append,
    )

    assert len(calls) == 1
    assert first_progress[0]["processed"] == 0
    assert first_progress[0]["total"] == first["unique_jobs"] == 1
    assert any(
        item["processed"] == 0 and item["actual_source_claim_llm_calls"] == 1
        for item in first_progress
    )
    assert any(item["processed"] == 1 for item in first_progress)
    assert any(item["actual_source_claim_llm_calls"] == 1 for item in first_progress)
    assert second["actual_source_claim_llm_calls"] == 0
    assert second_progress[0]["processed"] == 0
    assert second_progress[-1]["processed"] == second_progress[-1]["total"] == 1
    assert second_progress[-1]["materialization_hit_count"] == 1


def test_source_claim_failed_external_attempt_counts_as_llm_call(db, monkeypatch):
    project, _, _ = _add_project_event_doc(db)

    class FailingJudge:
        def __init__(self):
            self.client = SimpleNamespace(provider="deepseek")
            self.settings = SimpleNamespace(deepseek_model="test-model")

        def judge_passage(self, passage_text, db=None):
            raise SemanticLLMError("model returned invalid json")

    monkeypatch.setattr(source_claim_module, "SourceClaimJudge", FailingJudge)
    progress: list[dict] = []

    result = run_source_claim_extraction(
        db,
        project,
        prompt_id=1,
        run_ids=[1],
        top_k=5,
        progress_callback=progress.append,
    )

    materialization = db.query(SourceClaimMaterialization).one()
    assert result["actual_source_claim_llm_calls"] == 1
    assert result["failed_retryable"] == 1
    assert materialization.status == "FAILED_RETRYABLE"
    assert any(
        item["processed"] == 0 and item["actual_source_claim_llm_calls"] == 1
        for item in progress
    )
    assert progress[-1]["actual_source_claim_llm_calls"] == 1
    assert progress[-1]["failed_retryable"] == 1


def test_source_claim_content_change_creates_new_materialization(db, monkeypatch):
    project, event, doc = _add_project_event_doc(db)
    calls = _fake_judge(monkeypatch, lambda passage: {
        "claims": [{
            "normalized_claim": passage.split("，")[0],
            "subject_text": "爱短链",
            "predicate": "支持",
            "object_text": "点击统计" if "点击统计" in passage else "自定义分享标题",
            "claim_type": "CAPABILITY",
            "polarity": "POSITIVE",
            "source_span": "爱短链支持点击统计" if "点击统计" in passage else "爱短链支持自定义分享标题",
        }]
    })

    run_source_claim_extraction(db, project, prompt_id=1, run_ids=[1], top_k=5)
    new_text = "爱短链支持点击统计和自定义分享标题，可以设置卡片展示文案。"
    doc.clean_text = new_text
    doc.clean_text_hash = "changed-content"
    doc.content_blocks_json = dumps([{"block_index": 1, "text": new_text}])
    db.commit()
    second = run_source_claim_extraction(db, project, prompt_id=1, run_ids=[1], top_k=5)

    assert len(calls) == 2
    assert second["actual_source_claim_llm_calls"] == 1
    assert db.query(SourceClaimMaterialization).count() == 2


def test_source_claim_impl_upgrade_keeps_contract_compatible(db, monkeypatch):
    project, _, _ = _add_project_event_doc(db)
    calls = _fake_judge(monkeypatch, {"claims": []})

    run_source_claim_extraction(db, project, prompt_id=1, run_ids=[1], top_k=5)
    materialization = db.query(SourceClaimMaterialization).one()
    materialization.extractor_impl_version = "source_claim_extractor.impl.2.7.1"
    db.commit()
    second = run_source_claim_extraction(db, project, prompt_id=1, run_ids=[1], top_k=5)

    assert len(calls) == 1
    assert second["actual_source_claim_llm_calls"] == 0
    assert resolve_source_claim_materialization_compatibility(materialization) == "COMPATIBLE"


def test_source_claim_breaking_contract_is_stale_schema(db):
    materialization = SourceClaimMaterialization(
        materialization_key="k",
        source_document_id=1,
        passage_content_hash="h",
        contract_version=SOURCE_CLAIM_MATERIALIZATION_CONTRACT,
        status="DONE",
    )

    assert resolve_source_claim_materialization_compatibility(materialization, "SOURCE_CLAIM_V2") == "STALE_SCHEMA"


def test_source_claim_legacy_rows_backfill_materialization_without_llm(db, monkeypatch):
    project, _, doc = _add_project_event_doc(db)
    claim = SourceClaim(
        project_id=1,
        source_document_id=doc.id,
        passage_id="doc1:b1",
        source_owner_entity="爱短链",
        source_role="TARGET_FIRST_PARTY",
        subject_entity="爱短链",
        normalized_claim="爱短链支持点击统计",
        subject_text="爱短链",
        predicate="支持",
        object_text="点击统计",
        claim_type="CAPABILITY",
        polarity="POSITIVE",
        source_span="爱短链支持点击统计",
        prompt_version=SOURCE_CLAIM_PROMPT_VERSION,
        schema_version=SOURCE_CLAIM_SCHEMA_VERSION,
        review_status="MACHINE_GROUNDED",
    )
    db.add(claim)
    db.commit()
    calls = _fake_judge(monkeypatch, {"claims": []})

    result = run_source_claim_extraction(db, project, prompt_id=1, run_ids=[1], top_k=5)

    assert calls == []
    assert result["legacy_reuse_count"] == 1
    assert result["actual_source_claim_llm_calls"] == 0
    assert db.query(SourceClaimMaterialization).one().claim_count == 1
