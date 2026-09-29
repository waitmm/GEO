"""Provider-neutral helpers for strict semantic LLM admission."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from typing import Any

from app.services.semantic_llm.base import SemanticLLMError


def audit_excerpt(content: str, limit: int = 240) -> str:
    compact = " ".join((content or "").split())
    compact = re.sub(r"(?i)bearer\s+[a-z0-9._-]+", "Bearer [REDACTED]", compact)
    compact = re.sub(r"(?i)\bsk-[a-z0-9_-]+", "[REDACTED_KEY]", compact)
    return compact[:limit]


def response_error(
    message: str,
    *,
    code: str = "FAILED_PARSE",
    source: str,
    content: str,
    finish_reason: str = "",
    raw_response_hash: str = "",
    validation_errors: list[dict[str, Any]] | None = None,
) -> SemanticLLMError:
    exc = SemanticLLMError(message)
    exc.code = code
    exc.audit = {
        "response_source": source,
        "raw_response_hash": raw_response_hash or hashlib.sha256((content or "").encode("utf-8")).hexdigest(),
        "finish_reason": finish_reason or "unknown",
        "response_length": len(content or ""),
        "response_excerpt": audit_excerpt(content),
        "validation_errors": validation_errors or [],
    }
    return exc


def validate_response_payload(
    payload: Any,
    validator: Callable[[Any], dict[str, Any]] | None,
    *,
    source: str,
    content: str,
    finish_reason: str = "",
    raw_response_hash: str = "",
) -> dict[str, Any]:
    if validator is None:
        return payload
    try:
        return validator(payload)
    except SemanticLLMError as exc:
        audit = dict(getattr(exc, "audit", {}) or {})
        audit.update({
            "response_source": source,
            "raw_response_hash": raw_response_hash or hashlib.sha256((content or "").encode("utf-8")).hexdigest(),
            "finish_reason": finish_reason or audit.get("finish_reason") or "unknown",
            "response_length": len(content or ""),
            "response_excerpt": audit_excerpt(content),
        })
        exc.audit = audit
        raise
    except Exception as exc:
        raise response_error(
            f"模型响应未通过适用准入校验: {exc}",
            source=source,
            content=content,
            finish_reason=finish_reason,
            raw_response_hash=raw_response_hash,
        ) from exc


def extract_json_object(content: str) -> dict | None:
    """Extract the first complete JSON object for legacy non-strict callers."""
    start = content.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for index in range(start, len(content)):
        char = content[index]
        if in_str:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_str = False
            continue
        if char == '"':
            in_str = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(content[start:index + 1])
                except json.JSONDecodeError:
                    return None
    return None


def structured_input_hash(
    system_prompt: str,
    user_payload: dict,
    prompt_version: str,
    schema_version: str,
    thinking_mode: str | None = None,
    structured_output_mode: str | None = None,
    provider_schema_hash: str = "",
    transport_version: str = "",
    requested_model_alias: str = "",
    effective_request_model: str = "",
) -> str:
    identity: dict[str, Any] = {
        "system": system_prompt,
        "payload": user_payload,
        "pv": prompt_version,
        "sv": schema_version,
    }
    if thinking_mode:
        identity["generation"] = {"thinking": {"type": thinking_mode}}
    if structured_output_mode:
        identity["structured_output"] = {
            "mode": structured_output_mode,
            "provider_schema_hash": provider_schema_hash,
            "transport_version": transport_version,
            "requested_model_alias": requested_model_alias,
            "effective_request_model": effective_request_model,
        }
    raw = json.dumps(identity, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
