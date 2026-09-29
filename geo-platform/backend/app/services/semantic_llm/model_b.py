"""Explicit factory for the optional second-model critic."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.config import get_settings
from app.services.semantic_llm.base import SemanticLLMError
from app.services.semantic_llm.siliconflow import SiliconFlowClient


def create_model_b_client(
    *,
    cache_only: bool = True,
    max_attempts: int = 1,
    response_audit_sink: Callable[[dict[str, Any]], None] | None = None,
) -> SiliconFlowClient:
    settings = get_settings()
    if settings.model_b_provider != "siliconflow":
        raise SemanticLLMError(
            f"不支持的 Model B Provider: {settings.model_b_provider}"
        )
    if not settings.model_b_enabled and not cache_only:
        error = SemanticLLMError("Model B 默认关闭；必须显式启用并取得外部调用授权")
        error.code = "MODEL_B_DISABLED"
        raise error
    return SiliconFlowClient(
        cache_only=cache_only,
        max_attempts=max_attempts,
        response_audit_sink=response_audit_sink,
    )
