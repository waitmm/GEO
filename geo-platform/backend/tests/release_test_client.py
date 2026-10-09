"""Explicit peer identity for the installed Starlette TestClient transport."""
from fastapi.testclient import TestClient as StarletteClient


class TestClient(StarletteClient):
    __test__ = False

    def __init__(self, app, *, client=('127.0.0.1', 50000), **kwargs):
        async def transport(scope, receive, send):
            if scope['type'] in {'http', 'websocket'}:
                scope = {**scope, 'client': client}
            await app(scope, receive, send)
        super().__init__(transport, **kwargs)
