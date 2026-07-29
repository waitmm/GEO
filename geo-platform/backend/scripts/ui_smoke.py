import asyncio
from pathlib import Path

from playwright.async_api import async_playwright


async def main() -> None:
    output = Path(__file__).resolve().parents[2] / "artifacts" / "ui-validation-dashboard.png"
    config_output = Path(__file__).resolve().parents[2] / "artifacts" / "ui-audit-config.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(
        executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        headless=True,
    )
    page = await browser.new_page(viewport={"width": 1600, "height": 1000})
    await page.goto("http://127.0.0.1:5173", wait_until="networkidle")
    await page.get_by_text("Data Quality", exact=True).wait_for(state="visible", timeout=60_000)
    await page.wait_for_timeout(500)
    await page.screenshot(path=str(output), full_page=True)
    body = await page.locator("body").inner_text()
    required = ["GEO Audit Alpha", "Validation Dashboard", "Data Quality", "Top Domains"]
    missing = [label for label in required if label not in body]
    if missing:
        raise AssertionError(f"Missing UI labels: {missing}")
    await page.get_by_text("审计配置", exact=True).click()
    await page.get_by_text("创建采集 Batch", exact=True).wait_for(state="visible")
    await page.screenshot(path=str(config_output), full_page=True)
    print({"dashboard_screenshot": str(output), "config_screenshot": str(config_output), "required_labels": "ok"})
    await browser.close()
    await playwright.stop()


if __name__ == "__main__":
    asyncio.run(main())
