"""Offline browser acceptance for GEO Agent Experiment V1.

Creates a fresh release database, seeds one frozen Analysis and a scripted Agent
result, then exercises only loopback GET/UI interactions. No model, sampling,
source-fetch or publication call is possible in this check.
"""

from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import ProxyHandler, build_opener

from playwright.sync_api import expect, sync_playwright
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "tests"))


def main() -> None:
    out = ROOT / "backend" / "artifacts" / "acceptance" / (
        "agent-browser-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    out.mkdir(parents=True)
    database = out / "isolated.db"
    env = {**os.environ, "GEO_RELEASE_DATABASE_URL": f"sqlite:///{database}"}
    migration = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.release.ini", "upgrade", "head"],
        cwd=ROOT / "backend", env=env, capture_output=True, text=True,
    )
    (out / "migration.log").write_text(migration.stdout + migration.stderr, encoding="utf-8")
    migration.check_returncode()

    from app.core.release_database import _set_sqlite_pragma
    from app.core.release_sqlite import get_release_sqlite_dbapi
    from app.models import SinglePromptAnalysisContext
    from app.modules.agent_experiment.evidence_pack import build_evidence_pack
    from app.modules.agent_experiment.runner import execute_agent_run
    from app.modules.agent_experiment.service import create_agent_run
    from app.services.serialization import loads
    from test_agent_experiment import ScriptedEvidencePackClient, _evidence_markdown
    from test_release_first_slice import _seed_frozen_analysis

    engine = create_engine(env["GEO_RELEASE_DATABASE_URL"], module=get_release_sqlite_dbapi())
    event.listen(engine, "connect", _set_sqlite_pragma)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        analysis = _seed_frozen_analysis(db, reference_urls=[])
        context = db.query(SinglePromptAnalysisContext).filter_by(analysis_id=analysis.analysis_id).one()
        agent, _ = create_agent_run(
            db, project_id=1, prompt_id=44, analysis_id=analysis.analysis_id,
            context_id=context.context_id, idempotency_key="agent-browser-seed-0001", requested_by="browser-qa",
            execution_mode="EVIDENCE_PACK",
        )
        pack = build_evidence_pack(loads(agent.input_scope_json, {}))
        scripted = ScriptedEvidencePackClient(_evidence_markdown(pack))
        agent_id = agent.run_id
        analysis_id = analysis.analysis_id
    execute_agent_run(agent_id, session_factory=Session, client=scripted)

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    log = (out / "api.log").open("w", encoding="utf-8")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.release_main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT / "backend", env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    report = {"scope": "OFFLINE_ISOLATED_AGENT_UI", "external_calls": 0, "status": "FAIL",
              "screenshots": [], "errors": [], "agent_run_id": agent_id, "analysis_id": analysis_id}
    try:
        opener = build_opener(ProxyHandler({}))
        for _ in range(240):
            if server.poll() is not None:
                raise RuntimeError("isolated release API exited; inspect api.log")
            try:
                with opener.open(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.25)
        else:
            raise RuntimeError("isolated release API did not become ready")

        with sync_playwright() as playwright, ExitStack() as cleanup:
            browser = playwright.chromium.launch(headless=True, channel="chrome")
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            cleanup.callback(browser.close)
            context.route("**/*", lambda route: route.continue_()
                          if route.request.url.startswith(f"http://127.0.0.1:{port}/") else route.abort())
            page = context.new_page()
            page.on("pageerror", lambda error: report["errors"].append(str(error)))
            origin = f"http://127.0.0.1:{port}"
            page.goto(f"{origin}/?release_view=coreV2&v2_project=1&v2_prompt=44&v2_analysis={analysis_id}")
            expect(page.get_by_text("正式 Workflow", exact=True)).to_be_visible(timeout=15000)
            page.get_by_text("Agent 实验", exact=True).click()
            expect(page.get_by_role("region", name="GEO Agent 实验")).to_be_visible()
            expect(page.get_by_text("独立实验线路", exact=True)).to_be_visible()
            expect(page.get_by_text("冻结证据包（推荐）", exact=True)).to_be_visible(timeout=15000)
            expect(page.get_by_text("实验结果", exact=True)).to_be_visible(timeout=15000)
            expect(page.get_by_text(
                "服务端校验 PASS · 证据等级 L3_ACTIONABLE_WITHOUT_FACT_CLAIMS", exact=True,
            )).to_be_visible()
            expect(page.get_by_role("button", name="复制完整稿件", exact=True)).to_be_visible()
            expect(page.get_by_role("button", name="导出 Markdown", exact=True)).to_be_visible()
            expect(page.locator("body")).not_to_contain_text("正式库写入成功")
            page.screenshot(path=str(out / "agent-desktop.png"), full_page=True)
            report["screenshots"].append("agent-desktop.png")

            page.get_by_text("证据包覆盖、来源与限制", exact=True).click()
            expect(page.get_by_text("Evidence Pack hash", exact=True)).to_be_visible()
            page.get_by_text("运行 Trace（", exact=False).click()
            expect(page.get_by_text("EVIDENCE_PACK_FROZEN", exact=False)).to_be_visible()
            expect(page.get_by_text("EVIDENCE_PACK_OUTPUT_VALIDATED", exact=False)).to_be_visible()
            page.get_by_text("同输入 Workflow 对照（", exact=False).click()
            expect(page.get_by_text("该视图只比较同一冻结输入", exact=False)).to_be_visible()
            page.screenshot(path=str(out / "agent-trace-compare.png"), full_page=True)
            report["screenshots"].append("agent-trace-compare.png")

            page.set_viewport_size({"width": 390, "height": 1000})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=str(out / "agent-mobile.png"), full_page=True)
            report["screenshots"].append("agent-mobile.png")
            assert not report["errors"], report["errors"]
            report["status"] = "PASS"
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        log.close()
        (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({**report, "artifact_dir": str(out)}, ensure_ascii=False))
        if report["status"] != "PASS":
            raise RuntimeError(f"Agent browser acceptance failed; inspect {out}")


if __name__ == "__main__":
    main()
