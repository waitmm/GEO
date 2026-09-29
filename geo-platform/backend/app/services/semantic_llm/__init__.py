"""Runtime Semantic LLM clients.

- Model A Semantic Judges continue to use DeepSeek;
- optional Model B uses SiliconFlow Qwen through an explicit factory;
- 所有调用带 cache（input_hash + model + prompt_version 去重）；
- API Key 只从环境变量读取，禁止写死/打日志/进 Git。
"""

from app.services.semantic_llm.base import SemanticLLMClient, SemanticLLMError
from app.services.semantic_llm.deepseek import DeepSeekClient
from app.services.semantic_llm.cache import LLMCallCache
from app.services.semantic_llm.model_b import create_model_b_client
from app.services.semantic_llm.siliconflow import SiliconFlowClient

__all__ = [
    "SemanticLLMClient",
    "SemanticLLMError",
    "DeepSeekClient",
    "SiliconFlowClient",
    "create_model_b_client",
    "LLMCallCache",
]
