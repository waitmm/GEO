from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    AnswerDecisionBinding,
    AnswerEvidenceShadowRun,
    AnswerUnit,
    Base,
    Project,
    RecommendationEvent,
)
from app.modules.optimization.passage_retrieval import (
    SHADOW_INPUT_PIPELINE_VERSION,
    answer_binding_reason_inputs,
    retrieve_passages_for_reason,
    tokenize_zh,
)
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


def test_tokenize_zh_bigram():
    tokens = tokenize_zh("跨端跳转")
    assert "跨端" in tokens
    assert "端跳" in tokens


def test_tokenize_mixed_chinese_english():
    tokens = tokenize_zh("抖音 Scheme 协议")
    assert "抖音" in tokens
    assert "scheme" in tokens


def test_retrieve_ranks_relevant_passage_first():
    passages = [
        {"doc_id": 1, "passage_id": "d1:p0", "text": "这是一个完全无关的段落，讲天气和美食。"},
        {"doc_id": 1, "passage_id": "d1:p1", "text": "商加加支持抖音跳转微信，可以生成加密短链规避平台拦截。"},
        {"doc_id": 1, "passage_id": "d1:p2", "text": "另一个无关段落，讲历史故事。"},
    ]
    hits = retrieve_passages_for_reason("抖音跳转微信的加密短链能力", passages, top_k=3)
    assert len(hits) > 0
    assert hits[0]["passage_id"] == "d1:p1"


def test_retrieve_filters_zero_score_passages():
    passages = [
        {"doc_id": 1, "passage_id": "d1:p0", "text": "天气很好，适合出行。"},
    ]
    hits = retrieve_passages_for_reason("加密短链跳转能力", passages, top_k=3)
    assert hits == []


def test_retrieve_empty_passages():
    assert retrieve_passages_for_reason("任意", [], top_k=3) == []


def test_answer_binding_reason_inputs_uses_atomic_event_reason_anchor(db):
    project = Project(id=1, organization_id=1, name="P", brand_name="爱短链", website_url="https://aifabu.com")
    db.add(project)
    db.add(
        AnswerEvidenceShadowRun(
            id=1,
            project_id=1,
            prompt_id=19,
            source_run_ids_json=dumps([101]),
            pipeline_version=SHADOW_INPUT_PIPELINE_VERSION,
            status="completed",
            formal_output_impact="NONE",
        )
    )
    db.add(
        RecommendationEvent(
            id=1,
            project_id=1,
            prompt_id=19,
            run_id=101,
            entity_text="商加加",
            speech_act="RECOMMEND",
            review_status="HUMAN_CONFIRMED",
            reasons_json=dumps([
                {"normalized_reason": "可以自动生成加密短链", "reason_scope": "ENTITY_SPECIFIC", "reason_span": "自动生成加密短链"},
                {"normalized_reason": "可以规避平台拦截", "reason_scope": "ENTITY_SPECIFIC", "reason_span": "规避平台拦截"},
            ]),
        )
    )
    db.add(
        AnswerUnit(
            id=1,
            shadow_run_id=1,
            project_id=1,
            prompt_id=19,
            run_id=101,
            answer_claim_id=1,
            unit_text_original="商加加支持抖音跳转微信，填写目标微信信息后自动生成加密短链。",
            unit_text_normalized="抖音跳转微信填写目标微信信息自动生成加密短链",
            review_status="MACHINE_GROUNDED",
        )
    )
    db.add(
        AnswerDecisionBinding(
            id=1,
            shadow_run_id=1,
            project_id=1,
            prompt_id=19,
            run_id=101,
            recommendation_event_id=1,
            answer_unit_id=1,
            decision_role="DIRECT_REASON",
            binding_strength="HIGH",
            pipeline_version=SHADOW_INPUT_PIPELINE_VERSION,
            review_status="MACHINE_GROUNDED",
            judge_payload_json=dumps({"rule_candidate": {"reason_anchor_text": "自动生成加密短链"}}),
        )
    )
    db.commit()

    rows = answer_binding_reason_inputs(db, project, 19, [101])

    assert len(rows) == 1
    assert rows[0]["text"] == "可以自动生成加密短链"
    assert rows[0]["reason_anchor_text"] == "自动生成加密短链"
    assert rows[0]["answer_unit_text"] == "抖音跳转微信填写目标微信信息自动生成加密短链"
