from __future__ import annotations

from app.modules.optimization.passage_retrieval import (
    retrieve_passages_for_reason,
    tokenize_zh,
)


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
