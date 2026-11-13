"""Offline browser acceptance for GEO Agent Experiment V1.

Creates a fresh release database, seeds one frozen Analysis and a scripted Agent
result with HELP_DOC and FAQ child assets, then exercises only loopback/UI
interactions. Set ``GEO_AGENT_BROWSER_SCENARIO=partial`` to validate asset-level
partial success, export blocking, feedback, history and refresh recovery. No
model, sampling, source-fetch or publication call is possible in this check.
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
    scenario = os.environ.get("GEO_AGENT_BROWSER_SCENARIO", "success").strip().lower()
    if scenario not in {"success", "partial"}:
        raise RuntimeError(f"unsupported browser scenario: {scenario}")
    out = ROOT / "backend" / "artifacts" / "acceptance" / (
        f"agent-browser-{scenario}-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
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
    from app.modules.agent_experiment.service import (
        complete_draft_artifact_regeneration, create_agent_run,
        list_draft_artifacts, queue_draft_artifact_regeneration,
    )
    from app.services.serialization import loads
    from test_agent_draft_artifacts import _multi_markdown
    from test_agent_experiment import ScriptedEvidencePackClient
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
            requested_artifact_types=["HELP_DOC", "FAQ"],
        )
        pack = build_evidence_pack(loads(agent.input_scope_json, {}))
        aggregate_member_count = len(pack["aggregate_evidence_sets"][0]["members"])
        verified_observation = pack["verified_brand_observations"][0]["canonical_text"]
        scripted = ScriptedEvidencePackClient(_multi_markdown(pack, valid_faq=scenario != "partial"))
        agent_id = agent.run_id
        analysis_id = analysis.analysis_id
    execute_agent_run(agent_id, session_factory=Session, client=scripted)

    if scenario == "partial":
        with Session() as db:
            help_doc = next(row for row in list_draft_artifacts(
                db, run_id=agent_id, project_id=1, prompt_id=44,
            ) if row["artifact_type"] == "HELP_DOC")
            queued, _ = queue_draft_artifact_regeneration(
                db, artifact_version=help_doc["artifact_version"], project_id=1, prompt_id=44,
                idempotency_key="browser-help-history-0001", requested_by="browser-qa",
                server_policy={
                    "max_requests": 1, "max_total_tokens": 300_000, "max_cost_cny": 5.0,
                    "pricing_source": "offline-browser-script",
                    "pricing_checked_at": datetime.now(timezone.utc).date().isoformat(),
                },
            )
            complete_draft_artifact_regeneration(db, request_id=queued.request_id, generated={
                "asset_type": "HELP_DOC", "title": "小范围操作说明（复检版）",
                "body_markdown": (
                    "# 小范围操作说明（复检版）\n\n"
                    "## 步骤一：核对范围\n\n选择可复现样例，保存输入、权限和失败回退条件。\n\n"
                    "## 步骤二：执行测试\n\n执行小范围测试并记录真实结果；异常时停止扩大范围。\n\n"
                    "## 步骤三：完成复检\n\n检查事实来源和适用限制，保存版本后再按同一范围复测。"
                ),
                "action_ids": ["action-1"], "editorial_notes": ["品牌能力发布前核实"],
                "qa": {"status": "PASS", "verify_first": True},
                "artifact_validation": {"status": "PASS", "issues": []},
            })

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    log = (out / "api.log").open("w", encoding="utf-8")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.release_main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT / "backend", env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    report = {"scope": "OFFLINE_ISOLATED_MULTI_CONTENT_UI", "scenario": scenario,
              "external_calls": 0, "status": "FAIL",
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
            page.goto(f"{origin}/?release_view=releaseMonitor&v2_project=1")
            expect(page.get_by_role("region", name="项目监控概览")).to_be_visible(timeout=15000)
            prompt_entry = page.get_by_role("button", name="查看这个问题", exact=True)
            expect(prompt_entry).to_have_count(1)
            prompt_entry.click()
            expect(page).to_have_url(
                f"{origin}/?release_view=releaseMonitor&v2_project=1&v2_prompt=44"
            )
            expect(page.get_by_text("从这里开始：选择一段时间内的回答", exact=True)).to_be_visible()
            report["monitor_prompt_handoff"] = {
                "project_id": 1,
                "prompt_id": 44,
                "status": "PASS",
            }

            isolated_project_response = page.request.post(origin + "/api/projects", data={
                "name": "浏览器隔离新项目", "brand_name": "星河工具",
                "brand_aliases": ["星河"], "website_url": "https://xinghe.example/",
                "competitors": [{"name": "云端工具", "aliases": ["云端"]}],
            })
            assert isolated_project_response.ok, isolated_project_response.text()
            isolated_project_id = isolated_project_response.json()["id"]
            assert isolated_project_id != 1
            isolated_prompt_response = page.request.post(
                f"{origin}/api/projects/{isolated_project_id}/prompts",
                data={"prompt_text": "如何为团队选择一个可靠的文件协作工具？",
                      "intent_type": "product_selection"},
            )
            assert isolated_prompt_response.ok, isolated_prompt_response.text()
            isolated_prompt_id = isolated_prompt_response.json()["id"]
            assert isolated_prompt_id != 44
            prompt_versions = page.request.get(
                f"{origin}/api/projects/{isolated_project_id}/prompts/{isolated_prompt_id}/versions"
            ).json()
            configuration_versions = page.request.get(
                f"{origin}/api/projects/{isolated_project_id}/configuration-versions"
            ).json()
            imported_response = page.request.post(
                f"{origin}/api/v2/projects/{isolated_project_id}/prompts/{isolated_prompt_id}/manual-imports",
                data={
                    "prompt_version_id": prompt_versions[0]["prompt_version_id"],
                    "prompt_snapshot_hash": prompt_versions[0]["snapshot_hash"],
                    "configuration_version_id": configuration_versions[0]["configuration_version_id"],
                    "configuration_snapshot_hash": configuration_versions[0]["snapshot_hash"],
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                    "source_platform": "wenxin", "source_page_url": "https://yiyan.baidu.com/",
                    "answer_text": "这是人工观察到的完整回答，正文可以用于诊断，但页面引用区域当时无法可靠确认。",
                    "citations": [], "citation_observation_status": "UNKNOWN",
                    "citation_note": "引用区域未稳定显示，不能解释为零引用。",
                    "idempotency_key": "browser-isolated-import-0001",
                },
            )
            assert imported_response.ok, imported_response.text()
            isolated_run_id = imported_response.json()["run_id"]
            range_base = (
                f"{origin}/api/v2/projects/{isolated_project_id}/prompts/"
                f"{isolated_prompt_id}/analysis-ranges"
            )
            preview_response = page.request.post(
                range_base + "/preview", data={"mode": "RUN_IDS", "run_ids": [isolated_run_id]}
            )
            assert preview_response.ok, preview_response.text()
            preview = preview_response.json()
            selected_group = preview["groups"][0]
            freeze_response = page.request.post(range_base + "/freeze", data={
                "selector": preview["selector"], "preview_hash": preview["preview_hash"],
                "group_hash": selected_group["group_hash"], "selected_run_ids": [isolated_run_id],
            })
            assert freeze_response.ok, freeze_response.text()
            isolated_analysis_id = freeze_response.json()["analysis"]["analysis_id"]

            page.goto(f"{origin}/?release_view=releaseMonitor&v2_project={isolated_project_id}")
            expect(page.get_by_text("如何为团队选择一个可靠的文件协作工具？", exact=True)).to_be_visible(
                timeout=15000
            )
            isolated_prompt_entry = page.get_by_role("button", name="查看这个问题", exact=True)
            expect(isolated_prompt_entry).to_have_count(1)
            isolated_prompt_entry.click()
            expect(page).to_have_url(
                f"{origin}/?release_view=releaseMonitor&v2_project={isolated_project_id}"
                f"&v2_prompt={isolated_prompt_id}"
            )
            expect(page.get_by_text("累计采样尝试 1 条", exact=False)).to_be_visible(timeout=15000)
            page.reload()
            expect(page).to_have_url(
                f"{origin}/?release_view=releaseMonitor&v2_project={isolated_project_id}"
                f"&v2_prompt={isolated_prompt_id}"
            )
            page.goto(
                f"{origin}/?release_view=coreV2&v2_project={isolated_project_id}"
                f"&v2_prompt={isolated_prompt_id}&v2_analysis={isolated_analysis_id}"
            )
            expect(page.get_by_text("当前冻结分析还没有优化历史", exact=True)).to_be_visible(timeout=15000)
            expect(page.get_by_text("本次优化的内容资产", exact=True)).to_have_count(0)
            report["dynamic_project_isolation"] = {
                "project_id": isolated_project_id, "prompt_id": isolated_prompt_id,
                "run_id": isolated_run_id, "analysis_id": isolated_analysis_id,
                "citation_observation_status": "UNKNOWN", "status": "PASS",
            }
            page.goto(f"{origin}/?release_view=coreV2&v2_project=1&v2_prompt=44&v2_analysis={analysis_id}")
            expect(page.get_by_text("AI 优化", exact=True)).to_be_visible(timeout=15000)
            expect(page.get_by_role("region", name="AI 优化")).to_be_visible()
            expect(page.get_by_text("内部 Beta · AI 优化", exact=True)).to_be_visible()
            expect(page.get_by_text("当前仅开放历史结果使用", exact=True)).to_be_visible()
            expect(page.get_by_text("优化结果", exact=True)).to_be_visible(timeout=15000)
            if scenario == "success":
                expect(page.get_by_text(
                    "服务端校验通过 · L3_ACTIONABLE_WITHOUT_FACT_CLAIMS", exact=True,
                )).to_be_visible()
            else:
                expect(page.get_by_text("部分完成", exact=True).first).to_be_visible()
            expect(page.get_by_role("button", name="导出本次优化完整报告", exact=True)).to_be_visible()
            expect(page.get_by_text("本次优化的内容资产", exact=True)).to_be_visible()
            expect(page.get_by_text("每份内容独立保存和校验", exact=True)).to_be_visible()
            expect(page.get_by_text("本次品牌观察与证据范围", exact=True)).to_be_visible()
            expect(page.get_by_text(
                f"纳入 {aggregate_member_count} 条完整回答", exact=False,
            )).to_be_visible()
            expect(page.get_by_text(verified_observation, exact=True)).to_be_visible()
            report["aggregate_observation"] = {
                "member_count": aggregate_member_count,
                "business_text_visible": True,
                "internal_hashes_exposed_in_main_card": False,
            }
            expect(page.get_by_text("帮助文档", exact=True).first).to_be_visible()
            expect(page.get_by_text("常见问题 FAQ", exact=True).first).to_be_visible()
            export_buttons = page.get_by_role("button", name="导出 Markdown", exact=True)
            expect(export_buttons).to_have_count(2)
            if scenario == "partial":
                faq_card = page.get_by_test_id("draft-artifact-faq")
                help_card = page.get_by_test_id("draft-artifact-help_doc")
                expect(faq_card.get_by_text("失败", exact=True)).to_be_visible()
                expect(faq_card.get_by_text("稿件已保存，但未通过独立校验", exact=True)).to_be_visible()
                expect(faq_card.get_by_role("button", name="导出 Markdown", exact=True)).to_be_disabled()
                expect(help_card.get_by_role("button", name="导出 Markdown", exact=True)).to_be_enabled()
                with page.expect_download() as downloaded:
                    help_card.get_by_role("button", name="导出 Markdown", exact=True).click()
                assert downloaded.value.suggested_filename.endswith(".md")
                expect(page.get_by_text("已导出当前稿件版本", exact=True)).to_be_visible()
                expect(help_card.get_by_role("button", name="只重新生成这份", exact=True)).to_be_disabled()
                expect(page.get_by_text("单篇重新生成尚未启用", exact=True)).to_be_visible()

                history = page.get_by_label("帮助文档历史版本", exact=True).first
                expect(history).to_be_visible()
                history.click()
                page.get_by_text("第 1 版", exact=False).last.click()
                expect(help_card.get_by_text("第 1 版", exact=False)).to_be_visible()
                history.click()
                page.get_by_text("第 2 版", exact=False).last.click()
                expect(help_card.get_by_text("小范围操作说明（复检版）", exact=True).first).to_be_visible()

                help_card.get_by_text("这份稿件的反馈（0）", exact=True).click()
                help_card.get_by_label("是否可用", exact=True).click()
                page.get_by_text("可用", exact=True).last.click()
                help_card.get_by_label("建议", exact=True).fill("隔离浏览器反馈已保存")
                help_card.get_by_role("button", name="保存这份稿件的反馈", exact=True).click()
                expect(page.get_by_text("反馈已绑定当前稿件版本保存", exact=True)).to_be_visible()
                expect(help_card.get_by_text("隔离浏览器反馈已保存", exact=False)).to_be_visible()
                page.reload()
                expect(page.get_by_text("部分完成", exact=True).first).to_be_visible(timeout=15000)
                help_card = page.get_by_test_id("draft-artifact-help_doc")
                help_card.get_by_text("这份稿件的反馈（1）", exact=True).click()
                expect(help_card.get_by_text("隔离浏览器反馈已保存", exact=False)).to_be_visible()
            page.get_by_text("证据与 QA", exact=True).first.click()
            expect(page.get_by_text("服务端验证的范围说明", exact=True).first).to_be_visible()
            expect(page.get_by_text("VERIFY_FIRST：服务端已核验", exact=False).first).to_be_visible()
            expect(page.get_by_text("证据数量", exact=True).first).to_be_visible()
            expect(page.get_by_text("QA 资格", exact=True).first).to_be_visible()
            expect(page.get_by_text("技术详情（原始数据）", exact=True).first).to_be_visible()
            expect(page.locator("body")).not_to_contain_text("正式库写入成功")
            desktop_name = f"agent-{scenario}-desktop.png"
            page.screenshot(path=str(out / desktop_name), full_page=True)
            report["screenshots"].append(desktop_name)

            page.get_by_text("证据详情与资料限制", exact=True).click()
            expect(page.get_by_text("已反查证据", exact=False)).to_be_visible()
            page.get_by_text("技术审计信息", exact=True).click()
            page.get_by_text("运行记录（", exact=False).click()
            expect(page.get_by_text("EVIDENCE_PACK_FROZEN", exact=False)).to_be_visible()
            expect(page.get_by_text("EVIDENCE_PACK_OUTPUT_VALIDATED", exact=False)).to_be_visible()
            page.get_by_text("正式流程对照（严格同输入", exact=False).click()
            expect(page.get_by_text("该视图只比较同一冻结输入", exact=False)).to_be_visible()
            trace_name = f"agent-{scenario}-trace-compare.png"
            page.screenshot(path=str(out / trace_name), full_page=True)
            report["screenshots"].append(trace_name)

            page.set_viewport_size({"width": 390, "height": 1000})
            mobile_name = f"agent-{scenario}-mobile.png"
            page.screenshot(path=str(out / mobile_name), full_page=True)
            report["screenshots"].append(mobile_name)
            report["mobile_overflow"] = page.evaluate("""() => ({
              viewport: window.innerWidth,
              documentWidth: document.documentElement.scrollWidth,
              offenders: [...document.querySelectorAll('body *')]
                .map(el => ({
                  tag: el.tagName,
                  className: typeof el.className === 'string' ? el.className : '',
                  text: (el.textContent || '').trim().slice(0, 100),
                  left: Math.round(el.getBoundingClientRect().left),
                  right: Math.round(el.getBoundingClientRect().right),
                  scrollWidth: el.scrollWidth,
                  clientWidth: el.clientWidth,
                }))
                .filter(row => row.right > window.innerWidth + 1 || row.left < -1 || row.scrollWidth > row.clientWidth + 1)
                .slice(0, 20),
            })""")
            assert report["mobile_overflow"]["documentWidth"] <= report["mobile_overflow"]["viewport"], \
                report["mobile_overflow"]
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
