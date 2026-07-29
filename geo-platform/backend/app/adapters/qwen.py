from app.adapters.registry import PlaceholderAdapter


class QwenAdapter(PlaceholderAdapter):
    def __init__(self) -> None:
        super().__init__("qwen")
