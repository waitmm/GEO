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


def observation_check(page, origin, fixture, out, report):
    page.goto(f'{origin}/?release_view=releaseMonitor&v2_project=1&v2_prompt=44')
    overview = page.get_by_role('region', name='项目监控概览')
    mention_row = overview.get_by_role('row').filter(has=page.get_by_role('cell', name='正文提及', exact=True))
    expect(mention_row).to_contain_text('50.0%')
    expect(overview.get_by_role('row').filter(has_text='列为选项')).to_contain_text('不可计算')
    expect(page.get_by_text('累计采样尝试 2 条', exact=False)).to_be_visible()
    page.get_by_role('combobox', name='当前问题', exact=True).press('ArrowDown')
    page.get_by_text('全部 Prompt（项目视图）', exact=True).filter(visible=True).click()
    page.reload()
    expect(mention_row).to_contain_text('50.0%')
    expect(page.get_by_text('选择问题查看原文、采样计划和详细指标', exact=True)).to_be_visible()
    page.goto(f'{origin}/?release_view=releaseMonitor&v2_project=1&v2_prompt=44')
    expect(mention_row).to_contain_text('50.0%')
    page.get_by_role('menuitem', name='Validate · 变化比较', exact=True).click()
    for label, run_id in [('基线范围', fixture['baseline_run_id']), ('对照范围', fixture['comparison_run_id'])]:
        page.get_by_role('combobox', name=label, exact=True).click()
        page.get_by_text(re.compile(rf'^Runs {run_id} ·')).filter(visible=True).click()
    with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/observation-comparisons')) as response:
        page.get_by_role('button', name='生成变化比较', exact=True).click()
    saved = response.value.json()
    measured = saved['output']['metrics']['brand_mention_rate']
    assert measured['baseline']['hit_count'] == 0 and measured['baseline']['evaluable_count'] == 1
    assert measured['comparison']['hit_count'] == 1 and measured['comparison']['evaluable_count'] == 1
    assert measured['delta_percentage_points'] == 100
    expect(page.get_by_role('row').filter(has_text='正文提及')).to_contain_text('1/1 (100.0%)')
    expect(page.get_by_text('仅报告观察变化，不证明优化效果或生成因果', exact=True)).to_be_visible()
    page.reload()
    expect(page.get_by_role('row').filter(has_text='正文提及')).to_contain_text('0/1 (0.0%)')
    for run_id in [fixture['baseline_run_id'], fixture['comparison_run_id']]:
        expect(page.get_by_text(re.compile(rf'^Runs {run_id} ·')).filter(visible=True)).to_be_visible()
    for width in [1440, 1024, 390]:
        page.set_viewport_size({'width': width, 'height': 1000})
        name = f'comparison-{width}.png'
        page.screenshot(path=str(out / name), full_page=True)
        report['screenshots'].append(name)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.set_viewport_size({'width': 1440, 'height': 1000})
    page.get_by_role('menuitem', name='品牌资料', exact=True).click()
    for version in [1, 2]:
        page.get_by_label('资料标题', exact=True).fill(f'隔离资料 {version}')
        page.get_by_label('品牌资料正文', exact=True).fill(f'工程测试的维护资料版本 {version}，不可当作真实品牌事实。')
        page.get_by_role('button', name='保存新资料版本', exact=True).click()
        expect(page.get_by_text(f'版本 {version} · 隔离资料 {version}', exact=True)).to_be_visible()
    page.reload()
    for version in [1, 2]:
        expect(page.get_by_text(f'版本 {version} · 隔离资料 {version}', exact=True)).to_be_visible()
    # A failed read must remain visible and recover without mutating business data.
    uri = f'{origin}/api/v2/projects/1/monitor'
    page.route(uri, lambda route: route.fulfill(status=503, content_type='application/json', body='{"detail":"隔离验收：监测服务暂不可用"}'))
    page.get_by_role('menuitem', name='Monitor · 监测', exact=True).click()
    expect(page.get_by_text('隔离验收：监测服务暂不可用', exact=False)).to_be_visible()
    page.unroute(uri)
    page.get_by_role('button', name='刷新当前页面', exact=True).click()
    expect(mention_row).to_contain_text('50.0%')
    page.get_by_role('button', name='新建项目', exact=True).click()
    dialog = page.get_by_role('dialog')
    dialog.get_by_label('项目名称', exact=True).fill('空项目隔离验收')
    dialog.get_by_label('品牌名称', exact=True).fill('另一品牌')
    dialog.get_by_role('button', name=re.compile('创.*建')).click()
    expect(dialog).not_to_be_visible()
    expect(page.get_by_text('尚无可用问题，请先在问题配置中创建', exact=True)).to_be_visible()
    expect(mention_row).to_have_count(0)
    page.get_by_role('combobox', name='当前项目', exact=True).press('ArrowDown')
    page.get_by_text('Release', exact=True).filter(visible=True).click()
    expect(mention_row).to_contain_text('50.0%')
    report.update(status='PASS_SCOPED_SYNTHETIC_OBSERVATION_NOT_REAL_SAMPLING', comparison_version=saved['result_version'],
        verified=['MONITOR_INDEPENDENT_EXPECTED_COUNTS', 'UNKNOWN_NOT_ZERO', 'FORMAL_UI_COMPARISON',
            'COMPARISON_RELOAD_EXACT_VERSION', 'CONTEXT_TWO_VERSIONS', 'READ_FAILURE_RECOVERY',
            'PROJECT_SWITCH_CLEARS_PREVIOUS_DATA', 'RESPONSIVE_NO_PAGE_OVERFLOW'],
        not_verified=['REAL_SAMPLING', 'REAL_MODEL_QUALITY'], synthetic_runs=2)
    assert not report['errors'], report['errors']


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
    if '--optimize' in sys.argv or '--observe' in sys.argv:
        sys.path.insert(0, str(ROOT / 'backend'))
        sys.path.insert(0, str(ROOT / 'backend/tests'))
        from pytest import MonkeyPatch
        from sqlalchemy import create_engine, event
        from sqlalchemy.orm import sessionmaker
        from app.core.release_sqlite import get_release_sqlite_dbapi
        from app.core.release_database import _set_sqlite_pragma
        from test_release_first_slice import _seed_citation_contribution_fixture, _seed_frozen_analysis
        monkeypatch = MonkeyPatch()
        engine = create_engine(env['GEO_RELEASE_DATABASE_URL'], module=get_release_sqlite_dbapi())
        event.listen(engine, 'connect', _set_sqlite_pragma)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        with Session() as db:
            if '--optimize' in sys.argv:
                fixture = _seed_citation_contribution_fixture(db, monkeypatch, out, reviewed=False)
            else:
                from app.models import BrowserMonitorRun
                from app.modules.single_prompt_v2.service import create_analysis, claim_analysis, finalize_analysis
                baseline = _seed_frozen_analysis(db, reference_urls=[])
                first = db.query(BrowserMonitorRun).filter_by(task_id=baseline.task_id).one()
                second, _ = create_analysis(db, project_id=1, prompt_id=44, sample_count=1, idempotency_key='browser-second-synthetic-run')
                token = claim_analysis(db, second.analysis_id)
                run = db.query(BrowserMonitorRun).filter_by(task_id=second.task_id).one()
                run.status = 'success'; run.stage = 'success'; run.answer_text = 'Target 提供资料核对入口。'
                run.answer_char_count = len(run.answer_text); run.reference_complete = True
                db.commit()
                assert finalize_analysis(db, second.analysis_id, token)
                fixture = {'baseline_run_id': first.id, 'comparison_run_id': run.id}
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
                if '--observe' in sys.argv:
                    observation_check(page, f'http://127.0.0.1:{port}', fixture, out, report)
                else:
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
            page.get_by_label('意图', exact=True).click()
            page.get_by_text('使用与操作', exact=True).filter(visible=True).click()
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
            page.get_by_role('checkbox', name='采样完成后自动生成优化建议与稿件', exact=True).check()
            for label, value in [('每任务模型请求上限', '4'), ('每任务 token 上限', '300000'),
                    ('每任务费用上限（元）', '3'), ('输入/输出较高单价（元/百万token）', '10'),
                    ('已核实计费依据', '隔离价格仅用于工程验收，不能用于真实计费'),
                    ('计费核实日期', datetime.now(timezone.utc).date().isoformat()), ('授权人', 'isolated-ui-test')]:
                page.get_by_label(label, exact=True).fill(value)
            with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/sampling-schedules')) as response:
                page.get_by_role('button', name='授权并开启每日采样', exact=True).click()
            plan = response.value.json()['plan']['optimization']
            assert plan['total_authorization'] == {'max_requests': 4, 'max_tokens': 300000, 'max_cost_cny': 3}
            assert plan['configuration']['brand_context']['mode'] == 'EMPTY'
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
            report['verified'] = ['UI_PROJECT_CREATE', 'MULTILINE_PROMPT_PRESERVED', 'CONTEXT_SAVE_RELOAD', 'SCHEDULE_CREATE_PAUSE', 'FINITE_OPTIONAL_OPTIMIZE_AUTHORITY', 'RESPONSIVE_NO_PAGE_OVERFLOW']
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
