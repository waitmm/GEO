"""Offline browser acceptance against a freshly migrated, isolated release DB."""
import json
import os
from pathlib import Path
import socket
import re
import subprocess
import sys
import time
from contextlib import ExitStack
from urllib.request import build_opener, ProxyHandler

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]


def main():
    from datetime import datetime, timezone
    out = ROOT / 'backend/artifacts/acceptance' / ('browser-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    out.mkdir(parents=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = {**os.environ, 'GEO_RELEASE_DATABASE_URL': f'sqlite:///{out / "isolated.db"}'}
    migration = subprocess.run([sys.executable, '-m', 'alembic', '-c', 'alembic.release.ini', 'upgrade', 'head'],
        cwd=ROOT / 'backend', env=env, capture_output=True, text=True)
    (out / 'migration.log').write_text(migration.stdout + migration.stderr)
    migration.check_returncode()
    report = {'scope': 'OFFLINE_ISOLATED_UI', 'external_calls': 0, 'screenshots': [], 'errors': [], 'status': 'FAIL'}
    log = (out / 'api.log').open('w')
    server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.release_main:app', '--host', '127.0.0.1', '--port', str(port)],
        cwd=ROOT / 'backend', env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        opener = build_opener(ProxyHandler({}))
        for _ in range(240):
            if server.poll() is not None:
                raise RuntimeError('Isolated API exited; inspect api.log')
            try:
                with opener.open(f'http://127.0.0.1:{port}/api/health', timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(.25)
        else:
            raise RuntimeError('Isolated API not ready')
        with sync_playwright() as p, ExitStack() as cleanup:
            browser = p.chromium.launch(headless=True, channel='chrome')
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            context.tracing.start(screenshots=True, snapshots=True)
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(f'http://127.0.0.1:{port}/') else route.abort())
            page = context.new_page()
            cleanup.callback(context.tracing.stop, path=str(out / 'trace.zip'))
            def capture_failure():
                if report['status'] == 'FAIL':
                    page.screenshot(path=str(out / 'failure.png'), full_page=True, timeout=10000)
                    (out / 'failure.txt').write_text(page.locator('body').inner_text())
            cleanup.callback(capture_failure)
            page.on('pageerror', lambda error: report['errors'].append(str(error)))
            page.goto(f'http://127.0.0.1:{port}/')
            page.get_by_role('button', name='新建项目', exact=True).click()
            dialog = page.get_by_role('dialog')
            dialog.get_by_label('项目名称', exact=True).fill('隔离验收项目')
            dialog.get_by_label('品牌名称', exact=True).fill('测试过滤器')
            dialog.get_by_role('button', name=re.compile('创.*建')).click()
            expect(dialog).not_to_be_visible()
            page.get_by_role('menuitem', name='问题与采样配置', exact=True).click()
            page.screenshot(path=str(out / 'prompt-entry.png'), full_page=True)
            (out / 'prompt-entry.txt').write_text(page.locator('body').inner_text())
            page.get_by_label('问题原文', exact=True).fill('空气过滤器如何清洗？\n有哪些前提条件？')
            page.get_by_role('button', name='创建问题', exact=True).click()
            expect(page.get_by_role('cell', name='空气过滤器如何清洗？ 有哪些前提条件？', exact=True)).to_be_visible()
            page.get_by_role('menuitem', name='品牌资料', exact=True).click()
            page.get_by_label('资料标题', exact=True).fill('隔离品牌说明')
            page.get_by_label('品牌资料正文', exact=True).fill('测试过滤器提供过滤器维护资料，具体清洗条件应按型号确认。')
            page.get_by_label('资料出处或维护说明', exact=True).fill('本地工程测试，不是真实品牌证据')
            page.get_by_role('button', name='保存新资料版本', exact=True).click()
            expect(page.get_by_text('版本 1 · 隔离品牌说明', exact=True)).to_be_visible()
            page.reload()
            expect(page.get_by_text('版本 1 · 隔离品牌说明', exact=True)).to_be_visible()
            page.get_by_role('menuitem', name='Monitor · 监测', exact=True).click()
            page.get_by_text('持续采样计划', exact=True).click()
            page.get_by_label('采样授权说明', exact=True).fill('仅离线工程验证，worker不启动，不允许外部请求')
            page.get_by_role('button', name='授权并开启每日采样', exact=True).click()
            expect(page.get_by_role('cell', name='已开启', exact=True)).to_be_visible()
            page.get_by_role('button', name='暂停', exact=True).click()
            page.get_by_role('button', name=re.compile('确.*定')).click()
            expect(page.get_by_role('cell', name='已暂停', exact=True)).to_be_visible()
            for width in [1440, 1024, 390]:
                page.set_viewport_size({'width': width, 'height': 1000})
                path = f'monitor-{width}.png'
                page.screenshot(path=str(out / path), full_page=True)
                report['screenshots'].append(path)
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), f'page overflow: {width}'
            report['verified'] = ['UI_PROJECT_CREATE', 'MULTILINE_PROMPT_PRESERVED', 'CONTEXT_SAVE_RELOAD', 'SCHEDULE_CREATE_PAUSE', 'RESPONSIVE_NO_PAGE_OVERFLOW']
            report['not_verified'] = ['REAL_SAMPLING', 'AUTOMATIC_OPTIMIZE', 'COMPARISON_WITH_REAL_NEW_RUN']
            assert not report['errors'], report['errors']
            report['status'] = 'PASS_SCOPED_CHECKS_NOT_FULL_DELIVERY'
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill(); server.wait()
        log.close()
        (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(out, flush=True)


if __name__ == '__main__':
    main()
