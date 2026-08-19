"""Runtime Semantic LLM 统一客户端。

- 三个 Semantic Judge 通过本模块调用 DeepSeek；
- 所有调用带 cache（input_hash + model + prompt_version 去重）；
- API Key 只从环境变量读取，禁止写死/打日志/进 Git。
"""

from app.services.semantic_llm.base import SemanticLLMClient, SemanticLLMError
from app.services.semantic_llm.deepseek import DeepSeekClient
from app.services.semantic_llm.cache import LLMCallCache

__all__ = ["SemanticLLMClient", "SemanticLLMError", "DeepSeekClient", "LLMCallCache"]
