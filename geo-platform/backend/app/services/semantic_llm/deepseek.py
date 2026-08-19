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
from typing import Any

import httpx

from app.core.config import get_settings
from app.services.semantic_llm.base import SemanticLLMClient, SemanticLLMError
from app.services.semantic_llm.cache import LLMCallCache

logger = logging.getLogger("semantic_llm.deepseek")


def _extract_json_object(content: str) -> dict | None:
    """从文本中提取第一个完整 JSON 对象（容错推理模型的额外文本）。"""
    start = content.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(content)):
        ch = content[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(content[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _input_hash(system_prompt: str, user_payload: dict, prompt_version: str, schema_version: str) -> str:
    raw = json.dumps(
        {"system": system_prompt, "payload": user_payload, "pv": prompt_version, "sv": schema_version},
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class DeepSeekClient(SemanticLLMClient):
    provider = "deepseek"

    def __init__(self) -> None:
        self.settings = get_settings()
        self._calls = 0
        self._tokens = 0

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
    ) -> dict[str, Any]:
        self._assert_budget(db)

        model_name = model or self.settings.deepseek_model
        # v4-flash 是推理模型：reasoning 会消耗 token 预算，
        # 实际可用 max_tokens 需给足（默认 4096，调用方可覆盖）。
        effective_max_tokens = max_tokens if max_tokens >= 2048 else 2048
        input_key = _input_hash(system_prompt, user_payload, prompt_version, schema_version)

        # cache hit
        if db is not None:
            cached = LLMCallCache.get(
                db,
                provider=self.provider,
                model=model_name,
                prompt_version=prompt_version,
                schema_version=schema_version,
                input_hash=input_key,
            )
            if cached is not None:
                self._calls += 1
                self._tokens += cached.get("token_usage", 0)
                return cached["parsed_payload"]

        url = f"{self.settings.deepseek_base_url.rstrip('/')}/chat/completions"
        body = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            "temperature": 0.0,
            "max_tokens": effective_max_tokens,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",  # key 只出现在内存 header，不落日志
            "Content-Type": "application/json",
        }
        # 有限重试（最多 2 次，指数退避）——应对服务端偶发断连；不无限 retry
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with httpx.Client(timeout=self.settings.deepseek_timeout_seconds) as client:
                    resp = client.post(url, headers=headers, json=body)
                break
            except httpx.HTTPError as e:
                last_error = e
                if attempt < 2:
                    import time
                    time.sleep(1.5 * (attempt + 1))
        else:
            raise SemanticLLMError(f"DeepSeek 网络错误（重试3次后）: {last_error.__class__.__name__ if last_error else 'unknown'}") from last_error

        if resp.status_code != 200:
            # 响应体是 API 错误详情（不含 key），截断后透传，便于调试
            detail = resp.text[:300]
            raise SemanticLLMError(f"DeepSeek HTTP {resp.status_code} (model={model_name}): {detail}")

        data = resp.json()
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or prompt_tokens + completion_tokens)

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            # 推理模型偶发在 JSON 前后附带文本，提取第一个完整 JSON 对象容错
            parsed = _extract_json_object(content)
            if parsed is None:
                raise SemanticLLMError("DeepSeek 返回非 JSON 内容且无法提取")

        self._calls += 1
        self._tokens += total_tokens

        if db is not None:
            LLMCallCache.put(
                db,
                provider=self.provider,
                model=model_name,
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
