from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any, Optional

from app.core.config import get_settings
from app.modules.monitoring.collectors.wenxin.url_normalizer import (
    canonicalize_url,
    domain_from_url,
    extract_first_url,
    is_static_resource,
    normalize_serialized_text,
)


def title_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalize_title(left), normalize_title(right)).ratio()


def normalize_title(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def parse_standard_link_pair(value: str) -> Optional[dict[str, str]]:
    normalized = normalize_serialized_text(value)
    try:
        payload = json.loads(normalized)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    url = payload.get("linkUrl") or payload.get("link") or payload.get("url") or payload.get("href")
    title = payload.get("linkTitle") or payload.get("title") or ""
    if not url or is_static_resource(url):
        return None
    return {"url": url, "title": title}


def parse_malformed_link_pair(value: str) -> Optional[dict[str, str]]:
    normalized = normalize_serialized_text(value)
    url = (
        _extract_named_value(normalized, "linkUrl")
        or _extract_named_value(normalized, "link")
        or _extract_named_value(normalized, "url")
        or extract_first_url(normalized)
    )
    title = _extract_named_value(normalized, "linkTitle") or _extract_named_value(normalized, "title") or ""
    if not url or is_static_resource(url):
        return None
    return {"url": url, "title": title}


def _extract_named_value(value: str, key: str) -> Optional[str]:
    patterns = [
        rf'"{re.escape(key)}"\s*:\s*"([^"]+)"',
        rf"'{re.escape(key)}'\s*:\s*'([^']+)'",
        rf"{re.escape(key)}\s*[:=]\s*([^,&}}\]\s]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            return normalize_serialized_text(match.group(1)).strip().strip('"').strip("'")
    return None


def resolve_reference_url(reference_item: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    display_title = reference_item.get("display_title") or ""

    direct_url = (
        reference_item.get("href")
        or reference_item.get("data_url")
        or reference_item.get("data-url")
        or reference_item.get("data_href")
        or reference_item.get("data-href")
        or reference_item.get("data_link")
        or reference_item.get("data-link")
        or reference_item.get("data_source_url")
        or reference_item.get("data-source-url")
        or reference_item.get("data_target_url")
        or reference_item.get("data-target-url")
        or reference_item.get("data_jump_url")
        or reference_item.get("data-jump-url")
        or reference_item.get("data_redirect_url")
        or reference_item.get("data-redirect-url")
        or reference_item.get("url")
    )
    if direct_url and not is_static_resource(direct_url):
        return _resolved(reference_item, direct_url, display_title, "dom-direct-url", 1.0)

    serialized_values = [
        reference_item.get("outer_html") or "",
        reference_item.get("serialized") or "",
        reference_item.get("parent_outer_html") or "",
        *(reference_item.get("ancestor_outer_html") or []),
    ]
    for serialized in serialized_values:
        parsed = parse_standard_link_pair(serialized) or parse_malformed_link_pair(serialized)
        if not parsed:
            continue
        method = "serialized-same-reference-exact-title"
        confidence = 1.0
        parsed_title = parsed.get("title") or ""
        if parsed_title and normalize_title(parsed_title) != normalize_title(display_title):
            similarity = title_similarity(parsed_title, display_title)
            if similarity >= get_settings().reference_title_fuzzy_threshold:
                method = "serialized-same-reference-fuzzy-title"
                confidence = similarity
            else:
                method = "serialized-same-reference-index"
                confidence = 0.9
        return _resolved(reference_item, parsed["url"], parsed_title or display_title, method, confidence)

    candidate = match_candidate_by_title(display_title, candidates)
    if candidate:
        return _resolved(reference_item, candidate["url"], candidate.get("title") or display_title, "retrieval-candidate-title-match", candidate["confidence"])

    unresolved = dict(reference_item)
    unresolved.update(
        {
            "url": "",
            "canonical_url": "",
            "domain": "",
            "matched_title": "",
            "resolution_method": "unresolved",
            "match_confidence": 0,
        }
    )
    return unresolved


def match_candidate_by_title(display_title: str, candidates: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    best: Optional[dict[str, Any]] = None
    for candidate in candidates:
        url = candidate.get("url") or ""
        title = candidate.get("title") or ""
        if not url or is_static_resource(url):
            continue
        confidence = title_similarity(display_title, title)
        if confidence >= get_settings().reference_title_fuzzy_threshold and (not best or confidence > best["confidence"]):
            best = {**candidate, "confidence": confidence}
    return best


def _resolved(reference_item: dict[str, Any], url: str, matched_title: str, method: str, confidence: float) -> dict[str, Any]:
    clean_url = canonicalize_url(url)
    result = dict(reference_item)
    result.update(
        {
            "url": clean_url,
            "canonical_url": clean_url,
            "domain": domain_from_url(clean_url),
            "matched_title": matched_title,
            "resolution_method": method,
            "match_confidence": round(confidence, 4),
        }
    )
    return result
