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
        input_key = _input_hash(
            system_prompt,
            user_payload,
            prompt_version,
            schema_version,
            self.thinking_mode,
            structured_output_mode,
            provider_schema_hash,
            transport_version,
            requested_model_alias,
            effective_request_model,
        )
        request_identity = {
            "provider": self.provider,
            "requested_model_alias": requested_model_alias,
            "effective_request_model": effective_request_model,
            "prompt_version": prompt_version,
            "schema_version": schema_version,
            "input_hash": input_key,
            "structured_output_mode": structured_output_mode or "JSON_OBJECT_FALLBACK",
            "provider_schema_hash": provider_schema_hash,
            "transport_version": transport_version,
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
            audit_recorded = False
            try:
                self._external_calls += 1
                with httpx.Client(timeout=self.settings.deepseek_timeout_seconds) as client:
                    resp = client.post(url, headers=headers, json=body)
                response_text = resp.text
                if resp.status_code != 200:
                    # 响应体是 API 错误详情（不含 key），截断后透传，便于调试
                    detail = resp.text[:300]
                    raise SemanticLLMError(
                        f"DeepSeek HTTP {resp.status_code} (model={effective_request_model}): {detail}"
                    )
                data = resp.json()
                response_data = data
                response_model = str(data.get("model") or "")
                if structured_output_mode == "JSON_SCHEMA":
                    finish_reason = str(data.get("status") or "unknown")
                    if not response_model:
                        error = SemanticLLMError("DeepSeek Responses API 未返回 response.model")
                        error.code = "PROVIDER_MODEL_IDENTITY_MISSING"
                        raise error
                    if response_model != effective_request_model:
                        error = SemanticLLMError(
                            "DeepSeek response.model 与冻结 effective request model 不一致"
                        )
                        error.code = "PROVIDER_MODEL_IDENTITY_MISMATCH"
                        raise error
                    content = "".join(
                        str(part.get("text") or "")
                        for item in data.get("output") or []
                        if item.get("type") == "message"
                        for part in item.get("content") or []
                        if part.get("type") == "output_text"
                    )
                    choice: dict[str, Any] = {}
                else:
                    choice = (data.get("choices") or [{}])[0]
                    finish_reason = str(choice.get("finish_reason") or "unknown")
                    content = choice.get("message", {}).get("content", "")
                usage = data.get("usage") or {}
                prompt_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
                completion_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
                total_tokens = int(usage.get("total_tokens") or prompt_tokens + completion_tokens)
                self._external_tokens += total_tokens
                self._external_input_tokens += prompt_tokens
                self._external_output_tokens += completion_tokens
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
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError:
                    if strict_json:
                        raise _response_error(
                            "模型响应不是完整 JSON",
                            source="EXTERNAL_LLM",
                            content=content,
                            finish_reason=finish_reason,
                        )
                    # 推理模型偶发在 JSON 前后附带文本，提取第一个完整 JSON 对象容错
                    parsed = _extract_json_object(content)
                    if parsed is None:
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
                    self._record_response_audit({
                        "request_identity": {
                            **request_identity,
                            "attempt": attempt + 1,
                            "max_attempts": self.max_attempts,
                        },
                        "response_source": "EXTERNAL_LLM",
                        "validation_status": "REJECTED",
                        "finish_reason": finish_reason,
                        "raw_provider_response": response_data,
                        "raw_http_response": response_text if response_data is None else None,
                        "structured_response_text": content,
                        "raw_response_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
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
