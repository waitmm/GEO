import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.modules.monitoring.collectors.wenxin.selectors import CAPTCHA_TEXT_MARKERS, INPUT_CANDIDATES, LOGIN_TEXT_MARKERS


async def main() -> None:
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        raise SystemExit("未安装 Playwright。请先执行：pip install -r requirements.txt && playwright install chromium") from exc

    settings = get_settings()
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
        body_text = await page.locator("body").inner_text(timeout=5000)
        has_input = False
        for selector in INPUT_CANDIDATES:
            try:
                if await page.locator(selector).last.is_visible(timeout=800):
                    has_input = True
                    break
            except Exception:
                continue
        if any(marker in body_text for marker in CAPTCHA_TEXT_MARKERS):
            print("captcha_required")
        elif any(marker in body_text for marker in LOGIN_TEXT_MARKERS) and not has_input:
            print("login_required")
        elif has_input:
            print("session_ok")
        else:
            print("page_structure_not_matched")
        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
