"""SiliconFlow Qwen client for the optional Model B critic role."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from typing import Any

import httpx

from app.core.config import get_settings
from app.services.semantic_llm.base import SemanticLLMClient, SemanticLLMError
from app.services.semantic_llm.cache import LLMCallCache
from app.services.semantic_llm.common import (
    response_error,
    structured_input_hash,
    validate_response_payload,
)


SILICONFLOW_JSON_SCHEMA_TRANSPORT_VERSION = "semantic_llm.siliconflow.chat_json_schema.v1"


class SiliconFlowClient(SemanticLLMClient):
    """Strict Chat Completions client; it never silently falls back from Schema."""

    provider = "siliconflow"

    def __init__(
        self,
        *,
        max_attempts: int = 1,
        cache_only: bool = False,
        response_audit_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts 必须至少为 1")
        self.settings = get_settings()
        self.max_attempts = max_attempts
        self.cache_only = cache_only
        self.response_audit_sink = response_audit_sink
        self._calls = 0
        self._tokens = 0
        self._external_calls = 0
        self._external_input_tokens = 0
        self._external_output_tokens = 0

    @property
    def api_key(self) -> str:
        key = self.settings.siliconflow_api_key
        if not key:
            raise SemanticLLMError(
                "SILICONFLOW_API_KEY 未配置。请在 backend/.env 设置，代码和日志不得保存该值。"
            )
        return key

    def _record_audit(self, payload: dict[str, Any]) -> None:
        if self.response_audit_sink is not None:
            self.response_audit_sink(payload)

    def _assert_budget(self) -> None:
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
        strict_json: bool = True,
        response_validator: Callable[[Any], dict[str, Any]] | None = None,
        structured_output_mode: str = "JSON_SCHEMA",
        transport_version: str = SILICONFLOW_JSON_SCHEMA_TRANSPORT_VERSION,
    ) -> dict[str, Any]:
        self._assert_budget()
        if structured_output_mode != "JSON_SCHEMA":
            raise ValueError("SiliconFlow Model B 只允许 JSON_SCHEMA，不得静默降级")
        if not strict_json:
            raise ValueError("SiliconFlow Model B 必须启用 strict_json")
        if not hasattr(response_schema, "model_json_schema") or not hasattr(response_schema, "model_validate"):
            raise ValueError("SiliconFlow JSON_SCHEMA 要求 Pydantic typed response model")

        requested_model = model or self.settings.siliconflow_model
        effective_model = requested_model
        provider_schema = response_schema.model_json_schema(mode="validation")
        provider_schema_hash = hashlib.sha256(
            json.dumps(provider_schema, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        input_hash = structured_input_hash(
            system_prompt,
            user_payload,
            prompt_version,
            schema_version,
            "disabled",
            structured_output_mode,
            provider_schema_hash,
            transport_version,
            requested_model,
            effective_model,
        )
        request_identity = {
            "provider": self.provider,
            "requested_model_alias": requested_model,
            "effective_request_model": effective_model,
            "prompt_version": prompt_version,
            "schema_version": schema_version,
            "input_hash": input_hash,
            "structured_output_mode": structured_output_mode,
            "provider_schema_hash": provider_schema_hash,
            "transport_version": transport_version,
        }

        def admit(payload: Any, *, source: str, content: str, finish_reason: str) -> dict[str, Any]:
            def validate(value: Any) -> dict[str, Any]:
                admitted = response_schema.model_validate(value).model_dump(mode="json")
                return response_validator(admitted) if response_validator else admitted

            return validate_response_payload(
                payload,
                validate,
                source=source,
                content=content,
                finish_reason=finish_reason,
            )

        if db is not None:
            cached = LLMCallCache.get(
                db,
                provider=self.provider,
                model=effective_model,
                prompt_version=prompt_version,
                schema_version=schema_version,
                input_hash=input_hash,
            )
            if cached is not None:
                content = json.dumps(cached["parsed_payload"], ensure_ascii=False, sort_keys=True)
                try:
                    parsed = admit(
                        cached["parsed_payload"],
                        source="LLM_CALL_CACHE",
                        content=content,
                        finish_reason="cached",
                    )
                except Exception as exc:
                    self._record_audit({
                        "request_identity": request_identity,
                        "response_source": "LLM_CALL_CACHE",
                        "validation_status": "REJECTED",
                        "structured_response": cached["parsed_payload"],
                        "raw_response_hash": str(cached.get("raw_response_hash") or ""),
                        "rejection_code": str(getattr(exc, "code", "CACHE_REJECTED_BY_VALIDATION")),
                        "rejection_reason": str(exc),
                    })
                    raise
                self._calls += 1
                self._tokens += int(cached.get("token_usage") or 0)
                self._record_audit({
                    "request_identity": request_identity,
                    "response_source": "LLM_CALL_CACHE",
                    "validation_status": "ACCEPTED",
                    "structured_response": parsed,
                    "raw_response_hash": str(cached.get("raw_response_hash") or ""),
                    "token_usage": int(cached.get("token_usage") or 0),
                })
                return parsed

        if self.cache_only:
            raise response_error(
                "Model B 仅允许兼容缓存，但没有可消费缓存",
                code="CACHE_MISS",
                source="LLM_CALL_CACHE",
                content="",
            )

        url = f"{self.settings.siliconflow_base_url.rstrip('/')}/chat/completions"
        body = {
            "model": effective_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            "temperature": 0.0,
            "max_tokens": max_tokens,
            "enable_thinking": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": re.sub(r"[^a-zA-Z0-9_-]", "_", response_schema.__name__),
                    "strict": True,
                    "schema": provider_schema,
                },
            },
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(self.max_attempts):
            response_data: dict[str, Any] | None = None
            response_text = ""
            content = ""
            finish_reason = "unknown"
            usage: dict[str, Any] = {}
            trace_id = ""
            try:
                self._external_calls += 1
                with httpx.Client(timeout=self.settings.siliconflow_timeout_seconds) as client:
                    response = client.post(url, headers=headers, json=body)
                response_text = response.text
                response_headers = getattr(response, "headers", {}) or {}
                trace_id = str(response_headers.get("x-siliconcloud-trace-id") or "")
                if response.status_code != 200:
                    error = SemanticLLMError(
                        f"SiliconFlow HTTP {response.status_code} (model={effective_model}): {response.text[:300]}"
                    )
                    error.code = "PROVIDER_HTTP_ERROR"
                    raise error
                response_data = response.json()
                response_model = str(response_data.get("model") or "")
                if not response_model:
                    error = SemanticLLMError("SiliconFlow 未返回 response.model")
                    error.code = "PROVIDER_MODEL_IDENTITY_MISSING"
                    raise error
                if response_model != effective_model:
                    error = SemanticLLMError("SiliconFlow response.model 与冻结模型不一致")
                    error.code = "PROVIDER_MODEL_IDENTITY_MISMATCH"
                    raise error
                choice = (response_data.get("choices") or [{}])[0]
                finish_reason = str(choice.get("finish_reason") or "unknown")
                content = str((choice.get("message") or {}).get("content") or "")
                usage = response_data.get("usage") or {}
                prompt_tokens = int(usage.get("prompt_tokens") or 0)
                completion_tokens = int(usage.get("completion_tokens") or 0)
                total_tokens = int(usage.get("total_tokens") or prompt_tokens + completion_tokens)
                self._external_input_tokens += prompt_tokens
                self._external_output_tokens += completion_tokens
                if finish_reason != "stop":
                    raise response_error(
                        "SiliconFlow 响应未完整结束",
                        code="FAILED_INCOMPLETE_RESPONSE",
                        source="EXTERNAL_LLM",
                        content=content,
                        finish_reason=finish_reason,
                    )
                if not content.strip():
                    raise response_error(
                        "SiliconFlow 返回空白响应",
                        source="EXTERNAL_LLM",
                        content=content,
                        finish_reason=finish_reason,
                    )
                try:
                    raw_payload = json.loads(content)
                except json.JSONDecodeError as exc:
                    raise response_error(
                        "SiliconFlow 响应不是完整 JSON",
                        source="EXTERNAL_LLM",
                        content=content,
                        finish_reason=finish_reason,
                    ) from exc
                parsed = admit(
                    raw_payload,
                    source="EXTERNAL_LLM",
                    content=content,
                    finish_reason=finish_reason,
                )
                self._record_audit({
                    "request_identity": {**request_identity, "attempt": attempt + 1, "max_attempts": self.max_attempts},
                    "response_source": "EXTERNAL_LLM",
                    "validation_status": "ACCEPTED",
                    "finish_reason": finish_reason,
                    "response_model": response_model,
                    "provider_trace_id": trace_id,
                    "raw_provider_response": response_data,
                    "structured_response": parsed,
                    "raw_response_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    "token_usage": {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": total_tokens,
                    },
                })
                break
            except (SemanticLLMError, httpx.HTTPError) as exc:
                self._record_audit({
                    "request_identity": {**request_identity, "attempt": attempt + 1, "max_attempts": self.max_attempts},
                    "response_source": "EXTERNAL_LLM",
                    "validation_status": "REJECTED",
                    "finish_reason": finish_reason,
                    "provider_trace_id": trace_id,
                    "raw_provider_response": response_data,
                    "raw_http_response": response_text if response_data is None else None,
                    "raw_response_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    "token_usage": usage,
                    "rejection_code": str(getattr(exc, "code", exc.__class__.__name__)),
                    "rejection_reason": str(exc),
                })
                last_error = exc
                if attempt < self.max_attempts - 1:
                    time.sleep(1.5 * (attempt + 1))
        else:
            if isinstance(last_error, SemanticLLMError):
                raise last_error
            raise SemanticLLMError(
                f"SiliconFlow 网络错误（尝试{self.max_attempts}次后）: "
                f"{last_error.__class__.__name__ if last_error else 'unknown'}"
            ) from last_error

        self._calls += 1
        self._tokens += total_tokens
        if db is not None:
            LLMCallCache.put(
                db,
                provider=self.provider,
                model=effective_model,
                prompt_version=prompt_version,
                schema_version=schema_version,
                input_hash=input_hash,
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
    def external_input_token_count(self) -> int:
        return self._external_input_tokens

    @property
    def external_output_token_count(self) -> int:
        return self._external_output_tokens

    @property
    def external_token_count(self) -> int:
        return self._external_input_tokens + self._external_output_tokens
