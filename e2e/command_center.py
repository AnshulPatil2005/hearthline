"""The org admin's Command Center: 2,000 households in a server-side AG Grid. Filters, sorting and grouping
run on the server. Needs the API (fresh demo seed) and the web app running."""

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(exist_ok=True)
WEB = "http://localhost:5173"


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1500, "height": 1100}, color_scheme="light")
        errors = []
        page.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)
        requests = []
        page.on("request", lambda r: requests.append(r.post_data) if r.url.endswith("/command/households/rows") else None)

        await page.goto(f"{WEB}/login?as=sam.whitfield", wait_until="networkidle")
        await page.wait_for_url("**/command", timeout=10000)
        await page.wait_for_selector(".ag-row[row-index='0']", timeout=20000)
        print("matching:", await page.get_by_text("households match").inner_text())  # e.g. 2,005
        first = await page.locator(".ag-row[row-index='0']").last.inner_text()
        print("top row:", first.replace("\n", " | ")[:160])
        print("sparklines drawn:", await page.locator(".ag-sparkline-wrapper canvas").count())
        await page.screenshot(path=OUT / "command_center.png")

        # Group by damage: drag the column header into the row-group bar.
        src = await page.locator(".ag-header-cell", has_text="Damage").first.bounding_box()
        dst = await page.get_by_text("Drag here to set row groups").first.bounding_box()
        await page.mouse.move(src["x"] + 30, src["y"] + src["height"] / 2)
        await page.mouse.down()
        await page.mouse.move(dst["x"] + 20, dst["y"] + dst["height"] / 2, steps=15)
        await page.mouse.up()
        await page.wait_for_selector(".ag-row-group", timeout=15000)
        groups = await page.locator(".ag-row-group").all_inner_texts()
        print("groups:", [g.replace("\n", " ")[:70] for g in groups])
        await page.screenshot(path=OUT / "command_center_grouped.png")
        print("server requests:", len(requests))
        print("console errors:", [e for e in errors if "license" not in e.lower() and "trial" not in e.lower()][:4])
        await browser.close()


asyncio.run(main())
