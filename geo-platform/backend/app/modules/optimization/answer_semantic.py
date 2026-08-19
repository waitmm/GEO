"""Layer 1 — Answer Semantic Judge + Grounding Validator.

目标：把 12 个真实 Answer 转成 RecommendationEvent（entity/speech_act/reason），
而非关键词匹配。

关键纪律：
- Grounding 与 Normalization 分离：LLM 的 normalized_reason 可概括，
  answer_span 必须能定位回原文，否则 VALIDATION_FAILED。
- 12 个相同 Answer 按 answer_hash 只调一次 LLM，但每个 Run 独立关联事件。
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import BrowserMonitorRun, Project, Prompt, RecommendationEvent
from app.services.semantic_llm.base import SemanticLLMError
from app.services.semantic_llm.deepseek import DeepSeekClient
from app.services.serialization import dumps, loads

ANSWER_SEMANTIC_PROMPT_VERSION = "answer_semantic.v1"
ANSWER_SEMANTIC_SCHEMA_VERSION = "v1"

ANSWER_SEMANTIC_SYSTEM = """你是一个严格的 AI Answer 语义标注器。

你的任务不是评价答案质量，也不是补充知识，而是仅根据提供的 Answer 原文识别其中真实发生的品牌、产品、工具或解决方案选择行为。

严格规则：

1. 只能依据给出的 Answer。
2. 不允许使用外部知识。
3. 不允许因为某品牌知名就推断其被推荐。
4. “有人推荐X”“网上推荐X”不等于回答作者推荐X。
5. 没有“推荐/建议”字样也可能构成推荐行为，需要判断真实 Speech Act。
6. 否定、转折必须正确处理。
7. 每一个事件必须提供可在 Answer 原文定位的 answer_span。
8. normalized reason 可以概括，但 answer_span 不得伪造。
9. 不确定时输出 UNRESOLVED。
10. 不允许为了输出完整结构而制造事件。

speech_act 只能使用：
RECOMMEND / INCLUDE_AS_OPTION / PRAISE / COMPARE / MENTION / DISCOURAGE / REJECT

recommendation_strength 只能使用：
STRONG / MODERATE / WEAK / NONE

polarity 只能使用：
POSITIVE / NEUTRAL / NEGATIVE

reason_scope 只能使用：
ENTITY_SPECIFIC / MARKET_CRITERION

输出格式：
{
  "events": [
    {
      "entity_text": "商加加",
      "entity_type": "BRAND",
      "speech_act": "INCLUDE_AS_OPTION",
      "recommendation_strength": "MODERATE",
      "polarity": "POSITIVE",
      "answer_span": "可通过商加加外链等第三方工具",
      "reasons": [
        {
          "normalized_reason": "可以作为抖音跨端跳转工具",
          "reason_scope": "ENTITY_SPECIFIC",
          "reason_span": "抖音跳转微信：可通过商加加外链等第三方工具"
        }
      ]
    }
  ],
  "selection_criteria": [],
  "unresolved_items": []
}

没有真实事件时 events 返回空数组，不要编造。

必须输出纯 JSON 对象（DeepSeek JSON mode 要求）。
"""


# ---------------------------------------------------------------------------
# Grounding Validator（确定性）
# ---------------------------------------------------------------------------

def normalize_for_grounding(text: str) -> str:
    """Unicode 归一化 → HTML entity 解码 → 空白归一化。"""
    t = unicodedata.normalize("NFKC", text or "")
    t = t.replace("​", "").replace(" ", " ")  # 零宽空格/不换行空格
    # 常见 HTML entity（不含 &; 形式的数字引用，按需要补充）
    for entity, char in {"&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'"}.items():
        t = t.replace(entity, char)
    # 中文证据：空白不承载语义，全部移除（含换行/缩进/多空格）
    t = re.sub(r"\s+", "", t)
    return t.strip()


def locate_span(raw_answer: str, answer_span: str) -> dict:
    """在原文中定位 span。

    返回 {"raw_start", "raw_end", "raw_span"}；定位失败返回 None。
    基于归一化后的连续文本匹配，避免空格/全半角差异误判。
    """
    if not answer_span:
        return None
    raw = raw_answer or ""
    norm_raw = normalize_for_grounding(raw)
    norm_span = normalize_for_grounding(answer_span)
    if not norm_span:
        return None

    idx = norm_raw.find(norm_span)
    if idx < 0:
        return None

    # 归一化后偏移量映射回原文：逐字符扫描累积长度
    raw_start, raw_end = _map_offsets(raw, norm_raw, idx, idx + len(norm_span))
    if raw_start < 0:
        return None
    return {
        "raw_start": raw_start,
        "raw_end": raw_end,
        "raw_span": raw[raw_start:raw_end],
    }


def _map_offsets(raw: str, norm: str, n_start: int, n_end: int) -> tuple[int, int]:
    """将归一化文本偏移映射回原文偏移（基于逐字符归一化扫描）。"""
    r = 0
    n = 0
    out_start = -1
    out_end = -1
    while r < len(raw) and n < n_end:
        char_norm = normalize_for_grounding(raw[r])
        if char_norm == "":
            r += 1
            continue
        if n == n_start and out_start < 0:
            out_start = r
        n += len(char_norm)
        r += 1
    if out_start >= 0 and n >= n_end:
        out_end = r
        return out_start, out_end
    return -1, -1


# ---------------------------------------------------------------------------
# AnswerSemanticJudge（LLM）
# ---------------------------------------------------------------------------

class AnswerSemanticJudge:
    def __init__(self, client: DeepSeekClient | None = None) -> None:
        self.client = client or DeepSeekClient()
        self.settings = get_settings()

    def judge_answer(self, answer_text: str, prompt_text: str, brand_name: str, db: Session | None = None) -> dict:
        payload = {
            "prompt": prompt_text,
            "answer": answer_text,
            "target_brand": {"name": brand_name, "note": "仅作背景，禁止因品牌知名推断被推荐"},
        }
        return self.client.structured_generate_sync(
            system_prompt=ANSWER_SEMANTIC_SYSTEM,
            user_payload=payload,
            response_schema=dict,
            prompt_version=ANSWER_SEMANTIC_PROMPT_VERSION,
            schema_version=ANSWER_SEMANTIC_SCHEMA_VERSION,
            max_tokens=4096,
            db=db,
        )


def _answer_hash(answer_text: str) -> str:
    return hashlib.sha256((answer_text or "").encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Runner — 12 Runs，hash 去重，每 Run 独立关联
# ---------------------------------------------------------------------------

def run_answer_semantic(
    db: Session,
    project: Project,
    prompt: Prompt,
    run_ids: list[int],
    model: str | None = None,
) -> dict:
    runs = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.id.in_(run_ids)).all()
    if not runs:
        return {"status": "NO_RUNS", "events_created": 0, "runs_associated": 0}

    judge = AnswerSemanticJudge()
    # answer_hash → LLM 结果（相同答案只调一次）
    cache: dict[str, dict] = {}
    events_created = 0
    runs_associated = 0
    validation_failed = 0
    errors: list[str] = []

    for run in runs:
        answer = run.answer_text or ""
        if not answer.strip():
            continue
        ah = _answer_hash(answer)
        if ah not in cache:
            try:
                raw_result = judge.judge_answer(
                    answer_text=answer,
                    prompt_text=prompt.prompt_text,
                    brand_name=project.brand_name,
                    db=db,
                )
            except SemanticLLMError as e:
                errors.append(f"run {run.id}: {e}")
                continue
            cache[ah] = raw_result
        result = cache[ah]

        events = (result or {}).get("events") or []
        if not events:
            # 无事件的答案也记 unresolved 标记（保留 12 Run 独立统计）
            runs_associated += 1
            continue

        for event in events:
            answer_span = event.get("answer_span") or ""
            located = locate_span(answer, answer_span)
            if located is None:
                validation_failed += 1
                record = RecommendationEvent(
                    project_id=project.id,
                    prompt_id=prompt.id,
                    run_id=run.id,
                    answer_hash=ah,
                    entity_text=event.get("entity_text", ""),
                    entity_type=event.get("entity_type", "UNKNOWN"),
                    speech_act=event.get("speech_act", "UNRESOLVED"),
                    recommendation_strength=event.get("recommendation_strength", "NONE"),
                    polarity=event.get("polarity", "NEUTRAL"),
                    answer_span=answer_span,
                    raw_start=-1,
                    raw_end=-1,
                    reasons_json="[]",
                    selection_criteria_json="[]",
                    provider=self_client_provider(judge),
                    model=model or self_model(judge),
                    prompt_version=ANSWER_SEMANTIC_PROMPT_VERSION,
                    schema_version=ANSWER_SEMANTIC_SCHEMA_VERSION,
                    machine_payload_json=dumps(event),
                    review_status="VALIDATION_FAILED",
                )
                db.add(record)
                continue

            record = RecommendationEvent(
                project_id=project.id,
                prompt_id=prompt.id,
                run_id=run.id,
                answer_hash=ah,
                entity_text=event.get("entity_text", ""),
                entity_type=event.get("entity_type", "UNKNOWN"),
                speech_act=event.get("speech_act", "UNRESOLVED"),
                recommendation_strength=event.get("recommendation_strength", "NONE"),
                polarity=event.get("polarity", "NEUTRAL"),
                answer_span=answer_span,
                raw_start=located["raw_start"],
                raw_end=located["raw_end"],
                reasons_json=dumps(event.get("reasons") or []),
                selection_criteria_json=dumps(result.get("selection_criteria") or []),
                provider=self_client_provider(judge),
                model=model or self_model(judge),
                prompt_version=ANSWER_SEMANTIC_PROMPT_VERSION,
                schema_version=ANSWER_SEMANTIC_SCHEMA_VERSION,
                machine_payload_json=dumps(event),
                review_status="MACHINE_GROUNDED",
            )
            db.add(record)
            events_created += 1
        runs_associated += 1

    db.commit()
    return {
        "status": "OK",
        "unique_answers_judged": len(cache),
        "runs_associated": runs_associated,
        "events_created": events_created,
        "validation_failed": validation_failed,
        "errors": errors[:5],
    }


def self_client_provider(judge: AnswerSemanticJudge) -> str:
    return judge.client.provider


def self_model(judge: AnswerSemanticJudge) -> str:
    return judge.settings.deepseek_model
