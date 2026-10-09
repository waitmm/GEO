from __future__ import annotations

import hashlib
import html
import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse, urlunparse


CANONICALIZATION_VERSION = "url_identity.v2"

_TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "share_medium",
    "share_plat",
    "share_session_id",
    "share_source",
    "spm",
}
_TRACKING_QUERY_PREFIXES = ("utm_",)


@dataclass(frozen=True)
class UrlIdentity:
    raw_url: str
    canonical_url: str
    canonical_url_hash: str
    canonicalization_version: str
    valid: bool
    invalid_reason: str = ""


def _clean_url(value: str) -> str:
    cleaned = html.unescape(value or "")
    cleaned = cleaned.replace("\\u0022", '"').replace("\\u0026", "&")
    for _ in range(2):
        decoded = unquote(cleaned)
        if decoded == cleaned:
            break
        cleaned = decoded
    cleaned = cleaned.strip().strip('"').strip("'")
    cleaned = re.split(r'["\'\s<>。，，]', cleaned, maxsplit=1)[0]
    if cleaned.startswith("//"):
        cleaned = f"https:{cleaned}"
    return cleaned


def canonicalize_url(value: str) -> str:
    """Return the current stable, deterministic and idempotent URL identity."""
    cleaned = _clean_url(value)
    if not cleaned:
        return ""
    try:
        parsed = urlparse(cleaned if "://" in cleaned else f"https://{cleaned}")
        scheme = (parsed.scheme or "https").lower()
        if scheme not in {"http", "https"}:
            return ""
        host = (parsed.hostname or "").strip().lower().rstrip(".")
        if not host or any(char.isspace() for char in host):
            return ""
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            return ""
        if host.startswith("www."):
            host = host[4:]
        if "." not in host and host != "localhost":
            try:
                ipaddress.ip_address(host)
            except ValueError:
                return ""
        port = parsed.port
        netloc = f"{host}:{port}" if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)) else host
        path = quote(unquote(parsed.path or ""), safe="/%:@!$&'()*+,;=-._~")
        path = re.sub(r"/{2,}", "/", path)
        if path == "/":
            path = ""
        elif path:
            path = path.rstrip("/")
        query_pairs = [
            (key, val)
            for key, val in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in _TRACKING_QUERY_KEYS
            and not key.lower().startswith(_TRACKING_QUERY_PREFIXES)
        ]
        query = urlencode(sorted(query_pairs), doseq=True)
        return urlunparse((scheme, netloc, path, "", query, ""))
    except (TypeError, ValueError, UnicodeError):
        return ""


def canonical_url_hash(value: str) -> str:
    canonical = canonicalize_url(value)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest() if canonical else ""


def build_url_identity(raw_url: str, canonical_url: str = "") -> UrlIdentity:
    raw = (raw_url or "").strip()
    canonical = canonicalize_url(canonical_url or raw)
    if not canonical:
        return UrlIdentity(
            raw_url=raw,
            canonical_url="",
            canonical_url_hash="",
            canonicalization_version=CANONICALIZATION_VERSION,
            valid=False,
            invalid_reason="EMPTY_OR_INVALID_URL",
        )
    return UrlIdentity(
        raw_url=raw,
        canonical_url=canonical,
        canonical_url_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        canonicalization_version=CANONICALIZATION_VERSION,
        valid=True,
    )


def url_identity_fields(raw_url: str, canonical_url: str = "") -> dict[str, str]:
    identity = build_url_identity(raw_url, canonical_url)
    return {
        "canonical_url": identity.canonical_url,
        "canonical_url_hash": identity.canonical_url_hash,
        "canonicalization_version": identity.canonicalization_version,
    }
