import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings


async def main() -> None:
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        raise SystemExit("未安装 Playwright。请先执行：pip install -r requirements.txt && playwright install chromium") from exc

    settings = get_settings()
    profile_dir = Path(settings.wenxin_profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            viewport={"width": 1440, "height": 1000},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(settings.wenxin_web_url, wait_until="domcontentloaded")
        print(f"已打开文心助手，请在浏览器中手动登录。Profile 目录：{profile_dir}")
        print("登录完成后回到终端按 Enter 关闭浏览器。")
        input()
        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
