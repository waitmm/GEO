from __future__ import annotations

import re
from typing import Any

from app.models import Project
from app.services.serialization import loads


RECOMMENDATION_KEYWORDS = {
    4: ["最佳", "最好", "首选", "排名第一", "最推荐", "强烈推荐"],
    3: ["明确推荐", "值得选择", "优先考虑", "表现突出"],
    2: ["推荐", "适合", "候选", "可以选择", "供应商"],
}


def analyze_brand(answer_text: str, project: Project) -> dict[str, Any]:
    aliases = [project.brand_name] + loads(project.brand_aliases_json, [])
    matches = []
    for alias in aliases:
        if not alias:
            continue
        for match in re.finditer(re.escape(alias), answer_text, flags=re.IGNORECASE):
            matches.append({"alias": alias, "start": match.start(), "end": match.end()})

    matches.sort(key=lambda item: item["start"])
    mention_count = len(matches)
    first_position = matches[0]["start"] if matches else -1
    first_alias = matches[0]["alias"] if matches else ""
    recommendation_level = _recommendation_level(answer_text, mention_count)
    snippets = [_snippet(answer_text, item["start"], item["end"]) for item in matches[:5]]
    paragraphs = [paragraph for paragraph in answer_text.splitlines() if paragraph.strip()]
    first_paragraph_index = -1
    if first_position >= 0:
        offset = 0
        for index, paragraph in enumerate(paragraphs):
            end = offset + len(paragraph)
            if offset <= first_position <= end:
                first_paragraph_index = index
                break
            offset = end + 1

    return {
        "brand_mentioned": mention_count > 0,
        "brand_name": project.brand_name,
        "alias_matched": first_alias,
        "mention_count": mention_count,
        "first_char_position": first_position,
        "first_paragraph_index": first_paragraph_index,
        "recommendation_level": recommendation_level,
        "context_snippets": snippets,
    }


def _recommendation_level(answer_text: str, mention_count: int) -> int:
    if mention_count == 0:
        return 0
    for level, keywords in sorted(RECOMMENDATION_KEYWORDS.items(), reverse=True):
        if any(keyword in answer_text for keyword in keywords):
            return level
    return 1


def _snippet(text: str, start: int, end: int) -> str:
    return text[max(0, start - 80) : min(len(text), end + 80)]
