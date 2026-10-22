"""Browser acceptance against the persistent localhost-only M1 Beta deployment."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


SUGGESTION = "本机正式部署验收：历史结果查看、复制、导出和反馈链路正常。"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", default="http://127.0.0.1:8032")
    parser.add_argument("--analysis", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--submit-feedback", action="store_true")
    args = parser.parse_args()

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "contract": "geo.internal-beta.m1.local-deployment.v1",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "origin": args.origin,
        "external_model_calls": 0,
        "submit_feedback": args.submit_feedback,
        "status": "FAIL",
        "page_errors": [],
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel="chrome")
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.grant_permissions(["clipboard-read", "clipboard-write"], origin=args.origin)
        context.route("**/*", lambda route: route.continue_()
                      if route.request.url.startswith(args.origin + "/") else route.abort())
        page = context.new_page()
        page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
        try:
            health = page.request.get(args.origin + "/api/health")
            assert health.ok and health.json()["worker"]["status"] == "RUNNING"
            url = (f"{args.origin}/?release_view=coreV2&v2_project=1&v2_prompt=1"
                   f"&v2_analysis={args.analysis}")
            page.goto(url, wait_until="networkidle")
            expect(page.get_by_text("爱短链", exact=True).first).to_be_visible(timeout=20000)
            expect(page.get_by_text("抖音跳转链接", exact=True).first).to_be_visible()
            expect(page.get_by_role("region", name="AI 优化")).to_be_visible()
            expect(page.get_by_text("日常模型调用已启用", exact=True)).to_be_visible()
            expect(page.get_by_role("button", name="创建并运行 AI 优化")).to_be_enabled()
            expect(page.get_by_text("已保存的真实模型结果", exact=True).first).to_be_visible()
            expect(page.get_by_text("服务端校验 PASS · L2_PARTIALLY_GROUNDED", exact=True)).to_be_visible()
            for section in ["GEO 诊断与依据", "品牌表现与证据缺口", "优化策略与渠道", "完整正文", "QA 与事实限制", "复测计划"]:
                expect(page.get_by_text(section, exact=True)).to_be_visible()

            page.get_by_role("button", name="复制完整正文").click()
            expect(page.get_by_text("正文已复制", exact=True)).to_be_visible()
            copied = page.evaluate("navigator.clipboard.readText()")
            assert len(copied) > 500 and "抖音" in copied
            with page.expect_download() as download_info:
                page.get_by_role("button", name="导出完整报告").click()
            report["download"] = download_info.value.suggested_filename

            if args.submit_feedback:
                rating = page.locator(".ant-form-item").filter(has_text="这份结果是否可用")
                rating.locator(".ant-select").click()
                page.get_by_title("可用", exact=True).click()
                reasons = page.locator(".ant-form-item").filter(has_text="主要原因")
                reasons.locator(".ant-select").click()
                page.get_by_title("操作体验", exact=True).click()
                page.keyboard.press("Escape")
                page.locator(".ant-form-item").filter(has_text="建议或问题").locator("textarea").fill(SUGGESTION)
                page.get_by_role("button", name="保存反馈").click()
                expect(page.get_by_text("反馈已追加保存，原结果与此前反馈均未被覆盖", exact=True)).to_be_visible()
                page.reload(wait_until="networkidle")
            history = page.get_by_text("该版本历史反馈（", exact=False)
            expect(history).to_be_visible(timeout=20000)
            history.click()
            expect(page.get_by_text(SUGGESTION, exact=False)).to_be_visible()
            page.screenshot(path=str(output / ("after-submit.png" if args.submit_feedback else "after-restart.png")), full_page=True)
            page.get_by_role("menuitem", name="Monitor · 监测").click()
            page.get_by_text("定时采集管理", exact=True).click()
            expect(page.get_by_role("button", name="立即采集")).to_be_enabled(timeout=20000)
            page.screenshot(path=str(output / "sampling-enabled.png"), full_page=True)
            assert not report["page_errors"], report["page_errors"]
            report["status"] = "PASS"
        finally:
            browser.close()
            (output / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
