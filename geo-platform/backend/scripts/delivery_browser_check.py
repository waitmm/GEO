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


def automatic_check(page, origin, fixture, Session, monkeypatch, out, report):
    from datetime import datetime
    from app.modules.single_prompt_v2.automatic_delivery import execute_task
    from test_automatic_delivery import simulated_delivery_transport
    analysis = fixture['analysis']
    page.goto(f'{origin}/?v2_project=1&v2_prompt=44&v2_analysis={analysis.analysis_id}')
    panel = page.get_by_role('region', name='自动优化交付')
    expect(panel.get_by_role('button', name='开始自动优化', exact=True)).to_be_enabled()
    with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/optimization-tasks')) as response:
        panel.get_by_role('button', name='开始自动优化', exact=True).click()
    task_id = response.value.json()['task_id']
    expect(panel.get_by_role('button', name='开始自动优化', exact=True)).to_be_disabled()
    execute_task(task_id, session_factory=Session)  # CACHE_ONLY, never external.
    expect(panel.get_by_role('button', name='授权本任务模型调用')).to_be_visible(timeout=15000)
    panel.get_by_role('button', name='授权本任务模型调用').click()
    dialog = page.get_by_role('dialog', name='本任务独立调用授权')
    for label, value in [('请求次数上限', '4'), ('总 token 上限', '400000'), ('人民币硬预算', '4'),
            ('输入 / 输出每百万 token 的较高保守单价（人民币）', '10'),
            ('已核实计费依据', '隔离工程模拟价格，不是真实调用授权'),
            ('计费核实日期', datetime.utcnow().date().isoformat())]:
        dialog.get_by_label(label, exact=True).fill(value)
    dialog.get_by_role('button', name='确认授权并继续', exact=True).click()
    expect(dialog).not_to_be_visible()
    calls = simulated_delivery_transport(monkeypatch)
    execute_task(task_id, session_factory=Session)
    expect(panel.get_by_role('button', name='复制完整正文')).to_be_visible(timeout=15000)
    expect(panel.get_by_text('选用工具前的核对顺序', exact=False)).to_be_visible()
    assert len(calls) == 4
    page.reload()
    expect(panel.get_by_role('button', name='复制完整正文')).to_be_visible(timeout=15000)
    expect(panel.get_by_text('已记录 token', exact=True)).to_be_visible()
    for width in [1440, 1024, 390]:
        page.set_viewport_size({'width': width, 'height': 1000})
        panel.scroll_into_view_if_needed()
        path = f'optimize-{width}.png'
        page.screenshot(path=str(out / path), full_page=False)
        report['screenshots'].append(path)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), f'page overflow: {width}'
    report.update(verified=['UI_OPTIMIZE_CREATE', 'STABLE_QUEUED_ACTION', 'CACHE_MISS_NOT_FAILURE',
        'EXPLICIT_BUDGET_AUTHORIZATION', 'WORKER_EXISTING_STAGE_CHAIN', 'ACTUAL_DRAFT_AND_QA_READ',
        'REFRESH_PRESERVES_EXACT_RESULT', 'RESPONSIVE_NO_PAGE_OVERFLOW'],
        simulated_provider_requests=len(calls), not_verified=['REAL_MODEL_QUALITY', 'REAL_SAMPLING', 'REAL_SOURCE_FETCH'],
        task_id=task_id, status='PASS_SCOPED_SIMULATED_INTEGRATION_NOT_REAL_MODEL')
    assert not report['errors'], report['errors']


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
    fixture = None
    if '--optimize' in sys.argv:
        sys.path.insert(0, str(ROOT / 'backend'))
        sys.path.insert(0, str(ROOT / 'backend/tests'))
        from pytest import MonkeyPatch
        from sqlalchemy import create_engine, event
        from sqlalchemy.orm import sessionmaker
        from app.core.release_sqlite import get_release_sqlite_dbapi
        from app.core.release_database import _set_sqlite_pragma
        from test_release_first_slice import _seed_citation_contribution_fixture
        monkeypatch = MonkeyPatch()
        engine = create_engine(env['GEO_RELEASE_DATABASE_URL'], module=get_release_sqlite_dbapi())
        event.listen(engine, 'connect', _set_sqlite_pragma)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        with Session() as db:
            fixture = _seed_citation_contribution_fixture(db, monkeypatch, out, reviewed=False)
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
            if fixture:
                automatic_check(page, f'http://127.0.0.1:{port}', fixture, Session, monkeypatch, out, report)
                return
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
        if fixture:
            monkeypatch.undo()
            engine.dispose()
        (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(out, flush=True)


if __name__ == '__main__':
    main()
