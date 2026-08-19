"""Layer 3 — Reason-driven Passage Retrieval。

禁止"取 Citation 前 3"：
Recommendation Reason → 相关 Source（Content Quality Gate）→ Passage Split → BM25 检索 Top K。

只使用词法检索（中文 bigram BM25），本轮不建向量库。
"""

from __future__ import annotations

import math
import re
from collections import Counter

from sqlalchemy.orm import Session

from app.models import Project, RecommendationEvent, SourceDocument, SourceQuality
from app.services.serialization import loads

RETRIEVAL_VERSION = "passage_retrieval.v1_bm25"


def tokenize_zh(text: str) -> list[str]:
    """中文 bigram 词元化 + 英文单词小写。"""
    tokens: list[str] = []
    cleaned = re.sub(r"[^\w一-鿿]+", " ", text.lower())
    parts = cleaned.split()
    for part in parts:
        if re.fullmatch(r"[a-z0-9]+", part):
            tokens.append(part)
        else:
            tokens.extend(part[i:i + 2] for i in range(len(part) - 1))
    return tokens


class BM25:
    """简化 BM25（k1=1.5, b=0.75）。"""

    def __init__(self, corpus: list[list[str]]) -> None:
        self.k1 = 1.5
        self.b = 0.75
        self.doc_len = [len(d) for d in corpus]
        self.avgdl = sum(self.doc_len) / len(corpus) if corpus else 0
        self.n = len(corpus)
        self.df = Counter()
        for doc in corpus:
            for term in set(doc):
                self.df[term] += 1
        self.corpus = corpus

    def _idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log((self.n - df + 0.5) / (df + 0.5) + 1.0)

    def score(self, query_tokens: list[str], doc: list[str]) -> float:
        tf = Counter(doc)
        doc_len = len(doc)
        total = 0.0
        for term in set(query_tokens):
            if term not in self.df:
                continue
            f = tf.get(term, 0)
            idf = self._idf(term)
            total += idf * (f * (self.k1 + 1)) / (f + self.k1 * (1 - self.b + self.b * doc_len / max(self.avgdl, 1)))
        return total


def _split_document_passages(doc: SourceDocument) -> list[dict]:
    """把 SourceDocument 切成 Passage（复用已有 content_blocks_json）。"""
    blocks = loads(doc.content_blocks_json, [])
    passages = []
    for blk in blocks:
        text = (blk.get("text") or "").strip()
        if len(text) < 20:
            continue
        passages.append({
            "doc_id": doc.id,
            "passage_id": f"doc{doc.id}:b{blk.get('block_index', len(passages))}",
            "text": text,
        })
    # 无块时退化：整篇按段落切
    if not passages and doc.clean_text:
        for i, para in enumerate((doc.clean_text or "").split("\n")):
            para = para.strip()
            if len(para) >= 20:
                passages.append({"doc_id": doc.id, "passage_id": f"doc{doc.id}:p{i}", "text": para})
    return passages


def retrieve_passages_for_reason(
    reason_text: str,
    passages: list[dict],
    top_k: int = 5,
) -> list[dict]:
    """BM25 检索与 Reason 最相关的 Passage。"""
    if not passages:
        return []
    corpus = [tokenize_zh(p["text"]) for p in passages]
    bm25 = BM25(corpus)
    query_tokens = tokenize_zh(reason_text)
    scored = []
    for p, doc_tokens in zip(passages, corpus):
        s = bm25.score(query_tokens, doc_tokens)
        if s > 0:
            scored.append({**p, "bm25_score": round(s, 4)})
    scored.sort(key=lambda x: -x["bm25_score"])
    return scored[:top_k]


def run_reason_driven_retrieval(
    db: Session,
    project: Project,
    prompt_id: int,
    run_ids: list[int],
    top_k: int = 5,
) -> dict:
    """主流程：Reason → 有效 Source → Passage 检索。

    返回 {reason_id: [passages]} 供 Layer 4 使用。
    """
    # 1. 取 Grounded 事件及 Reason
    events = db.query(RecommendationEvent).filter(
        RecommendationEvent.project_id == project.id,
        RecommendationEvent.prompt_id == prompt_id,
        RecommendationEvent.run_id.in_(run_ids),
        RecommendationEvent.review_status.in_(["MACHINE_GROUNDED", "HUMAN_CONFIRMED"]),
    ).all()

    # 2. 只取 CONTENT_VALID 的 Source（Content Quality Gate）
    valid_doc_ids = {
        q.source_document_id
        for q in db.query(SourceQuality).filter(
            SourceQuality.content_quality_status == "CONTENT_VALID"
        ).all()
    }
    docs = db.query(SourceDocument).filter(SourceDocument.id.in_(valid_doc_ids)).all() if valid_doc_ids else []
    doc_passages: dict[int, list[dict]] = {}
    for doc in docs:
        doc_passages[doc.id] = _split_document_passages(doc)

    all_passages = [p for passages in doc_passages.values() for p in passages]

    # 3. 按 Reason 去重（相同 normalized_reason 只检索一次）
    seen_reasons: set[str] = set()
    result: dict[str, dict] = {}
    total_pages = 0
    # ownership → docs 映射（Reason 实体的第一方页面优先候选）
    ownership_map: dict[str, list[int]] = {}
    for doc in docs:
        from app.modules.optimization.source_qualification import resolve_ownership
        r = resolve_ownership(db, project, doc.url or "", doc.domain)
        owner = r["source_owner_entity"]
        if owner not in {"", "UNKNOWN"}:
            ownership_map.setdefault(owner, []).append(doc.id)

    for event in events:
        for reason in loads(event.reasons_json, []):
            rtext = reason.get("normalized_reason") or ""
            if not rtext or rtext in seen_reasons:
                continue
            seen_reasons.add(rtext)
            hits = retrieve_passages_for_reason(rtext, all_passages, top_k)
            # Reason-driven 增强：ENTITY_SPECIFIC reason 的实体第一方页面优先
            if reason.get("reason_scope") == "ENTITY_SPECIFIC":
                owner_doc_ids = ownership_map.get(event.entity_text, [])
                owner_hits = [p for p in all_passages if p["doc_id"] in owner_doc_ids]
                owner_scored = retrieve_passages_for_reason(rtext, owner_hits, top_k)
                merged = {p["passage_id"]: p for p in owner_scored}
                for p in hits:
                    if p["passage_id"] not in merged:
                        merged[p["passage_id"]] = p
                hits = sorted(merged.values(), key=lambda x: -x["bm25_score"])[:top_k]
            result[rtext] = {
                "reason_text": rtext,
                "reason_scope": reason.get("reason_scope"),
                "reason_entity": event.entity_text,
                "event_ids": [event.id],
                "passages": hits,
            }
            total_pages += len(hits)

    return {
        "status": "OK",
        "unique_reasons": len(result),
        "valid_documents": len(docs),
        "passages_retrieved": total_pages,
        "by_reason": result,
        "version": RETRIEVAL_VERSION,
    }
