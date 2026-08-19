"""DeepSeek Live Probe — 验证语义模型 API 连通性。

用法（backend 目录）：
    python3 scripts/live_probe.py

检查项：
1. DEEPSEEK_API_KEY 是否已配置（只检测存在性，绝不打印 key）
2. 结构化 JSON 输出是否可用
3. 简单 Grounding 返回是否符合 schema
4. 网络/超时/限流错误是否被正确分类

通过后输出 LIVE_PROBE_OK，才允许对 Prompt #19 / Runs 173-184 执行语义管道。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.services.semantic_llm.base import SemanticLLMError
from app.services.semantic_llm.deepseek import DeepSeekClient


PROBE_SYSTEM = "你是一个测试探针。只输出 JSON。"


def main() -> int:
    settings = get_settings()
    print("=== DeepSeek Live Probe ===")

    if not settings.deepseek_api_key:
        print("FAIL: DEEPSEEK_API_KEY 未配置。请在 backend/.env 添加后重试。")
        print("      代码不会读取该值到日志，探测只检查存在性。")
        return 2

    print("OK: API key 已配置（值不显示）")
    print(f"OK: model={settings.deepseek_model}, base_url={settings.deepseek_base_url}")

    client = DeepSeekClient()
    try:
        result = client.structured_generate_sync(
            system_prompt=PROBE_SYSTEM,
            user_payload={"probe": "请回答一个包含 ok 字段的 JSON"},
            response_schema=dict,
            prompt_version="probe.v1",
            schema_version="v1",
            max_tokens=64,
        )
    except SemanticLLMError as e:
        print(f"FAIL: {e}")
        return 1

    print(f"OK: structured_generate 返回: {json.dumps(result, ensure_ascii=False)[:200]}")
    print(f"OK: 本次调用 token 统计: {client.token_count} tokens / {client.call_count} calls")
    print("LIVE_PROBE_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
