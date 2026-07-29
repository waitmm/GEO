import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.modules.monitoring.collectors.wenxin.selectors import (
    INPUT_CANDIDATES,
    SUBMIT_BUTTON_CANDIDATES,
)


CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE_DIR = Path("runtime") / "wenxin-visible-demo"
QUERY = "谁是最好的二维码工具"


async def find_visible(page, selectors):
    for selector in selectors:
        locator = page.locator(selector).last
        try:
            if await locator.is_visible(timeout=1000):
                return locator
        except Exception:
            continue
    return None


async def main() -> None:
    from playwright.async_api import async_playwright

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            executable_path=CHROME_PATH,
            user_data_dir=str(PROFILE_DIR.resolve()),
            headless=False,
            viewport={"width": 1440, "height": 1000},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            args=["--start-maximized"],
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://chat.baidu.com/", wait_until="domcontentloaded", timeout=120_000)
        await page.wait_for_timeout(3000)

        input_box = await find_visible(page, INPUT_CANDIDATES)
        if input_box is None:
            print("未找到输入框；浏览器保持打开，请查看当前页面。", flush=True)
        else:
            await input_box.click()
            await input_box.fill(QUERY)
            submit = await find_visible(page, SUBMIT_BUTTON_CANDIDATES)
            if submit is not None:
                await submit.click()
            else:
                await page.keyboard.press("Enter")
            print(f"已发送问题：{QUERY}", flush=True)

        print("浏览器将保留 10 分钟；可以直接观察或手动关闭窗口。", flush=True)
        try:
            await page.wait_for_timeout(600_000)
        except Exception:
            pass
        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
