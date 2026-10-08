"""Offline delivery compilation: frozen evidence in, attributed text and QA out."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any


INPUT_VERSION = "single_prompt_delivery_input.v1"
TEXT_QA_VERSION = "single_prompt_execution_text_qa.v3"


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
        if item.get("material_use") == "ATTRIBUTED_BRAND_PAGE_OBSERVATION_NOT_TRUTH":
            # A product page observation provides a lookup destination, not a claim.
            continue
        before = item["proposed_text"]
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
    title = title or f"{prompt}：场景对照与选择检查"
    body = [f"# {title}", "", f"选择“{prompt}”相关方案时，先写清自己的使用场景、期望结果和实际可操作条件，"
            "再对照具体资料。下面把相关话题与各自出处放在一起，便于判断应继续核对哪一项，而不是把所有做法同时照搬。",
            "", "## 先对照自己的需求", "",
            "| 需要了解的话题 | 对照资料 | 选择前要核对 |", "| --- | --- | --- |"]
    evidence = {item["section_id"]: item for item in frozen["selected_evidence"]}
    checks = {
        "PROCEDURE": "操作环境、账号权限和适用条件是否与自己的场景一致？",
        "DECISION_REASON": "资料里的例子属于哪个工具，是否覆盖自己的具体需求？",
        "RULE_CONDITION": "规则适用于什么对象和条件，当前是否仍然适用？",
    }
    for section in sections:
        item = evidence.get(section["section_id"], {})
        unit = item.get("answer_unit") or {}
        raw = str(unit.get("raw_text") or "")
        label = raw.split("：", 1)[0] if "：" in raw and len(raw.split("：", 1)[0]) <= 40 else item.get("title", section["title"])
        cell = lambda text: str(text).replace("|", "\\|").replace("\n", " ")
        check = checks.get(unit.get("primary_type"), "主体、适用范围和时间是否与自己的需求一致？")
        body.append(f"| {cell(label)} | {cell(item.get('title', section['title']))} | {check} |")
    body.extend(["", "这些核对问题是选型步骤，不代表资料里的方法已经在你的账号或环境中验证通过。",
                 "", "## 对照资料原文", "", "请连同主体和适用条件阅读，不将一个工具的例子当成其他工具的能力说明。"])
    for section in sections:
        body.extend(["", f"## {section['title']}", "", section["draft_text"]])
    body.extend(["", f"## 准备了解{brand}时，去哪里核对", ""])
    observations = frozen.get("asset_observations") or []
    if observations:
        body.append(f"准备比较{brand}时，可以先查看以下相关资料，再向服务方核对与你的场景对应的具体支持范围：")
        for page in observations:
            body.append(f"- {page['title']}：{page['url']}")
    else:
        body.append(f"准备比较{brand}时，请向服务方核对适用场景和产品说明；本文没有提供未经核实的产品能力承诺。")
    body.extend([f"不要把上文其他工具的例子当成{brand}的能力，也不要仅凭页面的效果描述决定上线。",
                 "", "## 选择后，按这个顺序检查", "",
                 "1. 写清你的使用场景、期望结果，以及准备采用上表中的哪一种做法。",
                 "2. 对照该项资料，核对实际账号、使用环境、前提条件和服务方说明；条件不一致时先停止套用步骤。",
                 "3. 在自己可控制的小范围内实际尝试，记录采用的方法、测试环境、实际结果及失败情况。",
                 "4. 只有实际结果符合预期，才决定扩大使用；不符合时保留失败记录并调整选择，不把个别成功当成普遍保证。",
                 "", "## 结论", "",
                 f"对于“{prompt}”，先选适用场景，再核对具体方法和产品范围，最后用实际尝试决定是否采用。"
                 "这比把不同资料中的做法拼成一个通用承诺更稳妥。"])
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
