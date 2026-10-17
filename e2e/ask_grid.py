"""Ask the grid: the org admin types a question; AG Grid's AI Toolkit schema goes to the server, a model fills
it in, the server checks it, and the grid applies the filters, sorting and grouping. Uses two AI calls.
Needs the API and the web app running."""

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
        page = await browser.new_page(viewport={"width": 1500, "height": 1100}, color_scheme="light")
        errors = []
        page.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)

        await page.goto(f"{WEB}/login?as=sam.whitfield", wait_until="networkidle")
        await page.wait_for_selector(".ag-row[row-index='0']", timeout=20000)

        await page.get_by_label("Ask the grid").fill("destroyed homes on Juniper Lane that have no PayPal account yet")
        await page.get_by_role("button", name="Ask", exact=True).click()
        await page.wait_for_selector("text=AI set the filters", timeout=60000)
        await page.wait_for_timeout(1000)
        answer = await page.locator("section", has_text="Ask the grid").locator("p").first.inner_text()
        print("answer:", " ".join(answer.split())[:200])
        rows = await page.locator(".ag-root-wrapper").first.locator(".ag-row").all_inner_texts()
        print("first rows:", [" | ".join(r.split("\n")[:4]) for r in rows[:3]])
        print("filtered columns:", await page.locator(".ag-header-cell-filtered").count())
        await page.screenshot(path=OUT / "ask_grid.png")

        await page.get_by_label("Ask the grid").fill("total still needed by street for verified households")
        await page.get_by_role("button", name="Ask", exact=True).click()
        households = page.locator(".ag-root-wrapper").first  # the batch list below is a grid too
        await page.get_by_role("button", name="Ask", exact=True).wait_for(timeout=60000)  # done thinking
        await households.locator(".ag-row-group").first.wait_for(timeout=30000)
        groups = await households.locator(".ag-row-group").all_inner_texts()
        print("grouped:", [" ".join(g.split())[:60] for g in groups[:4]])
        await page.screenshot(path=OUT / "ask_grid_grouped.png")

        await page.get_by_role("button", name="Reset view").click()
        await page.wait_for_timeout(1000)
        print("after reset:", await page.get_by_text("households match").first.inner_text())
        print("console errors:", [e for e in errors if "license" not in e.lower() and "trial" not in e.lower() and "****" not in e][:4])
        await browser.close()


asyncio.run(main())
