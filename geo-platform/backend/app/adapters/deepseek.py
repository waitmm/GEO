from app.adapters.registry import PlaceholderAdapter


class DeepSeekAdapter(PlaceholderAdapter):
    def __init__(self) -> None:
        super().__init__("deepseek")
