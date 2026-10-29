"""Small fail-closed HTTPS reverse proxy for the single-machine M1 pilot.

The application remains bound to loopback.  This process is the only LAN
listener, restricts clients to one configured CIDR, terminates TLS, and
forwards the original client and HTTPS scheme to Uvicorn.
"""
from __future__ import annotations

import argparse
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import ssl
from urllib.parse import urlsplit


HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade",
}
MAX_REQUEST_BYTES = 16 * 1024 * 1024


class ProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, *, upstream_host: str, upstream_port: int,
                 allowed_network: ipaddress._BaseNetwork):
        super().__init__(address, handler)
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        self.allowed_network = allowed_network


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "GEO-M1-LAN/1.0"

    def _reject(self, status: int, message: str) -> None:
        body = (message + "\n").encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _proxy(self) -> None:
        try:
            client = ipaddress.ip_address(self.client_address[0])
        except ValueError:
            self._reject(403, "客户端地址无效")
            return
        if client not in self.server.allowed_network:
            self._reject(403, "当前地址不在内部试用网段")
            return
        if self.headers.get("Transfer-Encoding"):
            self._reject(400, "不支持分块请求")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._reject(400, "Content-Length 无效")
            return
        if length < 0 or length > MAX_REQUEST_BYTES:
            self._reject(413, "请求体过大")
            return
        body = self.rfile.read(length) if length else None
        path = urlsplit(self.path)
        if path.scheme or path.netloc or not self.path.startswith("/"):
            self._reject(400, "请求路径无效")
            return

        headers = {
            name: value for name, value in self.headers.items()
            if name.lower() not in HOP_BY_HOP and name.lower() not in {"content-length", "host"}
        }
        headers["Host"] = self.headers.get("Host", "")
        headers["X-Forwarded-Proto"] = "https"
        headers["X-Forwarded-For"] = str(client)
        headers["X-Forwarded-Host"] = self.headers.get("Host", "")
        if body is not None:
            headers["Content-Length"] = str(len(body))

        upstream = http.client.HTTPConnection(
            self.server.upstream_host, self.server.upstream_port, timeout=180,
        )
        try:
            upstream.request(self.command, self.path, body=body, headers=headers)
            response = upstream.getresponse()
            payload = response.read()
            self.send_response(response.status, response.reason)
            for name, value in response.getheaders():
                if name.lower() not in HOP_BY_HOP and name.lower() != "content-length":
                    self.send_header(name, value)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Strict-Transport-Security", "max-age=31536000")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
        except (OSError, http.client.HTTPException):
            self._reject(502, "GEO 后端暂时不可用")
        finally:
            upstream.close()

    do_GET = _proxy
    do_HEAD = _proxy
    do_POST = _proxy
    do_PUT = _proxy
    do_PATCH = _proxy
    do_DELETE = _proxy
    do_OPTIONS = _proxy

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.client_address[0]} - {fmt % args}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, required=True)
    parser.add_argument("--upstream-host", default="127.0.0.1")
    parser.add_argument("--upstream-port", type=int, required=True)
    parser.add_argument("--allowed-cidr", required=True)
    parser.add_argument("--certificate", required=True)
    parser.add_argument("--private-key", required=True)
    args = parser.parse_args()
    network = ipaddress.ip_network(args.allowed_cidr, strict=False)
    server = ProxyServer(
        (args.listen_host, args.listen_port), ProxyHandler,
        upstream_host=args.upstream_host, upstream_port=args.upstream_port,
        allowed_network=network,
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(args.certificate, args.private_key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
