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


def accessibility_check(page, out, report, name):
    page.wait_for_function("""() => document.fonts.status === 'loaded' &&
        document.getAnimations().every(a => a.playState !== 'running' ||
            a.playbackRate === 0 || !Number.isFinite(a.effect.getComputedTiming().endTime))
    """, timeout=10000)
    page.add_script_tag(path=str(ROOT / 'frontend/node_modules/axe-core/axe.min.js'))
    result = page.evaluate("""async () => await axe.run(document, {
        runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']}
    })""")
    artifact = f'accessibility-{name}.json'
    (out / artifact).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    report.setdefault('accessibility', []).append({'page': name, 'artifact': artifact,
        'violations': [{key: v[key] for key in ('id', 'impact', 'help')} for v in result['violations']],
        'incomplete_rules': [r['id'] for r in result['incomplete']],
        'passed_rule_count': len(result['passes']), 'engine': result['testEngine']})
    assert not result['violations'], [(v['id'], [n['target'] for n in v['nodes']]) for v in result['violations']]
    dialogs = page.get_by_role('dialog')
    focus_scope = dialogs if dialogs.count() else page
    scrollers = focus_scope.locator('.ant-table-content[tabindex="0"], .ant-table-body[tabindex="0"]')
    horizontal = 0
    for node in scrollers.all():
        if node.is_visible() and node.evaluate('(el) => el.scrollWidth > el.clientWidth'):
            node.evaluate('(el) => { el.scrollLeft = 0; }')
            node.focus()
            expect(node).to_be_focused()
            node.press('ArrowRight')
            page.wait_for_function('(el) => el.scrollLeft > 0', arg=node.element_handle())
            node.evaluate('(el) => { el.scrollLeft = 0; }')
            horizontal += 1
    report['accessibility'][-1]['keyboard_horizontal_tables_checked'] = horizontal


def observation_check(page, origin, fixture, out, report):
    page.goto(f'{origin}/?release_view=releaseMonitor&v2_project=1&v2_prompt=44')
    expect(page.get_by_text(re.compile('^后台执行服务未启动：'))).to_be_visible()
    health_url = f'{origin}/api/health'
    page.route(health_url, lambda route: route.fulfill(status=503, content_type='application/json', body='{}'))
    page.get_by_role('button', name='核对后台执行服务', exact=True).click()
    expect(page.get_by_text(re.compile('^暂时无法读取后台运行状态'))).to_be_visible()
    page.unroute(health_url)
    page.get_by_role('button', name='核对后台执行服务', exact=True).click()
    expect(page.get_by_text(re.compile('^后台执行服务未启动：'))).to_be_visible()
    overview = page.get_by_role('region', name='项目监控概览')
    mention_row = overview.get_by_role('row').filter(has=page.get_by_role('cell', name='正文提及', exact=True))
    expect(mention_row).to_contain_text('50.0%')
    expect(overview.get_by_role('row').filter(has_text='列为选项')).to_contain_text('不可计算')
    expect(page.get_by_text('累计采样尝试 2 条', exact=False)).to_be_visible()
    accessibility_check(page, out, report, 'monitor-populated')
    page.get_by_role('combobox', name='当前问题', exact=True).press('ArrowDown')
    page.get_by_text('全部 Prompt（项目视图）', exact=True).filter(visible=True).click()
    page.reload()
    expect(mention_row).to_contain_text('50.0%')
    expect(page.get_by_text('选择问题查看原文、采样计划和详细指标', exact=True)).to_be_visible()
    page.goto(f'{origin}/?release_view=releaseMonitor&v2_project=1&v2_prompt=44')
    expect(mention_row).to_contain_text('50.0%')
    page.get_by_role('menuitem', name='Validate · 变化比较', exact=True).click()
    for label, run_id in [('基线范围', fixture['baseline_run_id']), ('对照范围', fixture['comparison_run_id'])]:
        control = page.get_by_role('combobox', name=label, exact=True)
        control.press('ArrowDown')
        expect(control).to_have_attribute('aria-expanded', 'true')
        active = page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option-active')
        expect(active).to_have_count(1)
        for _ in range(2):
            if re.match(rf'^Runs {run_id} ·', active.inner_text()):
                break
            control.press('ArrowDown')
        expect(active).to_contain_text(f'Runs {run_id} ·')
        control.press('Enter')
        expect(control).to_have_attribute('aria-expanded', 'false')
        expect(page.locator('.ant-select-dropdown').filter(visible=True)).to_have_count(0)
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
        accessibility_check(page, out, report, f'comparison-{width}')
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
    accessibility_check(page, out, report, 'context-versions')
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
        verified=['WORKER_STOPPED_AND_HEALTH_READ_RECOVERY', 'MONITOR_INDEPENDENT_EXPECTED_COUNTS', 'UNKNOWN_NOT_ZERO', 'FORMAL_UI_COMPARISON',
            'COMPARISON_RELOAD_EXACT_VERSION', 'CONTEXT_TWO_VERSIONS', 'READ_FAILURE_RECOVERY',
            'PROJECT_SWITCH_CLEARS_PREVIOUS_DATA', 'RESPONSIVE_NO_PAGE_OVERFLOW'],
        not_verified=['REAL_SAMPLING', 'REAL_MODEL_QUALITY'], synthetic_runs=2)
    assert not report['errors'], report['errors']


def automatic_check(page, origin, fixture, Session, monkeypatch, out, report):
    from datetime import datetime
    from app.modules.single_prompt_v2.automatic_delivery import execute_task
    from test_automatic_delivery import simulated_delivery_transport
    analysis = fixture['analysis']
    slow_reads = []
    def delayed_first_read(route):
        if route.request.method == 'GET' and not slow_reads:
            slow_reads.append(route.request.url)
            response = route.fetch()
            # Longer than the polling interval: a new poll must not starve this response.
            time.sleep(3.5)
            route.fulfill(response=response)
        else:
            route.continue_()
    task_route = '**/optimization-tasks?*'
    page.route(task_route, delayed_first_read)
    page.goto(f'{origin}/?v2_project=1&v2_prompt=44&v2_analysis={analysis.analysis_id}')
    panel = page.get_by_role('region', name='自动优化交付')
    expect(panel.get_by_role('button', name='开始自动优化', exact=True)).to_be_enabled(timeout=15000)
    assert len(slow_reads) == 1
    page.unroute(task_route, delayed_first_read)
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
    def manuscript_qa(payload):
        return {'checks': [{'segment_id': s['segment_id'],
            'verdict': 'UNSUPPORTED' if '99元' in s['text'] else 'PASS',
            'rationale': '该价格没有来源支持。' if '99元' in s['text'] else '该段是核对建议。'} for s in payload['segments']]}
    calls = simulated_delivery_transport(monkeypatch, qa_response=manuscript_qa)
    execute_task(task_id, session_factory=Session)
    expect(panel.get_by_role('button', name='复制完整正文')).to_be_visible(timeout=15000)
    expect(panel.get_by_text('选用工具前的核对顺序', exact=False)).to_be_visible()
    assert len(calls) == 4
    page.reload()
    expect(panel.get_by_role('button', name='复制完整正文')).to_be_visible(timeout=15000)
    persisted = page.request.get(f'{origin}/api/v2/single-prompt/optimization-tasks/{task_id}/deliveries?project_id=1&prompt_id=44')
    assert persisted.ok
    expected_body = persisted.json()[0]['output']['publication_draft']['body_markdown']
    page.context.grant_permissions(['clipboard-read', 'clipboard-write'], origin=origin)
    copy_button = panel.get_by_role('button', name='复制完整正文', exact=True)
    copy_button.focus()
    expect(copy_button).to_be_focused()
    copy_button.press('Enter')
    expect(page.get_by_text('正文已复制', exact=True)).to_be_visible()
    assert page.evaluate('navigator.clipboard.readText()') == expected_body
    expect(panel.get_by_text('已记录 token', exact=True)).to_be_visible()
    expect(page.locator('.v2-advanced-details')).not_to_have_attribute('open', '')
    panel.get_by_text(re.compile(r'^质量问题与实际修复')).click()
    expect(panel.get_by_text('本次检查未发现问题，未进行修复', exact=True)).to_be_visible()
    page.get_by_text('原始资料、人工纠错与高级审计', exact=True).click()
    expect(page.locator('.v2-advanced-details')).to_have_attribute('open', '')
    page.get_by_text('原始资料、人工纠错与高级审计', exact=True).click()
    panel.get_by_role('button', name='编辑正文并复检', exact=True).click()
    editor = page.get_by_role('dialog', name='编辑正文', exact=True)
    editor.get_by_role('button', name='增加建议段落', exact=True).click()
    editor.get_by_label('正文 1.2', exact=True).fill('目标产品价格为99元。')
    page.set_viewport_size({'width': 390, 'height': 1000})
    accessibility_check(page, out, report, 'manuscript-editor-390')
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.screenshot(path=str(out / 'manuscript-editor-390.png'), full_page=True)
    report['screenshots'].append('manuscript-editor-390.png')
    with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/draft-revisions')) as response:
        editor.get_by_role('button', name='保存修改并排队复检', exact=True).click()
    revised_task = response.value.json()['task_id']
    expect(editor).not_to_be_visible()
    execute_task(revised_task, session_factory=Session)
    assert len(calls) == 4
    page.reload()
    expect(panel.get_by_text('正文修改复检：沿用原始分析与证据，只检查本次修改稿', exact=True)).to_be_visible()
    panel.get_by_text('本次提交的修改原文（不继承旧稿资格）', exact=True).click()
    expect(panel.get_by_text('目标产品价格为99元。', exact=True)).to_be_visible()
    expect(panel.get_by_role('button', name='复制完整正文')).to_have_count(0)
    panel.get_by_role('button', name='授权本任务模型调用').click()
    auth = page.get_by_role('dialog', name='本任务独立调用授权')
    for label, value in [('请求次数上限', '1'), ('总 token 上限', '100000'), ('人民币硬预算', '1'),
            ('输入 / 输出每百万 token 的较高保守单价（人民币）', '10'),
            ('已核实计费依据', '隔离工程模拟价格，不是真实调用授权'),
            ('计费核实日期', datetime.utcnow().date().isoformat())]:
        auth.get_by_label(label, exact=True).fill(value)
    auth.get_by_role('button', name='确认授权并继续', exact=True).click()
    expect(auth).not_to_be_visible()
    execute_task(revised_task, session_factory=Session)
    expect(panel.get_by_role('button', name='复制完整正文')).to_be_visible(timeout=15000)
    assert len(calls) == 5 and 'segments' in calls[-1]
    new_delivery = page.request.get(f'{origin}/api/v2/single-prompt/optimization-tasks/{revised_task}/deliveries?project_id=1&prompt_id=44').json()[0]
    assert new_delivery['result_version'] != persisted.json()[0]['result_version']
    assert '99元' not in new_delivery['output']['publication_draft']['body_markdown']
    assert page.request.get(f'{origin}/api/v2/single-prompt/optimization-tasks/{task_id}/deliveries?project_id=1&prompt_id=44').json() == persisted.json()
    panel.get_by_text(re.compile(r'^质量问题与实际修复')).click()
    expect(panel.get_by_role('cell', name='已删除不成立陈述', exact=True)).to_be_visible()
    expect(panel.get_by_role('cell', name='该价格没有来源支持。', exact=True)).to_be_visible()
    page.reload()
    expect(panel.get_by_role('button', name='复制完整正文')).to_be_visible(timeout=15000)
    panel.get_by_text(re.compile(r'^质量问题与实际修复')).click()
    expect(panel.get_by_role('cell', name='已删除不成立陈述', exact=True)).to_be_visible()
    for width in [1440, 1024, 390]:
        page.set_viewport_size({'width': width, 'height': 1000})
        panel.scroll_into_view_if_needed()
        path = f'optimize-{width}.png'
        page.screenshot(path=str(out / path), full_page=False)
        report['screenshots'].append(path)
        accessibility_check(page, out, report, f'optimize-{width}')
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), f'page overflow: {width}'
    page.set_viewport_size({'width': 1440, 'height': 1000})
    held = []
    def hold_analysis(route):
        held.append((route, route.fetch()))
    analysis_route = f'**/analyses/{analysis.analysis_id}?*'
    page.route(analysis_route, hold_analysis)
    page.get_by_role('button', name='刷新分析状态', exact=True).click()
    page.get_by_role('button', name='新建项目', exact=True).click()
    dialog = page.get_by_role('dialog')
    dialog.get_by_label('项目名称', exact=True).fill('延迟请求隔离项目')
    dialog.get_by_label('品牌名称', exact=True).fill('新品牌')
    dialog.get_by_role('button', name=re.compile('创.*建')).click()
    expect(dialog).not_to_be_visible()
    expect(panel).to_have_count(0)
    assert held, 'Delayed real analysis response was not captured'
    for route, response in held:
        route.fulfill(response=response)
    page.unroute(analysis_route, hold_analysis)
    page.wait_for_timeout(250)
    expect(panel).to_have_count(0)
    assert analysis.analysis_id not in page.url and 'v2_project=1&' not in page.url
    report.update(verified=['UI_OPTIMIZE_CREATE', 'STABLE_QUEUED_ACTION', 'CACHE_MISS_NOT_FAILURE',
        'EXPLICIT_BUDGET_AUTHORIZATION', 'WORKER_EXISTING_STAGE_CHAIN', 'ACTUAL_DRAFT_AND_QA_READ',
        'REFRESH_PRESERVES_EXACT_RESULT', 'SLOW_POLL_DOES_NOT_STARVE', 'ACTUAL_QA_EMPTY_REPAIRS', 'ADVANCED_AUDIT_OPT_IN',
        'KEYBOARD_COPY_EXACT_SAVED_BODY_NO_AUDIT_METADATA',
        'EDIT_SAVED_PENDING_WITHOUT_OLD_QUALIFICATION', 'ONE_QA_ONLY_NO_ANSWER_OR_CITATION_RECOMPUTE',
        'EDIT_REPAIR_NEW_VERSION_AND_OLD_RESULT_IMMUTABLE',
        'LATE_ANALYSIS_RESPONSE_CANNOT_RESTORE_OLD_PROJECT', 'RESPONSIVE_NO_PAGE_OVERFLOW'],
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
            create_button = page.get_by_role('button', name='新建项目', exact=True)
            create_button.focus()
            create_button.press('Enter')
            dialog = page.get_by_role('dialog')
            expect(dialog).to_be_visible()
            accessibility_check(page, out, report, 'create-project-dialog')
            page.keyboard.press('Escape')
            expect(dialog).not_to_be_visible()
            expect(create_button).to_be_focused()
            create_button.press('Enter')
            expect(dialog).to_be_visible()
            dialog.get_by_label('项目名称', exact=True).fill('隔离验收项目')
            dialog.get_by_label('品牌名称', exact=True).fill('测试过滤器')
            dialog.get_by_role('button', name=re.compile('创.*建')).click()
            expect(dialog).not_to_be_visible()
            page.get_by_role('menuitem', name='问题与采样配置', exact=True).click()
            page.screenshot(path=str(out / 'prompt-entry.png'), full_page=True)
            (out / 'prompt-entry.txt').write_text(page.locator('body').inner_text())
            page.get_by_label('问题原文', exact=True).fill('空气过滤器如何清洗？\n有哪些前提条件？')
            page.get_by_label('意图', exact=True).select_option('usage_instruction')
            page.get_by_role('button', name='创建问题', exact=True).click()
            expect(page.get_by_role('cell', name='空气过滤器如何清洗？ 有哪些前提条件？', exact=True)).to_be_visible()
            page.get_by_role('button', name='编辑问题1', exact=True).click()
            page.get_by_label('问题组（可选）', exact=True).fill('维护')
            page.get_by_label('业务优先级（1最低，5最高）', exact=True).fill('5')
            page.get_by_role('button', name='保存问题', exact=True).click()
            expect(page.get_by_role('cell', name='维护', exact=True)).to_be_visible()
            accessibility_check(page, out, report, 'prompt-editor')
            page.get_by_label('搜索问题或问题组', exact=True).fill('不存在的问题')
            expect(page.get_by_role('cell', name='维护', exact=True)).to_have_count(0)
            page.get_by_label('搜索问题或问题组', exact=True).fill('维护')
            expect(page.get_by_role('cell', name='维护', exact=True)).to_be_visible()
            page.get_by_role('button', name='停用', exact=True).click()
            expect(page.get_by_role('cell', name='已停用', exact=True)).to_be_visible()
            page.reload()
            expect(page.get_by_role('cell', name='已停用', exact=True)).to_be_visible()
            page.get_by_role('menuitem', name='Optimize · 分析与稿件', exact=True).click()
            expect(page.get_by_role('button', name='开始首次采样', exact=True)).to_be_disabled()
            expect(page.get_by_text('问题已停用：不再发起新采样，历史样本和已有分析仍可使用', exact=True)).to_be_visible()
            page.get_by_role('menuitem', name='问题与采样配置', exact=True).click()
            page.get_by_role('button', name='启用', exact=True).click()
            expect(page.get_by_role('cell', name='可用', exact=True)).to_be_visible()
            page.get_by_label('问题原文', exact=True).fill('误建且未使用的问题')
            with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/prompts')) as response:
                page.get_by_role('button', name='创建问题', exact=True).click()
            unused = response.value.json()['id']
            expect(page.get_by_role('cell', name='误建且未使用的问题', exact=True)).to_be_visible()
            page.get_by_role('button', name=f'删除问题{unused}', exact=True).click()
            page.get_by_role('button', name='确认删除', exact=True).click()
            expect(page.get_by_role('cell', name='误建且未使用的问题', exact=True)).to_have_count(0)
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
            confirm_pause = page.get_by_role('button', name='确认暂停', exact=True)
            expect(confirm_pause).to_be_visible()
            confirm_pause.focus()
            with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/pause')) as response:
                confirm_pause.press('Enter')
            assert response.value.ok
            expect(page.get_by_role('cell', name='已暂停', exact=True)).to_be_visible()
            for width in [1440, 1024, 390]:
                page.set_viewport_size({'width': width, 'height': 1000})
                path = f'monitor-{width}.png'
                page.screenshot(path=str(out / path), full_page=True)
                report['screenshots'].append(path)
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), f'page overflow: {width}'
                accessibility_check(page, out, report, f'monitor-schedule-{width}')
            navigation = page.get_by_role('button', name='展开主导航', exact=True)
            navigation.focus()
            navigation.press('Enter')
            expect(page.get_by_role('menuitem', name='问题与采样配置', exact=True)).to_be_visible()
            page.get_by_role('button', name='收起主导航', exact=True).press('Escape')
            expect(navigation).to_be_focused()
            navigation.press('Enter')
            page.get_by_role('menuitem', name='问题与采样配置', exact=True).click()
            expect(navigation).to_have_attribute('aria-expanded', 'false')
            page.get_by_role('button', name='批量添加问题', exact=True).click()
            batch = page.get_by_role('dialog', name='批量添加问题', exact=True)
            batch.get_by_label('问题 1', exact=True).fill('空气过滤器如何清洗？\n有哪些前提条件？')
            batch.get_by_role('button', name=re.compile('增加问题')).click()
            batch.get_by_label('问题 2', exact=True).fill('过滤器如何存放？\n潮湿环境有哪些限制？')
            batch.get_by_role('button', name=re.compile('增加问题')).click()
            with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/prompts/batch')) as response:
                batch.get_by_role('button', name='提交待处理问题（3）', exact=True).click()
            items = response.value.json()['items']
            assert [item['status'] for item in items] == ['EXISTING', 'CREATED', 'REJECTED']
            expect(batch.get_by_text('未创建', exact=True)).to_be_visible()
            accessibility_check(page, out, report, 'batch-prompts-error-390')
            batch.get_by_label('问题 3', exact=True).fill('过滤器寿命由什么因素决定？')
            with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/prompts/batch')) as response:
                batch.get_by_role('button', name='提交待处理问题（1）', exact=True).click()
            assert [item['status'] for item in response.value.json()['items']] == ['CREATED']
            expect(batch.get_by_role('button', name='提交待处理问题（0）', exact=True)).to_be_disabled()
            accessibility_check(page, out, report, 'batch-prompts-390')
            page.screenshot(path=str(out / 'batch-prompts-390.png'), full_page=True)
            report['screenshots'].append('batch-prompts-390.png')
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            batch.get_by_role('button', name='关闭批量添加', exact=True).click()
            page.reload()
            expect(page.get_by_role('cell', name='过滤器如何存放？ 潮湿环境有哪些限制？', exact=True)).to_be_visible()
            prompts = page.request.get(f'{origin}/api/projects/1/prompts').json()
            assert len(prompts) == 3
            assert next(item for item in prompts if item['id'] == items[1]['prompt_id'])['prompt_text'] == '过滤器如何存放？\n潮湿环境有哪些限制？'
            report['verified'] = ['UI_PROJECT_CREATE', 'MULTILINE_PROMPT_PRESERVED', 'PROMPT_EDIT_SEARCH_PRIORITY',
                'BATCH_PROMPT_PARTIAL_FAILURE_CORRECTION_DUPLICATE_REUSE_RELOAD',
                'NARROW_NAV_KEYBOARD_OPEN_ESCAPE_AND_SELECTION_CLOSE',
                'DELETE_UNUSED_PROMPT',
                'KEYBOARD_DIALOG_OPEN_ESCAPE_FOCUS_RESTORED',
                'DISABLED_PROMPT_PERSISTS_AND_BLOCKS_NEW_SAMPLING', 'PROMPT_REENABLE', 'CONTEXT_SAVE_RELOAD',
                'SCHEDULE_CREATE_PAUSE', 'FINITE_OPTIONAL_OPTIMIZE_AUTHORITY', 'RESPONSIVE_NO_PAGE_OVERFLOW']
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
