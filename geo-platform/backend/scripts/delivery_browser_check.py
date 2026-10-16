"""Offline browser acceptance against a freshly migrated, isolated release DB.

``--joint-readonly`` is deliberately separate from the synthetic fixture modes
below.  It opens an already populated *isolated* release database and only
exercises GET routes in a loopback browser.  It is intended for the joint T07
/ T21 handoff, not for creating test data or re-running a comparison.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import re
import subprocess
import sys
import time
from contextlib import ExitStack
from urllib.request import build_opener, ProxyHandler
from urllib.parse import quote

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
# Direct invocation sets sys.path to backend/scripts, but the joint gate also
# reuses the existing scripts.release_upgrade_check read-only fingerprint.
# Keep the backend package root available without relying on caller cwd.
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))


def _file_hashes(database: Path) -> dict[str, str | None]:
    """Return stable fingerprints without opening or changing the database."""
    hashes: dict[str, str | None] = {}
    for path in (database, Path(f"{database}-wal"), Path(f"{database}-shm")):
        if path.exists():
            hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            hashes[str(path)] = None
    return hashes


def _copy_sqlite_artifact(source: Path, destination: Path) -> Path:
    """Copy the SQLite main file and any WAL sidecars without opening source."""
    shutil.copyfile(source, destination)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{source}{suffix}")
        if sidecar.exists():
            shutil.copyfile(sidecar, Path(f"{destination}{suffix}"))
    return destination


def _joint_readonly_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only localhost browser acceptance for an isolated joint release DB.")
    parser.add_argument("--joint-readonly", action="store_true")
    parser.add_argument("--database", required=True, type=Path,
                        help="Existing isolated release SQLite database; never migrated or seeded.")
    parser.add_argument("--project-id", required=True, type=int)
    parser.add_argument("--t07-prompt-id", required=True, type=int,
                        help="First populated Prompt used for Monitor switching.")
    parser.add_argument("--t07-other-prompt-id", required=True, type=int,
                        help="Second populated Prompt in the same project.")
    parser.add_argument("--t21-prompt-id", required=True, type=int,
                        help="Prompt that owns --comparison-id.")
    parser.add_argument("--comparison-id", required=True,
                        help="Saved observation comparison result_version, not a latest lookup.")
    parser.add_argument("--artifact-dir", type=Path,
                        help="Optional writable directory for the read-only evidence report.")
    return parser.parse_args(argv)


def _local_json(opener, url: str):
    with opener.open(url, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"Unexpected read status {response.status}: {url}")
        return json.loads(response.read().decode("utf-8"))


def joint_readonly_browser_check(args: argparse.Namespace) -> None:
    """Validate saved T07/T21 UI state without permitting a durable write."""
    database = args.database.expanduser().resolve()
    if not database.is_file():
        raise RuntimeError(f"Joint release database does not exist: {database}")
    if len({args.t07_prompt_id, args.t07_other_prompt_id}) != 2:
        raise RuntimeError("T07 browser switching requires two distinct Prompt IDs")
    if args.project_id < 1 or args.t21_prompt_id < 1:
        raise RuntimeError("Project and Prompt IDs must be positive")
    if not (ROOT / "frontend/dist/index.html").is_file():
        raise RuntimeError("Release frontend is not built; run `cd frontend && npm run build` first")

    from datetime import datetime, timezone
    out = args.artifact_dir or ROOT / "backend/artifacts/acceptance" / (
        "joint-readonly-browser-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    source_before = _file_hashes(database)
    # SQLite's WAL setup may legitimately create sidecars.  It must happen to
    # this disposable copy, never to the evidence source supplied by the joint
    # run.  Copy both sidecars as a coherent SQLite artifact where they exist.
    runtime_database = _copy_sqlite_artifact(database, out / "runtime-release.db")
    from scripts.release_upgrade_check import business_fingerprint
    runtime_business_before = business_fingerprint(runtime_database)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    # No access config means release access is explicitly LOCAL_ONLY.  The
    # worker is never launched, and browser routing rejects every non-loopback
    # resource before it can leave the browser.
    env = {**os.environ, "GEO_RELEASE_DATABASE_URL": f"sqlite:///{runtime_database}", "MONITORING_WORKER": "0"}
    # A caller's invitation config could require an unavailable credential and
    # is outside this local-only acceptance scope.
    env.pop("GEO_RELEASE_ACCESS_CONFIG", None)
    report = {"scope": "JOINT_ISOLATED_READ_ONLY_BROWSER", "database": str(database),
              "runtime_database": str(runtime_database),
              "project_id": args.project_id, "t07_prompt_ids": [args.t07_prompt_id, args.t07_other_prompt_id],
              "t21_prompt_id": args.t21_prompt_id, "comparison_id": args.comparison_id,
              "external_calls": 0, "methods": [], "screenshots": [], "status": "FAIL", "usage": "UNKNOWN"}
    log = (out / "api.log").open("w")
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.release_main:app", "--host", "127.0.0.1", "--port", str(port)],
                              cwd=ROOT / "backend", env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        opener = build_opener(ProxyHandler({}))
        for _ in range(120):
            if server.poll() is not None:
                raise RuntimeError("Joint release API exited; inspect api.log")
            try:
                _local_json(opener, origin + "/api/health")
                break
            except OSError:
                time.sleep(.25)
        else:
            raise RuntimeError("Joint release API not ready")

        prefix = f"/api/v2/projects/{args.project_id}/prompts/"
        monitor_a = _local_json(opener, origin + prefix + f"{args.t07_prompt_id}/monitor")
        monitor_b = _local_json(opener, origin + prefix + f"{args.t07_other_prompt_id}/monitor")
        comparison = _local_json(opener, origin + prefix + f"{args.t21_prompt_id}/observation-comparisons/{args.comparison_id}")
        if monitor_a["prompt"]["id"] != args.t07_prompt_id or monitor_b["prompt"]["id"] != args.t07_other_prompt_id:
            raise RuntimeError("T07 Prompt ownership mismatch in supplied DB")
        runs_a = {row["run_id"] for row in monitor_a["runs"]}
        runs_b = {row["run_id"] for row in monitor_b["runs"]}
        if runs_a & runs_b:
            raise RuntimeError("T07 supplied Prompt pools overlap; cannot prove Prompt isolation")
        if comparison["result_version"] != args.comparison_id:
            raise RuntimeError("T21 comparison identity mismatch")
        if not comparison.get("input", {}).get("baseline") or not comparison["input"].get("comparison"):
            raise RuntimeError("T21 saved comparison lacks its two fixed scope identities")

        with sync_playwright() as playwright, ExitStack() as cleanup:
            browser = playwright.chromium.launch(headless=True, channel="chrome")
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            cleanup.callback(browser.close)
            requests: list[dict[str, str]] = []
            def only_local_get(route):
                request = route.request
                requests.append({"method": request.method, "url": request.url})
                if request.method != "GET" or not request.url.startswith(origin + "/"):
                    route.abort()
                else:
                    route.continue_()
            context.route("**/*", only_local_get)
            page = context.new_page()
            page_errors: list[str] = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))

            def monitor_url(prompt_id: int) -> str:
                return f"{origin}/?release_view=releaseMonitor&v2_project={args.project_id}&v2_prompt={prompt_id}"
            page.goto(monitor_url(args.t07_prompt_id), wait_until="networkidle")
            expect(page.get_by_text("按日期观察（UTC）", exact=True)).to_be_visible()
            expect(page.get_by_text("趋势按各日期各自冻结的 Run 范围展示；范围或 Prompt 版本不同的记录不会被静默合并为同一口径。", exact=True)).to_be_visible()
            expect(page.get_by_text(f"累计采样尝试 {monitor_a['pool_count']} 条", exact=False)).to_be_visible()
            prompt_control = page.get_by_role("combobox", name="当前问题", exact=True)
            expect(prompt_control).to_be_visible()
            # Ant Design puts the accessible combobox input beneath a visual
            # selector.  Open that visible selector rather than forcing a
            # click through the selection-item overlay.
            prompt_selector = page.locator(".prompt-select .ant-select-selector")
            expect(prompt_selector).to_be_visible()
            prompt_selector.click()
            expect(prompt_control).to_have_attribute("aria-expanded", "true")
            page.get_by_text(f"#{args.t07_other_prompt_id} {monitor_b['prompt']['text']}", exact=True).filter(visible=True).click()
            expect(page).to_have_url(re.compile(rf"v2_prompt={args.t07_other_prompt_id}(?:&|$)"))
            expect(page.get_by_text(f"累计采样尝试 {monitor_b['pool_count']} 条", exact=False)).to_be_visible()
            expect(page.get_by_text("按日期观察（UTC）", exact=True)).to_be_visible()
            page.reload(wait_until="networkidle")
            expect(page).to_have_url(re.compile(rf"v2_prompt={args.t07_other_prompt_id}(?:&|$)"))
            expect(page.get_by_text(f"累计采样尝试 {monitor_b['pool_count']} 条", exact=False)).to_be_visible()
            monitor_screenshot = "monitor-switch-refresh.png"
            page.screenshot(path=str(out / monitor_screenshot), full_page=True)
            report["screenshots"].append(monitor_screenshot)

            compare_url = (f"{origin}/?release_view=releaseCompare&v2_project={args.project_id}"
                           f"&v2_prompt={args.t21_prompt_id}&observation_result={quote(args.comparison_id, safe='')}")
            page.goto(compare_url, wait_until="networkidle")
            identity = comparison["input"].get("identity", {})
            expect(page.get_by_role("region", name="本结果测量身份")).to_contain_text(identity.get("canonical_brand_name", ""))
            fixed = page.get_by_role("region", name="固定范围身份")
            expect(fixed).to_contain_text(comparison["input"]["baseline"]["context_id"])
            expect(fixed).to_contain_text(comparison["input"]["comparison"]["context_id"])
            expect(page.get_by_text("当前展示的是保存时的测量身份；项目配置更新不会改写此结果。", exact=True)).to_be_visible()
            expect(page.get_by_role("combobox", name="历史比较", exact=True)).to_have_value(args.comparison_id)
            page.reload(wait_until="networkidle")
            expect(page).to_have_url(re.compile(re.escape("observation_result=" + quote(args.comparison_id, safe=""))))
            expect(page.get_by_role("region", name="本结果测量身份")).to_contain_text(identity.get("canonical_brand_name", ""))
            expect(page.get_by_role("region", name="固定范围身份")).to_contain_text(comparison["input"]["baseline"]["context_id"])
            comparison_screenshot = "saved-comparison-refresh.png"
            page.screenshot(path=str(out / comparison_screenshot), full_page=True)
            report["screenshots"].append(comparison_screenshot)
            if page_errors:
                raise RuntimeError("Browser page errors: " + "; ".join(page_errors))
            if any(item["method"] != "GET" or not item["url"].startswith(origin + "/") for item in requests):
                raise RuntimeError("Browser attempted a non-GET or non-localhost request")
            report.update(status="PASS_T07_T21_READ_ONLY", t07={
                "prompt_a_pool_count": monitor_a["pool_count"], "prompt_b_pool_count": monitor_b["pool_count"],
                "run_pool_overlap": False, "switch_refresh_preserved": True, "trend_visible": True},
                t21={"result_version": comparison["result_version"], "output_hash": comparison["output_hash"],
                     "baseline_context_id": comparison["input"]["baseline"]["context_id"],
                     "comparison_context_id": comparison["input"]["comparison"]["context_id"],
                     "refresh_preserved": True, "saved_identity_visible": True}, methods=sorted({r["method"] for r in requests}))
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill(); server.wait(timeout=10)
        log.close()
        source_after = _file_hashes(database)
        runtime_business_after = business_fingerprint(runtime_database)
        report["source_database_hash_before"] = source_before
        report["source_database_hash_after"] = source_after
        report["source_database_unchanged"] = source_before == source_after
        report["runtime_business_fingerprint_before"] = runtime_business_before
        report["runtime_business_fingerprint_after"] = runtime_business_after
        report["runtime_business_tables_unchanged"] = runtime_business_before == runtime_business_after
        if source_before != source_after:
            report["status"] = "FAIL_SOURCE_DATABASE_CHANGED"
        if runtime_business_before != runtime_business_after:
            report["status"] = "FAIL_RUNTIME_BUSINESS_DATA_CHANGED"
        (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["source_database_unchanged"]:
        raise RuntimeError(f"Read-only acceptance changed source database bytes; inspect {out / 'report.json'}")
    if not report["runtime_business_tables_unchanged"]:
        raise RuntimeError(f"Read-only acceptance changed runtime business data; inspect {out / 'report.json'}")
    if report["status"] != "PASS_T07_T21_READ_ONLY":
        raise RuntimeError(f"Joint browser acceptance did not pass; inspect {out / 'report.json'}")
    print(json.dumps(report, ensure_ascii=False))


def saved_detail_failure_check(page, report, expected_body):
    detail = page.locator('#v2-execution')
    article = detail.get_by_role('article', name='方案详情完整正文')
    exact_url = page.url
    for endpoint in ['strategy-readiness', 'qualification-projection']:
        pattern = f'**/{endpoint}?*'
        failures = []
        def fail(route):
            failures.append(route.request.url)
            route.fulfill(status=503, content_type='application/json', body=json.dumps({'detail': '隔离资格读取故障'}))
        page.route(pattern, fail)
        try:
            page.reload()
            expect(article).to_contain_text(expected_body, timeout=15000)
            expect(page).to_have_url(exact_url)
            expect(page.get_by_text('当前资格暂不可用，已保存稿件仍可查看', exact=True)).to_be_visible()
            expect(page.get_by_role('button', name='固化策略并继续', exact=True)).to_have_count(0)
            assert failures
        finally:
            page.unroute(pattern, fail)
        page.get_by_role('button', name='重试读取资格', exact=True).click()
        expect(page.get_by_text('当前资格暂不可用，已保存稿件仍可查看', exact=True)).to_have_count(0)
        expect(page.get_by_text('机器分析已自动到达策略和执行草案', exact=True)).to_be_visible(timeout=15000)
        expect(article).to_contain_text(expected_body)
        report.setdefault('saved_detail_read_recovery', []).append(endpoint)
    from urllib.parse import urlsplit, parse_qs
    strategy_id = parse_qs(urlsplit(exact_url).query)['v2_strategy'][0]
    pattern = f'**/diagnoses/*/strategies/{strategy_id}?*'
    def unavailable(route):
        route.fulfill(status=404, content_type='application/json', body=json.dumps({'detail': '隔离策略归属不匹配'}))
    page.route(pattern, unavailable)
    try:
        page.reload()
        expect(detail.get_by_text('无法读取已保存策略与稿件', exact=True)).to_be_visible(timeout=15000)
        expect(article).to_have_count(0)
        expect(detail.get_by_role('button', name='生成完整执行方案与稿件')).to_have_count(0)
        expect(page).to_have_url(exact_url)
    finally:
        page.unroute(pattern, unavailable)
    detail.get_by_role('button', name='重试读取结果', exact=True).click()
    expect(article).to_contain_text(expected_body, timeout=15000)
    report['saved_detail_missing_strategy_refused'] = True


def accessibility_check(page, out, report, name):
    page.wait_for_function("""() => document.fonts.status === 'loaded' &&
        document.getAnimations().every(a => a.playState !== 'running' ||
            a.playbackRate === 0 || !Number.isFinite(a.effect.getComputedTiming().endTime))
    """, timeout=10000)
    trigger = page.locator('.side-nav.ant-layout-sider-collapsed .ant-layout-sider-zero-width-trigger')
    if page.viewport_size['width'] < 768 and trigger.count() and trigger.is_visible():
        header_box = page.locator('.app-shell .topbar').bounding_box()
        button_box = trigger.bounding_box()
        assert header_box and button_box
        assert header_box['y'] <= button_box['y'] and (
            button_box['y'] + button_box['height'] <= header_box['y'] + header_box['height']
        ), ('Mobile navigation overlays content outside header', header_box, button_box)
        report.setdefault('navigation_geometry_checks', []).append({
            'page': name, 'scroll_y': page.evaluate('window.scrollY'),
            'header': header_box, 'trigger': button_box})
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


def access_check(page, origin, fixture, out, report):
    from scripts.release_upgrade_check import business_fingerprint
    page.goto(origin + '/')
    expect(page.get_by_role('heading', name='GEO 项目登录')).to_be_visible()
    assert page.request.get(origin + '/api/projects').status == 401
    expect(page.locator('body')).not_to_contain_text('FORBIDDEN_PROJECT_TITLE')
    page.get_by_label('访问凭证', exact=True).fill('incorrect-credential-0123456789-0123456789')
    page.get_by_role('button', name='登录', exact=True).press('Enter')
    expect(page.get_by_text('访问凭证无效', exact=True)).to_be_visible()
    for width in [1440, 390]:
        page.set_viewport_size({'width': width, 'height': 1000})
        accessibility_check(page, out, report, f'login-error-{width}')
        name = f'login-error-{width}.png'
        page.screenshot(path=str(out / name), full_page=True)
        report['screenshots'].append(name)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.set_viewport_size({'width': 1440, 'height': 1000})
    page.get_by_label('访问凭证', exact=True).fill(fixture['access_key'])
    page.get_by_role('button', name='登录', exact=True).press('Enter')
    expect(page.get_by_role('button', name='退出登录', exact=True)).to_be_visible()
    expect(page.get_by_role('combobox', name='当前项目', exact=True)).to_be_visible()
    assert [v['id'] for v in page.request.get(origin + '/api/projects').json()] == [1]
    page.reload()
    expect(page.get_by_role('button', name='退出登录', exact=True)).to_be_visible()
    page.goto(origin + '/?release_view=brandContext&v2_project=2')
    expect(page.get_by_role('button', name='退出登录', exact=True)).to_be_visible()
    expect(page.locator('body')).not_to_contain_text('FORBIDDEN_PROJECT_TITLE')
    assert page.request.get(origin + '/api/v2/projects/2/brand-contexts').status == 403
    page.get_by_role('button', name='退出登录', exact=True).click()
    expect(page.get_by_role('heading', name='GEO 项目登录')).to_be_visible()
    expect(page.get_by_role('combobox', name='当前项目', exact=True)).to_have_count(0)
    assert page.request.get(origin + '/api/projects').status == 401
    page.get_by_label('访问凭证', exact=True).fill(fixture['access_key'])
    page.get_by_role('button', name='登录', exact=True).press('Enter')
    expect(page.get_by_role('button', name='退出登录', exact=True)).to_be_visible()
    fixture['account']['enabled'] = False
    fixture['access_path'].write_text(json.dumps({'accounts': [fixture['account']]}))
    page.reload()
    expect(page.get_by_role('heading', name='GEO 项目登录')).to_be_visible()
    expect(page.get_by_role('combobox', name='当前项目', exact=True)).to_have_count(0)
    assert page.request.get(origin + '/api/projects').status == 401
    accessibility_check(page, out, report, 'revoked-session')
    report['verified'] = ['UNAUTHENTICATED_NO_DATA', 'INVALID_KEY_VISIBLE', 'KEYBOARD_LOGIN',
        'SCOPED_PROJECT_LIST', 'REFRESH_SESSION', 'FOREIGN_DEEP_LINK_NO_DATA',
        'LOGOUT_REMOVES_OLD_APP', 'REVOKED_SESSION_REMOVES_OLD_APP', 'BUSINESS_TABLES_UNCHANGED']
    assert business_fingerprint(out / 'isolated.db') == fixture['business_before']
    assert not report['errors'], report['errors']
    report['status'] = 'PASS_ISOLATED_INVITATION_NOT_REMOTE_TLS_DEPLOYMENT'


def select_comparison_scope(page, label, run_ids):
    control = page.get_by_role('combobox', name=label, exact=True)
    control.press('ArrowDown')
    expect(control).to_have_attribute('aria-expanded', 'true')
    list_id = control.get_attribute('aria-controls')
    assert list_id, f'{label} has no associated option list'
    # Ant Select keeps the preceding popup mounted during its close animation.
    dropdown = page.locator('.ant-select-dropdown').filter(
        has=page.locator(f'[id={json.dumps(list_id)}]'))
    expect(dropdown).to_have_count(1)
    expect(dropdown).to_be_visible()
    active = dropdown.locator('.ant-select-item-option-active')
    expect(active).to_have_count(1)
    prefix = 'Runs ' + '、'.join(map(str, run_ids)) + ' ·'
    for _ in range(2):
        if prefix in active.inner_text():
            break
        control.press('ArrowDown')
    expect(active).to_contain_text(prefix)
    control.press('Enter')
    expect(control).to_have_attribute('aria-expanded', 'false')
    expect(dropdown).not_to_be_visible()


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
        select_comparison_scope(page, label, [run_id])
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
        expect(page.get_by_text(re.compile(rf'Runs {run_id} ·')).filter(visible=True)).to_be_visible()
    for width in [1440, 1024, 390]:
        page.set_viewport_size({'width': width, 'height': 1000})
        name = f'comparison-{width}.png'
        accessibility_check(page, out, report, f'comparison-{width}')
        page.screenshot(path=str(out / name), full_page=True)
        report['screenshots'].append(name)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.set_viewport_size({'width': 1440, 'height': 1000})
    # Reverse two explicit isolated scopes to verify a negative observation is persisted.
    for label, run_id in [('基线范围', fixture['comparison_run_id']), ('对照范围', fixture['baseline_run_id'])]:
        select_comparison_scope(page, label, [run_id])
    with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/observation-comparisons')) as response:
        page.get_by_role('button', name='生成变化比较', exact=True).click()
    negative = response.value.json()
    assert negative['output']['metrics']['brand_mention_rate']['delta_percentage_points'] == -100
    assert negative['result_version'] != saved['result_version']
    page.reload()
    expect(page.get_by_role('row').filter(has_text='正文提及')).to_contain_text('-100')
    identity = page.get_by_role('region', name='本结果测量身份')
    expect(identity).to_contain_text('本结果测量身份：Target')
    for brand in ['Target 改版', 'Target']:
        page.get_by_role('button', name='编辑项目', exact=True).click()
        editor = page.get_by_role('dialog', name='编辑项目')
        editor.get_by_label('品牌名称', exact=True).fill(brand)
        editor.get_by_role('button', name=re.compile('^保\\s*存$')).click()
        expect(editor).not_to_be_visible()
        page.reload()
        expect(identity).to_contain_text('本结果测量身份：Target')
        expect(identity).not_to_contain_text('Target 改版')
        expect(page.get_by_role('row').filter(has_text='正文提及')).to_contain_text('-100')
    assert page.request.get(f'{origin}/api/v2/projects/1/prompts/44/observation-comparisons/{negative["result_version"]}').json()['output_hash'] == negative['output_hash']
    page.screenshot(path=str(out / 'negative-comparison.png'), full_page=True)
    report['screenshots'].append('negative-comparison.png')
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
    handoffs = []
    def capture_handoff(route):
        response = route.fetch()
        assert response.status == 201
        handoffs.append(response.json())
        route.fulfill(response=response)
    page.route('**/monitor-analysis', capture_handoff)
    page.get_by_role('button', name='分析这 2 条回答', exact=True).click()
    page.wait_for_url('**/?release_view=coreV2&**', wait_until='domcontentloaded')
    expect(page.get_by_text('来自监测的固定范围：', exact=False)).to_be_visible(timeout=15000)
    handoff = handoffs[0]
    assert handoff['origin_monitor_scope']['selected_run_ids'] == [fixture['baseline_run_id'], fixture['comparison_run_id']]
    assert [r['run_id'] for r in handoff['runs']] == handoff['origin_monitor_scope']['selected_run_ids']
    expect(page.get_by_text('来自监测的固定范围：', exact=False)).to_be_visible()
    expect(page.get_by_role('region', name='自动优化交付').get_by_role('button', name='开始自动优化', exact=True)).to_be_enabled()
    page.reload()
    expect(page.get_by_text('来自监测的固定范围：', exact=False)).to_be_visible(timeout=15000)
    assert f"v2_analysis={handoff['analysis']['analysis_id']}" in page.url
    for width in [1440, 390]:
        page.set_viewport_size({'width': width, 'height': 1000})
        name = f'monitor-handoff-{width}.png'
        accessibility_check(page, out, report, f'monitor-handoff-{width}')
        page.screenshot(path=str(out / name), full_page=True)
        report['screenshots'].append(name)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        primary = page.get_by_role('region', name='自动优化交付').get_by_role('button', name='开始自动优化', exact=True)
        page.evaluate('window.scrollTo(0, 0)')
        bounds = primary.bounding_box()
        assert bounds and 0 <= bounds['y'] and bounds['y'] + bounds['height'] <= 1000
    page.set_viewport_size({'width': 1440, 'height': 1000})
    page.goto(f'{origin}/?release_view=releaseCompare&v2_project={fixture["metric_project_id"]}&v2_prompt={fixture["metric_prompt_id"]}')
    for label, ids in [('基线范围', fixture['metric_baseline']), ('对照范围', fixture['metric_comparison'])]:
        select_comparison_scope(page, label, ids)
    with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/observation-comparisons')) as response:
        page.get_by_role('button', name='生成变化比较', exact=True).click()
    nine = response.value.json()
    nine_metric = nine['output']['metrics']['brand_mention_rate']
    assert nine_metric['baseline']['hit_count'] == 0 and nine_metric['baseline']['evaluable_count'] == 9
    assert nine_metric['comparison']['hit_count'] == 1 and nine_metric['comparison']['evaluable_count'] == 9
    assert abs(nine_metric['delta_percentage_points'] - 11.1111) < .0001
    expect(page.get_by_role('columnheader', name='基线覆盖（可评估 / 有效 / 固定范围）', exact=True)).to_be_visible()
    expect(page.get_by_role('columnheader', name='对照覆盖（可评估 / 有效 / 固定范围）', exact=True)).to_be_visible()
    for width in [1440, 1024, 390]:
        page.set_viewport_size({'width': width, 'height': 1000})
        row = page.get_by_role('row').filter(has_text='正文提及')
        expect(row).to_contain_text('0/9 (0.0%)')
        expect(row).to_contain_text('1/9 (11.1%)')
        expect(row).to_contain_text('11.1111')
        name = f'nine-run-comparison-{width}.png'
        accessibility_check(page, out, report, f'nine-run-comparison-{width}')
        page.screenshot(path=str(out / name), full_page=True)
        report['screenshots'].append(name)
    page.set_viewport_size({'width': 1440, 'height': 1000})
    for label, ids in [('基线范围', fixture['metric_baseline']), ('对照范围', [fixture['conflict_run_id']])]:
        select_comparison_scope(page, label, ids)
    with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/observation-comparisons')) as response:
        page.get_by_role('button', name='生成变化比较', exact=True).click()
    conflict = response.value.json()
    conflict_metric = conflict['output']['metrics']['brand_mention_rate']
    assert (conflict_metric['baseline']['hit_count'], conflict_metric['baseline']['evaluable_count']) == (0, 9)
    assert (conflict_metric['comparison']['hit_count'], conflict_metric['comparison']['evaluable_count']) == (1, 1)
    assert conflict_metric['delta_percentage_points'] is None
    assert 'platform:CONFLICT' in conflict['output']['conflicts']
    for width in [1440, 390]:
        page.set_viewport_size({'width': width, 'height': 1000})
        page.reload()
        row = page.get_by_role('row').filter(has_text='正文提及')
        expect(row).to_contain_text('0/9 (0.0%)')
        expect(row).to_contain_text('1/1 (100.0%)')
        expect(row).to_contain_text('不可比/不可计算')
        expect(page.get_by_text('条件不可比：采样平台不一致', exact=False)).to_be_visible()
        accessibility_check(page, out, report, f'condition-conflict-{width}')
        page.screenshot(path=str(out / f'condition-conflict-{width}.png'), full_page=True)
        report['screenshots'].append(f'condition-conflict-{width}.png')
    report['condition_conflict'] = {'result_version': conflict['result_version'], 'raw_counts_preserved': True,
        'delta_blocked': True, 'warning_visible_after_refresh': True}
    report.update(status='PASS_SCOPED_SYNTHETIC_OBSERVATION_NOT_REAL_SAMPLING', comparison_version=saved['result_version'],
        nine_run_comparison_version=nine['result_version'],
        negative_comparison_version=negative['result_version'], monitor_analysis=handoff['analysis']['analysis_id'],
        verified=['WORKER_STOPPED_AND_HEALTH_READ_RECOVERY', 'MONITOR_INDEPENDENT_EXPECTED_COUNTS', 'UNKNOWN_NOT_ZERO', 'FORMAL_UI_COMPARISON',
            'COMPARISON_RELOAD_EXACT_VERSION', 'CONTEXT_TWO_VERSIONS', 'READ_FAILURE_RECOVERY',
            'NEGATIVE_COMPARISON_PERSISTED', 'MONITOR_EXACT_SCOPE_HANDOFF_WITHOUT_EXTERNAL_WORK',
            'HISTORICAL_MEASUREMENT_IDENTITY_SURVIVES_PROJECT_EDIT',
            'PRIMARY_OPTIMIZE_ACTION_FIRST_VIEWPORT', 'NINE_RUN_ZERO_TO_ONE_INDEPENDENT_COUNTS',
            'PROJECT_SWITCH_CLEARS_PREVIOUS_DATA', 'RESPONSIVE_NO_PAGE_OVERFLOW'],
        not_verified=['REAL_SAMPLING', 'REAL_MODEL_QUALITY'], synthetic_runs=21)
    assert not report['errors'], report['errors']


def automatic_check(page, origin, fixture, Session, monkeypatch, out, report):
    from datetime import datetime
    from app.modules.single_prompt_v2.automatic_delivery import execute_task
    from test_automatic_delivery import simulated_delivery_transport
    analysis = fixture['analysis']
    supplemental = '--supplemental-source' in sys.argv
    official = bool(fixture.get('official_snapshot_id')) or supplemental
    with_context = '--brand-context' in sys.argv
    context_versions = []
    context_texts = ['短链工具选题背景：优先解释团队交接时需要核对的问题。',
                     '短链工具选题背景：优先解释采购前需要核对的问题。']
    unrelated_context = '办公室搬迁安排由行政另行通知。'
    analysis_url = f'{origin}/?v2_project=1&v2_prompt=44&v2_analysis={analysis.analysis_id}'
    def save_context_in_browser(index):
        page.get_by_role('menuitem', name='品牌资料', exact=True).click()
        page.get_by_label('资料标题', exact=True).fill(f'内部选题资料 {index + 1}')
        page.get_by_label('品牌资料正文', exact=True).fill(context_texts[index] + '\n\n' + unrelated_context)
        page.get_by_role('combobox', name='当前问题', exact=True).press('ArrowDown')
        page.get_by_text('全部 Prompt（项目视图）', exact=True).filter(visible=True).click()
        expect(page.get_by_label('资料标题', exact=True)).to_have_value(f'内部选题资料 {index + 1}')
        expect(page.get_by_label('品牌资料正文', exact=True)).to_have_value(context_texts[index] + '\n\n' + unrelated_context)
        with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/brand-contexts')) as saved:
            page.get_by_role('button', name='保存新资料版本', exact=True).click()
        assert saved.value.ok
        context_versions.append(saved.value.json())
        expect(page.get_by_text(f'版本 {index + 1} · 内部选题资料 {index + 1}', exact=True)).to_be_visible()
    if with_context:
        page.goto(analysis_url)
        save_context_in_browser(0)
    if supplemental:
        from app.modules.single_prompt_v2.supplemental_sources import execute_source
        from test_delivery_supplemental_sources import fetched, URL
        page.goto(analysis_url)
        page.get_by_role('button', name='编辑项目', exact=True).click()
        editor = page.get_by_role('dialog', name='编辑项目')
        editor.get_by_label('品牌官网', exact=True).fill('https://example.com')
        editor.get_by_role('button', name=re.compile('^保\\s*存$')).click()
        expect(editor).not_to_be_visible()
        page.get_by_role('menuitem', name='品牌资料', exact=True).click()
        region = page.get_by_role('region', name='补充公开资料', exact=True)
        region.get_by_label('公开页面 URL', exact=True).fill(URL)
        region.get_by_role('checkbox').check()
        with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/supplemental-sources')) as queued:
            region.get_by_role('button', name='获取公开资料', exact=True).click()
        assert queued.value.ok and queued.value.json()['status'] == 'QUEUED'
        extra_id = queued.value.json()['source_id']
        execute_source(extra_id, session_factory=Session, fetcher=lambda urls: [fetched()])
        region.get_by_role('button', name='刷新补充公开资料', exact=True).click()
        expect(region.get_by_text('已获取完整正文', exact=True)).to_be_visible(timeout=15000)
        page.reload()
        expect(region.get_by_text('已获取完整正文', exact=True)).to_be_visible()
        fixture['official_snapshot_id'] = extra_id
    initial_requests = 6 if official else 4
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
    context_route = f'{origin}/api/v2/projects/1/brand-contexts'
    page.route(context_route, lambda route: route.fulfill(status=503, content_type='application/json',
        body='{"detail":"隔离验收：品牌资料暂不可读"}'))
    page.goto(analysis_url)
    panel = page.get_by_role('region', name='自动优化交付')
    expect(panel.get_by_role('button', name='开始自动优化', exact=True)).to_be_enabled(timeout=15000)
    assert len(slow_reads) == 1
    page.unroute(task_route, delayed_first_read)
    expect(panel.get_by_text('品牌资料读取失败', exact=True)).to_be_visible()
    expect(panel.get_by_role('combobox', name='补充品牌资料版本', exact=True)).to_be_disabled()
    page.unroute(context_route)
    panel.get_by_role('button', name='刷新品牌资料版本', exact=True).click()
    expect(panel.get_by_role('combobox', name='补充品牌资料版本', exact=True)).to_be_enabled()
    expect(panel.get_by_text('品牌资料读取失败', exact=True)).to_have_count(0)
    if supplemental:
        control = panel.get_by_role('combobox', name='本次补充公开资料版本', exact=True)
        expect(control).to_be_enabled()
        control.click()
        page.locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden)').get_by_text(re.compile('^隔离补充官网资料')).click()
        control.press('Escape')
    if with_context:
        panel.get_by_role('combobox', name='补充品牌资料版本', exact=True).click()
        page.get_by_text('资料版本 1 · 内部选题资料 1', exact=True).click()
    with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/optimization-tasks')) as response:
        panel.get_by_role('button', name='开始自动优化', exact=True).click()
    task_id = response.value.json()['task_id']
    if with_context:
        assert response.value.json()['brand_context_version_id'] == context_versions[0]['context_version_id']
        save_context_in_browser(1)
        page.goto(analysis_url)
    expect(panel.get_by_role('button', name='开始自动优化', exact=True)).to_be_disabled()
    execute_task(task_id, session_factory=Session)  # CACHE_ONLY, never external.
    expect(panel.get_by_role('button', name='授权本任务模型调用')).to_be_visible(timeout=15000)
    panel.get_by_role('button', name='授权本任务模型调用').click()
    dialog = page.get_by_role('dialog', name='本任务独立调用授权')
    for label, value in [('请求次数上限', str(initial_requests)), ('总 token 上限', '400000'), ('人民币硬预算', '4'),
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
    def citation_with_one_grounded_binding(payload):
        evaluations = []
        selected = False
        for pair in payload['frozen_candidate_pairs']:
            answer_text = payload['untrusted_answer_units'][pair['answer_unit_index']]['raw_text']
            source_text = payload['untrusted_source_passages'][pair['passage_index']]['text']
            span = '支持批量生成短链'
            positive = not selected and span in answer_text and span in source_text
            selected = selected or positive
            evaluations.append({**pair, 'answer_span': span if positive else None,
                'source_span': span if positive else None,
                'correspondence_mode': 'DIRECT_REUSE' if positive else 'NO_CORRESPONDENCE',
                'evidence_relation': 'SUPPORTS_PARTIAL' if positive else 'NO_MATCH',
                'rationale': '离线测试中两个原文片段一致，仅支持批量能力，不推导品牌推荐或生成因果。' if positive else '离线模拟未发现对应。'})
        assert selected, 'Offline fixture must contain the independently expected shared span'
        return {'evaluations': evaluations, 'no_binding_reason': None}
    from test_delivery_official_facts import approved, BROWSER_CLAIM
    def official_claim(payload):
        claim = {'normalized_claim': BROWSER_CLAIM, 'subject_text': 'Target', 'predicate': '支持',
            'object_text': '批量生成短链（仅限已创建项目）', 'claim_type': 'CAPABILITY',
            'polarity': 'POSITIVE', 'source_span': BROWSER_CLAIM}
        assert claim['source_span'] in payload['untrusted_source_passage']
        return {'claims': [claim]}
    def official_draft(payload):
        blocks = [{'kind': 'INSTRUCTION', 'text': ('记录检查结果，再核对不同处理方式的适用条件。'
            if payload.get('explicit_regeneration') else '先核对使用场景和设备范围，再按服务说明验证处理结果。'), 'evidence_ids': []}]
        if official:
            fact = next(e for e in payload['public_evidence'] if e.get('attribution_prefix'))
            blocks.append({'kind': 'TARGET_STATEMENT', 'text': fact['text'], 'evidence_ids': [fact['evidence_id']]})
        return {'sections': [{'heading': '选用工具前的核对顺序', 'blocks': blocks}]}
    calls = simulated_delivery_transport(monkeypatch, qa_response=manuscript_qa, citation_response=citation_with_one_grounded_binding,
        source_response=official_claim if official else None,
        fact_response=(lambda payload: {'checks': [approved(c['claim_id']) for c in payload['claims']]}) if official else None,
        draft_response=official_draft)
    execute_task(task_id, session_factory=Session)
    expect(panel.get_by_role('button', name='复制完整正文')).to_be_visible(timeout=15000)
    expect(panel.get_by_text('选用工具前的核对顺序', exact=False)).to_be_visible()
    assert len(calls) == initial_requests
    if with_context:
        writer = next(c for c in calls if 'public_evidence' in c)
        assert writer['internal_context']['context_version_id'] == context_versions[0]['context_version_id']
        assert [p['text'] for p in writer['internal_context']['passages']] == [context_texts[0]]
        assert context_texts[1] not in json.dumps(calls, ensure_ascii=False)
        assert unrelated_context not in json.dumps(calls, ensure_ascii=False)
    page.reload()
    expect(panel.get_by_role('button', name='复制完整正文')).to_be_visible(timeout=15000)
    persisted = page.request.get(f'{origin}/api/v2/single-prompt/optimization-tasks/{task_id}/deliveries?project_id=1&prompt_id=44')
    assert persisted.ok
    expected_body = persisted.json()[0]['output']['publication_draft']['body_markdown']
    article = panel.get_by_role('article', name='完整稿件正文')
    for section in persisted.json()[0]['output']['publication_draft']['sections']:
        expect(article.get_by_role('heading', name=section['title'], exact=True)).to_be_visible()
        expect(article.get_by_text(section['draft_text'], exact=True)).to_be_visible()
    frozen = persisted.json()[0]['output']['delivery_input']
    assert len(frozen['selected_evidence']) == 1
    panel.get_by_role('button', name='查看分析依据', exact=True).click()
    evidence = page.get_by_role('dialog', name='方案依据与原始回答', exact=True)
    expect(evidence.get_by_role('region', name='Run 1 完整回答', exact=True)).to_contain_text(frozen['answers'][0]['text'])
    evidence.get_by_role('tab', name='来源证据', exact=True).click()
    expect(evidence.get_by_text('仅部分支持', exact=True)).to_be_visible()
    expect(evidence.get_by_text(frozen['selected_evidence'][0]['passage_text'], exact=True)).to_be_visible()
    page.set_viewport_size({'width': 390, 'height': 1000})
    accessibility_check(page, out, report, 'delivery-evidence-390')
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.screenshot(path=str(out / 'delivery-evidence-390.png'), full_page=True)
    report['screenshots'].append('delivery-evidence-390.png')
    evidence.get_by_role('button', name='定位完整回答', exact=True).click()
    expect(evidence.locator('mark')).to_have_text(frozen['selected_evidence'][0]['answer_unit']['raw_text'])
    evidence.get_by_role('tab', name='品牌资料', exact=True).click()
    if with_context:
        expect(evidence.get_by_text('内部选题资料 1 · 资料版本 1', exact=True)).to_be_visible()
        expect(evidence.get_by_text(context_texts[0], exact=True)).to_be_visible()
        expect(evidence.get_by_text(context_texts[1], exact=True)).to_have_count(0)
        expect(evidence.get_by_text(unrelated_context, exact=True)).to_have_count(0)
        expect(evidence.get_by_text('用户提供的内部资料，未独立核实，不自动成为公开事实', exact=True)).to_be_visible()
        assert context_texts[0] not in expected_body
        accessibility_check(page, out, report, 'basic-context-390')
        page.screenshot(path=str(out / 'basic-context-390.png'), full_page=True)
        report['screenshots'].append('basic-context-390.png')
    if official:
        facts = persisted.json()[0]['output']['generation_receipt']['official_facts']
        assert len(facts['accepted']) == 1
        assert facts['accepted'][0]['snapshot_id'] == fixture['official_snapshot_id']
        assert facts['accepted'][0]['statement'] in expected_body
        assert facts['accepted'][0]['valid_as_of'] in expected_body
        region = evidence.get_by_role('region', name='官方资料自动核实结果')
        expect(region).to_contain_text('官方资料核实：1 项')
        expect(region).to_contain_text(BROWSER_CLAIM)
        expect(region).to_contain_text('不等于独立产品实测')
        if supplemental:
            expect(region.get_by_text('补充公开资料，不是原答案引用', exact=True)).to_be_visible()
            expect(evidence.get_by_role('region', name='本版额外公开资料')).to_contain_text('1 份，不计入原答案引用数')
            assert facts['accepted'][0]['source_role'] == 'SUPPLEMENTAL_PUBLIC_SOURCE'
            citation_call = next(c for c in calls if 'frozen_candidate_pairs' in c)
            assert URL not in json.dumps(citation_call)
        accessibility_check(page, out, report, 'official-facts-390')
        page.screenshot(path=str(out / 'official-facts-390.png'), full_page=True)
        report['screenshots'].append('official-facts-390.png')
    else:
        expect(evidence.get_by_text('本版没有采用已核实品牌事实；这不表示品牌没有相应能力', exact=True)).to_be_visible()
    evidence.press('Escape')
    expect(evidence).not_to_be_visible()
    page.set_viewport_size({'width': 1440, 'height': 1000})
    page.context.grant_permissions(['clipboard-read', 'clipboard-write'], origin=origin)
    copy_button = panel.get_by_role('button', name='复制完整正文', exact=True)
    copy_button.focus()
    expect(copy_button).to_be_focused()
    copy_button.press('Enter')
    expect(page.get_by_text('正文已复制', exact=True)).to_be_visible()
    assert page.evaluate('navigator.clipboard.readText()') == expected_body
    download_button = panel.get_by_role('button', name='导出 Markdown', exact=True)
    download_button.focus()
    with page.expect_download() as saved_download:
        download_button.press('Enter')
    download = saved_download.value
    assert download.suggested_filename.endswith('.md')
    exported = out / 'exported-manuscript.md'
    download.save_as(exported)
    assert exported.read_bytes() == expected_body.encode('utf-8')
    expect(panel.get_by_text('正文下载已发起', exact=True)).to_be_visible()
    from hashlib import sha256
    report['manuscript_export'] = {'filename': download.suggested_filename,
        'hash': sha256(exported.read_bytes()).hexdigest(), 'matches_saved_body': True}
    expect(panel.get_by_text('已记录 token', exact=True)).to_be_visible()
    details = page.locator('.v2-advanced-details')
    expect(details).to_have_count(3)
    for item in details.all():
        expect(item).not_to_have_attribute('open', '')
    panel.get_by_text(re.compile(r'^质量问题与实际修复')).click()
    expect(panel.get_by_text('本次检查未发现问题，未进行修复', exact=True)).to_be_visible()
    page.get_by_text('原始资料、人工纠错与高级审计', exact=True).click()
    audit = details.filter(has=page.locator('summary').filter(has_text='原始资料、人工纠错与高级审计'))
    expect(audit).to_have_attribute('open', '')
    expect(details.locator('summary')).to_have_count(3)
    page.get_by_text('原始资料、人工纠错与高级审计', exact=True).click()
    expect(audit).not_to_have_attribute('open', '')
    panel.get_by_role('button', name='编辑正文并复检', exact=True).click()
    editor = page.get_by_role('dialog', name='编辑正文', exact=True)
    prior_blocks = editor.get_by_role('textbox', name=re.compile(r'^正文 1\.')).count()
    editor.get_by_role('button', name='增加建议段落', exact=True).click()
    editor.get_by_label(f'正文 1.{prior_blocks + 1}', exact=True).fill('目标产品价格为99元。')
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
    assert len(calls) == initial_requests
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
    assert len(calls) == initial_requests + 1 and 'segments' in calls[-1]
    new_delivery = page.request.get(f'{origin}/api/v2/single-prompt/optimization-tasks/{revised_task}/deliveries?project_id=1&prompt_id=44').json()[0]
    assert new_delivery['result_version'] != persisted.json()[0]['result_version']
    assert '99元' not in new_delivery['output']['publication_draft']['body_markdown']
    if official:
        assert BROWSER_CLAIM in new_delivery['output']['publication_draft']['body_markdown']
        assert new_delivery['output']['generation_receipt']['official_facts'] == facts
    assert page.request.get(f'{origin}/api/v2/single-prompt/optimization-tasks/{task_id}/deliveries?project_id=1&prompt_id=44').json() == persisted.json()
    panel.get_by_text(re.compile(r'^质量问题与实际修复')).click()
    expect(panel.get_by_role('cell', name='已删除不成立陈述', exact=True)).to_be_visible()
    expect(panel.get_by_role('cell', name='该价格没有来源支持。', exact=True)).to_be_visible()
    page.reload()
    expect(panel.get_by_role('button', name='复制完整正文')).to_be_visible(timeout=15000)
    panel.get_by_text(re.compile(r'^质量问题与实际修复')).click()
    expect(panel.get_by_role('cell', name='已删除不成立陈述', exact=True)).to_be_visible()
    with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/draft-regenerations')) as response:
        panel.get_by_role('button', name='重新生成正文', exact=True).click()
    regenerated_task = response.value.json()['task_id']
    assert response.value.status == 201
    execute_task(regenerated_task, session_factory=Session)
    assert len(calls) == initial_requests + 1
    page.reload()
    expect(panel.get_by_text('正文重新生成：保留原稿，沿用冻结分析与证据，仅生成和检查新正文', exact=True)).to_be_visible(timeout=15000)
    expect(panel.get_by_role('button', name='复制完整正文')).to_have_count(0)
    panel.get_by_role('button', name='授权本任务模型调用').click()
    auth = page.get_by_role('dialog', name='本任务独立调用授权')
    for label, value in [('请求次数上限', '2'), ('总 token 上限', '200000'), ('人民币硬预算', '2'),
            ('输入 / 输出每百万 token 的较高保守单价（人民币）', '10'),
            ('已核实计费依据', '隔离工程模拟价格，不是真实调用授权'),
            ('计费核实日期', datetime.utcnow().date().isoformat())]:
        auth.get_by_label(label, exact=True).fill(value)
    auth.get_by_role('button', name='确认授权并继续', exact=True).click()
    expect(auth).not_to_be_visible()
    execute_task(regenerated_task, session_factory=Session)
    expect(panel.get_by_role('button', name='复制完整正文')).to_be_visible(timeout=15000)
    assert len(calls) == initial_requests + 3
    assert calls[-2]['explicit_regeneration']['task_id'] == regenerated_task and 'segments' in calls[-1]
    regenerated = page.request.get(f'{origin}/api/v2/single-prompt/optimization-tasks/{regenerated_task}/deliveries?project_id=1&prompt_id=44').json()[0]
    assert regenerated['result_version'] != new_delivery['result_version']
    assert regenerated['output']['delivery_input'] == new_delivery['output']['delivery_input']
    assert regenerated['output']['automatic_qa']['repairs'] == []
    assert '记录检查结果' in regenerated['output']['publication_draft']['body_markdown']
    if official:
        assert regenerated['output']['generation_receipt']['official_facts'] == facts
    assert page.request.get(f'{origin}/api/v2/single-prompt/optimization-tasks/{revised_task}/deliveries?project_id=1&prompt_id=44').json()[0] == new_delivery
    page.reload()
    expect(panel.get_by_role('article', name='完整稿件正文', exact=True)).to_contain_text(
        '记录检查结果，再核对不同处理方式的适用条件。', timeout=15000)
    # Historical selection must survive refresh; missing identities cannot fall back.
    chooser = panel.get_by_role('combobox', name='优化任务版本', exact=True)
    chooser.press('ArrowDown')
    page.locator('.ant-select-dropdown').filter(visible=True).get_by_text(re.compile(r'^任务 1 ·')).click()
    expect(page).to_have_url(re.compile(r'optimization_task=' + task_id))
    exact_link = panel.get_by_role('link', name='方案详情与可选发布记录', exact=True)
    expect(exact_link).to_have_attribute('href', re.compile(re.escape(quote(persisted.json()[0]['result_version'], safe=''))))
    page.reload()
    expect(exact_link).to_have_attribute('href', re.compile(re.escape(quote(persisted.json()[0]['result_version'], safe=''))), timeout=15000)
    report['historical_version_refresh'] = {'task_id': task_id, 'result_version': persisted.json()[0]['result_version'], 'preserved': True}
    if official:
        historical_url = origin + exact_link.get_attribute('href')
        before_detail = len(calls)
        exact_link.click()
        detail = page.locator('#v2-execution')
        expect(detail.get_by_text('正在查看历史稿件版本', exact=True)).to_be_visible(timeout=15000)
        expect(detail.get_by_role('article', name='方案详情完整正文')).to_contain_text(expected_body)
        expect(detail.get_by_role('button', name='保存并重新校验')).to_have_count(0)
        expect(detail.get_by_role('textbox').first).to_be_disabled()
        page.reload()
        expect(detail.get_by_text('正在查看历史稿件版本', exact=True)).to_be_visible(timeout=15000)
        expect(detail.get_by_text(persisted.json()[0]['result_version'], exact=True)).to_be_visible()
        expect(detail.get_by_role('article', name='方案详情完整正文')).to_contain_text(expected_body)
        page.set_viewport_size({'width': 390, 'height': 1000})
        detail.scroll_into_view_if_needed()
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.screenshot(path=str(out / 'historical-detail-390.png'), full_page=False)
        report['screenshots'].append('historical-detail-390.png')
        from urllib.parse import urlsplit, urlunsplit, parse_qs, urlencode
        parts = urlsplit(historical_url)
        query = parse_qs(parts.query)
        query['v2_execution_result'] = ['missing-result']
        missing_url = urlunsplit(parts._replace(query=urlencode(query, doseq=True)))
        page.goto(missing_url)
        expect(detail.get_by_text('无法读取指定稿件版本', exact=True)).to_be_visible(timeout=15000)
        expect(detail.get_by_role('article', name='方案详情完整正文')).to_have_count(0)
        expect(detail.get_by_role('button', name='生成完整执行方案与稿件')).to_have_count(0)
        expect(page).to_have_url(re.compile('v2_execution_result=missing-result'))
        assert len(calls) == before_detail
        report['historical_detail'] = {'version': persisted.json()[0]['result_version'],
            'refresh_preserved': True, 'missing_rejected': True, 'model_calls': 0}
        page.set_viewport_size({'width': 1440, 'height': 1000})
        query['v2_execution_result'] = [regenerated['result_version']]
        page.goto(urlunsplit(parts._replace(query=urlencode(query, doseq=True))))
        expect(detail.get_by_role('button', name='保存并重新校验')).to_be_visible(timeout=15000)
        operator = detail.get_by_role('textbox', name='执行操作者', exact=True)
        expect(operator).to_have_value('本机操作者')
        expect(operator).to_have_js_property('readOnly', True)
        detail.get_by_role('combobox', name='最终资产操作', exact=True).press('ArrowDown')
        page.locator('.ant-select-dropdown').filter(visible=True).get_by_text('更新已核实的页面', exact=True).click()
        for label, value in [
            ('已核查的栏目或页面范围', '官网帮助栏目，人工核对现有说明页'),
            ('已有页面 URL', 'https://example.com/help/guide'), ('已有页面标题', '现有帮助说明'),
            ('页面当前版本或最后修改时间', 'cms-revision-12'), ('品牌归属及编辑权限依据', '品牌内容编辑账号已授予页面编辑权限'),
        ]:
            detail.get_by_role('textbox', name=label, exact=True).fill(value)
        detail.get_by_role('checkbox', name='确认具有该页面的编辑权限', exact=True).check()
        detail.get_by_role('checkbox', name='确认该页面适合承接当前稿件', exact=True).check()
        with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/revisions')) as revision:
            detail.get_by_role('button', name='保存并重新校验').click()
        assert revision.value.status == 200
        assert revision.value.json()['result']['output']['human_revision']['editor'] == 'local-owner'
        expect(page).not_to_have_url(re.compile(re.escape(quote(regenerated['result_version'], safe=''))))
        saved_asset_url = page.url
        expect(detail.get_by_role('article', name='方案详情完整正文')).to_contain_text(regenerated['output']['publication_draft']['body_markdown'])
        page.reload()
        expect(detail.get_by_role('textbox', name='已有页面 URL', exact=True)).to_have_value('https://example.com/help/guide', timeout=15000)
        expect(detail.get_by_role('checkbox', name='确认具有该页面的编辑权限', exact=True)).to_be_checked()
        expect(detail.get_by_role('checkbox', name='确认该页面适合承接当前稿件', exact=True)).to_be_checked()
        expect(page).to_have_url(saved_asset_url)
        expect(operator).to_have_value('本机操作者')
        expect(operator).to_have_js_property('readOnly', True)
        report['authenticated_operator'] = {'actor': 'local-owner', 'form_read_only': True,
            'saved_revision_actor_matches': True, 'refresh_preserved': True}
        page.set_viewport_size({'width': 390, 'height': 1000})
        detail.get_by_role('textbox', name='已有页面 URL', exact=True).scroll_into_view_if_needed()
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        accessibility_check(page, out, report, 'asset-verification-390')
        detail.get_by_role('textbox', name='已有页面 URL', exact=True).scroll_into_view_if_needed()
        page.screenshot(path=str(out / 'asset-verification-390.png'), full_page=False)
        report['screenshots'].append('asset-verification-390.png')
        assert len(calls) == before_detail
        assert page.request.get(f'{origin}/api/v2/single-prompt/optimization-tasks/{regenerated_task}/deliveries?project_id=1&prompt_id=44').json()[0] == regenerated
        report['asset_verification'] = {'operation': 'UPDATE_EXISTING', 'refresh_preserved': True,
            'original_delivery_unchanged': True, 'model_calls': 0, 'provenance': 'USER_REPORTED'}
        saved_detail_failure_check(page, report, regenerated['output']['publication_draft']['body_markdown'])
        assert len(calls) == before_detail
        page.set_viewport_size({'width': 1440, 'height': 1000})
    page.goto(f'{origin}/?v2_project=1&v2_prompt=44&v2_analysis={analysis.analysis_id}&optimization_task=missing-task')
    expect(panel.get_by_text('当前链接未匹配本分析的自动任务', exact=True)).to_be_visible(timeout=15000)
    expect(panel.get_by_role('article', name='完整稿件正文', exact=True)).to_have_count(0)
    expect(panel.get_by_role('button', name='复制完整正文', exact=True)).to_have_count(0)
    chooser.press('ArrowDown')
    page.locator('.ant-select-dropdown').filter(visible=True).get_by_text(re.compile(r'^任务 3 ·')).click()
    expect(panel.get_by_role('article', name='完整稿件正文', exact=True)).to_contain_text('记录检查结果', timeout=15000)
    expect(page).to_have_url(re.compile(r'optimization_task=' + regenerated_task))
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
        'KEYBOARD_DOWNLOAD_EXACT_SAVED_UTF8_BODY_NO_AUDIT_METADATA',
        'EDIT_SAVED_PENDING_WITHOUT_OLD_QUALIFICATION', 'ONE_QA_ONLY_NO_ANSWER_OR_CITATION_RECOMPUTE',
        'EDIT_REPAIR_NEW_VERSION_AND_OLD_RESULT_IMMUTABLE',
        'EXPLICIT_REGENERATION_ONLY_WRITER_AND_QA_NEW_BUDGET_OLD_RESULTS_PRESERVED',
        'EXACT_HISTORICAL_TASK_SURVIVES_REFRESH_NO_MISSING_ID_FALLBACK',
        'LATE_ANALYSIS_RESPONSE_CANNOT_RESTORE_OLD_PROJECT', 'RESPONSIVE_NO_PAGE_OVERFLOW'],
        simulated_provider_requests=len(calls), not_verified=['REAL_MODEL_QUALITY', 'REAL_SAMPLING', 'REAL_SOURCE_FETCH'],
        task_id=task_id, status='PASS_SCOPED_SIMULATED_INTEGRATION_NOT_REAL_MODEL')
    assert not report['errors'], report['errors']

    if official:
        report['verified'].append('SYNTHETIC_OFFICIAL_SOURCE_CLAIM_CHECK_RECEIPT_UI_NO_HUMAN_REVIEW')
    if with_context:
        report['verified'].extend(['UI_BASIC_CONTEXT_VERSION_SAVE_AND_SELECT',
            'PROJECT_CONTEXT_DRAFT_SURVIVES_PROMPT_SWITCH',
            'NEW_CONTEXT_DOES_NOT_REPLACE_QUEUED_TASK_INPUT', 'ONLY_RELEVANT_CONTEXT_IN_WRITER',
            'FROZEN_CONTEXT_VISIBLE_AFTER_REFRESH_NOT_PUBLIC_FACT'])
    if supplemental:
        report['verified'].extend(['EXPLICIT_UI_SUPPLEMENTAL_FETCH_AUTHORITY', 'SUPPLEMENTAL_FROZEN_SNAPSHOT_SELECTED',
            'EXTRA_SOURCE_NOT_ORIGINAL_CITATION', 'SUPPLEMENTAL_FACT_SOURCE_ROLE_VISIBLE'])
        report['simulated_source_acquisitions'] = 1


def truth_correction_check(page, origin, fixture, Session, monkeypatch, out, report):
    from datetime import datetime
    from app.models import Project, TargetBrandCapabilityTruth, SinglePromptAnalysisContext, SinglePromptOptimizationTask
    from app.modules.single_prompt_v2.automatic_delivery import execute_task
    from test_automatic_delivery import simulated_delivery_transport
    from test_delivery_truth_corrections import grounded_brand_answer
    with Session() as db:
        db.get(Project, 1).brand_name = '甲工具'
        db.add(TargetBrandCapabilityTruth(project_id=1, capability_key='支持批量生成短链', capability_label='支持批量生成短链',
            product_truth_status='SUPPORTED', truth_source='MANUAL_CONFIRMED', source_reference='https://example.com/product',
            reviewed_by='isolated-human-fixture', reviewed_at=datetime.utcnow()))
        db.commit()
        raw_hash = db.query(SinglePromptAnalysisContext).filter_by(analysis_id=fixture['analysis'].analysis_id).one().raw_output_hash
    calls = simulated_delivery_transport(monkeypatch, answer_response=grounded_brand_answer)
    base = origin + '/api/v2/single-prompt'
    created = page.request.post(f'{base}/analyses/{fixture["analysis"].analysis_id}/optimization-tasks', data={
        'project_id': 1, 'prompt_id': 44, 'raw_output_hash': raw_hash, 'idempotency_key': 'browser-truth-correction-parent'})
    assert created.status == 201, created.text()
    parent = created.json()
    auth = {'project_id': 1, 'prompt_id': 44, 'expected_revision': parent['revision'], 'input_hash': parent['input_hash'],
        'max_requests': 4, 'max_tokens': 800000, 'max_cost_cny': 8, 'conservative_cny_per_million_tokens': 10,
        'pricing_source': 'isolated-not-real-model-billing', 'pricing_checked_at': datetime.utcnow().date().isoformat()}
    assert page.request.post(f'{base}/optimization-tasks/{parent["task_id"]}/authorization', data=auth).status == 200
    execute_task(parent['task_id'], session_factory=Session)
    with Session() as db:
        row = db.query(SinglePromptOptimizationTask).filter_by(task_id=parent['task_id']).one()
        assert row.status.startswith('COMPLETED'), row.blocker_detail
        original = (row.input_json, row.progress_json)
    url = f'{origin}/?v2_project=1&v2_prompt=44&v2_analysis={fixture["analysis"].analysis_id}&optimization_task={parent["task_id"]}'
    page.goto(url)
    panel = page.get_by_role('region', name='自动优化交付')
    panel.get_by_role('button', name='纠正品牌事实', exact=True).click(timeout=15000)
    dialog = page.get_by_role('dialog', name='品牌事实纠错', exact=True)
    select = dialog.get_by_role('combobox', name='选择待纠正事实', exact=True)
    select.press('ArrowDown'); select.press('Enter')
    expect(dialog.get_by_label('单项事实及适用条件', exact=True)).to_have_value('支持批量生成短链')
    dialog.get_by_label('人工判断', exact=True).select_option('UNKNOWN')
    dialog.get_by_label('纠错原因与依据', exact=True).fill('隔离人工验收：原资料未确认当前能力，不应作公开承诺。')
    dialog.get_by_role('button', name='预览影响范围', exact=True).click()
    expect(dialog.get_by_text('受影响方向', exact=True)).to_be_visible()
    expect(dialog.get_by_role('button', name='保存事实纠错', exact=True)).to_be_disabled()
    for width in [1440, 390]:
        page.set_viewport_size({'width': width, 'height': 1000})
        accessibility_check(page, out, report, f'truth-preview-{width}')
        screenshot = f'truth-preview-{width}.png'
        page.screenshot(path=str(out / screenshot), full_page=True); report['screenshots'].append(screenshot)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    dialog.get_by_role('checkbox', name='我已核对事实与依据，确认保存独立纠错版本').check()
    with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/truth-corrections')) as saved:
        dialog.get_by_role('button', name='保存事实纠错', exact=True).click()
    correction = saved.value.json()
    assert saved.value.status == 201 and correction['output']['product_truth_status'] == 'UNKNOWN'
    expect(dialog.get_by_text('事实纠错第 1 版已保存；原稿和原判断保持不变', exact=True)).to_be_visible()
    page.reload()
    panel.get_by_role('button', name='纠正品牌事实', exact=True).click(timeout=15000)
    dialog.get_by_text('纠错 1 · 支持批量生成短链 · 尚无法确认', exact=True).click()
    with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/truth-reprojections')) as queued:
        dialog.get_by_role('button', name='更新受影响内容', exact=True).click()
    new = queued.value.json()
    assert queued.value.status == 201 and new['task_kind'] == 'TRUTH_REPROJECTION'
    assert new['authorization']['policy'] == 'CACHE_ONLY'
    execute_task(new['task_id'], session_factory=Session)
    panel.get_by_role('button', name='授权本任务模型调用', exact=True).click(timeout=15000)
    authorization = page.get_by_role('dialog', name='本任务独立调用授权')
    expect(authorization).to_contain_text('回答、引用和资料核实不允许新增模型请求')
    for label, value in [('请求次数上限', '2'), ('总 token 上限', '800000'), ('人民币硬预算', '8'),
        ('输入 / 输出每百万 token 的较高保守单价（人民币）', '10'),
        ('已核实计费依据', '隔离工程模拟价格，不是真实调用授权'), ('计费核实日期', datetime.utcnow().date().isoformat())]:
        authorization.get_by_label(label, exact=True).fill(value)
    authorization.get_by_role('button', name='确认授权并继续', exact=True).click()
    expect(authorization).not_to_be_visible()
    execute_task(new['task_id'], session_factory=Session)
    expect(panel.get_by_role('button', name='复制完整正文', exact=True)).to_be_visible(timeout=15000)
    page.reload()
    expect(panel.get_by_role('button', name='复制完整正文', exact=True)).to_be_visible(timeout=15000)
    expect(panel.get_by_text(re.compile('^事实纠错局部更新：'))).to_be_visible()
    with Session() as db:
        old = db.query(SinglePromptOptimizationTask).filter_by(task_id=parent['task_id']).one()
        row = db.query(SinglePromptOptimizationTask).filter_by(task_id=new['task_id']).one()
        assert (old.input_json, old.progress_json) == original
        assert row.status.startswith('COMPLETED'), row.blocker_detail
        requests = json.loads(row.progress_json)['requests']
        assert len(requests) == 2 and {r['stage'] for r in requests} == {'DRAFT', 'TEXT_QA'}
        assert db.query(TargetBrandCapabilityTruth).one().product_truth_status == 'SUPPORTED'
    panel.get_by_role('button', name='查看原任务与历史稿件', exact=True).click()
    expect(panel.get_by_text(re.compile('^事实纠错局部更新：'))).to_have_count(0)
    expect(panel.get_by_role('button', name='复制完整正文', exact=True)).to_be_visible(timeout=15000)
    assert len(calls) == 6 and not report['errors']
    report.update(status='PASS_OFFLINE_SIMULATED_PROVIDER', simulated_provider_requests=len(calls),
        verified=['HUMAN_PREVIEW_AND_EXPLICIT_CONFIRMATION', 'APPEND_ONLY_CORRECTION', 'REFRESH_HISTORY',
            'EXACT_PARENT_REPROJECTION', 'NO_UPSTREAM_EXTERNAL_CALLS', 'NEW_DRAFT_AND_QA', 'ORIGINAL_UNCHANGED'],
        not_verified=['REAL_MODEL_QUALITY', 'REAL_HUMAN_FACT_ACCURACY'], correction_id=correction['correction_id'])


def main():
    if "--joint-readonly" in sys.argv:
        joint_readonly_browser_check(_joint_readonly_args(sys.argv[1:]))
        return
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
    if any(mode in sys.argv for mode in ['--optimize', '--observe', '--access']):
        sys.path.insert(0, str(ROOT / 'backend'))
        sys.path.insert(0, str(ROOT / 'backend/tests'))
        from pytest import MonkeyPatch
        from sqlalchemy import create_engine, event
        from sqlalchemy.orm import sessionmaker
        from app.core.release_sqlite import get_release_sqlite_dbapi
        from app.core.release_database import _set_sqlite_pragma
        from test_release_first_slice import (
            _add_project_configuration,
            _analysis_prompt_binding,
            _record_prompt_binding,
            _seed_citation_contribution_fixture,
            _seed_frozen_analysis,
        )
        monkeypatch = MonkeyPatch()
        engine = create_engine(env['GEO_RELEASE_DATABASE_URL'], module=get_release_sqlite_dbapi())
        event.listen(engine, 'connect', _set_sqlite_pragma)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        with Session() as db:
            if '--access' in sys.argv:
                from hashlib import sha256
                from app.models import Project
                from scripts.release_upgrade_check import business_fingerprint
                _seed_frozen_analysis(db, reference_urls=[])
                db.add(Project(id=2, organization_id=1, name='FORBIDDEN_PROJECT_TITLE', brand_name='FORBIDDEN_BRAND'))
                db.commit()
                key = 'isolated-browser-invitation-not-a-real-key-0123456789'
                account = {'name': '隔离审核员', 'key_sha256': sha256(key.encode()).hexdigest(), 'project_ids': [1]}
                access = out / 'isolated-access.json'
                access.write_text(json.dumps({'accounts': [account]}))
                access.chmod(0o600)
                env['GEO_RELEASE_ACCESS_CONFIG'] = str(access)
                fixture = {'access_key': key, 'account': account, 'access_path': access,
                    'business_before': business_fingerprint(out / 'isolated.db')}
            elif '--optimize' in sys.argv:
                fixture = _seed_citation_contribution_fixture(db, monkeypatch, out, reviewed=False)
                if '--official-facts' in sys.argv:
                    from test_delivery_official_facts import seed_isolated_official_source
                    fixture['official_snapshot_id'] = seed_isolated_official_source(db)
            else:
                from app.models import BrowserMonitorRun, Project, Prompt
                from app.modules.single_prompt_v2.service import create_analysis, claim_analysis, finalize_analysis
                baseline = _seed_frozen_analysis(db, reference_urls=[])
                first = db.query(BrowserMonitorRun).filter_by(task_id=baseline.task_id).one()
                second, _ = create_analysis(
                    db, project_id=1, prompt_id=44, **_analysis_prompt_binding(baseline),
                    sample_count=1, idempotency_key='browser-second-synthetic-run')
                token = claim_analysis(db, second.analysis_id)
                run = db.query(BrowserMonitorRun).filter_by(task_id=second.task_id).one()
                run.status = 'success'; run.stage = 'success'; run.answer_text = 'Target 提供资料核对入口。'
                run.answer_char_count = len(run.answer_text); run.reference_complete = True
                db.commit()
                assert finalize_analysis(db, second.analysis_id, token)
                fixture = {'baseline_run_id': first.id, 'comparison_run_id': run.id}
                metric_project = Project(organization_id=1, name='独立指标工程验收', brand_name='MetricTarget')
                db.add(metric_project); db.flush()
                _add_project_configuration(db, project_id=metric_project.id, brand_name='MetricTarget')
                metric_prompt = Prompt(project_id=metric_project.id, title='隔离指标', prompt_text='过滤器如何保养？')
                db.add(metric_prompt); db.commit()
                metric_prompt_binding = _record_prompt_binding(db, metric_prompt.id)
                fixture.update(metric_project_id=metric_project.id, metric_prompt_id=metric_prompt.id)
                for part in ['baseline', 'comparison']:
                    batch, _ = create_analysis(db, project_id=metric_project.id, prompt_id=metric_prompt.id,
                        **metric_prompt_binding, sample_count=9, idempotency_key=f'isolated-nine-{part}')
                    token = claim_analysis(db, batch.analysis_id)
                    runs = db.query(BrowserMonitorRun).filter_by(task_id=batch.task_id).order_by(BrowserMonitorRun.id).all()
                    for index, run in enumerate(runs):
                        run.status = 'success'; run.stage = 'success'
                        run.answer_text = 'MetricTarget 是一个名称。' if part == 'comparison' and index == 0 else f'维护前核对设备说明，第{index + 1}份隔离回答。'
                        run.answer_char_count = len(run.answer_text); run.reference_complete = True
                    db.commit()
                    assert finalize_analysis(db, batch.analysis_id, token)
                    fixture[f'metric_{part}'] = [r.id for r in runs]
                batch, _ = create_analysis(db, project_id=metric_project.id, prompt_id=metric_prompt.id,
                    **metric_prompt_binding, sample_count=1, idempotency_key='isolated-conflicting-platform')
                token = claim_analysis(db, batch.analysis_id)
                run = db.query(BrowserMonitorRun).filter_by(task_id=batch.task_id).one()
                run.status = 'success'; run.stage = 'success'; run.platform = 'isolated_other_platform'
                run.answer_text = 'MetricTarget 是一个名称。'
                run.answer_char_count = len(run.answer_text); run.reference_complete = True
                db.commit()
                assert finalize_analysis(db, batch.analysis_id, token)
                fixture['conflict_run_id'] = run.id
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
            origin = f'http://127.0.0.1:{port}'
            page.goto(origin + '/')
            if fixture:
                if '--access' in sys.argv:
                    access_check(page, origin, fixture, out, report)
                elif '--observe' in sys.argv:
                    observation_check(page, f'http://127.0.0.1:{port}', fixture, out, report)
                elif '--truth-correction' in sys.argv:
                    truth_correction_check(page, origin, fixture, Session, monkeypatch, out, report)
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
            dialog.get_by_label('品牌别名（逗号分隔）', exact=True).fill('过滤器甲, 过滤器甲, Filter A')
            dialog.get_by_label('地区', exact=True).fill('US')
            dialog.get_by_label('语言', exact=True).fill('en-US')
            preview = dialog.get_by_role('region', name='保存配置预览')
            expect(preview).to_contain_text('未配置，官方来源归属未知')
            dialog.get_by_label('品牌官网', exact=True).fill('javascript:alert(1)')
            expect(preview).to_contain_text('配置尚未通过校验')
            dialog.get_by_role('button', name=re.compile('创.*建')).click()
            expect(dialog.get_by_text('项目保存未完成', exact=True)).to_be_visible()
            assert page.request.get(origin + '/api/projects').json() == []
            expect(dialog.get_by_label('品牌名称', exact=True)).to_have_value('测试过滤器')
            dialog.get_by_label('品牌官网', exact=True).fill('https://EXAMPLE.com/help')
            expect(preview).to_contain_text('example.com（用户配置，未核实所有权）')
            expect(preview).to_contain_text('已合并 1 项重复')
            page.set_viewport_size({'width': 390, 'height': 1000})
            accessibility_check(page, out, report, 'project-preview-390')
            page.screenshot(path=str(out / 'project-preview-390.png'), full_page=True)
            report['screenshots'].append('project-preview-390.png')
            preview.scroll_into_view_if_needed()
            page.screenshot(path=str(out / 'project-preview-details-390.png'), full_page=True)
            report['screenshots'].append('project-preview-details-390.png')
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            page.set_viewport_size({'width': 1440, 'height': 1000})
            dialog.get_by_role('button', name=re.compile('创.*建')).click()
            expect(dialog).not_to_be_visible()
            created_project = page.request.get(origin + '/api/projects').json()[0]
            assert created_project['brand_aliases'] == ['过滤器甲', 'Filter A']
            assert (created_project['region'], created_project['language']) == ('US', 'en-US')
            page.reload()
            expect(page.get_by_text('尚无可用问题，请先在问题配置中创建', exact=True)).to_be_visible()
            page.get_by_role('button', name='编辑项目', exact=True).click()
            editor = page.get_by_role('dialog', name='编辑项目')
            expect(editor.get_by_label('地区', exact=True)).to_have_value('US')
            expect(editor.get_by_label('语言', exact=True)).to_have_value('en-US')
            editor.get_by_label('品牌官网', exact=True).fill('')
            expect(editor.get_by_role('region', name='保存配置预览')).to_contain_text('未配置，官方来源归属未知')
            editor.get_by_role('button', name=re.compile('^保\\s*存$')).click()
            expect(editor).not_to_be_visible()
            edited_project = page.request.get(origin + '/api/projects').json()[0]
            assert edited_project['website_url'] == ''
            assert (edited_project['region'], edited_project['language']) == ('US', 'en-US')
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
            dialogs = []
            page.on('dialog', lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
            page.add_init_script('window.__geoUntrustedExecuted = 0;')
            page.evaluate('window.__geoUntrustedExecuted = 0')
            context_text = ('测试过滤器提供过滤器维护资料，具体清洗条件应按型号确认。'
                '<img data-geo-injected="true" src=x onerror="window.__geoUntrustedExecuted=1">'
                '<script data-geo-injected="true">window.__geoUntrustedExecuted=1</script>'
                '[伪链接](javascript:alert(1))')
            page.get_by_label('资料标题', exact=True).fill('隔离品牌说明')
            page.get_by_label('品牌资料正文', exact=True).fill(context_text)
            page.get_by_label('资料出处或维护说明', exact=True).fill('javascript:alert(1)')
            page.get_by_role('button', name='保存新资料版本', exact=True).click()
            expect(page.get_by_text('版本 1 · 隔离品牌说明', exact=True)).to_be_visible()
            for reload in [False, True]:
                if reload:
                    page.reload()
                page.get_by_text('版本 1 · 隔离品牌说明', exact=True).click()
                expect(page.get_by_text(context_text, exact=True)).to_be_visible()
                expect(page.locator('[data-geo-injected], a[href^="javascript:"]')).to_have_count(0)
                assert page.evaluate('window.__geoUntrustedExecuted') == 0 and not dialogs
            report['untrusted_context_rendering'] = 'LITERAL_BEFORE_AND_AFTER_RELOAD_NO_SCRIPT_OR_JAVASCRIPT_LINK'
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
                'PROJECT_PREVIEW_SHARED_VALIDATION_NO_WRITE', 'PROJECT_SAVE_ERROR_PRESERVES_INPUT',
                'PROJECT_LOCALE_PRESERVED_ON_EDIT', 'NO_DOMAIN_PROJECT_CONTINUES_TO_PROMPT',
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
