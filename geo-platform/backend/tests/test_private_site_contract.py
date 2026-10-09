from html.parser import HTMLParser
from pathlib import Path

from release_test_client import TestClient
from app.release_main import create_release_app


class Head(HTMLParser):
    def __init__(self):
        super().__init__()
        self.lang = None
        self.robots = None
    def handle_starttag(self, tag, attrs):
        value = dict(attrs)
        if tag == 'html':
            self.lang = value.get('lang')
        if tag == 'meta' and value.get('name') == 'robots':
            self.robots = set(value.get('content', '').replace(' ', '').split(','))


def test_private_console_has_language_and_noindex_not_customer_sitemap():
    head = Head()
    head.feed((Path(__file__).resolve().parents[2] / 'frontend/index.html').read_text())
    assert head.lang == 'zh-CN'
    assert {'noindex', 'nofollow', 'nosnippet'} <= head.robots
    client = TestClient(create_release_app(validate_on_startup=False), base_url='http://127.0.0.1', client=('127.0.0.1', 50000))
    robots = client.get('/robots.txt')
    assert robots.status_code == 200 and robots.text == 'User-agent: *\nDisallow: /\n'
    for path in ['/this-page-does-not-exist', '/sitemap.xml', '/api/unknown']:
        response = client.get(path)
        assert response.status_code == 404
        assert 'noindex' in response.headers['x-robots-tag']
    response = client.get('/api/health')
    assert 'no-store' in response.headers['cache-control']
    assert response.headers['x-content-type-options'] == 'nosniff'
