"""Offline egress tests: no DNS, remote sockets or provider requests."""
import gzip
import io
import socket
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import public_web as web


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    resolver = Mock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))])
    monkeypatch.setattr(web.socket, 'getaddrinfo', resolver)
    return resolver


@pytest.mark.parametrize('url', [
    'file:///etc/passwd', 'ftp://example.com', 'http://localhost',
    'https://a.internal', 'https://a.local', 'https://user:secret@example.com',
    'https://example.com:8000', 'https://example.com/\r\ninject',
    'https://[fe80::1%en0]/',
])
def test_invalid_url_never_resolves(url, public_dns):
    with pytest.raises(web.PublicWebError, match='UNSAFE_PUBLIC_URL'):
        web.public_target(url)
    public_dns.assert_not_called()


@pytest.mark.parametrize('address', ['127.0.0.1', '10.0.0.1', '169.254.169.254',
                                     '100.64.0.1', '224.0.0.1', '::1', 'fc00::1',
                                     '::ffff:127.0.0.1'])
def test_all_dns_answers_must_be_public(address, public_dns):
    family = socket.AF_INET6 if ':' in address else socket.AF_INET
    public_dns.return_value.append((family, socket.SOCK_STREAM, 6, '', (address, 443)))
    with pytest.raises(web.PublicWebError, match='NON_PUBLIC_NETWORK_TARGET'):
        web.public_target('https://example.com/')


def test_pinned_connection_has_no_second_lookup_and_verifies_tls(monkeypatch, public_dns):
    target = web.public_target('https://example.com/正文?q=中文')
    sock = Mock()
    monkeypatch.setattr(web.socket, 'socket', Mock(return_value=sock))
    tls = Mock()
    tls.wrap_socket.return_value = sock
    factory = Mock(return_value=tls)
    monkeypatch.setattr(web.ssl, 'create_default_context', factory)
    connection = web._PinnedConnection(target, 1)
    connection.connect()
    sock.connect.assert_called_once_with(('8.8.8.8', 443))
    public_dns.assert_called_once()
    tls.wrap_socket.assert_called_once_with(sock, server_hostname='example.com')
    assert factory.call_args.kwargs['cafile']
    assert '%E6%AD%A3' in target.path
    connection.close()


class WireSocket:
    """Socket-shaped HTTP input; SocketIO owns the body after connection close."""
    def __init__(self, wire):
        self.wire = io.BytesIO(wire)
        self.closed = False
        self.files = []

    def makefile(self, mode, buffering=0):
        self.files.append(self.wire)
        return self.wire

    def settimeout(self, value):
        assert value > 0

    def sendall(self, data):
        pass

    def close(self):
        self.closed = True


def install_wire(monkeypatch, messages):
    sockets = []

    def connect(connection):
        sock = WireSocket(messages.pop(0))
        sockets.append(sock)
        connection.sock = web._ResponseSocket(sock, connection.deadline)

    monkeypatch.setattr(web._PinnedConnection, 'connect', connect)
    return sockets


@pytest.mark.parametrize('protocol', [b'HTTP/1.0', b'HTTP/1.1'])
def test_connection_close_body_is_consumed_and_file_closed(monkeypatch, protocol):
    sockets = install_wire(monkeypatch, [protocol + b' 200 OK\r\nConnection: close\r\nContent-Length: 5\r\nSet-Cookie: secret=1\r\n\r\nhello'])
    result = web.public_get('https://example.com')
    assert result.body == b'hello'
    assert 'set-cookie' not in result.headers
    assert sockets[0].closed and sockets[0].wire.closed
    assert result.receipts[0]['url'] == 'https://example.com/'
    assert result.receipts[0]['tls_verified'] is True
    assert result.receipts[0]['response_body_hash'] == web.hashlib.sha256(b'hello').hexdigest()


def test_transport_receipt_preserves_redirect_and_final_host(monkeypatch):
    install_wire(monkeypatch, [
        b'HTTP/1.1 302 Found\r\nLocation: https://other.example/docs\r\nContent-Length: 0\r\n\r\n',
        b'HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\nhello',
    ])
    result = web.public_get('https://example.com/')
    assert [r['url'] for r in result.receipts] == ['https://example.com/', 'https://other.example/docs']
    assert result.url == 'https://other.example/docs'
    assert [r['status'] for r in result.receipts] == [302, 200]


def test_private_redirect_rejected_before_next_connection(monkeypatch, public_dns):
    public_dns.side_effect = lambda host, *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '',
         ('127.0.0.1' if host == 'private.test' else '8.8.8.8', 443))]
    sockets = install_wire(monkeypatch, [b'HTTP/1.1 302 Found\r\nLocation: https://private.test\r\nContent-Length: 0\r\n\r\n'])
    with pytest.raises(web.PublicWebError, match='NON_PUBLIC_NETWORK_TARGET'):
        web.public_get('https://example.com')
    assert len(sockets) == 1


@pytest.mark.parametrize('wire,reason', [
    (b'HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n', 'TOO_LARGE'),
    (b'HTTP/1.0 200 OK\r\n\r\n01234567890', 'TOO_LARGE'),
    (b'HTTP/1.1 302 Found\r\nLocation: https://example.com/\r\nContent-Length: 0\r\n\r\n', 'REDIRECT_LOOP'),
])
def test_transport_limits(monkeypatch, wire, reason):
    install_wire(monkeypatch, [wire])
    with pytest.raises(web.PublicWebError, match=reason):
        web.public_get('https://example.com/', max_bytes=10)


def test_compressed_body_limit(monkeypatch):
    body = gzip.compress(b'x' * 1000)
    install_wire(monkeypatch, [b'HTTP/1.0 200 OK\r\nContent-Encoding: gzip\r\n\r\n' + body])
    with pytest.raises(web.PublicWebError, match='ENCODING_LIMIT'):
        web.public_get('https://example.com', max_bytes=100)


def test_deadline_reader_rejects_slow_body(monkeypatch):
    raw = WireSocket(b'hello')
    reader = web._DeadlineReader(raw, 10)
    monkeypatch.setattr(web.time, 'monotonic', lambda: 11)
    with pytest.raises(TimeoutError, match='DEADLINE'):
        reader.readinto(bytearray(5))
    reader.close()
    assert raw.wire.closed


def test_native_socket_file_survives_connection_close():
    left, right = socket.socketpair()
    try:
        right.sendall(b'HTTP/1.0 200 OK\r\nContent-Length: 5\r\n\r\nhello')
        wrapped = web._ResponseSocket(left, web.time.monotonic() + 1)
        response = web.http.client.HTTPResponse(wrapped)
        response.begin()
        wrapped.close()
        assert response.read() == b'hello'
        response.close()
        assert left.fileno() == -1
    finally:
        left.close()
        right.close()


def test_browser_guard_pins_get_blocks_writes_and_private_navigation(monkeypatch):
    context = Mock()
    state = web.guard_browser_context(context)
    handler = context.route.call_args.args[1]
    fetch = Mock(return_value=web.PublicResponse('https://example.com', 200, {}, b'hello'))
    monkeypatch.setattr(web, 'public_get', fetch)
    route = Mock(request=SimpleNamespace(method='GET', resource_type='document',
                                        url='https://example.com', is_navigation_request=lambda: True))
    handler(route)
    route.fulfill.assert_called_once()
    route.continue_.assert_not_called()
    route.request.method = 'POST'
    handler(route)
    route.abort.assert_called_once_with('blockedbyclient')
    assert fetch.call_count == 1
    route.request.method = 'GET'
    fetch.side_effect = web.PublicWebError('NON_PUBLIC_NETWORK_TARGET')
    handler(route)
    assert state['main_failure'] == 'NON_PUBLIC_NETWORK_TARGET'
    ws = Mock()
    context.route_web_socket.call_args.args[1](ws)
    ws.close.assert_called_once()


def test_http_fallback_uses_same_guard_and_decodes_existing_content(monkeypatch):
    from app.modules.optimization import passage_service as passages
    text = '这是可复验的原始正文。' * 20
    response = web.PublicResponse('https://example.com/page', 200,
                                  {'content-type': 'text/html; charset=gbk'},
                                  f'<title>来源</title><p>{text}</p>'.encode('gbk'))
    fetch = Mock(return_value=response)
    monkeypatch.setattr(passages, 'public_get', fetch)
    result = passages.fetch_page('https://example.com')
    assert result['fetch_status'] == 'SUCCESS'
    assert text in result['clean_text'] and result['title'] == '来源'
    fetch.side_effect = web.PublicWebError('NON_PUBLIC_NETWORK_TARGET')
    result = passages.fetch_page('https://example.com')
    assert result['fetch_status'] == 'FETCH_FAILED'
    assert result['failure_reason'] == 'NON_PUBLIC_NETWORK_TARGET'
    assert fetch.call_count == 2


def test_source_browser_is_ephemeral_and_closes_failed_initialization(monkeypatch):
    from app.modules.optimization import passage_service as passages
    monkeypatch.setattr(passages, '_find_browser_executable_for_fetch', lambda: None)
    playwright = Mock()
    browser = playwright.chromium.launch.return_value
    passages._launch_browser_context_for_fetch(playwright)
    assert browser.new_context.call_args.kwargs['ignore_https_errors'] is False
    assert browser.new_context.call_args.kwargs['service_workers'] == 'block'
    playwright.chromium.launch_persistent_context.assert_not_called()
    assert '--no-sandbox' not in playwright.chromium.launch.call_args.kwargs['args']
    assert playwright.chromium.launch.call_args.kwargs['chromium_sandbox'] is True
    browser.new_context.side_effect = RuntimeError('failed')
    with pytest.raises(RuntimeError):
        passages._launch_browser_context_for_fetch(playwright)
    browser.close.assert_called_once()


def test_browser_renders_guarded_content_and_rejects_private_subrequest(monkeypatch, public_dns):
    from app.modules.optimization import passage_service as passages
    public_dns.side_effect = lambda host, *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, '',
         ('127.0.0.1' if host == 'private.test' else '8.8.8.8', 443))]
    text = 'Visible public source paragraph. ' * 20
    calls = []

    def fetch(url, **kwargs):
        calls.append(url)
        web.public_target(url)
        body = '<html><title>Controlled source</title><body><p>' + text + '</p>'
        if url.endswith('/blocked'):
            body += '<script>fetch("https://private.test/secret").catch(()=>{});</script>'
        raw = (body + '</body></html>').encode()
        record = {'url': url, 'status': 200, 'tls_verified': True, 'public_address_pinned': True,
                  'response_body_hash': web.hashlib.sha256(raw).hexdigest(), 'content_type': 'text/html', 'last_modified': ''}
        return web.PublicResponse(url, 200, {'content-type': 'text/html'}, raw, (record,))

    monkeypatch.setattr(web, 'public_get', fetch)
    fallback = Mock(side_effect=AssertionError('Browser must render, not bypass to fallback'))
    monkeypatch.setattr(passages, 'fetch_page', fallback)
    results = passages.fetch_page_playwright(['https://example.com/complete', 'https://example.com/blocked'])
    assert [r['fetch_status'] for r in results] == ['SUCCESS', 'PARTIAL']
    assert text.strip() in results[0]['clean_text']
    assert 'NON_PUBLIC_NETWORK_TARGET' in results[1]['failure_reason']
    assert calls == ['https://example.com/complete', 'https://example.com/blocked', 'https://private.test/secret']
    assert results[0]['acquisition_receipt']['final_url'] == 'https://example.com/complete'
    assert results[1]['acquisition_receipt'] == {}
    fallback.assert_not_called()


def test_http_truncation_cannot_claim_full_body_or_acquisition_receipt(monkeypatch):
    from app.modules.optimization import passage_service as passages
    raw = ('<p>' + '正文' * 110000 + '</p>').encode()
    response = web.PublicResponse('https://example.com', 200, {'content-type': 'text/html; charset=utf-8'}, raw)
    monkeypatch.setattr(passages, 'public_get', lambda *args, **kwargs: response)
    result = passages.fetch_page('https://example.com')
    assert result['fetch_status'] == 'PARTIAL'
    assert '保存上限' in result['failure_reason']
    assert result['acquisition_receipt'] == {}
