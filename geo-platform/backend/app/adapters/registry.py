from app.adapters.base import BaseAIAdapter
from app.adapters.mock import MockAdapter
from app.adapters.wenxin import WenxinAdapter
from app.core.config import get_settings


class PlaceholderAdapter(MockAdapter):
    def __init__(self, platform_key: str):
        self.platform_key = platform_key
        self.entry_type = "official_api_placeholder"


def get_adapter(platform_key: str) -> BaseAIAdapter:
    if platform_key == "mock":
        return MockAdapter()
    if platform_key == "wenxin":
        return WenxinAdapter()
    if platform_key in {"qwen", "kimi", "deepseek"}:
        return PlaceholderAdapter(platform_key)
    raise ValueError(f"Unsupported platform: {platform_key}")


def list_platforms() -> list[dict[str, str]]:
    settings = get_settings()
    wenxin_status = "ready" if settings.wenxin_api_key and settings.wenxin_secret_key else "needs_config"
    return [
        {"platform_key": "wenxin", "platform_name": "百度文心 / 千帆", "status": wenxin_status},
        {"platform_key": "mock", "platform_name": "Mock测试平台", "status": "ready"},
        {"platform_key": "qwen", "platform_name": "通义千问 / 百炼", "status": "placeholder"},
        {"platform_key": "kimi", "platform_name": "Kimi", "status": "placeholder"},
        {"platform_key": "deepseek", "platform_name": "DeepSeek", "status": "placeholder"},
    ]
