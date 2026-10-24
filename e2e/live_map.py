"""The Command Center's live map: households by damage on OpenStreetMap tiles with the fire zone and the town's stores;
clicking a pin shows that household; "Ask the grid" narrows the map to the grid's households; approving
first-72-hours aid draws the paid households' rings, the new ones pulsing. Needs a freshly seeded database; one AI
call ("Ask the grid") and one sandbox Payouts batch.
"""

import asyncio
import os
import re
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(exist_ok=True)
WEB = os.environ.get("E2E_WEB", "http://localhost:5173")


async def shown(section) -> str:
    return await section.locator("p[aria-live]").inner_text()


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 1100}, color_scheme="light")
        await page.goto(f"{WEB}/login?as=sam.whitfield&next=/command", wait_until="networkidle")
        section = page.locator("section[aria-labelledby='map-title']")
        await section.wait_for(timeout=30000)
        await page.wait_for_selector(".leaflet-tile-loaded", timeout=30000)
        await section.get_by_text(re.compile(r"^2,0\d\d households shown")).wait_for(timeout=30000)
        print("map:", await shown(section))
        print("stores on the map:", await section.locator(".map-store").count() - 1)  # minus the legend's swatch

        box = await section.locator(".leaflet-container").bounding_box()
        for dx in (0, 6, -6, 12, -12, 18):  # the zone is dense with pins: one of these lands on a household
            await page.mouse.click(box["x"] + box["width"] / 2 + dx, box["y"] + box["height"] / 2 + dx)
            popup = section.locator(".leaflet-popup-content").last
            try:
                await popup.get_by_text("household").first.wait_for(timeout=4000)
                break
            except Exception:  # noqa: BLE001 - missed the pin, try a few pixels over
                continue
        print("clicked a pin:", " | ".join((await popup.inner_text()).split("\n")[:3]))
        await page.keyboard.press("Escape")

        await page.get_by_label("Ask the grid").fill("destroyed homes")
        await page.get_by_role("button", name="Ask", exact=True).click()
        await page.wait_for_selector("text=AI set the filters", timeout=90000)
        await section.get_by_text(re.compile(r"^583 households shown")).wait_for(timeout=30000)
        print("after asking the grid:", await shown(section))
        await page.get_by_role("button", name="Reset view").click()
        await section.get_by_text(re.compile(r"^2,0\d\d households shown")).wait_for(timeout=30000)

        rapid = page.locator("section[aria-labelledby='rapid-title']")
        await rapid.get_by_role("button", name="Simulate an evacuation order (demo)").click()
        proposal = rapid.locator("li", has_text="simulated for this demo").first
        await proposal.get_by_role("button", name="Approve and pay").click()
        await proposal.get_by_text("Decided by").wait_for(timeout=90000)
        await section.get_by_text(re.compile(r"· [1-9]\d* paid in the first 72 hours")).wait_for(timeout=30000)
        fresh = await section.locator("path.map-paid-new").count()
        print("after approving first-72-hours aid:", await shown(section), f"({fresh} rings pulsing)")
        assert fresh > 0
        await section.screenshot(path=OUT / "live_map.png")
        await browser.close()


asyncio.run(main())
