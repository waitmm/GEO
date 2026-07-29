from app.modules.monitoring.collectors.base import BaseCollector
from app.modules.monitoring.collectors.wenxin.collector import WenxinWebCollector
from app.modules.monitoring.enums import WENXIN_WEB_PLATFORM


def get_collector(platform: str) -> BaseCollector:
    if platform == WENXIN_WEB_PLATFORM:
        return WenxinWebCollector()
    raise ValueError(f"Unsupported browser collector: {platform}")
