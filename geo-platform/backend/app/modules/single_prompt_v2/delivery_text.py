"""Offline delivery compilation: frozen evidence in, attributed text and QA out."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any


INPUT_VERSION = "single_prompt_delivery_input.v1"
TEXT_QA_VERSION = "single_prompt_execution_text_qa.v2"


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def text_digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def quote_text(evidence: dict) -> str:
    # Whole paragraphs retain subjects and qualifications surrounding the matched span.
    return f"资料《{evidence['title']}》记载：\n\n" + "\n".join(
        f"> {line}" for line in evidence["passage_text"].splitlines()
    ) + f"\n\n来源：{evidence['url']}"


def check_statement(text: str, evidence: dict, subjects: list[str]) -> list[dict]:
    """Only a complete, attributed source projection is mechanically publishable.

    A paraphrase failing this rule is unverified, not declared semantically false.
    Additional diagnostics explain provable differences without granting permission.
    """
    source = evidence["passage_text"]
    if text == quote_text(evidence):
        return []
    issues = []
    for subject in subjects:
        if subject and subject in text and subject not in source:
            issues.append({"code": "SUBJECT_NOT_SUPPORTED", "detail": f"拟写主体“{subject}”不在所绑定来源段落中。"})
    numbers = lambda value: set(re.findall(r"\d+(?:\.\d+)?(?:%|％|元|年|天|小时|倍)?", value))
    added = sorted(numbers(text) - numbers(source))
    if added:
        issues.append({"code": "NUMBER_NOT_SUPPORTED", "detail": f"来源未支持新增数值：{'、'.join(added)}"})
    conditions = re.findall(r"(?:仅限|仅在|只适用|如果|若|当|需先|必须|不得|不能|不支持)[^，。；\n]{1,60}", source)
    if any(value not in text for value in conditions):
        issues.append({"code": "QUALIFIER_NOT_PRESERVED", "detail": "拟写文本未保留来源中的条件或否定范围，需要收窄。"})
    issues.append({
        "code": "UNVERIFIED_PARAPHRASE",
        "detail": "有引用不等于该改写成立；当前离线检查不能证明主体、条件和能力范围全部等价，改用完整归因原文。",
    })
    return issues


def build_sections(frozen: dict) -> tuple[list[dict], list[dict], list[dict]]:
    sections, findings, repairs = [], [], []
    for item in frozen["selected_evidence"]:
        before = quote_text(item) if item.get("material_use") == "ATTRIBUTED_BRAND_PAGE_OBSERVATION_NOT_TRUTH" else item["proposed_text"]
        issues = check_statement(before, item, frozen["subjects"])
        after = quote_text(item)
        section_id = item["section_id"]
        section = {
            "section_id": section_id, "content_class": "PUBLIC_CONTENT",
            "purpose": "ATTRIBUTED_SOURCE_EXCERPT", "title": f"资料：{item['title']}",
            "draft_text": after,
            "binding_ids": [item["binding_id"]] if item.get("binding_id") else [],
            "citation_ids": [item["citation_id"]], "answer_unit_id": item.get("answer_unit_id"),
            "source_snapshot_ids": [item["snapshot_id"]], "source_excerpt": item["passage_text"],
            "passage_id": item["passage_id"], "source_url": item["url"],
            "evidence_relation": item.get("evidence_relation"),
            "answer_anchor": item.get("answer_anchor", "UNPROVEN"),
            "generation_influence": item.get("generation_influence", "UNAVAILABLE"),
            "truth_ids": [], "reason_ids": [], "theme_ids": [], "allowed_claim_ids": [],
        }
        sections.append(section)
        for issue in issues:
            findings.append({**issue, "section_id": section_id, "original_text": before,
                             "source_text": item["passage_text"], "status": "REPAIRED"})
        if before != after:
            repairs.append({
                "code": "REPLACE_UNVERIFIED_PARAPHRASE_WITH_ATTRIBUTED_SOURCE",
                "section_id": section_id, "issue_codes": [row["code"] for row in issues],
                "before": before, "after": after, "before_hash": text_digest(before),
                "after_hash": text_digest(after), "result": "APPLIED",
                "recheck": "PASS" if not check_statement(after, item, frozen["subjects"]) else "FAIL",
                "detail": "仅替换当前内容块，不改变回答、来源和机器关系；保留来源完整段落和明确出处。",
            })
    return sections, findings, repairs


def render_draft(frozen: dict, sections: list[dict], title: str | None = None) -> dict:
    prompt = frozen["prompt_text"]
    brand = frozen["brand"]["brand_name"]
    title = title or f"{prompt}：资料解读与适用边界"
    body = [f"# {title}", "", f"围绕“{prompt}”，下文按资料分别说明相关做法及适用范围。"
            "不同来源的主体和条件不能互相替换；所列内容是来源表述，不代表独立验证或效果保证。"]
    for section in sections:
        body.extend(["", f"## {section['title']}", "", section["draft_text"]])
    body.extend(["", f"## {brand}与这个问题", "",
                 f"这份解读围绕“{prompt}”整理可回查资料，供读者对照自身场景选择下一步。"
                 f"资料中其他工具的功能不代表{brand}具备相同能力；具体产品范围应以明确的产品说明为准。",
                 "", "## 如何使用这些资料", "",
                 "先确定自己的使用场景，再逐项对照来源中的主体、适用条件和操作前提。"
                 "涉及实际操作时，先核对当前版本和权限，再在可控范围验证；不要把不同资料的片段拼成未经验证的承诺。",
                 "", "## 结论", "",
                 f"对于“{prompt}”，应保留各来源自己的适用边界。"
                 "本文提供可回查的资料和使用次序，不把内容发布等同于效果已经实现。"])
    text = "\n".join(body)
    return {"deliverable_type": "EVIDENCE_BASED_ARTICLE", "title": title,
            "body_markdown": text, "content_hash": text_digest(text), "sections": copy.deepcopy(sections)}


def audit_draft(frozen: dict, draft: dict, *, findings: list | None = None, repairs: list | None = None) -> dict:
    evidence = {item["section_id"]: item for item in frozen["selected_evidence"]}
    errors, checks = [], []
    seen = set()
    sections = draft.get("sections") or []
    for section in sections:
        key = section.get("section_id")
        item = evidence.get(key)
        issues = []
        if not item or key in seen:
            issues = [{"code": "UNKNOWN_OR_DUPLICATE_SECTION", "detail": "没有唯一的冻结依据"}]
        else:
            issues = check_statement(str(section.get("draft_text") or ""), item, frozen["subjects"])
            if section.get("source_excerpt") != item["passage_text"] or section.get("source_snapshot_ids") != [item["snapshot_id"]]:
                issues.append({"code": "EVIDENCE_BINDING_CHANGED", "detail": "正文引用与冻结依据不一致"})
            if section.get("title") != f"资料：{item['title']}":
                issues.append({"code": "UNVERIFIED_SECTION_TITLE", "detail": "章节标题出现未经验证的改写"})
        seen.add(key)
        errors.extend({**issue, "section_id": key} for issue in issues)
        checks.append({"section_id": key, "status": "FAIL" if issues else "PASS",
                       "rule": "FULL_ATTRIBUTED_PASSAGE", "scope": "仅证明引用原文及主体/限定未被改写，不证明来源事实为真",
                       "issues": issues})
    expected = render_draft(frozen, sections)
    if draft.get("body_markdown") != expected["body_markdown"] or draft.get("title") != expected["title"]:
        errors.append({"code": "UNBOUND_PUBLIC_TEXT", "detail": "正文或标题包含不属于已校验内容块/通用引导的改写"})
    if draft.get("content_hash") != text_digest(str(draft.get("body_markdown") or "")):
        errors.append({"code": "CONTENT_HASH_MISMATCH", "detail": "QA 目标正文 hash 不一致"})
    if not sections:
        errors.append({"code": "NO_SUPPORTED_CONTENT", "detail": "当前没有可交付的有据内容块"})
    return {
        "contract_version": TEXT_QA_VERSION, "status": "READY" if not errors else "NEEDS_REPAIR",
        "publication_eligibility": "NEEDS_BUSINESS_CONFIRMATION" if not errors else "NOT_ELIGIBLE",
        "checked_content_hash": draft.get("content_hash"), "delivery_input_hash": digest(frozen),
        "method": "DETERMINISTIC_ATTRIBUTED_EXTRACTION",
        "checks": {"statement_grounding": "PASS" if not errors else "FAIL",
                   "complete_text_binding": "PASS" if not any(r["code"] == "UNBOUND_PUBLIC_TEXT" for r in errors) else "FAIL"},
        "statement_checks": checks, "findings": copy.deepcopy(findings or []), "issues": errors,
        "repairs": copy.deepcopy(repairs or []),
        "limitations": ["来源原文归因不等于核实来源事实", "自由改写不自动通过；复杂语义不声称已被规则完整判定",
                        "不会将来源表述转成目标品牌能力或生成因果", "未实时核验平台规则与页面时效"],
    }
