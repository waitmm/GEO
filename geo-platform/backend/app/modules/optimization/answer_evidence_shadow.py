"""Citation Decision V1.1 Phase 0 shadow evidence chain.

This module is intentionally audit-only. It creates AnswerUnit /
AnswerDecisionBinding / AnswerEvidenceShadow* rows and never writes formal
SourceClaim, EvidenceAlignment, Benchmark, Gap, Priority, Action, Strategy, or
Experiment outputs.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    AnswerClaim,
    AnswerDecisionBinding,
    AnswerEvidenceShadowResult,
    AnswerEvidenceShadowRun,
    AnswerUnit,
    BrowserMonitorRun,
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
from app.modules.optimization.answer_semantic import locate_span
from app.modules.optimization.evidence_alignment import EvidenceAlignmentJudge
from app.modules.optimization.passage_retrieval import _split_document_passages, retrieve_passages_for_reason
from app.modules.optimization.source_claim import SourceClaimJudge, _normalize_subject_entity
from app.modules.optimization.source_qualification import derive_content_status, resolve_ownership
from app.services.semantic_llm.base import SemanticLLMError
from app.services.semantic_llm.deepseek import DeepSeekClient
from app.services.serialization import dumps, loads

SHADOW_PIPELINE_VERSION = "citation_decision_v1_1_shadow"
ANSWER_UNIT_VERSION = "answer_unit.v1_1_shadow"
BINDING_PROMPT_VERSION = "answer_evidence_binding.v1_1_shadow"
BINDING_SCHEMA_VERSION = "v1"

BINDING_SYSTEM = """你是一个严格的答案推荐说明作用域判断器。

你判断一条答案原子事实是否属于某个推荐事件的 Recommendation Explanation Scope。

你会看到：
A. AI 答案里的推荐事件
B. 同一答案里的原子事实

核心原则：
- 如果答案存在真实推荐事件，且原子事实位于被推荐品牌的说明作用域内，主动描述该品牌的能力、优势、价格、效果、适用场景或比较优势，默认可以绑定为 SUPPORTING_REASON；
- 不要求答案显式出现“因为/所以”；
- 只有原子事实被明确表达为选择条件、明确因果、明确比较依据或需求匹配时，才使用 DIRECT_REASON；
- PROCEDURE / GENERAL_FACT / 其他品牌内容 / 脱离说明作用域的主张不能绑定为正向推荐理由；
- LIMITATION 或风险限制应使用 COUNTER_REASON。

禁止：
- 使用引用正文或外部知识；
- 把来源事实当作答案事实；
- 因为实体名称相同就强行判断为推荐理由；
- 生成任何策略、缺口、行动建议。

decision_role 只能使用：
DIRECT_REASON / SUPPORTING_REASON / COUNTER_REASON / NOT_RELATED

scope_type 只能使用：
SAME_SENTENCE / SAME_LIST_ITEM / SAME_PARAGRAPH / ENTITY_HEADING_SCOPE /
PRONOUN_INHERITANCE / ADJACENT_PARAGRAPH / CROSS_PARAGRAPH / OUT_OF_SCOPE

输出格式（纯 JSON 对象）：
{
  "bind": true,
  "decision_role": "SUPPORTING_REASON",
  "binding_strength": "MEDIUM",
  "scope_type": "SAME_PARAGRAPH",
  "scope_reason": "该原子事实位于被推荐品牌的同一说明段落内，描述其能力。",
  "rationale": "该原子事实展开说明了被推荐品牌的能力。"
}

如果不相关，bind=false 且 decision_role=NOT_RELATED。
必须输出纯 JSON 对象。
"""

_CLAUSE_SPLIT = re.compile(r"[。；;]\s*|\n+")
_SOFT_SPLIT = re.compile(r"[，,]\s*")
_ITEM_SPLIT = re.compile(r"[、/]\s*")
_ENTITY_PREFIX = re.compile(r"^\s*([^：:]{2,40})[：:]\s*(.+)$")
_CAPABILITY_WORDS = ("支持", "自带", "具备", "提供", "生成", "统计", "自定义", "缩短", "跳转", "创建", "管理")
_BENEFIT_WORDS = ("高效", "完整", "稳定", "免费", "快速", "简单", "便捷", "优势", "提高", "提升", "降低")
_PRICE_WORDS = ("免费", "付费", "价格", "套餐", "费用", "成本")
_RESULT_EFFECT_WORDS = ("效果", "提高", "提升", "降低", "增加", "便于", "解决")
_COMPARATIVE_WORDS = ("相比", "比", "更", "优于", "胜过", "对比")
_USE_CASE_WORDS = ("适合", "场景", "用于", "面向")
_PROCEDURE_WORDS = ("点击", "输入", "粘贴", "打开", "进入", "选择", "保存", "提交", "流程", "步骤")
_LIMITATION_WORDS = ("不支持", "无法", "不能", "风险", "限制", "失败")
_DIRECT_REASON_CUES = ("因为", "所以", "因此", "如果", "需要", "优先", "更推荐", "建议选择", "推荐理由", "选择依据")
_RECOMMEND_SPEECH_ACTS = {
    "RECOMMEND",
    "POSITIVE_RECOMMENDATION",
    "TOP_RECOMMENDATION",
    "CANDIDATE",
    "MENTION_AS_OPTION",
}
_DECISION_BINDING_ROLES = {"DIRECT_REASON", "SUPPORTING_REASON", "COUNTER_REASON"}


class AnswerEvidenceBindingJudge:
    def __init__(self, client: DeepSeekClient | None = None) -> None:
        self.client = client or DeepSeekClient()
        self.settings = get_settings()

    def judge(self, event: RecommendationEvent, unit: AnswerUnit, db: Session | None = None) -> dict:
        return self.client.structured_generate_sync(
            system_prompt=BINDING_SYSTEM,
            user_payload={
                "recommendation_event": {
                    "entity_text": event.entity_text,
                    "speech_act": event.speech_act,
                    "answer_span": event.answer_span,
                },
                "answer_unit": {
                    "unit_text_original": unit.unit_text_original,
                    "unit_text_normalized": unit.unit_text_normalized,
                    "semantic_type": unit.semantic_type,
                    "entity_hint": unit.entity_hint,
                },
            },
            response_schema=dict,
            prompt_version=BINDING_PROMPT_VERSION,
            schema_version=BINDING_SCHEMA_VERSION,
            max_tokens=2048,
            db=db,
        )


def _normalize_url_key(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlsplit(url.strip())
    except ValueError:
        return url.strip().lower()
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower() or "https", host, path, "", ""))


def _latest_package(db: Session, project_id: int, prompt_id: int) -> OptimizationEvidencePackage | None:
    return (
        db.query(OptimizationEvidencePackage)
        .filter(
            OptimizationEvidencePackage.project_id == project_id,
            OptimizationEvidencePackage.prompt_id == prompt_id,
            OptimizationEvidencePackage.status == "active",
        )
        .order_by(OptimizationEvidencePackage.created_at.desc(), OptimizationEvidencePackage.id.desc())
        .first()
    )


def _resolve_package(
    db: Session,
    project_id: int,
    prompt_id: int,
    evidence_package_id: int | None,
) -> OptimizationEvidencePackage | None:
    if evidence_package_id:
        package = db.get(OptimizationEvidencePackage, int(evidence_package_id))
        if not package or package.project_id != project_id or package.prompt_id != prompt_id:
            raise ValueError("指定的证据包不属于当前项目/问题")
        return package
    return _latest_package(db, project_id, prompt_id)


def _resolve_run_ids(
    db: Session,
    project_id: int,
    prompt_id: int,
    package: OptimizationEvidencePackage | None,
    requested_run_ids: list[int] | None,
) -> list[int]:
    if requested_run_ids:
        run_ids = [int(item) for item in requested_run_ids]
    elif package:
        run_ids = [int(item) for item in loads(package.source_run_ids_json, [])]
    else:
        run_ids = [
            row.id
            for row in db.query(BrowserMonitorRun)
            .filter(
                BrowserMonitorRun.project_id == project_id,
                BrowserMonitorRun.prompt_id == prompt_id,
                BrowserMonitorRun.status.in_(["success", "partial_success"]),
            )
            .order_by(BrowserMonitorRun.id.desc())
            .limit(12)
            .all()
        ]
    valid_ids = {
        row.id
        for row in db.query(BrowserMonitorRun)
        .filter(
            BrowserMonitorRun.id.in_(run_ids),
            BrowserMonitorRun.project_id == project_id,
            BrowserMonitorRun.prompt_id == prompt_id,
        )
        .all()
    }
    return [run_id for run_id in run_ids if run_id in valid_ids]


def _semantic_type(text: str) -> str:
    if any(word in text for word in _LIMITATION_WORDS):
        return "LIMITATION"
    if "点击统计" in text:
        return "FEATURE"
    if any(word in text for word in _USE_CASE_WORDS):
        return "USE_CASE"
    if re.search(r"(点击|输入|粘贴|打开|进入|选择|保存|提交).*(然后|后|再|即可|完成)", text):
        return "PROCEDURE"
    if any(word in text for word in _PROCEDURE_WORDS):
        return "PROCEDURE"
    if any(word in text for word in _CAPABILITY_WORDS):
        return "FEATURE"
    if any(word in text for word in _PRICE_WORDS):
        return "PRICE"
    if any(word in text for word in _BENEFIT_WORDS):
        return "BENEFIT"
    if any(word in text for word in _RESULT_EFFECT_WORDS):
        return "RESULT_EFFECT"
    if any(word in text for word in _COMPARATIVE_WORDS):
        return "COMPARATIVE_ADVANTAGE"
    return "GENERAL_FACT"


def _claim_parts(claim_text: str) -> tuple[str, str]:
    match = _ENTITY_PREFIX.match(claim_text.strip())
    if not match:
        return "", claim_text.strip()
    return match.group(1).strip(), match.group(2).strip()


def _split_claim_units(claim: AnswerClaim) -> list[dict]:
    raw_text = (claim.raw_text or "").strip()
    if not raw_text:
        return []
    entity_hint, body = _claim_parts(raw_text)
    units: list[dict] = []

    for clause in _CLAUSE_SPLIT.split(body):
        clause = clause.strip()
        if not clause:
            continue
        for soft_part in _SOFT_SPLIT.split(clause):
            part = soft_part.strip()
            if not part:
                continue
            if part.startswith("自带") and "、" in part:
                suffix = re.sub(r"等功能$", "", part[2:]).strip()
                for item in _ITEM_SPLIT.split(suffix):
                    item = item.strip()
                    if item:
                        units.append({"span": item, "text": f"自带{item}", "entity_hint": entity_hint})
                continue
            units.append({"span": part, "text": part, "entity_hint": entity_hint})

    result = []
    seen: set[str] = set()
    for item in units:
        text = item["text"].strip()
        if len(text) < 3:
            continue
        normalized = f"{entity_hint}{text}" if entity_hint and entity_hint not in text else text
        key = re.sub(r"\s+", "", normalized)
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "unit_text_original": text,
            "unit_text_normalized": normalized,
            "source_span": item["span"],
            "semantic_type": _semantic_type(text),
            "entity_hint": entity_hint,
        })
    return result


def _locate_unit_in_answer(run: BrowserMonitorRun, claim: AnswerClaim, source_span: str) -> dict:
    answer_text = run.answer_text or ""
    claim_text = claim.raw_text or ""
    claim_start = answer_text.find(claim_text)
    if claim_start >= 0:
        inner_start = claim_text.find(source_span)
        if inner_start >= 0:
            return {"raw_start": claim_start + inner_start, "raw_end": claim_start + inner_start + len(source_span)}
        return {"raw_start": claim_start, "raw_end": claim_start + len(claim_text)}
    located = locate_span(answer_text, source_span)
    if located:
        return located
    return {"raw_start": -1, "raw_end": -1}


def _same_entity(a: str, b: str) -> bool:
    a = (a or "").strip()
    b = (b or "").strip()
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _is_recommendation_event(event: RecommendationEvent) -> bool:
    return (event.speech_act or "").upper() in _RECOMMEND_SPEECH_ACTS and event.review_status in {
        "MACHINE_GROUNDED",
        "HUMAN_CONFIRMED",
    }


def _infer_scope(event: RecommendationEvent, unit: AnswerUnit) -> dict | None:
    entity = event.entity_text or ""
    unit_text = unit.unit_text_normalized or unit.unit_text_original
    event_span = event.answer_span or ""
    entity_matches = _same_entity(entity, unit.entity_hint) or (entity and entity in unit_text)
    if not entity_matches:
        return None
    if event_span and unit.unit_text_original and unit.unit_text_original in event_span:
        return {
            "scope_type": "SAME_SENTENCE",
            "scope_reason": "ANSWER_UNIT_IN_RECOMMENDATION_EVENT_SPAN",
        }
    if unit.entity_hint and _same_entity(entity, unit.entity_hint):
        return {
            "scope_type": "ENTITY_HEADING_SCOPE",
            "scope_reason": "ANSWER_UNIT_IN_ENTITY_HEADING_SCOPE",
        }
    return {
        "scope_type": "SAME_PARAGRAPH",
        "scope_reason": "ANSWER_UNIT_ENTITY_MATCH_IN_SAME_RUN",
    }


def _has_direct_reason_cue(event: RecommendationEvent, unit: AnswerUnit) -> bool:
    text = f"{event.answer_span or ''} {unit.unit_text_original or ''} {unit.unit_text_normalized or ''}"
    if any(cue in text for cue in _DIRECT_REASON_CUES):
        return True
    return unit.semantic_type == "COMPARATIVE_ADVANTAGE"


def _rule_binding(event: RecommendationEvent, unit: AnswerUnit) -> dict | None:
    if unit.semantic_type == "PROCEDURE":
        return None
    unit_text = unit.unit_text_normalized or unit.unit_text_original
    entity = event.entity_text or ""
    scope = _infer_scope(event, unit)
    if not scope:
        return None
    if unit.semantic_type == "LIMITATION":
        return {
            "decision_role": "COUNTER_REASON",
            "binding_strength": "MEDIUM",
            **scope,
            "rationale": "原子事实与推荐实体相关，但表达限制或风险。",
        }
    if unit.semantic_type == "GENERAL_FACT" and not _has_direct_reason_cue(event, unit):
        return None
    if _has_direct_reason_cue(event, unit):
        role = "DIRECT_REASON"
        strength = "HIGH"
    elif unit.semantic_type in {
        "FEATURE",
        "BENEFIT",
        "PRICE",
        "USE_CASE",
        "RESULT_EFFECT",
        "COMPARATIVE_ADVANTAGE",
    }:
        strength = "MEDIUM"
        role = "SUPPORTING_REASON"
    else:
        strength = "LOW"
        role = "SUPPORTING_REASON"
    return {
        "decision_role": role,
        "binding_strength": strength,
        **scope,
        "rationale": "同一答案中该原子事实解释或补充了推荐实体的能力/场景。",
    }


def _build_answer_units(db: Session, shadow_run: AnswerEvidenceShadowRun, runs_by_id: dict[int, BrowserMonitorRun]) -> list[AnswerUnit]:
    claims = (
        db.query(AnswerClaim)
        .filter(AnswerClaim.run_id.in_(list(runs_by_id.keys())))
        .order_by(AnswerClaim.run_id, AnswerClaim.claim_index)
        .all()
    )
    units: list[AnswerUnit] = []
    for claim in claims:
        run = runs_by_id.get(claim.run_id)
        if not run:
            continue
        for index, item in enumerate(_split_claim_units(claim), start=1):
            located = _locate_unit_in_answer(run, claim, item["source_span"])
            status = "MACHINE_GROUNDED" if located["raw_start"] >= 0 else "VALIDATION_FAILED"
            unit = AnswerUnit(
                shadow_run_id=shadow_run.id,
                project_id=shadow_run.project_id,
                prompt_id=shadow_run.prompt_id,
                run_id=claim.run_id,
                answer_claim_id=claim.id,
                unit_index=index,
                unit_text_original=item["unit_text_original"],
                unit_text_normalized=item["unit_text_normalized"],
                source_span=item["source_span"],
                raw_start=located["raw_start"],
                raw_end=located["raw_end"],
                semantic_type=item["semantic_type"],
                entity_hint=item["entity_hint"],
                extraction_method="RULE_ATOMICIZE",
                extraction_version=ANSWER_UNIT_VERSION,
                machine_payload_json=dumps({"source_answer_claim_id": claim.id}),
                review_status=status,
            )
            db.add(unit)
            units.append(unit)
    db.flush()
    return units


def _build_decision_bindings(
    db: Session,
    shadow_run: AnswerEvidenceShadowRun,
    units: list[AnswerUnit],
    use_llm_binding: bool,
    binding_judge: AnswerEvidenceBindingJudge | None,
    entity_filter: str | None = None,
    max_bindings: int | None = None,
    include_procedural_context: bool = False,
) -> tuple[list[AnswerDecisionBinding], list[str]]:
    events = (
        db.query(RecommendationEvent)
        .filter(
            RecommendationEvent.project_id == shadow_run.project_id,
            RecommendationEvent.prompt_id == shadow_run.prompt_id,
            RecommendationEvent.run_id.in_(loads(shadow_run.source_run_ids_json, [])),
        )
        .order_by(RecommendationEvent.run_id, RecommendationEvent.id)
        .all()
    )
    units_by_run: dict[int, list[AnswerUnit]] = defaultdict(list)
    for unit in units:
        if unit.review_status == "MACHINE_GROUNDED":
            units_by_run[unit.run_id].append(unit)

    judge = binding_judge or (AnswerEvidenceBindingJudge() if use_llm_binding else None)
    bindings: list[AnswerDecisionBinding] = []
    errors: list[str] = []
    seen: set[tuple[int, int]] = set()
    for event in events:
        if not _is_recommendation_event(event):
            continue
        if entity_filter and not _same_entity(event.entity_text, entity_filter):
            continue
        for unit in units_by_run.get(event.run_id, []):
            if include_procedural_context and unit.semantic_type == "PROCEDURE":
                unit_text = unit.unit_text_normalized or unit.unit_text_original
                entity = event.entity_text or ""
                if _same_entity(entity, unit.entity_hint) or (entity and entity in unit_text):
                    key = (event.id, unit.id)
                    if key in seen:
                        continue
                    seen.add(key)
                    binding = AnswerDecisionBinding(
                        shadow_run_id=shadow_run.id,
                        project_id=shadow_run.project_id,
                        prompt_id=shadow_run.prompt_id,
                        run_id=event.run_id,
                        recommendation_event_id=event.id,
                        answer_unit_id=unit.id,
                        decision_role="PROCEDURAL_CONTEXT",
                        binding_strength="LOW",
                        scope_type="ENTITY_HEADING_SCOPE",
                        scope_reason="PROCEDURE_IN_RECOMMENDED_ENTITY_SCOPE",
                        binding_method="RULE_SHADOW_CONTEXT",
                        pipeline_version=SHADOW_PIPELINE_VERSION,
                        judge_payload_json=dumps({
                            "rule_candidate": {
                                "decision_role": "PROCEDURAL_CONTEXT",
                                "binding_strength": "LOW",
                                "rationale": "过程型答案单元只作为 Shadow 上下文证据审计，不作为推荐理由。",
                            }
                        }),
                        review_status="SHADOW_CONTEXT_ONLY",
                    )
                    db.add(binding)
                    bindings.append(binding)
                    if max_bindings and len(bindings) >= max_bindings:
                        db.flush()
                        return bindings, errors
                continue
            rule = _rule_binding(event, unit)
            if not rule:
                continue
            payload = {"rule_candidate": rule}
            role = rule["decision_role"]
            strength = rule["binding_strength"]
            scope_type = rule.get("scope_type") or "SAME_PARAGRAPH"
            scope_reason = rule.get("scope_reason") or ""
            method = "RULE_SHADOW_CANDIDATE"
            if judge:
                try:
                    judged = judge.judge(event, unit, db=db)
                    payload["judge"] = judged
                    if not judged.get("bind", False):
                        continue
                    role = judged.get("decision_role") or role
                    strength = judged.get("binding_strength") or strength
                    scope_type = judged.get("scope_type") or scope_type
                    scope_reason = judged.get("scope_reason") or scope_reason
                    method = "LLM_SHADOW"
                except SemanticLLMError as exc:
                    errors.append(f"binding event#{event.id}/unit#{unit.id}: {str(exc)[:120]}")
            if role not in _DECISION_BINDING_ROLES:
                continue
            key = (event.id, unit.id)
            if key in seen:
                continue
            seen.add(key)
            binding = AnswerDecisionBinding(
                shadow_run_id=shadow_run.id,
                project_id=shadow_run.project_id,
                prompt_id=shadow_run.prompt_id,
                run_id=event.run_id,
                recommendation_event_id=event.id,
                answer_unit_id=unit.id,
                decision_role=role,
                binding_strength=strength,
                scope_type=scope_type,
                scope_reason=scope_reason,
                binding_method=method,
                pipeline_version=SHADOW_PIPELINE_VERSION,
                judge_payload_json=dumps(payload),
                review_status="MACHINE_GROUNDED",
            )
            db.add(binding)
            bindings.append(binding)
            if max_bindings and len(bindings) >= max_bindings:
                db.flush()
                return bindings, errors
    db.flush()
    return bindings, errors


def _docs_for_runs(db: Session, project: Project, run_ids: list[int]) -> dict[int, list[dict]]:
    refs = db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(run_ids)).order_by(ReferenceSource.run_id, ReferenceSource.reference_index).all()
    docs = db.query(SourceDocument).all()
    doc_by_key: dict[str, SourceDocument] = {}
    for doc in docs:
        for url in {doc.url, doc.original_url, doc.canonical_url}:
            key = _normalize_url_key(url or "")
            if key:
                doc_by_key[key] = doc

    quality_by_doc_id: dict[int, SourceQuality] = {}
    qualities = db.query(SourceQuality).order_by(SourceQuality.id.desc()).all()
    for quality in qualities:
        quality_by_doc_id.setdefault(quality.source_document_id, quality)

    result: dict[int, list[dict]] = defaultdict(list)
    for ref in refs:
        doc = None
        for url in {ref.canonical_url, ref.url}:
            key = _normalize_url_key(url or "")
            if key in doc_by_key:
                doc = doc_by_key[key]
                break
        if not doc:
            continue
        quality = quality_by_doc_id.get(doc.id)
        content = derive_content_status(doc, quality)
        if content.get("content_status") != "CONTENT_VALID":
            continue
        ownership = resolve_ownership(db, project, doc.url or doc.canonical_url or doc.original_url, doc.domain)
        passages = _split_document_passages(doc)
        if not passages:
            continue
        result[ref.run_id].append({
            "reference": ref,
            "document": doc,
            "ownership": ownership,
            "passages": passages,
        })
    return result


def _classify_shadow_evidence(relation: str, decision_role: str, source_claim_type: str) -> str:
    relation = (relation or "").upper()
    decision_role = (decision_role or "").upper()
    if relation == "CONTRADICTS":
        return "COUNTER_EVIDENCE"
    if relation == "SUPPORTS" and decision_role == "PROCEDURAL_CONTEXT":
        return "PROCEDURAL_EVIDENCE"
    if relation == "SUPPORTS" and decision_role == "DIRECT_REASON":
        return "RECOMMENDATION_EVIDENCE"
    if relation == "SUPPORTS" and decision_role == "SUPPORTING_REASON":
        return "RECOMMENDATION_SUPPORTING_EVIDENCE"
    if relation == "SUPPORTS" and source_claim_type == "USAGE":
        return "PROCEDURAL_EVIDENCE"
    return "NO_RECOMMENDATION_EVIDENCE"


def _classify_unbound_answer_evidence(relation: str, unit: AnswerUnit, source_claim_type: str) -> str:
    relation = (relation or "").upper()
    if relation == "CONTRADICTS":
        return "COUNTER_EVIDENCE"
    if relation != "SUPPORTS":
        return "NO_SUPPORTING_EVIDENCE"
    semantic_type = (unit.semantic_type or "").upper()
    if semantic_type in {"FEATURE", "BENEFIT", "PRICE", "USE_CASE", "RESULT_EFFECT", "COMPARATIVE_ADVANTAGE"}:
        return "BRAND_CAPABILITY_EVIDENCE"
    if semantic_type == "PROCEDURE" or (source_claim_type or "").upper() == "USAGE":
        return "PROCEDURAL_EVIDENCE"
    return "FACTUAL_EVIDENCE"


def _same_scope(event: RecommendationEvent, claim_subject: str, owner: str) -> bool:
    entity = event.entity_text or ""
    if not entity:
        return True
    if _same_entity(entity, claim_subject):
        return True
    if claim_subject in {"", "UNKNOWN"} and _same_entity(entity, owner):
        return True
    return False


def _same_unit_scope(unit: AnswerUnit, claim_subject: str, owner: str) -> bool:
    entity = unit.entity_hint or ""
    if not entity:
        return True
    if _same_entity(entity, claim_subject):
        return True
    if claim_subject in {"", "UNKNOWN"} and _same_entity(entity, owner):
        return True
    return False


def _run_shadow_source_chain(
    db: Session,
    shadow_run: AnswerEvidenceShadowRun,
    project: Project,
    bindings: list[AnswerDecisionBinding],
    top_k: int,
    source_claim_judge: SourceClaimJudge | Any | None,
    alignment_judge: EvidenceAlignmentJudge | Any | None,
) -> tuple[int, list[str]]:
    if not bindings:
        return 0, []

    run_ids = loads(shadow_run.source_run_ids_json, [])
    docs_by_run = _docs_for_runs(db, project, run_ids)
    units_by_id = {row.id: row for row in db.query(AnswerUnit).filter(AnswerUnit.shadow_run_id == shadow_run.id).all()}
    events_by_id = {
        row.id: row
        for row in db.query(RecommendationEvent)
        .filter(RecommendationEvent.id.in_([binding.recommendation_event_id for binding in bindings]))
        .all()
    }
    judge = source_claim_judge or SourceClaimJudge()
    aligner = alignment_judge or EvidenceAlignmentJudge()
    created = 0
    errors: list[str] = []

    for binding in bindings:
        unit = units_by_id.get(binding.answer_unit_id)
        event = events_by_id.get(binding.recommendation_event_id)
        if not unit or not event:
            continue
        source_groups = docs_by_run.get(binding.run_id, [])
        passages_with_context: list[dict] = []
        for group in source_groups:
            for passage in group["passages"]:
                passages_with_context.append({**passage, "group": group})
        query = f"{event.entity_text} {unit.unit_text_normalized}".strip()
        hits = retrieve_passages_for_reason(query, passages_with_context, top_k=top_k)
        if not hits:
            continue
        for hit in hits:
            group = hit["group"]
            doc = group["document"]
            ref = group["reference"]
            ownership = group["ownership"]
            try:
                judged_claims = judge.judge_passage(hit["text"], db=db)
            except SemanticLLMError as exc:
                errors.append(f"source doc#{doc.id}: {str(exc)[:120]}")
                continue
            claims = (judged_claims or {}).get("claims") or []
            if not claims:
                db.add(AnswerEvidenceShadowResult(
                    shadow_run_id=shadow_run.id,
                    project_id=shadow_run.project_id,
                    prompt_id=shadow_run.prompt_id,
                    run_id=binding.run_id,
                    evidence_package_id=shadow_run.evidence_package_id,
                    recommendation_event_id=event.id,
                    answer_unit_id=unit.id,
                    decision_binding_id=binding.id,
                    reference_source_id=ref.id,
                    source_document_id=doc.id,
                    passage_id=hit["passage_id"],
                    passage_text=hit["text"][:4000],
                    retrieval_score=float(hit.get("bm25_score") or 0),
                    source_claim_payload_json=dumps({"claims": []}),
                    source_claim_review_status="NO_CLAIM",
                    alignment_relation="NO_SUPPORT",
                    alignment_payload_json=dumps({"reason": "来源片段未抽取到 grounded 主张"}),
                    evidence_classification="NO_SOURCE_CLAIM",
                    pipeline_version=SHADOW_PIPELINE_VERSION,
                    formal_output_impact="NONE",
                ))
                created += 1
                continue
            for claim in claims:
                span_text = claim.get("source_span") or ""
                located = locate_span(hit["text"], span_text)
                source_status = "MACHINE_GROUNDED" if located else "VALIDATION_FAILED"
                subject = _normalize_subject_entity(
                    claim.get("subject_text") or "",
                    ownership["source_owner_entity"],
                )
                normalized_claim = claim.get("normalized_claim", "")
                relation = "NO_SUPPORT"
                alignment_payload = {"reason": "未进入语义对齐"}
                if source_status == "MACHINE_GROUNDED":
                    if not _same_scope(event, subject, ownership["source_owner_entity"]):
                        alignment_payload = {"precheck": "ENTITY_SCOPE_MISMATCH"}
                    else:
                        try:
                            judged_alignment = aligner.judge(unit.unit_text_normalized, normalized_claim, db=db)
                            raw_relation = (judged_alignment or {}).get("relation", "NONE").upper()
                            relation = raw_relation if raw_relation in {"SUPPORTS", "CONTRADICTS"} else "NO_SUPPORT"
                            alignment_payload = judged_alignment or {}
                        except SemanticLLMError as exc:
                            errors.append(f"alignment doc#{doc.id}: {str(exc)[:120]}")
                            alignment_payload = {"error": str(exc)[:300]}
                classification = _classify_shadow_evidence(relation, binding.decision_role, claim.get("claim_type", "OTHER"))
                db.add(AnswerEvidenceShadowResult(
                    shadow_run_id=shadow_run.id,
                    project_id=shadow_run.project_id,
                    prompt_id=shadow_run.prompt_id,
                    run_id=binding.run_id,
                    evidence_package_id=shadow_run.evidence_package_id,
                    recommendation_event_id=event.id,
                    answer_unit_id=unit.id,
                    decision_binding_id=binding.id,
                    reference_source_id=ref.id,
                    source_document_id=doc.id,
                    passage_id=hit["passage_id"],
                    passage_text=hit["text"][:4000],
                    retrieval_score=float(hit.get("bm25_score") or 0),
                    source_claim_payload_json=dumps(claim),
                    source_claim_text=normalized_claim,
                    source_claim_subject=subject or "UNKNOWN",
                    source_claim_review_status=source_status,
                    alignment_relation=relation,
                    alignment_payload_json=dumps(alignment_payload),
                    evidence_classification=classification,
                    pipeline_version=SHADOW_PIPELINE_VERSION,
                    formal_output_impact="NONE",
                    review_status="MACHINE_GROUNDED" if source_status == "MACHINE_GROUNDED" else "VALIDATION_FAILED",
                ))
                created += 1
    db.flush()
    return created, errors


def _run_unbound_answer_unit_source_chain(
    db: Session,
    shadow_run: AnswerEvidenceShadowRun,
    project: Project,
    units: list[AnswerUnit],
    bindings: list[AnswerDecisionBinding],
    top_k: int,
    source_claim_judge: SourceClaimJudge | Any | None,
    alignment_judge: EvidenceAlignmentJudge | Any | None,
) -> tuple[int, list[str]]:
    bound_unit_ids = {binding.answer_unit_id for binding in bindings}
    candidate_units = [
        unit
        for unit in units
        if unit.review_status == "MACHINE_GROUNDED"
        and unit.id not in bound_unit_ids
        and unit.semantic_type in {
            "FEATURE",
            "BENEFIT",
            "PRICE",
            "USE_CASE",
            "RESULT_EFFECT",
            "COMPARATIVE_ADVANTAGE",
            "PROCEDURE",
            "GENERAL_FACT",
        }
    ]
    if not candidate_units:
        return 0, []

    run_ids = loads(shadow_run.source_run_ids_json, [])
    docs_by_run = _docs_for_runs(db, project, run_ids)
    judge = source_claim_judge or SourceClaimJudge()
    aligner = alignment_judge or EvidenceAlignmentJudge()
    created = 0
    errors: list[str] = []

    for unit in candidate_units:
        source_groups = docs_by_run.get(unit.run_id, [])
        passages_with_context: list[dict] = []
        for group in source_groups:
            for passage in group["passages"]:
                passages_with_context.append({**passage, "group": group})
        query = unit.unit_text_normalized or unit.unit_text_original
        hits = retrieve_passages_for_reason(query, passages_with_context, top_k=top_k)
        if not hits:
            continue
        for hit in hits:
            group = hit["group"]
            doc = group["document"]
            ref = group["reference"]
            ownership = group["ownership"]
            try:
                judged_claims = judge.judge_passage(hit["text"], db=db)
            except SemanticLLMError as exc:
                errors.append(f"unbound source doc#{doc.id}: {str(exc)[:120]}")
                continue
            claims = (judged_claims or {}).get("claims") or []
            if not claims:
                db.add(AnswerEvidenceShadowResult(
                    shadow_run_id=shadow_run.id,
                    project_id=shadow_run.project_id,
                    prompt_id=shadow_run.prompt_id,
                    run_id=unit.run_id,
                    evidence_package_id=shadow_run.evidence_package_id,
                    recommendation_event_id=None,
                    answer_unit_id=unit.id,
                    decision_binding_id=None,
                    reference_source_id=ref.id,
                    source_document_id=doc.id,
                    passage_id=hit["passage_id"],
                    passage_text=hit["text"][:4000],
                    retrieval_score=float(hit.get("bm25_score") or 0),
                    source_claim_payload_json=dumps({"claims": []}),
                    source_claim_review_status="NO_CLAIM",
                    alignment_relation="NO_SUPPORT",
                    alignment_payload_json=dumps({"reason": "来源片段未抽取到 grounded 主张"}),
                    evidence_classification="NO_SOURCE_CLAIM",
                    pipeline_version=SHADOW_PIPELINE_VERSION,
                    formal_output_impact="NONE",
                ))
                created += 1
                continue
            for claim in claims:
                span_text = claim.get("source_span") or ""
                located = locate_span(hit["text"], span_text)
                source_status = "MACHINE_GROUNDED" if located else "VALIDATION_FAILED"
                subject = _normalize_subject_entity(
                    claim.get("subject_text") or "",
                    ownership["source_owner_entity"],
                )
                normalized_claim = claim.get("normalized_claim", "")
                relation = "NO_SUPPORT"
                alignment_payload = {"reason": "未进入语义对齐"}
                if source_status == "MACHINE_GROUNDED":
                    if not _same_unit_scope(unit, subject, ownership["source_owner_entity"]):
                        alignment_payload = {"precheck": "ENTITY_SCOPE_MISMATCH"}
                    else:
                        try:
                            judged_alignment = aligner.judge(unit.unit_text_normalized, normalized_claim, db=db)
                            raw_relation = (judged_alignment or {}).get("relation", "NONE").upper()
                            relation = raw_relation if raw_relation in {"SUPPORTS", "CONTRADICTS"} else "NO_SUPPORT"
                            alignment_payload = judged_alignment or {}
                        except SemanticLLMError as exc:
                            errors.append(f"unbound alignment doc#{doc.id}: {str(exc)[:120]}")
                            alignment_payload = {"error": str(exc)[:300]}
                classification = _classify_unbound_answer_evidence(relation, unit, claim.get("claim_type", "OTHER"))
                db.add(AnswerEvidenceShadowResult(
                    shadow_run_id=shadow_run.id,
                    project_id=shadow_run.project_id,
                    prompt_id=shadow_run.prompt_id,
                    run_id=unit.run_id,
                    evidence_package_id=shadow_run.evidence_package_id,
                    recommendation_event_id=None,
                    answer_unit_id=unit.id,
                    decision_binding_id=None,
                    reference_source_id=ref.id,
                    source_document_id=doc.id,
                    passage_id=hit["passage_id"],
                    passage_text=hit["text"][:4000],
                    retrieval_score=float(hit.get("bm25_score") or 0),
                    source_claim_payload_json=dumps(claim),
                    source_claim_text=normalized_claim,
                    source_claim_subject=subject or "UNKNOWN",
                    source_claim_review_status=source_status,
                    alignment_relation=relation,
                    alignment_payload_json=dumps(alignment_payload),
                    evidence_classification=classification,
                    pipeline_version=SHADOW_PIPELINE_VERSION,
                    formal_output_impact="NONE",
                    review_status="MACHINE_GROUNDED" if source_status == "MACHINE_GROUNDED" else "VALIDATION_FAILED",
                ))
                created += 1
    db.flush()
    return created, errors


def _shadow_run_summary(db: Session, shadow_run: AnswerEvidenceShadowRun, before_counts: dict) -> dict:
    units = db.query(AnswerUnit).filter(AnswerUnit.shadow_run_id == shadow_run.id).all()
    bindings = db.query(AnswerDecisionBinding).filter(AnswerDecisionBinding.shadow_run_id == shadow_run.id).all()
    decision_bindings = [row for row in bindings if row.decision_role in _DECISION_BINDING_ROLES]
    results = db.query(AnswerEvidenceShadowResult).filter(AnswerEvidenceShadowResult.shadow_run_id == shadow_run.id).all()
    relation_counts = Counter(row.alignment_relation for row in results)
    classification_counts = Counter(row.evidence_classification for row in results)
    formal_after = {
        "source_claim_count": db.query(SourceClaim)
        .filter(SourceClaim.project_id == shadow_run.project_id)
        .count(),
        "evidence_alignment_count": db.query(EvidenceAlignment)
        .filter(
            EvidenceAlignment.project_id == shadow_run.project_id,
            EvidenceAlignment.prompt_id == shadow_run.prompt_id,
        )
        .count(),
    }
    return {
        "answer_unit_count": len(units),
        "grounded_answer_unit_count": sum(1 for row in units if row.review_status == "MACHINE_GROUNDED"),
        "binding_count": len(decision_bindings),
        "context_binding_count": len(bindings) - len(decision_bindings),
        "direct_reason_count": sum(1 for row in decision_bindings if row.decision_role == "DIRECT_REASON"),
        "supporting_reason_count": sum(1 for row in decision_bindings if row.decision_role == "SUPPORTING_REASON"),
        "counter_reason_count": sum(1 for row in decision_bindings if row.decision_role == "COUNTER_REASON"),
        "shadow_result_count": len(results),
        "shadow_source_claim_count": sum(1 for row in results if row.source_claim_review_status == "MACHINE_GROUNDED"),
        "shadow_alignment_count": sum(1 for row in results if row.source_claim_review_status == "MACHINE_GROUNDED"),
        "supports_count": relation_counts.get("SUPPORTS", 0),
        "no_support_count": relation_counts.get("NO_SUPPORT", 0),
        "contradicts_count": relation_counts.get("CONTRADICTS", 0),
        "recommendation_evidence_eligible_count": (
            classification_counts.get("RECOMMENDATION_EVIDENCE", 0)
            + classification_counts.get("RECOMMENDATION_SUPPORTING_EVIDENCE", 0)
        ),
        "brand_capability_evidence_count": classification_counts.get("BRAND_CAPABILITY_EVIDENCE", 0),
        "procedural_evidence_count": classification_counts.get("PROCEDURAL_EVIDENCE", 0),
        "factual_evidence_count": classification_counts.get("FACTUAL_EVIDENCE", 0),
        "relation_counts": dict(relation_counts),
        "evidence_classification_counts": dict(classification_counts),
        "formal_source_claim_count_before": before_counts["source_claim_count"],
        "formal_source_claim_count_after": formal_after["source_claim_count"],
        "formal_evidence_alignment_count_before": before_counts["evidence_alignment_count"],
        "formal_evidence_alignment_count_after": formal_after["evidence_alignment_count"],
        "formal_output_impact": "NONE",
        "boundary_note": "Phase 0 Shadow 只写审计结果，不改变正式 Benchmark / Gap / Priority / Action / Strategy / Experiment。",
    }


def shadow_run_to_read(db: Session, shadow_run: AnswerEvidenceShadowRun, include_results: bool = True) -> dict:
    results = []
    if include_results:
        rows = (
            db.query(AnswerEvidenceShadowResult)
            .filter(AnswerEvidenceShadowResult.shadow_run_id == shadow_run.id)
            .order_by(AnswerEvidenceShadowResult.id)
            .limit(300)
            .all()
        )
        results = [
            {
                "id": row.id,
                "run_id": row.run_id,
                "recommendation_event_id": row.recommendation_event_id,
                "answer_unit_id": row.answer_unit_id,
                "decision_binding_id": row.decision_binding_id,
                "reference_source_id": row.reference_source_id,
                "source_document_id": row.source_document_id,
                "passage_id": row.passage_id,
                "retrieval_score": row.retrieval_score,
                "source_claim_text": row.source_claim_text,
                "source_claim_subject": row.source_claim_subject,
                "source_claim_review_status": row.source_claim_review_status,
                "alignment_relation": row.alignment_relation,
                "alignment_payload": loads(row.alignment_payload_json, {}),
                "evidence_classification": row.evidence_classification,
                "pipeline_version": row.pipeline_version,
                "formal_output_impact": row.formal_output_impact,
            }
            for row in rows
        ]
    return {
        "id": shadow_run.id,
        "project_id": shadow_run.project_id,
        "prompt_id": shadow_run.prompt_id,
        "evidence_package_id": shadow_run.evidence_package_id,
        "source_run_ids": loads(shadow_run.source_run_ids_json, []),
        "pipeline_version": shadow_run.pipeline_version,
        "status": shadow_run.status,
        "formal_output_impact": shadow_run.formal_output_impact,
        "started_at": shadow_run.started_at,
        "finished_at": shadow_run.finished_at,
        "summary": loads(shadow_run.summary_json, {}),
        "error_message": shadow_run.error_message,
        "results": results,
    }


def latest_answer_evidence_shadow_run(
    db: Session,
    project_id: int,
    prompt_id: int,
    evidence_package_id: int | None = None,
) -> AnswerEvidenceShadowRun | None:
    query = db.query(AnswerEvidenceShadowRun).filter(
        AnswerEvidenceShadowRun.project_id == project_id,
        AnswerEvidenceShadowRun.prompt_id == prompt_id,
    )
    if evidence_package_id:
        query = query.filter(AnswerEvidenceShadowRun.evidence_package_id == evidence_package_id)
    return query.order_by(AnswerEvidenceShadowRun.created_at.desc(), AnswerEvidenceShadowRun.id.desc()).first()


def run_answer_evidence_shadow_chain(
    db: Session,
    project_id: int,
    prompt_id: int,
    evidence_package_id: int | None = None,
    run_ids: list[int] | None = None,
    top_k: int = 3,
    use_llm_binding: bool = True,
    entity_filter: str | None = None,
    max_bindings: int | None = None,
    include_procedural_context: bool = False,
    include_unbound_answer_units: bool = False,
    binding_judge: AnswerEvidenceBindingJudge | None = None,
    source_claim_judge: SourceClaimJudge | Any | None = None,
    alignment_judge: EvidenceAlignmentJudge | Any | None = None,
) -> dict:
    project = db.get(Project, project_id)
    prompt = db.get(Prompt, prompt_id)
    if not project or not prompt or prompt.project_id != project_id:
        raise ValueError("项目或问题不存在")
    package = _resolve_package(db, project_id, prompt_id, evidence_package_id)
    source_run_ids = _resolve_run_ids(db, project_id, prompt_id, package, run_ids)
    if not source_run_ids:
        raise ValueError("当前问题没有可用于 Shadow 审计的采集 Run")

    before_counts = {
        "source_claim_count": db.query(SourceClaim).filter(SourceClaim.project_id == project_id).count(),
        "evidence_alignment_count": db.query(EvidenceAlignment)
        .filter(EvidenceAlignment.project_id == project_id, EvidenceAlignment.prompt_id == prompt_id)
        .count(),
    }
    shadow_run = AnswerEvidenceShadowRun(
        project_id=project_id,
        prompt_id=prompt_id,
        evidence_package_id=package.id if package else None,
        source_run_ids_json=dumps(source_run_ids),
        pipeline_version=SHADOW_PIPELINE_VERSION,
        status="running",
        formal_output_impact="NONE",
        started_at=datetime.utcnow(),
        summary_json=dumps({
            "formal_output_impact": "NONE",
            "boundary_note": "Shadow Run 初始化，正式输出不变。",
            "entity_filter": entity_filter or "",
            "max_bindings": max_bindings,
            "include_procedural_context": include_procedural_context,
            "include_unbound_answer_units": include_unbound_answer_units,
        }),
    )
    db.add(shadow_run)
    db.commit()
    db.refresh(shadow_run)

    try:
        runs = (
            db.query(BrowserMonitorRun)
            .filter(BrowserMonitorRun.id.in_(source_run_ids))
            .order_by(BrowserMonitorRun.id)
            .all()
        )
        runs_by_id = {run.id: run for run in runs}
        units = _build_answer_units(db, shadow_run, runs_by_id)
        bindings, binding_errors = _build_decision_bindings(
            db,
            shadow_run,
            units,
            use_llm_binding,
            binding_judge,
            entity_filter=entity_filter,
            max_bindings=max_bindings,
            include_procedural_context=include_procedural_context,
        )
        _, chain_errors = _run_shadow_source_chain(
            db,
            shadow_run,
            project,
            bindings,
            max(1, min(int(top_k or 3), 8)),
            source_claim_judge,
            alignment_judge,
        )
        _, unbound_errors = _run_unbound_answer_unit_source_chain(
            db,
            shadow_run,
            project,
            units,
            bindings,
            max(1, min(int(top_k or 3), 8)),
            source_claim_judge,
            alignment_judge,
        ) if include_unbound_answer_units else (0, [])
        errors = binding_errors + chain_errors + unbound_errors
        summary = _shadow_run_summary(db, shadow_run, before_counts)
        summary["entity_filter"] = entity_filter or ""
        summary["max_bindings"] = max_bindings
        summary["include_procedural_context"] = include_procedural_context
        summary["include_unbound_answer_units"] = include_unbound_answer_units
        if errors:
            summary["errors"] = errors[:10]
        shadow_run.summary_json = dumps(summary)
        shadow_run.status = "completed_with_warnings" if errors else "completed"
        shadow_run.finished_at = datetime.utcnow()
        shadow_run.formal_output_impact = "NONE"
        db.commit()
        db.refresh(shadow_run)
        return shadow_run_to_read(db, shadow_run)
    except Exception as exc:
        shadow_run.status = "failed"
        shadow_run.error_message = str(exc)[:1000]
        shadow_run.finished_at = datetime.utcnow()
        shadow_run.formal_output_impact = "NONE"
        db.commit()
        raise
