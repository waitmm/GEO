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

from app.models import (
    AnswerDecisionBinding,
    AnswerEvidenceShadowRun,
    AnswerUnit,
    Project,
    RecommendationEvent,
    ReferenceSource,
    SourceDocument,
    SourceQuality,
)
from app.services.serialization import loads
from app.services.url_identity import canonicalize_url

RETRIEVAL_VERSION = "passage_retrieval.v1_bm25"
FORMAL_V1_1_INPUT_VERSION = "citation_decision_v1_1_formal_input.v1"
ANSWER_BINDING_REASON_SOURCE = "ANSWER_DECISION_BINDING"
EVENT_REASON_SOURCE = "RECOMMENDATION_EVENT_REASONS_JSON"
SHADOW_INPUT_PIPELINE_VERSION = "citation_decision_v1_1_shadow"
_FORMAL_REASON_BINDING_ROLES = {"DIRECT_REASON", "SUPPORTING_REASON"}
_INVISIBLE_CHARS = re.compile(r"[\u200b\u200c\u200d\ufeff]")


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


def _clean_reason_text(text: str) -> str:
    return _INVISIBLE_CHARS.sub("", text or "").strip()


def _reason_text_matches_anchor(reason: dict, anchor_text: str) -> bool:
    if not anchor_text:
        return False
    anchor = _clean_reason_text(anchor_text)
    for key in ("reason_span", "normalized_reason", "text", "reason"):
        value = _clean_reason_text(str(reason.get(key) or ""))
        if value and (anchor in value or value in anchor):
            return True
    return False


def _binding_reason_anchor_text(binding: AnswerDecisionBinding) -> str:
    payload = loads(binding.judge_payload_json, {})
    if not isinstance(payload, dict):
        payload = {}
    candidate = payload.get("rule_candidate") if isinstance(payload, dict) else {}
    if not isinstance(candidate, dict):
        candidate = {}
    return _clean_reason_text(
        candidate.get("reason_anchor_text")
        or candidate.get("normalized_reason")
        or payload.get("reason_anchor_text")
        or ""
    )


def _binding_formal_reason_text(
    binding: AnswerDecisionBinding,
    unit: AnswerUnit,
    event: RecommendationEvent,
) -> tuple[str, str]:
    """Return the atomic formal reason for an AnswerDecisionBinding.

    The binding is created against a recommendation reason span. Evidence
    Alignment must judge that atomic reason, not the whole answer unit sentence;
    otherwise composite answer text can make valid capability evidence look only
    RELATED.
    """
    anchor_text = _binding_reason_anchor_text(binding)
    if anchor_text:
        for reason in loads(event.reasons_json, []):
            if isinstance(reason, dict) and _reason_text_matches_anchor(reason, anchor_text):
                normalized = _clean_reason_text(str(reason.get("normalized_reason") or ""))
                if normalized:
                    return normalized, anchor_text
        return anchor_text, anchor_text
    return _clean_reason_text(unit.unit_text_normalized or unit.unit_text_original or ""), ""


def _normalize_url_key(url: str) -> str:
    return canonicalize_url(url)


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


def _latest_completed_shadow_run(
    db: Session,
    project_id: int,
    prompt_id: int,
    run_ids: list[int],
) -> AnswerEvidenceShadowRun | None:
    expected = {int(run_id) for run_id in run_ids}
    rows = (
        db.query(AnswerEvidenceShadowRun)
        .filter(
            AnswerEvidenceShadowRun.project_id == project_id,
            AnswerEvidenceShadowRun.prompt_id == prompt_id,
            AnswerEvidenceShadowRun.pipeline_version == SHADOW_INPUT_PIPELINE_VERSION,
            AnswerEvidenceShadowRun.status.in_(["completed", "completed_with_warnings"]),
            AnswerEvidenceShadowRun.formal_output_impact == "NONE",
        )
        .order_by(AnswerEvidenceShadowRun.created_at.desc(), AnswerEvidenceShadowRun.id.desc())
        .all()
    )
    for row in rows:
        row_run_ids = {int(item) for item in loads(row.source_run_ids_json, [])}
        if row_run_ids == expected:
            return row
    return None


def answer_binding_reason_inputs(
    db: Session,
    project: Project,
    prompt_id: int,
    run_ids: list[int],
) -> list[dict]:
    """读取 Phase 0 已审计 Binding，作为 Phase 1 正式 reason 输入候选。

    注意：这里不读取 Shadow Evidence Result，也不直接升级 Benchmark。
    它只把 grounded AnswerUnit 暴露给正式 Passage Retrieval / Alignment。
    """
    shadow_run = _latest_completed_shadow_run(db, project.id, prompt_id, run_ids)
    if not shadow_run:
        return []
    rows = (
        db.query(AnswerDecisionBinding, AnswerUnit, RecommendationEvent)
        .join(AnswerUnit, AnswerUnit.id == AnswerDecisionBinding.answer_unit_id)
        .join(RecommendationEvent, RecommendationEvent.id == AnswerDecisionBinding.recommendation_event_id)
        .filter(
            AnswerDecisionBinding.shadow_run_id == shadow_run.id,
            AnswerDecisionBinding.project_id == project.id,
            AnswerDecisionBinding.prompt_id == prompt_id,
            AnswerDecisionBinding.run_id.in_(run_ids),
            AnswerDecisionBinding.pipeline_version == SHADOW_INPUT_PIPELINE_VERSION,
            AnswerDecisionBinding.review_status.in_(["MACHINE_GROUNDED", "HUMAN_CONFIRMED"]),
            AnswerDecisionBinding.decision_role.in_(_FORMAL_REASON_BINDING_ROLES),
            AnswerUnit.review_status == "MACHINE_GROUNDED",
            RecommendationEvent.review_status.in_(["MACHINE_GROUNDED", "HUMAN_CONFIRMED"]),
        )
        .order_by(AnswerDecisionBinding.run_id, AnswerDecisionBinding.id)
        .all()
    )
    result: list[dict] = []
    for binding, unit, event in rows:
        reason_text, anchor_text = _binding_formal_reason_text(binding, unit, event)
        if not reason_text:
            continue
        result.append({
            "text": reason_text,
            "scope": "ENTITY_SPECIFIC",
            "entity": event.entity_text or "",
            "event_id": event.id,
            "run_id": event.run_id,
            "reason_id": f"answer_unit:{unit.id}:binding:{binding.id}",
            "reason_source": ANSWER_BINDING_REASON_SOURCE,
            "decision_role": binding.decision_role,
            "binding_strength": binding.binding_strength,
            "scope_type": binding.scope_type,
            "reason_anchor_text": anchor_text,
            "answer_unit_text": _clean_reason_text(unit.unit_text_normalized or unit.unit_text_original or ""),
            "shadow_run_id": shadow_run.id,
            "answer_unit_id": unit.id,
            "decision_binding_id": binding.id,
        })
    return result


def _cited_document_ids_for_runs(db: Session, run_ids: list[int], docs: list[SourceDocument]) -> set[int]:
    refs = db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(run_ids)).all()
    doc_by_key: dict[str, int] = {}
    for doc in docs:
        for url in {doc.url, doc.original_url, doc.canonical_url}:
            key = _normalize_url_key(url or "")
            if key:
                doc_by_key[key] = doc.id
    cited: set[int] = set()
    for ref in refs:
        for url in {ref.canonical_url, ref.url}:
            key = _normalize_url_key(url or "")
            if key in doc_by_key:
                cited.add(doc_by_key[key])
    return cited


def _passage_mentions_entity(passage: dict, entity: str, docs_by_id: dict[int, SourceDocument]) -> bool:
    if not entity:
        return False
    doc = docs_by_id.get(passage["doc_id"])
    haystack = f"{passage.get('text') or ''} {doc.title if doc else ''} {doc.url if doc else ''}"
    return entity in haystack


def _merge_ranked_passages(*ranked_groups: list[dict], top_k: int) -> list[dict]:
    merged: dict[str, dict] = {}
    for group in ranked_groups:
        for passage in group:
            merged.setdefault(passage["passage_id"], passage)
    return sorted(merged.values(), key=lambda x: -x["bm25_score"])[:top_k]


def run_reason_driven_retrieval(
    db: Session,
    project: Project,
    prompt_id: int,
    run_ids: list[int],
    top_k: int = 5,
    include_answer_binding_reasons: bool = False,
    doc_id_filter: list[int] | None = None,
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

    # 2. 只取 CONTENT_VALID 的 Source（Content Quality Gate）。
    # 有些补录/重抓来源有正文但尚未生成 SourceQuality 行，统一使用
    # derive_content_status 兜底，避免可用正文被正式检索误排除。
    from app.modules.optimization.source_qualification import derive_content_status

    quality_by_doc_id: dict[int, SourceQuality] = {}
    for quality in db.query(SourceQuality).order_by(SourceQuality.id.desc()).all():
        quality_by_doc_id.setdefault(quality.source_document_id, quality)
    allowed_doc_ids = None if doc_id_filter is None else {int(item) for item in doc_id_filter}
    docs = [
        doc
        for doc in db.query(SourceDocument).all()
        if derive_content_status(doc, quality_by_doc_id.get(doc.id)).get("content_status") == "CONTENT_VALID"
        and (allowed_doc_ids is None or doc.id in allowed_doc_ids)
    ]
    doc_passages: dict[int, list[dict]] = {}
    for doc in docs:
        doc_passages[doc.id] = _split_document_passages(doc)

    all_passages = [p for passages in doc_passages.values() for p in passages]
    docs_by_id = {doc.id: doc for doc in docs}
    cited_doc_ids = _cited_document_ids_for_runs(db, run_ids, docs) if include_answer_binding_reasons else set()
    cited_passages = [p for p in all_passages if p["doc_id"] in cited_doc_ids]

    # 3. 按 Reason 去重（相同 normalized_reason 只检索一次）
    seen_reasons: set[str] = set()
    result: dict[str, dict] = {}
    total_pages = 0
    legacy_reasons_added = 0
    binding_reasons_added = 0
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
            rtext = _clean_reason_text(rtext)
            reason_scope = reason.get("reason_scope") or "ENTITY_SPECIFIC"
            reason_entity = event.entity_text if reason_scope == "ENTITY_SPECIFIC" else ""
            seen_key = f"{reason_scope}|{reason_entity}|{rtext}"
            if not rtext or seen_key in seen_reasons:
                continue
            seen_reasons.add(seen_key)
            hits = retrieve_passages_for_reason(rtext, all_passages, top_k)
            # Reason-driven 增强：ENTITY_SPECIFIC reason 的实体第一方页面优先
            if reason_scope == "ENTITY_SPECIFIC":
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
                "reason_scope": reason_scope,
                "reason_entity": reason_entity,
                "event_ids": [event.id],
                "reason_source": EVENT_REASON_SOURCE,
                "reason_id": f"reason:{rtext[:60]}",
                "passages": hits,
            }
            total_pages += len(hits)
            legacy_reasons_added += 1

    binding_reasons = answer_binding_reason_inputs(db, project, prompt_id, run_ids) if include_answer_binding_reasons else []
    for reason in binding_reasons:
        rtext = reason["text"]
        reason_entity = reason.get("entity") or ""
        reason_scope = reason.get("scope") or "ENTITY_SPECIFIC"
        seen_key = f"{reason_scope}|{reason_entity}|{rtext}"
        if not rtext or seen_key in seen_reasons:
            continue
        seen_reasons.add(seen_key)
        hits = retrieve_passages_for_reason(rtext, all_passages, top_k)
        if reason_scope == "ENTITY_SPECIFIC":
            owner_doc_ids = ownership_map.get(reason_entity, [])
            owner_hits = [p for p in all_passages if p["doc_id"] in owner_doc_ids]
            owner_scored = retrieve_passages_for_reason(rtext, owner_hits, top_k)
            same_entity_cited = [
                p for p in cited_passages
                if _passage_mentions_entity(p, reason_entity, docs_by_id)
            ]
            same_entity_cited_scored = retrieve_passages_for_reason(rtext, same_entity_cited, top_k)
            cited_scored = retrieve_passages_for_reason(rtext, cited_passages, top_k)
            hits = _merge_ranked_passages(
                same_entity_cited_scored,
                owner_scored,
                cited_scored,
                hits,
                top_k=top_k,
            )
        result_key = f"{ANSWER_BINDING_REASON_SOURCE}:{reason.get('reason_id')}:{rtext[:40]}"
        result[result_key] = {
            "reason_text": rtext,
            "reason_scope": reason_scope,
            "reason_entity": reason_entity,
            "event_ids": [reason["event_id"]],
            "reason_source": ANSWER_BINDING_REASON_SOURCE,
            "reason_id": reason.get("reason_id"),
            "decision_role": reason.get("decision_role"),
            "binding_strength": reason.get("binding_strength"),
            "shadow_run_id": reason.get("shadow_run_id"),
            "answer_unit_id": reason.get("answer_unit_id"),
            "decision_binding_id": reason.get("decision_binding_id"),
            "passages": hits,
        }
        total_pages += len(hits)
        binding_reasons_added += 1

    return {
        "status": "OK",
        "unique_reasons": len(result),
        "legacy_event_reasons": legacy_reasons_added,
        "answer_binding_reasons": binding_reasons_added,
        "answer_binding_candidates": len(binding_reasons) if include_answer_binding_reasons else 0,
        "include_answer_binding_reasons": include_answer_binding_reasons,
        "valid_documents": len(docs),
        "passages_retrieved": total_pages,
        "doc_id_filter": sorted(allowed_doc_ids) if allowed_doc_ids is not None else [],
        "by_reason": result,
        "version": RETRIEVAL_VERSION,
        "formal_input_version": FORMAL_V1_1_INPUT_VERSION if include_answer_binding_reasons else "",
    }
