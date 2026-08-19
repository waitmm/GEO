"""Semantic LLM 抽象基类。"""

from __future__ import annotations

from typing import Any


class SemanticLLMError(Exception):
    pass


class SemanticLLMClient:
    """统一语义模型调用接口。

    prompt_version + schema_version 参与 cache key，
    同一输入不会重复调用 API。
    """

    provider: str = "base"

    async def structured_generate(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        response_schema: type,
        model: str,
        prompt_version: str,
        schema_version: str = "v1",
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def structured_generate_sync(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        response_schema: type,
        model: str,
        prompt_version: str,
        schema_version: str = "v1",
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        raise NotImplementedError
