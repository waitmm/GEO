from __future__ import annotations

import html
import re
import urllib.parse
from typing import Optional


STATIC_DOMAINS = (
    "t7.baidu.com",
    "t8.baidu.com",
    "t9.baidu.com",
    "ss0.baidu.com",
    "ss1.baidu.com",
    "bdstatic.com",
)

STATIC_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".css",
    ".js",
    ".mjs",
    ".map",
    ".woff",
    ".woff2",
    ".ttf",
    ".mp4",
    ".webm",
    ".mp3",
)


def normalize_serialized_text(value: str) -> str:
    normalized = html.unescape(value or "")
    normalized = normalized.replace("\\u0022", '"').replace("\\u0026", "&")
    for _ in range(2):
        decoded = urllib.parse.unquote(normalized)
        if decoded == normalized:
            break
        normalized = decoded
    return normalized


def clean_resolved_url(value: str) -> str:
    url = normalize_serialized_text(value).strip().strip('"').strip("'")
    url = re.split(r'["\'\s<>。，，]', url, maxsplit=1)[0]
    if url.startswith("//"):
        url = f"https:{url}"
    return url


def canonicalize_url(value: str) -> str:
    url = clean_resolved_url(value)
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url if "://" in url else f"https://{url}")
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path or ""
    query_pairs = [
        pair
        for pair in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if not pair[0].lower().startswith(("utm_", "spm", "from"))
    ]
    query = urllib.parse.urlencode(query_pairs)
    return urllib.parse.urlunparse((scheme, netloc, path, "", query, ""))


def domain_from_url(value: str) -> str:
    url = clean_resolved_url(value)
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url if "://" in url else f"https://{url}")
    return parsed.netloc.lower().removeprefix("www.")


def is_static_resource(value: str) -> bool:
    url = clean_resolved_url(value)
    if not url:
        return True
    domain = domain_from_url(url)
    path = urllib.parse.urlparse(url).path.lower()
    if any(static_domain in domain for static_domain in STATIC_DOMAINS):
        return True
    return path.endswith(STATIC_EXTENSIONS)


def extract_first_url(value: str) -> Optional[str]:
    normalized = normalize_serialized_text(value)
    match = re.search(r"https?://[^\s\"'<>\\]+", normalized)
    if not match:
        return None
    url = clean_resolved_url(match.group(0))
    return "" if is_static_resource(url) else url
