from app.adapters.registry import PlaceholderAdapter


class KimiAdapter(PlaceholderAdapter):
    def __init__(self) -> None:
        super().__init__("kimi")
