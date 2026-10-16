"""T22 local-only browser acceptance for one saved Validate comparison.

Copies the supplied SQLite artifact before starting the release API.  The
browser is restricted to loopback GET requests, so this check cannot create a
new comparison or trigger an external business request.
"""

import argparse
import json
import os
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from urllib.parse import quote
from urllib.request import ProxyHandler, build_opener

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from scripts.delivery_browser_check import _copy_sqlite_artifact, _file_hashes
from scripts.release_upgrade_check import business_fingerprint


def _arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="T22 saved Validate browser acceptance")
    parser.add_argument("--database", required=True, type=Path,
                        help="Existing isolated release SQLite database; it is never opened for writing.")
    parser.add_argument("--project-id", required=True, type=int)
    parser.add_argument("--prompt-id", required=True, type=int)
    parser.add_argument("--comparison-id", required=True,
                        help="Explicit saved result_version; this check never resolves a latest comparison.")
    parser.add_argument("--artifact-dir", type=Path,
                        help="Writable evidence directory (defaults under backend/artifacts/acceptance).")
    return parser.parse_args(argv)


def _json(opener, url: str) -> dict:
    with opener.open(url, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"Unexpected status {response.status}: {url}")
        return json.loads(response.read().decode("utf-8"))


def main(argv: list[str] | None = None) -> None:
    args = _arguments(argv or sys.argv[1:])
    source = args.database.expanduser().resolve()
    if not source.is_file():
        raise RuntimeError(f"Database does not exist: {source}")
    if not (ROOT / "frontend" / "dist" / "index.html").is_file():
        raise RuntimeError("Release frontend is not built; run `cd frontend && npm run build` first")

    out = (args.artifact_dir or ROOT / "backend" / "artifacts" / "acceptance" /
           ("t22-validate-browser-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))).resolve()
    out.mkdir(parents=True, exist_ok=False)
    source_before = _file_hashes(source)
    runtime = _copy_sqlite_artifact(source, out / "runtime-release.db")
    runtime_before = business_fingerprint(runtime)
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        port = candidate.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    report = {
        "scope": "T22_ISOLATED_SAVED_VALIDATE_BROWSER",
        "database": str(source), "runtime_database": str(runtime),
        "project_id": args.project_id, "prompt_id": args.prompt_id,
        "comparison_id": args.comparison_id, "external_calls": 0,
        "methods": [], "screenshots": [], "usage": "UNKNOWN", "status": "FAIL",
    }
    env = {**os.environ, "GEO_RELEASE_DATABASE_URL": f"sqlite:///{runtime}", "MONITORING_WORKER": "0"}
    env.pop("GEO_RELEASE_ACCESS_CONFIG", None)
    log = (out / "api.log").open("w")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.release_main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT / "backend", env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    try:
        opener = build_opener(ProxyHandler({}))
        for _ in range(120):
            if server.poll() is not None:
                raise RuntimeError("Release API exited; inspect api.log")
            try:
                _json(opener, origin + "/api/health")
                break
            except OSError:
                time.sleep(0.25)
        else:
            raise RuntimeError("Release API not ready")

        prefix = f"/api/v2/projects/{args.project_id}/prompts/{args.prompt_id}"
        comparison = _json(opener, origin + prefix + "/observation-comparisons/" + quote(args.comparison_id, safe=""))
        if comparison.get("result_version") != args.comparison_id:
            raise RuntimeError("Saved comparison identity mismatch")
        if not comparison.get("input", {}).get("baseline") or not comparison["input"].get("comparison"):
            raise RuntimeError("Saved comparison lacks fixed baseline/comparison identities")

        with sync_playwright() as playwright, ExitStack() as cleanup:
            browser = playwright.chromium.launch(headless=True, channel="chrome")
            cleanup.callback(browser.close)
            context = browser.new_context(viewport={"width": 1440, "height": 1100})
            cleanup.callback(context.close)
            requests: list[dict[str, str]] = []

            def local_get_only(route):
                request = route.request
                requests.append({"method": request.method, "url": request.url})
                if request.method != "GET" or not request.url.startswith(origin + "/"):
                    route.abort()
                else:
                    route.continue_()

            context.route("**/*", local_get_only)
            page = context.new_page()
            page_errors: list[str] = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            url = (f"{origin}/?release_view=releaseCompare&v2_project={args.project_id}"
                   f"&v2_prompt={args.prompt_id}&observation_result={quote(args.comparison_id, safe='')}")
            page.goto(url, wait_until="networkidle")
            expect(page.get_by_role("region", name="固定范围身份")).to_contain_text(comparison["input"]["baseline"]["context_id"])
            expect(page.get_by_role("alert", name="本轮观察限制")).to_contain_text("小样本和单轮变化不能自动判定策略有效")
            expect(page.get_by_role("alert", name="本轮观察限制")).to_contain_text("不会自动晋升为策略规则")
            expect(page.get_by_text("仅报告观察变化，不证明优化效果或生成因果", exact=True)).to_be_visible()
            history = page.get_by_role("combobox", name="历史比较", exact=True)
            expect(history.locator("xpath=ancestor::div[contains(@class,'ant-select-selector')]")
                   .locator(".ant-select-selection-item")).to_contain_text(args.comparison_id)
            page.screenshot(path=str(out / "saved-validate-report.png"), full_page=True)
            report["screenshots"].append("saved-validate-report.png")
            page.reload(wait_until="networkidle")
            expect(page).to_have_url(re.compile(re.escape("observation_result=" + quote(args.comparison_id, safe=""))))
            expect(page.get_by_role("alert", name="本轮观察限制")).to_contain_text("正文提及本轮观察")
            expect(page.get_by_role("combobox", name="历史比较", exact=True)
                   .locator("xpath=ancestor::div[contains(@class,'ant-select-selector')]")
                   .locator(".ant-select-selection-item")).to_contain_text(args.comparison_id)
            if page_errors:
                raise RuntimeError("Browser page errors: " + "; ".join(page_errors))
            if any(item["method"] != "GET" or not item["url"].startswith(origin + "/") for item in requests):
                raise RuntimeError("Browser attempted a non-GET or non-localhost request")
            report.update(status="PASS_T22_SAVED_VALIDATE", methods=sorted({item["method"] for item in requests}),
                          saved_result_restored=True, fixed_scope_visible=True,
                          non_causal_small_sample_limit_visible=True)
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)
        log.close()
        report["source_database_hash_before"] = source_before
        report["source_database_hash_after"] = _file_hashes(source)
        report["source_database_unchanged"] = report["source_database_hash_before"] == report["source_database_hash_after"]
        report["runtime_business_fingerprint_before"] = runtime_before
        report["runtime_business_fingerprint_after"] = business_fingerprint(runtime)
        report["runtime_business_tables_unchanged"] = (report["runtime_business_fingerprint_before"] ==
                                                       report["runtime_business_fingerprint_after"])
        if not report["source_database_unchanged"]:
            report["status"] = "FAIL_SOURCE_DATABASE_CHANGED"
        if not report["runtime_business_tables_unchanged"]:
            report["status"] = "FAIL_RUNTIME_BUSINESS_DATA_CHANGED"
        (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "PASS_T22_SAVED_VALIDATE":
        raise RuntimeError(f"T22 browser acceptance did not pass; inspect {out / 'report.json'}")


if __name__ == "__main__":
    main()
