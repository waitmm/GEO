"""Browser acceptance for the M1 employee flow against a running isolated Beta copy."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", default="http://127.0.0.1:5183")
    parser.add_argument("--project", type=int, default=1)
    parser.add_argument("--prompt", type=int, default=1)
    parser.add_argument("--analysis", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "contract": "geo.internal-beta.m1.browser-acceptance.v1",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "origin": args.origin,
        "project_id": args.project,
        "prompt_id": args.prompt,
        "analysis_id": args.analysis,
        "external_model_calls": 0,
        "status": "FAIL",
        "screenshots": [],
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
            url = (f"{args.origin}/?release_view=coreV2&v2_project={args.project}"
                   f"&v2_prompt={args.prompt}&v2_analysis={args.analysis}")
            page.goto(url, wait_until="networkidle")
            expect(page.get_by_text("AI 优化", exact=True)).to_be_visible(timeout=20000)
            expect(page.get_by_role("region", name="AI 优化")).to_be_visible()
            expect(page.get_by_text("内部 Beta · AI 优化", exact=True)).to_be_visible()
            expect(page.get_by_text("当前仅开放历史结果使用", exact=True)).to_be_visible()
            expect(page.get_by_role("button", name="创建并运行 AI 优化")).to_be_disabled()
            expect(page.get_by_text("已保存的真实模型结果", exact=True).first).to_be_visible()
            expect(page.get_by_text("服务端校验 PASS · L2_PARTIALLY_GROUNDED", exact=True)).to_be_visible()
            expect(page.get_by_role("combobox", name="结果历史版本")).to_be_visible()
            expect(page.get_by_text("GEO 诊断与依据", exact=True)).to_be_visible()
            expect(page.get_by_text("品牌表现与证据缺口", exact=True)).to_be_visible()
            expect(page.get_by_text("完整正文", exact=True)).to_be_visible()
            page.screenshot(path=str(output / "m1-result-desktop.png"), full_page=True)
            report["screenshots"].append("m1-result-desktop.png")

            page.get_by_role("button", name="复制完整正文").click()
            expect(page.get_by_text("正文已复制", exact=True)).to_be_visible()
            copied = page.evaluate("navigator.clipboard.readText()")
            assert len(copied) > 500 and "抖音" in copied
            with page.expect_download() as download_info:
                page.get_by_role("button", name="导出完整报告").click()
            download = download_info.value
            assert download.suggested_filename.endswith(".md")
            report["download"] = download.suggested_filename

            rating = page.locator(".ant-form-item").filter(has_text="这份结果是否可用")
            rating.locator(".ant-select").click()
            page.locator(".ant-select-item-option").filter(has_text="需修改").click()
            reasons = page.locator(".ant-form-item").filter(has_text="主要原因")
            reasons.locator(".ant-select").click()
            page.locator(".ant-select-item-option").filter(has_text="品牌关联不足").click()
            page.keyboard.press("Escape")
            page.locator(".ant-form-item").filter(has_text="建议或问题").locator("textarea").fill(
                "浏览器验收反馈：品牌关联需要更具体，但不能把关联目标写成品牌事实。"
            )
            page.get_by_role("button", name="保存反馈").click()
            expect(page.get_by_text("反馈已追加保存，原结果与此前反馈均未被覆盖", exact=True)).to_be_visible()
            expect(page.get_by_text("该版本历史反馈（1）", exact=True)).to_be_visible(timeout=10000)
            page.reload(wait_until="networkidle")
            expect(page.get_by_text("该版本历史反馈（1）", exact=True)).to_be_visible(timeout=20000)
            page.get_by_text("该版本历史反馈（1）", exact=True).click()
            expect(page.get_by_text("浏览器验收反馈：品牌关联需要更具体", exact=False)).to_be_visible()
            page.screenshot(path=str(output / "m1-feedback-refresh.png"), full_page=True)
            report["screenshots"].append("m1-feedback-refresh.png")

            isolated = page.request.post(args.origin + "/api/projects", data={
                "name": "M1 隔离检查", "brand_name": "隔离品牌", "brand_aliases": [],
                "website_url": "", "competitors": [], "industry": "验收", "region": "CN", "language": "zh-CN",
            })
            assert isolated.ok, isolated.text()
            isolated_project_id = isolated.json()["id"]
            page.reload(wait_until="networkidle")
            page.locator(".project-select").click()
            page.get_by_text("M1 隔离检查", exact=True).click()
            expect(page).to_have_url(re.compile(rf"[?&]v2_project={isolated_project_id}(?:&|$)"))
            expect(page.get_by_text("已保存的真实模型结果", exact=True)).to_have_count(0)
            assert "agent-result-v1:agent-run-9e3d4fa8" not in page.locator("body").inner_text()
            page.screenshot(path=str(output / "m1-project-isolation.png"), full_page=True)
            report["screenshots"].append("m1-project-isolation.png")

            page.goto(f"{args.origin}/?release_view=brandContext&v2_project={args.project}", wait_until="networkidle")
            expect(page.get_by_text("品牌关联目标不等于品牌事实", exact=True)).to_be_visible(timeout=20000)
            for label in ["希望建立的品牌关联", "项目组声明为已核实的产品能力", "能力来源与维护依据",
                          "待核实能力与资料缺口", "禁止使用的品牌表述", "可供考虑的内容资产", "可供考虑的发布渠道"]:
                expect(page.get_by_label(label, exact=True)).to_be_visible()
            page.screenshot(path=str(output / "m1-brand-context.png"), full_page=True)
            report["screenshots"].append("m1-brand-context.png")

            page.goto(url, wait_until="networkidle")
            page.set_viewport_size({"width": 390, "height": 844})
            expect(page.get_by_role("region", name="AI 优化")).to_be_visible(timeout=20000)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=str(output / "m1-mobile.png"), full_page=True)
            report["screenshots"].append("m1-mobile.png")
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
