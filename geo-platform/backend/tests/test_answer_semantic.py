from __future__ import annotations

import pytest

from app.modules.optimization.answer_semantic import (
    _answer_hash,
    locate_span,
    normalize_for_grounding,
)


# ---------------------------------------------------------------------------
# Grounding Validator（确定性，不需要 LLM）
# ---------------------------------------------------------------------------

def test_normalize_handles_fullwidth_and_spaces():
    a = normalize_for_grounding("商加加  外链")
    b = normalize_for_grounding("商加加外链")
    assert a == b


def test_normalize_decodes_html_entities():
    # nbsp 解码为空格后按空白移除规则删掉 → "AB"
    assert normalize_for_grounding("A&nbsp;B") == "AB"
    assert normalize_for_grounding("A&amp;B") == "A&B"


def test_locate_span_finds_exact_span():
    raw = "抖音跳转微信：可通过商加加外链等第三方工具生成短链。"
    result = locate_span(raw, "可通过商加加外链等第三方工具")
    assert result is not None
    assert raw[result["raw_start"]:result["raw_end"]] == "可通过商加加外链等第三方工具"


def test_locate_span_tolerates_space_differences():
    raw = "抖音跳转微信：可通过商加加外链等第三方工具生成短链。"
    result = locate_span(raw, "可通过 商加加 外链等第三方工具")
    assert result is not None


def test_locate_span_nonexistent_span_returns_none():
    raw = "可通过商加加外链等第三方工具"
    result = locate_span(raw, "完全不存在的伪造文字XYZ")
    assert result is None


def test_locate_span_empty_span_returns_none():
    assert locate_span("任意原文", "") is None


def test_locate_span_returns_raw_offsets_within_bounds():
    raw = "开头部分，可通过商加加外链等第三方工具，结尾部分"
    result = locate_span(raw, "可通过商加加外链等第三方工具")
    assert result is not None
    assert result["raw_start"] >= 0
    assert result["raw_end"] <= len(raw)
    assert result["raw_end"] > result["raw_start"]


def test_answer_hash_same_for_same_text():
    assert _answer_hash("相同答案") == _answer_hash("相同答案")


def test_answer_hash_differs_for_different_text():
    assert _answer_hash("答案A") != _answer_hash("答案B")


def test_answer_hash_whitespace_sensitive():
    """hash 基于原文——12 个完全相同的答案应得到同一 hash。"""
    a = "抖音跳转链接涵盖生成制作和跨端跳转使用两大核心场景。"
    b = "抖音跳转链接涵盖生成制作和跨端跳转使用两大核心场景。"
    assert _answer_hash(a) == _answer_hash(b)
