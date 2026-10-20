"""DeepSeek 语义模型客户端（OpenAI 兼容 API）。

- API Key 只从 settings 读取（settings 从环境变量加载）；
- 调用过程不打印任何 key/token/secret；
- 响应支持 JSON mode 结构化输出；
- 单案例调用量由 settings.semantic_case_max_calls 保护。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable
from typing import Any, Literal

import httpx

from app.core.config import get_settings
from app.services.semantic_llm.base import SemanticLLMClient, SemanticLLMError
from app.services.semantic_llm.cache import LLMCallCache
from app.services.semantic_llm.common import (
    audit_excerpt as _audit_excerpt,
    extract_json_object as _extract_json_object,
    response_error as _response_error,
    structured_input_hash as _input_hash,
    validate_response_payload as _validate_response_payload,
)

logger = logging.getLogger("semantic_llm.deepseek")


StructuredOutputMode = Literal["JSON_SCHEMA", "STRICT_TOOL", "JSON_OBJECT_FALLBACK"]
DEEPSEEK_JSON_SCHEMA_TRANSPORT_VERSION = "semantic_llm.deepseek.responses_json_schema.v2"
DEEPSEEK_TEXT_TRANSPORT_VERSION = "semantic_llm.deepseek.responses_text.v1"
DEEPSEEK_CHAT_JSON_TRANSPORT_VERSION = "semantic_llm.deepseek.chat_json_object.v1"
DERIVED_MODEL_CALL_IDENTITY_VERSION = "derived_model_call_identity.v1"
DERIVED_MODEL_CACHE_IDENTITY_VERSION = "derived_model_call_cache.v1"


def _provider_protocol_error(message: str, code: str) -> SemanticLLMError:
    error = SemanticLLMError(message)
    error.code = code
    return error


def _responses_output_candidate(
    data: dict[str, Any], *, expected_function_name: str,
) -> tuple[str, dict[str, Any] | None, str]:
    """Extract one unambiguous decision from a Responses API envelope."""
    output = data.get("output")
    if not isinstance(output, list) or "choices" in data:
        raise _provider_protocol_error(
            "Provider 响应 envelope 与冻结 Responses transport 不一致",
            "PROVIDER_TRANSPORT_IDENTITY_MISMATCH",
        )
    candidates: list[tuple[str, dict[str, Any]]] = []
    for item in output:
        if not isinstance(item, dict):
            raise _provider_protocol_error(
                "Responses output item 不是对象", "PROVIDER_OUTPUT_ITEM_INVALID",
            )
        item_type = item.get("type")
        if item_type == "reasoning":
            continue
        if item_type == "message":
            content = item.get("content")
            if not isinstance(content, list) or not content:
                raise _provider_protocol_error(
                    "Responses message 缺少 content", "PROVIDER_MESSAGE_CONTENT_INVALID",
                )
            text_parts: list[str] = []
            for part in content:
                if not isinstance(part, dict) or part.get("type") != "output_text" \
                        or not isinstance(part.get("text"), str):
                    raise _provider_protocol_error(
                        "Responses message 包含不支持的 content 类型",
                        "PROVIDER_MESSAGE_CONTENT_INVALID",
                    )
                text_parts.append(part["text"])
            candidates.append(("MESSAGE_OUTPUT_TEXT", {"text": "".join(text_parts)}))
            continue
        if item_type == "function_call":
            candidates.append(("FUNCTION_CALL", item))
            continue
        raise _provider_protocol_error(
            f"Responses output 包含不支持的类型: {item_type}",
            "PROVIDER_OUTPUT_ITEM_UNSUPPORTED",
        )
    if len(candidates) != 1:
        raise _provider_protocol_error(
            "Responses 响应必须包含且只能包含一个明确决策",
            "PROVIDER_DECISION_CANDIDATE_AMBIGUOUS",
        )
    output_kind, candidate = candidates[0]
    if output_kind == "MESSAGE_OUTPUT_TEXT":
        return str(candidate["text"]), None, output_kind
    if candidate.get("name") != expected_function_name:
        raise _provider_protocol_error(
            "Responses function_call 名称与冻结响应 Schema 不一致",
            "PROVIDER_FUNCTION_NAME_MISMATCH",
        )
    arguments = candidate.get("arguments")
    if not isinstance(arguments, str):
        raise _provider_protocol_error(
            "Responses function_call arguments 不是 JSON 字符串",
            "PROVIDER_FUNCTION_ARGUMENTS_INVALID",
        )
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError as exc:
        raise _provider_protocol_error(
            "Responses function_call arguments 不是完整 JSON",
            "PROVIDER_FUNCTION_ARGUMENTS_INVALID",
        ) from exc
    if not isinstance(parsed, dict):
        raise _provider_protocol_error(
            "Responses function_call arguments 顶层必须为对象",
            "PROVIDER_FUNCTION_ARGUMENTS_INVALID",
        )
    return arguments, parsed, output_kind


def _responses_envelope_observation(data: dict[str, Any]) -> dict[str, Any]:
    """Extract auditable envelope metadata without treating partial output as success.

    Visible ``output_text`` is retained for the restricted audit archive. Reasoning
    text remains only inside the raw restricted envelope and is never copied into
    product-facing events or result objects.
    """
    output = data.get("output")
    summaries: list[dict[str, Any]] = []
    visible_parts: list[str] = []
    if isinstance(output, list):
        for index, item in enumerate(output):
            if not isinstance(item, dict):
                summaries.append({"index": index, "type": "INVALID", "status": "UNKNOWN"})
                continue
            item_type = str(item.get("type") or "UNKNOWN")
            summary = {
                "index": index,
                "type": item_type,
                "status": str(item.get("status") or "UNKNOWN"),
            }
            if item_type == "message" and isinstance(item.get("content"), list):
                output_text_parts = [
                    part.get("text") for part in item["content"]
                    if isinstance(part, dict) and part.get("type") == "output_text"
                    and isinstance(part.get("text"), str)
                ]
                visible_parts.extend(output_text_parts)
                summary["output_text_parts"] = len(output_text_parts)
                summary["output_text_characters"] = sum(len(part) for part in output_text_parts)
            summaries.append(summary)
    incomplete = data.get("incomplete_details")
    incomplete_reason = (
        str(incomplete.get("reason"))
        if isinstance(incomplete, dict) and incomplete.get("reason") is not None else "UNKNOWN"
    )
    provider_error = data.get("error")
    provider_error_state = (
        "UNKNOWN" if "error" not in data else
        "NULL" if provider_error is None else
        "PRESENT" if isinstance(provider_error, dict) else "INVALID"
    )
    return {
        "provider_response_id": data.get("id") if isinstance(data.get("id"), str) else None,
        "provider_response_status": str(data.get("status") or "UNKNOWN"),
        "incomplete_reason": incomplete_reason,
        "provider_error": provider_error if isinstance(provider_error, dict) else None,
        "provider_error_state": provider_error_state,
        "provider_output_summary": summaries,
        "partial_output_text": "".join(visible_parts),
    }


def _responses_usage_observation(data: dict[str, Any]) -> dict[str, Any]:
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return {}
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
    total_tokens = usage.get("total_tokens")
    normalized: dict[str, Any] = {}
    if isinstance(input_tokens, int) and not isinstance(input_tokens, bool) and input_tokens >= 0:
        normalized["input_tokens"] = input_tokens
    if isinstance(output_tokens, int) and not isinstance(output_tokens, bool) and output_tokens >= 0:
        normalized["output_tokens"] = output_tokens
    if isinstance(total_tokens, int) and not isinstance(total_tokens, bool) and total_tokens >= 0:
        normalized["total_tokens"] = total_tokens
    details = usage.get("output_tokens_details")
    if isinstance(details, dict):
        reasoning_tokens = details.get("reasoning_tokens")
        if isinstance(reasoning_tokens, int) and not isinstance(reasoning_tokens, bool) \
                and reasoning_tokens >= 0:
            normalized["output_tokens_details"] = {"reasoning_tokens": reasoning_tokens}
    return normalized


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def derive_deepseek_call_contract(
    *, system_prompt: str, response_schema: type, prompt_version: str,
    schema_version: str, requested_model_alias: str, thinking_mode: str | None,
    max_tokens: int, structured_output_mode: StructuredOutputMode | None,
    transport_version: str = "", endpoint_base_url: str | None = None,
    allow_json_wrapper_recovery: bool = False,
    recovery_contract_version: str = "",
    provider_schema_strict: bool = False,
) -> dict[str, Any]:
    """Return the complete immutable identity of one derived model call kind."""
    mode = structured_output_mode or "JSON_OBJECT_FALLBACK"
    effective_model = resolve_deepseek_request_model(requested_model_alias, structured_output_mode)
    effective_max_tokens = max(max_tokens, 2048)
    if mode == "JSON_SCHEMA":
        if not hasattr(response_schema, "model_json_schema"):
            raise ValueError("JSON_SCHEMA 模式要求 Pydantic typed response model")
        schema_hash = _canonical_hash(response_schema.model_json_schema(mode="validation"))
        transport = transport_version or DEEPSEEK_JSON_SCHEMA_TRANSPORT_VERSION
        endpoint_path = "/responses"
        transport_kind = "RESPONSES_JSON_SCHEMA"
    else:
        schema_hash = ""
        transport = transport_version or DEEPSEEK_CHAT_JSON_TRANSPORT_VERSION
        endpoint_path = "/chat/completions"
        transport_kind = "CHAT_COMPLETIONS_JSON_OBJECT"
    base = (endpoint_base_url or get_settings().deepseek_base_url).rstrip("/")
    body = {
        "contract_version": DERIVED_MODEL_CALL_IDENTITY_VERSION,
        "provider": "deepseek",
        "endpoint": f"{base}{endpoint_path}",
        "endpoint_path": endpoint_path,
        "requested_model_alias": requested_model_alias,
        "effective_request_model": effective_model,
        "transport_kind": transport_kind,
        "transport_version": transport,
        "prompt_version": prompt_version,
        "prompt_hash": hashlib.sha256(system_prompt.encode("utf-8")).hexdigest(),
        "schema_version": schema_version,
        "provider_schema_hash": schema_hash,
        "generation_parameters": {
            "temperature": 0.0,
            "max_output_tokens": effective_max_tokens,
            "thinking_mode": thinking_mode,
            **({"provider_schema_strict": True} if provider_schema_strict else {}),
            **({"json_wrapper_recovery": "EXTRACT_THEN_STRICT_VALIDATE"}
               if allow_json_wrapper_recovery else {}),
            **({"non_json_recovery_contract": recovery_contract_version}
               if recovery_contract_version else {}),
        },
        "input_scope_contract": "canonical_user_payload_sha256.v1",
        "cache_identity_version": DERIVED_MODEL_CACHE_IDENTITY_VERSION,
    }
    return {**body, "call_identity_hash": _canonical_hash(body)}


def resolve_deepseek_request_model(
    requested_model_alias: str,
    structured_output_mode: StructuredOutputMode | None,
) -> str:
    """Resolve legacy Flash aliases only for the Responses API transport."""
    if structured_output_mode == "JSON_SCHEMA" and requested_model_alias in {
        "deepseek-v4-flash",
        "deepseek-v4-flash-vision-exp",
    }:
        return "deepseek-flash"
    return requested_model_alias


class DeepSeekClient(SemanticLLMClient):
    provider = "deepseek"

    def __init__(
        self,
        *,
        thinking_mode: str | None = None,
        max_attempts: int = 3,
        cache_only: bool = False,
        response_audit_sink: Callable[[dict[str, Any]], None] | None = None,
        request_guard: Callable[[dict[str, Any]], None] | None = None,
        frozen_call_contracts: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        if thinking_mode not in {None, "enabled", "disabled"}:
            raise ValueError("thinking_mode 必须是 enabled、disabled 或 None")
        if max_attempts < 1:
            raise ValueError("max_attempts 必须至少为 1")
        self.settings = get_settings()
        self.thinking_mode = thinking_mode
        self.max_attempts = max_attempts
        self.cache_only = cache_only
        self.response_audit_sink = response_audit_sink
        self.request_guard = request_guard
        self.frozen_call_contracts = frozen_call_contracts
        self._calls = 0
        self._tokens = 0
        self._external_calls = 0
        self._external_tokens = 0
        self._external_input_tokens = 0
        self._external_output_tokens = 0

    def _record_response_audit(self, payload: dict[str, Any]) -> None:
        if self.response_audit_sink is not None:
            self.response_audit_sink(payload)

    @property
    def api_key(self) -> str:
        key = self.settings.deepseek_api_key
        if not key:
            raise SemanticLLMError(
                "DEEPSEEK_API_KEY 未配置。请在 backend/.env 设置（代码与日志禁止输出该值）。"
            )
        return key

    def _assert_budget(self, db=None) -> None:
        if self._calls >= self.settings.semantic_case_max_calls:
            raise SemanticLLMError(
                f"语义调用次数达到上限 {self.settings.semantic_case_max_calls}，已停止。"
            )
        if self._tokens >= self.settings.semantic_case_max_tokens:
            raise SemanticLLMError(
                f"语义 token 达到上限 {self.settings.semantic_case_max_tokens}，已停止。"
            )

    def structured_generate_sync(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        response_schema: type,
        model: str | None = None,
        prompt_version: str,
        schema_version: str = "v1",
        max_tokens: int = 4096,
        db=None,
        strict_json: bool = False,
        response_validator: Callable[[Any], dict[str, Any]] | None = None,
        structured_output_mode: StructuredOutputMode | None = None,
        transport_version: str = "",
        allow_json_wrapper_recovery: bool = False,
        non_json_response_recovery: Callable[[str], dict[str, Any] | None] | None = None,
        recovery_contract_version: str = "",
        provider_schema_strict: bool = False,
    ) -> dict[str, Any]:
        self._assert_budget(db)

        requested_model_alias = model or self.settings.deepseek_model
        effective_request_model = resolve_deepseek_request_model(
            requested_model_alias,
            structured_output_mode,
        )
        # v4-flash 是推理模型：reasoning 会消耗 token 预算，
        # 实际可用 max_tokens 需给足（默认 4096，调用方可覆盖）。
        effective_max_tokens = max_tokens if max_tokens >= 2048 else 2048
        provider_schema: dict[str, Any] | None = None
        provider_schema_hash = ""
        if structured_output_mode == "JSON_SCHEMA":
            if provider_schema_strict and not strict_json:
                raise ValueError("provider_schema_strict 要求同时启用 strict_json")
            if not hasattr(response_schema, "model_json_schema"):
                raise ValueError("JSON_SCHEMA 模式要求 Pydantic typed response model")
            provider_schema = response_schema.model_json_schema(mode="validation")
            provider_schema_hash = hashlib.sha256(
                json.dumps(
                    provider_schema,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            if not transport_version:
                transport_version = DEEPSEEK_JSON_SCHEMA_TRANSPORT_VERSION
        elif structured_output_mode == "STRICT_TOOL":
            raise ValueError("STRICT_TOOL 尚未接入；不得静默降级 transport")
        call_contract = derive_deepseek_call_contract(
            system_prompt=system_prompt, response_schema=response_schema,
            prompt_version=prompt_version, schema_version=schema_version,
            requested_model_alias=requested_model_alias, thinking_mode=self.thinking_mode,
            max_tokens=effective_max_tokens, structured_output_mode=structured_output_mode,
            transport_version=transport_version, endpoint_base_url=self.settings.deepseek_base_url,
            allow_json_wrapper_recovery=allow_json_wrapper_recovery,
            recovery_contract_version=recovery_contract_version,
            provider_schema_strict=provider_schema_strict,
        )
        if self.frozen_call_contracts is not None:
            frozen = self.frozen_call_contracts.get(prompt_version)
            if frozen is None:
                error = SemanticLLMError("冻结任务没有登记当前派生模型调用身份")
                error.code = "DERIVED_MODEL_CALL_IDENTITY_LEGACY_UNBOUND"
                raise error
            if frozen != call_contract:
                error = SemanticLLMError("当前派生模型调用身份与冻结任务不一致")
                error.code = "DERIVED_MODEL_CALL_IDENTITY_DRIFT"
                raise error
        input_scope_hash = _canonical_hash(user_payload)
        input_key = _canonical_hash({
            "cache_identity_version": DERIVED_MODEL_CACHE_IDENTITY_VERSION,
            "call_identity_hash": call_contract["call_identity_hash"],
            "input_scope_hash": input_scope_hash,
        })
        request_identity = {
            "provider": self.provider,
            "requested_model_alias": requested_model_alias,
            "effective_request_model": effective_request_model,
            "prompt_version": prompt_version,
            "schema_version": schema_version,
            "input_hash": input_key,
            "structured_output_mode": structured_output_mode or "JSON_OBJECT_FALLBACK",
            "provider_schema_hash": provider_schema_hash,
            "transport_version": call_contract["transport_version"],
            "derived_call_identity_contract_version": DERIVED_MODEL_CALL_IDENTITY_VERSION,
            "call_identity_hash": call_contract["call_identity_hash"],
            "endpoint": call_contract["endpoint"],
            "endpoint_path": call_contract["endpoint_path"],
            "transport_kind": call_contract["transport_kind"],
            "prompt_hash": call_contract["prompt_hash"],
            "generation_parameters": call_contract["generation_parameters"],
            "generation_parameters_hash": _canonical_hash(call_contract["generation_parameters"]),
            "input_scope_contract": call_contract["input_scope_contract"],
            "input_scope_hash": input_scope_hash,
            "cache_identity_version": DERIVED_MODEL_CACHE_IDENTITY_VERSION,
        }

        # cache hit
        if db is not None:
            cached = LLMCallCache.get(
                db,
                provider=self.provider,
                model=effective_request_model,
                prompt_version=prompt_version,
                schema_version=schema_version,
                input_hash=input_key,
            )
            if cached is not None:
                cached_content = json.dumps(cached["parsed_payload"], ensure_ascii=False, sort_keys=True)
                try:
                    parsed = _validate_response_payload(
                        cached["parsed_payload"],
                        response_validator,
                        source="LLM_CALL_CACHE",
                        content=cached_content,
                        raw_response_hash=str(cached.get("raw_response_hash") or ""),
                    )
                except Exception as exc:
                    self._record_response_audit({
                        "request_identity": request_identity,
                        "response_source": "LLM_CALL_CACHE",
                        "validation_status": "REJECTED",
                        "structured_response": cached["parsed_payload"],
                        "raw_response_hash": str(cached.get("raw_response_hash") or ""),
                        "token_usage": int(cached.get("token_usage") or 0),
                        "rejection_code": str(getattr(exc, "code", "CACHE_REJECTED_BY_VALIDATION")),
                        "rejection_reason": str(exc),
                    })
                    raise
                self._record_response_audit({
                    "request_identity": request_identity,
                    "response_source": "LLM_CALL_CACHE",
                    "validation_status": "ACCEPTED",
                    "structured_response": cached["parsed_payload"],
                    "accepted_response": parsed,
                    "raw_response_hash": str(cached.get("raw_response_hash") or ""),
                    "token_usage": int(cached.get("token_usage") or 0),
                })
                self._calls += 1
                self._tokens += cached.get("token_usage", 0)
                return parsed

        if self.cache_only:
            raise _response_error(
                "当前语义测量仅允许兼容缓存，但没有可消费缓存",
                code="CACHE_MISS",
                source="LLM_CALL_CACHE",
                content="",
            )

        if structured_output_mode == "JSON_SCHEMA":
            url = f"{self.settings.deepseek_base_url.rstrip('/')}/responses"
            body = {
                "model": effective_request_model,
                "instructions": system_prompt,
                "input": json.dumps(user_payload, ensure_ascii=False),
                "temperature": 0.0,
                "max_output_tokens": effective_max_tokens,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": re.sub(r"[^a-zA-Z0-9_-]", "_", response_schema.__name__),
                        "schema": provider_schema,
                    }
                },
            }
            if provider_schema_strict:
                body["text"]["format"]["strict"] = True
            if self.thinking_mode:
                body["reasoning"] = {
                    "effort": "none" if self.thinking_mode == "disabled" else "high"
                }
        else:
            url = f"{self.settings.deepseek_base_url.rstrip('/')}/chat/completions"
            body = {
                "model": effective_request_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                ],
                "temperature": 0.0,
                "max_tokens": effective_max_tokens,
                "response_format": {"type": "json_object"},
            }
            if self.thinking_mode:
                body["thinking"] = {"type": self.thinking_mode}
        headers = {
            "Authorization": f"Bearer {self.api_key}",  # key 只出现在内存 header，不落日志
            "Content-Type": "application/json",
        }
        # 有限重试（最多 3 次，指数退避）——覆盖网络断连与推理模型偶发的非 JSON 输出；不无限 retry
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            if self.request_guard is not None:
                # Admission/cache recovery precede authorization. Reserve the complete
                # request before network I/O; headers and credentials never enter audit.
                try:
                    self.request_guard({**request_identity,
                        "provider_payload_hash": hashlib.sha256(json.dumps(body, ensure_ascii=False,
                            sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                        "input_token_upper_bound": len(json.dumps(body, ensure_ascii=False).encode("utf-8")) + 4096,
                        "max_output_tokens": effective_max_tokens, "attempt": attempt + 1})
                except SemanticLLMError as exc:
                    exc.request_sent = False
                    raise
            response_data: dict[str, Any] | None = None
            response_text = ""
            content = ""
            finish_reason = "unknown"
            usage: dict[str, Any] = {}
            provider_candidate: dict[str, Any] | None = None
            provider_output_kind = ""
            audit_recorded = False
            try:
                self._external_calls += 1
                with httpx.Client(timeout=self.settings.deepseek_timeout_seconds) as client:
                    resp = client.post(url, headers=headers, json=body)
                response_text = resp.text
                if resp.status_code != 200:
                    error = SemanticLLMError(
                        f"DeepSeek HTTP {resp.status_code} (model={effective_request_model})"
                    )
                    error.code = "PROVIDER_HTTP_ERROR"
                    error.http_status = resp.status_code
                    error.provider_error_category = "HTTP_ERROR"
                    try:
                        provider_error = resp.json().get("error") or {}
                        if isinstance(provider_error, dict):
                            error.provider_error_category = str(
                                provider_error.get("code") or provider_error.get("type") or "HTTP_ERROR"
                            )[:120]
                    except Exception:
                        pass
                    raise error
                data = resp.json()
                response_data = data
                response_model = str(data.get("model") or "")
                if not response_model:
                    error = SemanticLLMError("DeepSeek 未返回 response.model，不能推断 effective model")
                    error.code = "PROVIDER_MODEL_IDENTITY_MISSING"
                    raise error
                if response_model != effective_request_model:
                    error = SemanticLLMError("DeepSeek response.model 与冻结 effective request model 不一致")
                    error.code = "PROVIDER_MODEL_IDENTITY_MISMATCH"
                    raise error
                usage = data.get("usage") or {}
                prompt_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
                completion_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
                total_tokens = int(usage.get("total_tokens") or prompt_tokens + completion_tokens)
                self._external_tokens += total_tokens
                self._external_input_tokens += prompt_tokens
                self._external_output_tokens += completion_tokens
                if structured_output_mode == "JSON_SCHEMA":
                    finish_reason = str(data.get("status") or "unknown")
                    content, provider_candidate, provider_output_kind = _responses_output_candidate(
                        data,
                        expected_function_name=re.sub(
                            r"[^a-zA-Z0-9_-]", "_", response_schema.__name__,
                        ),
                    )
                    choice: dict[str, Any] = {}
                else:
                    if not isinstance(data.get("choices"), list) or "output" in data:
                        error = SemanticLLMError("Provider 响应 envelope 与冻结 Chat transport 不一致")
                        error.code = "PROVIDER_TRANSPORT_IDENTITY_MISMATCH"
                        raise error
                    choice = (data.get("choices") or [{}])[0]
                    finish_reason = str(choice.get("finish_reason") or "unknown")
                    content = choice.get("message", {}).get("content", "")
                if strict_json and finish_reason == "length":
                    raise _response_error(
                        "模型响应因长度限制被截断",
                        source="EXTERNAL_LLM",
                        content=content,
                        finish_reason=finish_reason,
                    )
                if (
                    strict_json
                    and structured_output_mode == "JSON_SCHEMA"
                    and finish_reason != "completed"
                ):
                    raise _response_error(
                        "模型响应未完整完成",
                        source="EXTERNAL_LLM",
                        content=content,
                        finish_reason=finish_reason,
                    )
                if strict_json and not content.strip():
                    raise _response_error(
                        "模型返回空白响应",
                        source="EXTERNAL_LLM",
                        content=content,
                        finish_reason=finish_reason,
                    )
                if provider_candidate is not None:
                    parsed = provider_candidate
                else:
                    try:
                        parsed = json.loads(content)
                    except json.JSONDecodeError:
                        # A protocol-specific adapter receives the complete text.
                        # Agent callers disable generic nested-object extraction,
                        # which could confuse tool arguments with the decision.
                        parsed = (non_json_response_recovery(content)
                                  if non_json_response_recovery is not None else None)
                        if parsed is None and allow_json_wrapper_recovery:
                            parsed = _extract_json_object(content)
                    if parsed is None:
                        if strict_json:
                            raise _response_error(
                                "模型响应不是完整 JSON 且无法恢复",
                                source="EXTERNAL_LLM", content=content,
                                finish_reason=finish_reason,
                            )
                        message = choice.get("message") or {}
                        reasoning = message.get("reasoning_content") or ""
                        raise SemanticLLMError(
                            "DeepSeek 返回非 JSON 内容且无法提取"
                            f" (finish_reason={choice.get('finish_reason') or 'unknown'},"
                            f" content_length={len(content)}, reasoning_length={len(reasoning)},"
                            f" total_tokens={total_tokens})"
                        )
                parsed = _validate_response_payload(
                    parsed,
                    response_validator,
                    source="EXTERNAL_LLM",
                    content=content,
                    finish_reason=finish_reason,
                )
                self._record_response_audit({
                    "request_identity": {
                        **request_identity,
                        "attempt": attempt + 1,
                        "max_attempts": self.max_attempts,
                    },
                    "response_source": "EXTERNAL_LLM",
                    "validation_status": "ACCEPTED",
                    "finish_reason": finish_reason,
                    "response_model": response_model,
                    "response_transport_kind": call_contract["transport_kind"],
                    "response_transport_version": call_contract["transport_version"],
                    "provider_output_kind": provider_output_kind,
                    "raw_provider_response": response_data,
                    "structured_response": parsed,
                    "raw_response_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    "token_usage": {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": total_tokens,
                    },
                })
                audit_recorded = True
                break  # 成功拿到可解析结果
            except SemanticLLMError as e:
                if not audit_recorded:
                    audited_response_text = content or (
                        json.dumps(response_data, ensure_ascii=False, sort_keys=True)
                        if response_data is not None else response_text
                    )
                    self._record_response_audit({
                        "request_identity": {
                            **request_identity,
                            "attempt": attempt + 1,
                            "max_attempts": self.max_attempts,
                        },
                        "response_source": "EXTERNAL_LLM",
                        "validation_status": "REJECTED",
                        "finish_reason": finish_reason,
                        "response_model": response_model if response_data is not None else "",
                        "provider_output_kind": provider_output_kind,
                        "raw_provider_response": response_data,
                        "raw_http_response": response_text if response_data is None else None,
                        "http_status": getattr(e, "http_status", None),
                        "provider_error_category": getattr(e, "provider_error_category", None),
                        "structured_response_text": content,
                        "response_excerpt": _audit_excerpt(content),
                        "response_length": len(audited_response_text),
                        "raw_response_hash": hashlib.sha256(
                            audited_response_text.encode("utf-8")
                        ).hexdigest(),
                        "token_usage": usage,
                        "rejection_code": str(getattr(e, "code", "SEMANTIC_LLM_ERROR")),
                        "rejection_reason": str(e),
                    })
                last_error = e
                if attempt < self.max_attempts - 1:
                    import time
                    time.sleep(1.5 * (attempt + 1))
            except httpx.HTTPError as e:
                self._record_response_audit({
                    "request_identity": {
                        **request_identity,
                        "attempt": attempt + 1,
                        "max_attempts": self.max_attempts,
                    },
                    "response_source": "EXTERNAL_LLM",
                    "validation_status": "TRANSPORT_FAILED",
                    "raw_provider_response": None,
                    "raw_response_hash": hashlib.sha256(b"").hexdigest(),
                    "token_usage": {},
                    "rejection_code": e.__class__.__name__,
                    "rejection_reason": str(e),
                })
                last_error = e
                if attempt < self.max_attempts - 1:
                    import time
                    time.sleep(1.5 * (attempt + 1))
        else:
            if isinstance(last_error, SemanticLLMError):
                raise last_error
            raise SemanticLLMError(
                f"DeepSeek 网络错误（尝试{self.max_attempts}次后）: "
                f"{last_error.__class__.__name__ if last_error else 'unknown'}"
            ) from last_error

        self._calls += 1
        self._tokens += total_tokens

        if db is not None:
            LLMCallCache.put(
                db,
                provider=self.provider,
                model=effective_request_model,
                prompt_version=prompt_version,
                schema_version=schema_version,
                input_hash=input_key,
                raw_response_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                parsed_payload=parsed,
                token_usage=total_tokens,
            )
        return parsed

    def text_generate_sync(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        model: str | None = None,
        prompt_version: str,
        schema_version: str = "plain-text.v1",
        max_tokens: int = 8192,
        db=None,
        transport_version: str = DEEPSEEK_TEXT_TRANSPORT_VERSION,
    ) -> str:
        """Generate one complete Responses API text artifact without JSON mode.

        This transport exists for the isolated evidence-pack experiment. It
        deliberately has no parser recovery and callers set max_attempts=1.
        """
        self._assert_budget(db)
        requested_model_alias = model or self.settings.deepseek_model
        effective_request_model = (
            "deepseek-flash" if requested_model_alias in {
                "deepseek-v4-flash", "deepseek-v4-flash-vision-exp",
            } else requested_model_alias
        )
        effective_max_tokens = max(max_tokens, 2048)
        endpoint = f"{self.settings.deepseek_base_url.rstrip('/')}/responses"
        prompt_hash = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()
        contract = {
            "contract_version": DERIVED_MODEL_CALL_IDENTITY_VERSION,
            "provider": self.provider,
            "endpoint": endpoint,
            "endpoint_path": "/responses",
            "requested_model_alias": requested_model_alias,
            "effective_request_model": effective_request_model,
            "transport_kind": "RESPONSES_TEXT",
            "transport_version": transport_version,
            "prompt_version": prompt_version,
            "prompt_hash": prompt_hash,
            "schema_version": schema_version,
            "provider_schema_hash": "",
            "generation_parameters": {
                "temperature": 0.0, "max_output_tokens": effective_max_tokens,
                "thinking_mode": self.thinking_mode,
            },
            "input_scope_contract": "canonical_user_payload_sha256.v1",
            "cache_identity_version": DERIVED_MODEL_CACHE_IDENTITY_VERSION,
        }
        contract["call_identity_hash"] = _canonical_hash(contract)
        input_scope_hash = _canonical_hash(user_payload)
        input_key = _canonical_hash({
            "cache_identity_version": DERIVED_MODEL_CACHE_IDENTITY_VERSION,
            "call_identity_hash": contract["call_identity_hash"],
            "input_scope_hash": input_scope_hash,
        })
        identity = {
            "provider": self.provider,
            "requested_model_alias": requested_model_alias,
            "effective_request_model": effective_request_model,
            "prompt_version": prompt_version,
            "schema_version": schema_version,
            "input_hash": input_key,
            "structured_output_mode": "TEXT",
            "provider_schema_hash": "",
            "transport_version": transport_version,
            "derived_call_identity_contract_version": DERIVED_MODEL_CALL_IDENTITY_VERSION,
            "call_identity_hash": contract["call_identity_hash"],
            "endpoint": endpoint,
            "endpoint_path": "/responses",
            "transport_kind": "RESPONSES_TEXT",
            "prompt_hash": prompt_hash,
            "generation_parameters": contract["generation_parameters"],
            "generation_parameters_hash": _canonical_hash(contract["generation_parameters"]),
            "input_scope_contract": contract["input_scope_contract"],
            "input_scope_hash": input_scope_hash,
            "cache_identity_version": DERIVED_MODEL_CACHE_IDENTITY_VERSION,
        }
        if db is not None:
            cached = LLMCallCache.get(
                db, provider=self.provider, model=effective_request_model,
                prompt_version=prompt_version, schema_version=schema_version,
                input_hash=input_key,
            )
            if cached is not None:
                parsed = cached.get("parsed_payload") or {}
                markdown = parsed.get("markdown") if isinstance(parsed, dict) else None
                if not isinstance(markdown, str) or not markdown.strip():
                    raise _response_error(
                        "文本缓存不是完整 Markdown", code="CACHE_REJECTED_BY_VALIDATION",
                        source="LLM_CALL_CACHE", content="",
                    )
                self._record_response_audit({
                    "request_identity": identity, "response_source": "LLM_CALL_CACHE",
                    "validation_status": "ACCEPTED", "structured_response": parsed,
                    "raw_response_hash": str(cached.get("raw_response_hash") or ""),
                    "token_usage": int(cached.get("token_usage") or 0),
                })
                self._calls += 1
                self._tokens += int(cached.get("token_usage") or 0)
                return markdown
        if self.cache_only:
            raise _response_error(
                "当前证据包实验仅允许兼容缓存，但没有可消费缓存",
                code="CACHE_MISS", source="LLM_CALL_CACHE", content="",
            )

        body = {
            "model": effective_request_model,
            "instructions": system_prompt,
            "input": json.dumps(user_payload, ensure_ascii=False),
            "temperature": 0.0,
            "max_output_tokens": effective_max_tokens,
        }
        if self.thinking_mode:
            body["reasoning"] = {
                "effort": "none" if self.thinking_mode == "disabled" else "high"
            }
        if self.request_guard is not None:
            self.request_guard({
                **identity,
                "provider_payload_hash": _canonical_hash(body),
                "input_token_upper_bound": len(json.dumps(body, ensure_ascii=False).encode("utf-8")) + 4096,
                "max_output_tokens": effective_max_tokens,
                "attempt": 1,
            })
        response_data: dict[str, Any] | None = None
        response_text = ""
        content = ""
        usage: dict[str, Any] = {}
        finish_reason = "unknown"
        envelope_observation: dict[str, Any] = {}
        try:
            self._external_calls += 1
            with httpx.Client(timeout=self.settings.deepseek_timeout_seconds) as client:
                response = client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=body,
                )
            response_text = response.text
            if response.status_code != 200:
                error = SemanticLLMError(
                    f"DeepSeek HTTP {response.status_code} (model={effective_request_model})"
                )
                error.code = "PROVIDER_HTTP_ERROR"
                error.http_status = response.status_code
                error.provider_error_category = "HTTP_ERROR"
                try:
                    provider_error = response.json().get("error") or {}
                    if isinstance(provider_error, dict):
                        error.provider_error_category = str(
                            provider_error.get("code") or provider_error.get("type") or "HTTP_ERROR"
                        )[:120]
                except Exception:
                    pass
                raise error
            try:
                parsed_response = response.json()
            except Exception as parse_error:
                error = SemanticLLMError("DeepSeek 200 响应不是合法 JSON envelope")
                error.code = "PROVIDER_RESPONSE_JSON_INVALID"
                error.http_status = response.status_code
                raise error from parse_error
            if not isinstance(parsed_response, dict):
                error = SemanticLLMError("DeepSeek 200 响应不是对象 envelope")
                error.code = "PROVIDER_RESPONSE_ENVELOPE_INVALID"
                error.http_status = response.status_code
                raise error
            response_data = parsed_response
            envelope_observation = _responses_envelope_observation(response_data)
            usage = _responses_usage_observation(response_data)
            content = str(envelope_observation.get("partial_output_text") or "")
            response_model = str(response_data.get("model") or "")
            if response_model != effective_request_model:
                raise _provider_protocol_error(
                    "DeepSeek response.model 与冻结 effective request model 不一致",
                    "PROVIDER_MODEL_IDENTITY_MISMATCH",
                )
            finish_reason = str(response_data.get("status") or "unknown")
            if finish_reason != "completed":
                raise _response_error(
                    "模型文本响应未完整完成", code="PROVIDER_INCOMPLETE",
                    source="EXTERNAL_LLM", content=content, finish_reason=finish_reason,
                )
            content, candidate, output_kind = _responses_output_candidate(
                response_data, expected_function_name="EvidencePackMarkdown",
            )
            if candidate is not None or output_kind != "MESSAGE_OUTPUT_TEXT" or not content.strip():
                raise _provider_protocol_error(
                    "证据包生成必须返回唯一非空 output_text",
                    "PROVIDER_TEXT_OUTPUT_INVALID",
                )
            raw_input = usage.get("input_tokens", usage.get("prompt_tokens"))
            raw_output = usage.get("output_tokens", usage.get("completion_tokens"))
            raw_total = usage.get("total_tokens")
            if not all(isinstance(value, int) and not isinstance(value, bool) and value >= 0
                       for value in (raw_input, raw_output, raw_total)):
                raise _provider_protocol_error("DeepSeek usage 缺失", "PROVIDER_USAGE_INCOMPLETE")
            input_tokens, output_tokens, total_tokens = raw_input, raw_output, raw_total
            if total_tokens < input_tokens + output_tokens:
                raise _provider_protocol_error("DeepSeek usage 非法", "PROVIDER_USAGE_INVALID")
            self._external_tokens += total_tokens
            self._external_input_tokens += input_tokens
            self._external_output_tokens += output_tokens
            self._record_response_audit({
                "request_identity": identity, "response_source": "EXTERNAL_LLM",
                "validation_status": "ACCEPTED", "finish_reason": finish_reason,
                "response_model": response_model, "provider_output_kind": output_kind,
                "raw_provider_response": response_data,
                **envelope_observation,
                "raw_response_hash": hashlib.sha256(
                    json.dumps(response_data, ensure_ascii=False, sort_keys=True).encode("utf-8")
                ).hexdigest(),
                "token_usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                                "total_tokens": total_tokens,
                                **({"output_tokens_details": usage["output_tokens_details"]}
                                   if "output_tokens_details" in usage else {})},
            })
        except SemanticLLMError as error:
            audited = (json.dumps(response_data, ensure_ascii=False, sort_keys=True)
                       if response_data is not None else response_text)
            self._record_response_audit({
                "request_identity": identity, "response_source": "EXTERNAL_LLM",
                "validation_status": "REJECTED", "finish_reason": finish_reason,
                "response_model": str((response_data or {}).get("model") or ""),
                "raw_provider_response": response_data,
                "raw_http_response": response_text if response_data is None else None,
                "structured_response_text": content,
                "response_excerpt": _audit_excerpt(content),
                "response_length": len(audited),
                "raw_response_hash": hashlib.sha256(audited.encode("utf-8")).hexdigest(),
                "token_usage": usage,
                **envelope_observation,
                "rejection_code": str(getattr(error, "code", "SEMANTIC_LLM_ERROR")),
                "rejection_reason": str(error),
                "http_status": getattr(error, "http_status", None),
                "provider_error_category": getattr(error, "provider_error_category", None),
            })
            raise
        except httpx.HTTPError as error:
            self._record_response_audit({
                "request_identity": identity, "response_source": "EXTERNAL_LLM",
                "validation_status": "TRANSPORT_FAILED", "raw_provider_response": None,
                "raw_response_hash": hashlib.sha256(b"").hexdigest(), "token_usage": {},
                "rejection_code": error.__class__.__name__, "rejection_reason": str(error),
            })
            raise SemanticLLMError(
                f"DeepSeek 网络错误（尝试1次后）: {error.__class__.__name__}"
            ) from error
        self._calls += 1
        self._tokens += total_tokens
        if db is not None:
            LLMCallCache.put(
                db, provider=self.provider, model=effective_request_model,
                prompt_version=prompt_version, schema_version=schema_version,
                input_hash=input_key,
                raw_response_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                parsed_payload={"markdown": content}, token_usage=total_tokens,
            )
        return content

    @property
    def call_count(self) -> int:
        return self._calls

    @property
    def token_count(self) -> int:
        return self._tokens

    @property
    def external_call_count(self) -> int:
        return self._external_calls

    @property
    def external_token_count(self) -> int:
        return self._external_tokens

    @property
    def external_input_token_count(self) -> int:
        return self._external_input_tokens

    @property
    def external_output_token_count(self) -> int:
        return self._external_output_tokens
