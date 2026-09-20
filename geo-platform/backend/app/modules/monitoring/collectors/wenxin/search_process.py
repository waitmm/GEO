from __future__ import annotations

import hashlib
import re
from typing import Any


SEARCH_OBSERVATION_CONTRACT_VERSION = "wenxin-platform-search-observation-v1"
ANSWER_BOUNDARY_CONTRACT_VERSION = "wenxin-final-answer-boundary-v1"

_SEARCH_COUNT_RE = re.compile(r"^\s*搜索\s*(\d+)\s*个关键词(?:\s|$)")
_SEARCH_TERMS_RE = re.compile(r"^\s*搜索关键词\s*(.+?)\s*$")
_QUOTED_TERM_RE = re.compile(r"[\u201c\"]([^\u201d\"\r\n]+)[\u201d\"]")


def project_platform_search_observation(
    text: str | None,
    *,
    source: str = "WENXIN_THINKING_STEPS_DOM",
) -> dict[str, Any]:
    """Project Wenxin-reported search terms without treating them as retrieval facts."""

    raw_text = str(text or "")
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    reported_count: int | None = None
    evidence_line: str | None = None
    terms: list[str] = []
    for line in lines:
        count_match = _SEARCH_COUNT_RE.match(line)
        if count_match and reported_count is None:
            reported_count = int(count_match.group(1))
        terms_match = _SEARCH_TERMS_RE.match(line)
        if terms_match and evidence_line is None:
            evidence_line = line
            for term in _QUOTED_TERM_RE.findall(terms_match.group(1)):
                cleaned = term.strip()
                if cleaned and cleaned not in terms:
                    terms.append(cleaned)

    return {
        "contract_version": SEARCH_OBSERVATION_CONTRACT_VERSION,
        "status": "MODEL_REPORTED" if terms else "NOT_REPORTED",
        "terms": terms,
        "reported_count": reported_count,
        "count_consistent": reported_count == len(terms) if reported_count is not None and terms else None,
        "source": source,
        "verification_status": "UNVERIFIED_RETRIEVAL_TRACE",
        "consumption_policy": "OBSERVATION_ONLY",
        "evidence_line": evidence_line,
        "source_text_sha256": hashlib.sha256(raw_text.encode("utf-8")).hexdigest() if raw_text else None,
    }


def final_answer_boundary() -> dict[str, str]:
    return {
        "contract_version": ANSWER_BOUNDARY_CONTRACT_VERSION,
        "status": "FINAL_ANSWER_ONLY",
        "source": "WENXIN_FINAL_MARKDOWN_DOM",
    }


def legacy_mixed_answer_boundary(answer_text: str | None) -> dict[str, str]:
    projection = project_platform_search_observation(
        answer_text,
        source="LEGACY_MIXED_ANSWER_TEXT_PROJECTION",
    )
    if projection["status"] == "MODEL_REPORTED":
        return {
            "contract_version": ANSWER_BOUNDARY_CONTRACT_VERSION,
            "status": "LEGACY_MIXED_CONTAINER",
            "source": "ANSWER_TEXT_PATTERN_DETECTION",
        }
    return {
        "contract_version": ANSWER_BOUNDARY_CONTRACT_VERSION,
        "status": "UNVERIFIED",
        "source": "NO_SEMANTIC_REGION_ARTIFACT",
    }


def normalize_platform_search_observation(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if value.get("contract_version") != SEARCH_OBSERVATION_CONTRACT_VERSION:
        return None
    terms = value.get("terms")
    if not isinstance(terms, list) or any(not isinstance(term, str) for term in terms):
        return None
    reported_count = value.get("reported_count")
    if reported_count is not None and (not isinstance(reported_count, int) or isinstance(reported_count, bool)):
        return None
    status = value.get("status")
    if status not in {"MODEL_REPORTED", "NOT_REPORTED"}:
        return None
    return {
        "contract_version": SEARCH_OBSERVATION_CONTRACT_VERSION,
        "status": status,
        "terms": list(dict.fromkeys(term.strip() for term in terms if term.strip())),
        "reported_count": reported_count,
        "count_consistent": value.get("count_consistent"),
        "source": str(value.get("source") or "WENXIN_THINKING_STEPS_DOM"),
        "verification_status": "UNVERIFIED_RETRIEVAL_TRACE",
        "consumption_policy": "OBSERVATION_ONLY",
        "evidence_line": value.get("evidence_line"),
        "source_text_sha256": value.get("source_text_sha256"),
    }


def normalize_answer_content_boundary(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    if value.get("contract_version") != ANSWER_BOUNDARY_CONTRACT_VERSION:
        return None
    if value.get("status") != "FINAL_ANSWER_ONLY":
        return None
    if value.get("source") != "WENXIN_FINAL_MARKDOWN_DOM":
        return None
    return final_answer_boundary()
