"""Price Watch: the public report lists essential prices against their pre-disaster baseline, with
sparklines and the over-the-limit ones in red. Needs the API (demo seed) and the web app running."""

import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(exist_ok=True)
WEB = os.environ.get("E2E_WEB", "http://localhost:5173")


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1500, "height": 1000}, color_scheme="light")
        errors = []
        page.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)
        await page.goto(f"{WEB}/price-watch", wait_until="networkidle")
        await page.wait_for_selector(".ag-row", timeout=20000)
        print("summary:", (await page.locator("p.rounded-lg").first.inner_text()).strip())
        print("rows:", await page.locator(".ag-center-cols-container .ag-row, .ag-row").count() // 1)
        print("red change cells:", await page.locator(".ag-cell.text-danger").count())
        print("sparklines:", await page.locator(".ag-sparkline-wrapper canvas").count())
        top = await page.locator(".ag-row[row-index='0']").first.inner_text()
        print("top row:", " | ".join(top.split("\n"))[:140])
        await page.screenshot(path=OUT / "price_watch.png")
        print("console errors:", [e for e in errors if all(s not in e.lower() for s in ("license", "trial", "****"))][:4])
        await browser.close()


asyncio.run(main())
