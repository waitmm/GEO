"""Answer Intelligence — Claim Extraction V1.

Provides:
- ClaimExtractionProvider abstract interface
- RuleBasedClaimExtractionProvider — deterministic split on connectors
- API for running extraction and reviewing atomic claims
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import AnswerClaim, AtomicClaim, BrowserMonitorRun, ClaimExtractionRun
from app.services.serialization import dumps, loads


# ---------------------------------------------------------------------------
# Provider abstraction
# ---------------------------------------------------------------------------

class ClaimExtractionProvider:
    """Abstract provider for extracting AtomicClaims from AnswerSegments."""

    def extract(self, segments: list[AnswerClaim], extraction_run: ClaimExtractionRun) -> list[dict]:
        raise NotImplementedError


class RuleBasedClaimExtractionProvider(ClaimExtractionProvider):
    """Deterministic rule-based Claim extraction.

    Splits on Chinese connector words (并且, 而且, 同时, 但, 不过, etc.)
    while preserving negation, conditionals, and modifiers.
    """

    CONNECTORS = [
        (r"[，,\s]*并且[，,\s]*", True),
        (r"[，,\s]*而且[，,\s]*", True),
        (r"[，,\s]*同时[，,\s]*", True),
        (r"[，,\s]*另外[，,\s]*", True),
        (r"[，,\s]*此外[，,\s]*", True),
        (r"[，,\s]*但[，,\s]*(是)?[，,\s]*", True),
        (r"[，,\s]*不过[，,\s]*", True),
        (r"[，,\s]*然而[，,\s]*", True),
        (r"[，,\s]*所以[，,\s]*", True),
        (r"[，,\s]*因此[，,\s]*", True),
        (r"[，,\s]*因为[，,\s]*", True),
        (r"[，,\s]*如果[，,\s]*", True),
        (r"[，,\s]*只要[，,\s]*", True),
    ]

    _NEED_PATTERNS = {
        "PRODUCT_CAPABILITY": ["支持", "可以", "能够", "提供", "具备", "兼容", "适用"],
        "TOOL_RECOMMENDATION": ["推荐", "建议使用", "首选", "更适合", "更好用"],
        "PROCEDURE": ["点击", "打开", "选择", "输入", "上传", "下载", "生成", "设置", "创建", "发布"],
        "COMPARISON": ["相比", "对比", "优于", "不如", "更", "比.*更"],
        "LIMITATION": ["不能", "无法", "不支持", "限制", "不超过", "需.*才", "暂不"],
        "PRICING": ["免费", "收费", "价格", "费用", "付费", "会员"],
        "VALIDITY": ["长期有效", "永久", "有效期", "过期"],
        "DEFINITION": ["是指", "即", "定义", "指的是", "所谓"],
        "SCENARIO": ["适用于", "用于", "场景", "适合"],
        "FACTUAL_ASSERTION": [],
    }

    def extract(self, segments: list[AnswerClaim], extraction_run: ClaimExtractionRun) -> list[dict]:
        results = []
        for seg in segments:
            text = (seg.raw_text or "").strip()
            if not text or len(text) < 4:
                continue
            # Skip pure structural text
            if self._is_structural(text):
                continue
            # Split on connectors
            parts = self._split_on_connectors(text)
            for part in parts:
                part = part.strip()
                if not part or len(part) < 4:
                    continue
                claim = self._classify_claim(part, seg, extraction_run)
                results.append(claim)
        return results

    def _is_structural(self, text: str) -> bool:
        structural = [
            r"^下面介绍", r"^以下是", r"^主要有", r"^总结", r"^综上", r"^常见.*如下",
            r"^例如[：:]", r"^比如[：:]", r"^包括[：:]", r"^需要.*帮助",
        ]
        return any(re.match(p, text) for p in structural) and len(text) < 30

    def _split_on_connectors(self, text: str) -> list[str]:
        for pattern, _ in self.CONNECTORS:
            if re.search(pattern, text):
                parts = re.split(pattern, text)
                if len(parts) >= 2 and all(len(p.strip()) > 4 for p in parts):
                    return parts
        return [text]

    def _classify_claim(self, text: str, seg: AnswerClaim, run: ClaimExtractionRun) -> dict:
        types = []
        for ctype, patterns in self._NEED_PATTERNS.items():
            if not patterns:
                continue
            if any(re.search(p, text) for p in patterns):
                types.append(ctype)

        # Speech act
        if any(kw in text for kw in ["推荐", "建议", "首选"]):
            speech_act = "RECOMMENDATION"
        elif any(kw in text for kw in ["点击", "选择", "输入", "上传", "打开", "生成"]):
            speech_act = "INSTRUCTION"
        elif any(kw in text for kw in ["相比", "对比", "更"]):
            speech_act = "COMPARISON"
        elif any(kw in text for kw in ["注意", "不能", "避免", "警惕"]):
            speech_act = "WARNING"
        else:
            speech_act = "ASSERTION"

        # Epistemic
        if any(kw in text for kw in ["一定", "必然", "就是", "确定"]):
            epistemic = "CERTAIN"
        elif any(kw in text for kw in ["通常", "一般", "大多", "大概率"]):
            epistemic = "PROBABLE"
        elif any(kw in text for kw in ["可能", "也许", "或许", "可以考虑"]):
            epistemic = "POSSIBLE"
        else:
            epistemic = "UNKNOWN"

        # Polarity
        negated = any(kw in text for kw in ["不", "无", "没", "未", "非", "否"])
        polarity = "NEGATIVE" if negated else "POSITIVE"

        # Priority
        verif = "HIGH" if types and "PRODUCT_CAPABILITY" in types else "MEDIUM" if types else "LOW"
        geo = "HIGH" if types and types[0] in ("PRODUCT_CAPABILITY", "TOOL_RECOMMENDATION", "PROCEDURE") else "MEDIUM" if types else "LOW"

        return {
            "source_segment_id": seg.id,
            "claim_extraction_run_id": run.id,
            "run_id": seg.run_id,
            "claim_text": text,
            "claim_types_json": dumps(types),
            "speech_act": speech_act,
            "epistemic_status": epistemic,
            "polarity": polarity,
            "is_negated": negated,
            "verification_priority": verif,
            "geo_importance": geo,
            "extraction_confidence": 0.7 if len(types) > 0 else 0.5,
        }


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------

def run_claim_extraction(
    db: Session,
    run_ids: list[int],
    provider_type: str = "rule",
) -> dict:
    """Run claim extraction on answer segments for given runs."""
    # Create extraction run
    ext_run = ClaimExtractionRun(
        extractor_type=provider_type,
        extraction_version="v1",
        started_at=datetime.utcnow(),
        status="running",
    )
    db.add(ext_run)
    db.flush()

    # Get segments
    segments = db.query(AnswerClaim).filter(AnswerClaim.run_id.in_(run_ids)).all()
    if not segments:
        ext_run.status = "completed"
        ext_run.finished_at = datetime.utcnow()
        db.commit()
        return {"status": "no_segments", "extraction_run_id": ext_run.id}

    # Extract
    provider = RuleBasedClaimExtractionProvider()
    claims = provider.extract(segments, ext_run)

    # Save
    saved = 0
    for c in claims:
        ac = AtomicClaim(**c)
        db.add(ac)
        saved += 1

    ext_run.status = "completed"
    ext_run.finished_at = datetime.utcnow()
    db.commit()
    return {
        "extraction_run_id": ext_run.id,
        "segments_processed": len(segments),
        "atomic_claims_created": saved,
        "extraction_version": "v1",
    }


def list_atomic_claims(db: Session, run_ids: list[int] | None = None) -> list[dict]:
    query = db.query(AtomicClaim)
    if run_ids:
        query = query.filter(AtomicClaim.run_id.in_(run_ids))
    claims = query.order_by(AtomicClaim.id).all()
    return [_atomic_claim_to_dict(c) for c in claims]


def review_atomic_claim(db: Session, claim_id: int, payload: dict) -> dict:
    claim = db.get(AtomicClaim, claim_id)
    if not claim:
        raise ValueError(f"AtomicClaim #{claim_id} not found")
    status = payload.get("review_status", claim.review_status)
    claim.review_status = status
    if status in ("EDITED", "NEEDS_SPLIT"):
        claim.human_claim_text = payload.get("human_claim_text", claim.claim_text)
        claim.machine_claim_text = claim.machine_claim_text or claim.claim_text
    elif status == "CONFIRMED":
        claim.machine_claim_text = claim.machine_claim_text or claim.claim_text
    claim.reviewer = payload.get("reviewer", "human")
    claim.reviewed_at = datetime.utcnow()
    claim.review_note = payload.get("review_note", "")
    db.commit()
    return _atomic_claim_to_dict(claim)


def _atomic_claim_to_dict(c: AtomicClaim) -> dict:
    return {
        "id": c.id, "source_segment_id": c.source_segment_id,
        "run_id": c.run_id, "claim_text": c.claim_text,
        "claim_types": loads(c.claim_types_json, []),
        "speech_act": c.speech_act, "epistemic_status": c.epistemic_status,
        "polarity": c.polarity, "is_negated": c.is_negated,
        "verification_priority": c.verification_priority,
        "geo_importance": c.geo_importance,
        "review_status": c.review_status,
        "machine_claim_text": c.machine_claim_text,
        "human_claim_text": c.human_claim_text,
        "claim_extraction_run_id": c.claim_extraction_run_id,
    }
