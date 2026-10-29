from __future__ import annotations

from hashlib import sha256
import http.server
import json
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from scripts.create_lan_access_config import create
from scripts.lan_https_proxy import ProxyHandler, ProxyServer
import ipaddress


class _Upstream(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        payload = json.dumps({
            "scheme": self.headers.get("X-Forwarded-Proto"),
            "client": self.headers.get("X-Forwarded-For"),
        }).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        return


def _server(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def test_proxy_preserves_https_and_real_client_identity():
    upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    proxy = ProxyServer(
        ("127.0.0.1", 0), ProxyHandler,
        upstream_host="127.0.0.1", upstream_port=upstream.server_port,
        allowed_network=ipaddress.ip_network("127.0.0.0/8"),
    )
    _server(upstream); _server(proxy)
    try:
        with urlopen(f"http://127.0.0.1:{proxy.server_port}/api/health") as response:
            value = json.load(response)
            assert response.headers["Strict-Transport-Security"] == "max-age=31536000"
        assert value == {"scheme": "https", "client": "127.0.0.1"}
    finally:
        proxy.shutdown(); upstream.shutdown()


def test_proxy_rejects_client_outside_configured_network():
    upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    proxy = ProxyServer(
        ("127.0.0.1", 0), ProxyHandler,
        upstream_host="127.0.0.1", upstream_port=upstream.server_port,
        allowed_network=ipaddress.ip_network("192.0.2.0/24"),
    )
    _server(upstream); _server(proxy)
    try:
        with pytest.raises(HTTPError) as error:
            urlopen(f"http://127.0.0.1:{proxy.server_port}/")
        assert error.value.code == 403
    finally:
        proxy.shutdown(); upstream.shutdown()


def test_invitation_generator_hashes_runtime_config_and_never_overwrites(tmp_path: Path):
    config = tmp_path / "access.json"
    recovery = tmp_path / "keys.txt"
    create(config, recovery, "admin", ["operator-1", "operator-2"], 1)
    value = json.loads(config.read_text())
    assert [row["name"] for row in value["accounts"]] == ["admin", "operator-1", "operator-2"]
    assert value["accounts"][1]["project_ids"] == [1]
    assert value["accounts"][1]["admin"] is False
    plaintext = recovery.read_text()
    for row in value["accounts"]:
        key = next(line.split(": ", 1)[1] for line in plaintext.splitlines() if line.startswith(row["name"] + ": "))
        assert sha256(key.encode()).hexdigest() == row["key_sha256"]
        assert key not in config.read_text()
    assert (config.stat().st_mode & 0o777) == 0o600
    assert (recovery.stat().st_mode & 0o777) == 0o600
    with pytest.raises(FileExistsError):
        create(config, recovery, "admin", ["operator-1"], 1)
