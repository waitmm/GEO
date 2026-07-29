import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.modules.monitoring.collectors.wenxin.selectors import INPUT_CANDIDATES


async def main() -> None:
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        raise SystemExit("未安装 Playwright。请先执行：pip install -r requirements.txt && playwright install chromium") from exc

    settings = get_settings()
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    output_dir = Path("artifacts") / "debug" / f"wenxin-{stamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=settings.wenxin_profile_dir,
            headless=settings.wenxin_headless,
            viewport={"width": 1440, "height": 1000},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(settings.wenxin_web_url, wait_until="domcontentloaded", timeout=settings.wenxin_browser_timeout_seconds * 1000)
        await page.wait_for_timeout(3000)

        body_text = await page.locator("body").inner_text(timeout=5000)
        body_html = await page.locator("body").evaluate("node => node.outerHTML")
        selector_report = []
        for selector in INPUT_CANDIDATES:
            locators = page.locator(selector)
            try:
                count = await locators.count()
            except Exception:
                count = 0
            items = []
            for index in range(min(count, 10)):
                locator = locators.nth(index)
                try:
                    items.append(
                        {
                            "index": index,
                            "visible": await locator.is_visible(timeout=500),
                            "enabled": await locator.is_enabled(timeout=500),
                            "text": (await locator.inner_text(timeout=500))[:200],
                        }
                    )
                except Exception as exc:
                    items.append({"index": index, "error": str(exc)[:200]})
            selector_report.append({"selector": selector, "count": count, "items": items})

        (output_dir / "body.txt").write_text(body_text, encoding="utf-8")
        (output_dir / "body.html").write_text(body_html, encoding="utf-8")
        (output_dir / "selectors.json").write_text(json.dumps(selector_report, ensure_ascii=False, indent=2), encoding="utf-8")
        await page.screenshot(path=str(output_dir / "page.png"), full_page=True)
        await context.close()
        print(f"debug artifacts saved: {output_dir}")


if __name__ == "__main__":
    asyncio.run(main())
