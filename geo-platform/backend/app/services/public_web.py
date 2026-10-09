"""Bounded anonymous public GET transport with DNS pinned before socket connect."""
from __future__ import annotations

import http.client
import ipaddress
import io
import socket
import ssl
import time
import zlib
from dataclasses import dataclass
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import certifi

MAX_RESPONSE_BYTES = 2_000_000
MAX_REDIRECTS = 8


class PublicWebError(ValueError):
    pass


@dataclass(frozen=True)
class PublicTarget:
    url: str
    host: str
    port: int
    address: tuple
    family: int
    tls: bool
    path: str


@dataclass(frozen=True)
class PublicResponse:
    url: str
    status: int
    headers: dict[str, str]
    body: bytes


def public_target(url: str) -> PublicTarget:
    try:
        if not isinstance(url, str) or len(url) > 8192 or any(ord(c) < 33 or ord(c) == 127 for c in url):
            raise ValueError()
        parts = urlsplit(url)
        host = (parts.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        tls = parts.scheme == "https"
        port = parts.port or (443 if tls else 80)
        if (parts.scheme not in {"http", "https"} or not host or parts.username is not None
                or parts.password is not None or port not in {80, 443} or '%' in host
                or host == "localhost" or host.endswith((".localhost", ".local", ".internal"))):
            raise ValueError()
    except (ValueError, UnicodeError) as exc:
        raise PublicWebError("UNSAFE_PUBLIC_URL") from exc
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise PublicWebError("PUBLIC_DNS_UNAVAILABLE") from exc
    if not addresses:
        raise PublicWebError("PUBLIC_DNS_UNAVAILABLE")
    for family, _, _, _, address in addresses:
        ip = ipaddress.ip_address(address[0])
        mapped = getattr(ip, "ipv4_mapped", None)
        if (family not in {socket.AF_INET, socket.AF_INET6} or not ip.is_global
                or ip.is_multicast or ip.is_reserved or (mapped and (not mapped.is_global or mapped.is_multicast))):
            raise PublicWebError("NON_PUBLIC_NETWORK_TARGET")
    family, _, _, _, address = addresses[0]
    netloc = f"[{host}]" if ':' in host else host
    default_port = 443 if tls else 80
    if port != default_port:
        netloc += f":{port}"
    path = quote(parts.path or '/', safe="/%:@!$&'()*+,;=-._~")
    query = quote(parts.query, safe="%/?@:!$&'()*+,;=-._~")
    clean = urlunsplit((parts.scheme, netloc, path, query, ''))
    return PublicTarget(clean, host, port, address, family, tls,
                        path + ('?' + query if query else ''))


class _DeadlineReader(io.RawIOBase):
    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock, deadline
        # SocketIO retains the descriptor when HTTPConnection closes an HTTP/1.0
        # connection before the response body has been consumed.
        self.raw = sock.makefile('rb', buffering=0)

    def readable(self):
        return True

    def readinto(self, buffer):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('PUBLIC_REQUEST_DEADLINE')
        self.sock.settimeout(remaining)
        return self.raw.readinto(buffer)

    def close(self):
        try:
            self.raw.close()
        finally:
            super().close()


class _ResponseSocket:
    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock, deadline

    def makefile(self, mode):
        if mode != 'rb':
            raise ValueError('PUBLIC_RESPONSE_READ_ONLY')
        return io.BufferedReader(_DeadlineReader(self.sock, self.deadline))

    def __getattr__(self, key):
        return getattr(self.sock, key)


class _PinnedConnection(http.client.HTTPConnection):
    def __init__(self, target: PublicTarget, timeout: float):
        super().__init__(target.host, target.port, timeout=timeout)
        self.target = target
        self.deadline = time.monotonic() + timeout

    def connect(self):
        # Connect to the validated numeric address, never resolve the hostname again.
        sock = socket.socket(self.target.family, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(self.target.address)
            if self.target.tls:
                sock = ssl.create_default_context(cafile=certifi.where()).wrap_socket(sock, server_hostname=self.target.host)
            self.sock = _ResponseSocket(sock, self.deadline)
        except BaseException:
            sock.close()
            raise


def public_get(url: str, *, follow_redirects: bool = True, timeout: float = 8,
               max_bytes: int = MAX_RESPONSE_BYTES) -> PublicResponse:
    current = url
    seen = set()
    deadline = time.monotonic() + timeout
    for _ in range(MAX_REDIRECTS + 1):
        target = public_target(current)
        if target.url in seen:
            raise PublicWebError("REDIRECT_LOOP")
        seen.add(target.url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('PUBLIC_REQUEST_DEADLINE')
        connection = _PinnedConnection(target, remaining)
        response = None
        try:
            connection.request('GET', target.path, headers={
                'User-Agent': 'GEOAuditBot/1.0', 'Accept': 'text/html,application/xhtml+xml,*/*;q=0.5',
                'Accept-Encoding': 'identity', 'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.5',
            })
            response = connection.getresponse()
            headers = {k.lower(): v for k, v in response.getheaders()}
            if int(headers.get('content-length', '0')) > max_bytes:
                raise PublicWebError("PUBLIC_RESPONSE_TOO_LARGE")
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise PublicWebError("PUBLIC_RESPONSE_TOO_LARGE")
            encoding = headers.get('content-encoding', '').lower()
            if encoding == 'gzip':
                decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
                body = decoder.decompress(body, max_bytes + 1)
                if len(body) > max_bytes or not decoder.eof or decoder.unused_data:
                    raise PublicWebError("PUBLIC_RESPONSE_ENCODING_LIMIT")
            elif encoding not in {'', 'identity'}:
                raise PublicWebError("PUBLIC_RESPONSE_ENCODING_UNSUPPORTED")
            headers.pop('content-encoding', None)
            headers.pop('transfer-encoding', None)
            headers.pop('content-length', None)
            # No cookies or credential challenges survive this anonymous transport.
            headers.pop('set-cookie', None)
            if response.status in {301, 302, 303, 307, 308}:
                location = headers.get('location')
                if not location:
                    raise PublicWebError("REDIRECT_LOCATION_MISSING")
                current = urljoin(target.url, location)
                public_target(current)  # Reject an unsafe hop before returning/following it.
                headers['location'] = current
                if follow_redirects:
                    continue
            return PublicResponse(target.url, response.status, headers, body)
        finally:
            if response is not None:
                response.close()
            connection.close()
    raise PublicWebError("REDIRECT_LIMIT")


def guard_browser_context(context):
    """Fulfil HTTP(S) reads through the pinned transport; block browser sockets."""
    state = {'requests': 0, 'bytes': 0, 'blocked': [], 'main_failure': None}
    deadline = time.monotonic() + 35

    def handle(route):
        request = route.request
        kind = request.resource_type
        if request.method != 'GET' or kind not in {'document', 'script', 'stylesheet', 'xhr', 'fetch'}:
            route.abort('blockedbyclient')
            return
        state['requests'] += 1
        try:
            if state['requests'] > 64 or state['bytes'] >= 12_000_000 or time.monotonic() >= deadline:
                raise PublicWebError('PAGE_RESOURCE_BUDGET_EXHAUSTED')
            result = public_get(request.url, follow_redirects=False, timeout=min(8, deadline - time.monotonic()))
            state['bytes'] += len(result.body)
            if state['bytes'] > 12_000_000:
                raise PublicWebError('PAGE_RESOURCE_BUDGET_EXHAUSTED')
            if kind == 'document' and result.status >= 400:
                raise PublicWebError(f'PUBLIC_HTTP_{result.status}')
            route.fulfill(status=result.status, headers=result.headers, body=result.body)
        except Exception as exc:
            code = str(exc) if isinstance(exc, PublicWebError) else type(exc).__name__
            state['blocked'].append(code)
            if request.is_navigation_request():
                state['main_failure'] = code
            route.abort('blockedbyclient')

    context.route('**/*', handle)
    context.route_web_socket('**/*', lambda route: route.close())
    return state
