from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel


class Citation(BaseModel):
    title: str
    url: str
    snippet: Optional[str] = None
    source_name: Optional[str] = None


class AdapterResult(BaseModel):
    platform: str
    entry_type: str
    model: Optional[str] = None
    model_version: Optional[str] = None
    web_search_enabled: bool = True
    prompt: str
    answer_text: Optional[str] = None
    citations: list[Citation] = []
    raw_response: dict[str, Any] = {}
    status: Literal["success", "failed", "partial"] = "success"
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    latency_ms: int = 0
    token_usage: Optional[dict[str, Any]] = None
    cost_estimate: Optional[float] = None


class BaseAIAdapter:
    platform_key = "base"
    entry_type = "official_api_web_search"

    async def run_query(
        self,
        prompt: str,
        model: Optional[str] = None,
        web_search_enabled: bool = True,
        metadata: Optional[dict[str, Any]] = None,
    ) -> AdapterResult:
        raise NotImplementedError
