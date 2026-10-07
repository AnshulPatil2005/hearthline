"""A reviewer books a video call on a medium-risk case; it appears in Bryntum Calendar and the
case pipeline appears in Bryntum TaskBoard. Needs the API (demo seed) and the web app running."""

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(exist_ok=True)
WEB = "http://localhost:5173"


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 1000}, color_scheme="light")
        errors = []
        page.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)

        await page.goto(f"{WEB}/login?as=priya.nair", wait_until="networkidle")
        await page.locator(".ag-row", has_text="Kowalski").first.click()
        await page.wait_for_selector("text=Video verification", timeout=15000)
        approve = await page.get_by_role("button", name="Approve").count()
        await page.get_by_role("button", name="Book 20-minute call").click()
        await page.wait_for_selector("text=Mark call done", timeout=10000)
        print("call booked on the case page; approve button present:", bool(approve))

        await page.goto(f"{WEB}/review/calendar", wait_until="networkidle")
        await page.wait_for_selector(".b-cal-event", timeout=30000)
        events = await page.locator(".b-cal-event").all_inner_texts()
        print("calendar events:", [e.replace("\n", " ")[:60] for e in events])
        await page.screenshot(path=OUT / "calendar.png")

        await page.goto(f"{WEB}/review/board", wait_until="networkidle")
        await page.wait_for_selector(".b-task-board-card", timeout=30000)
        cards = await page.locator(".b-task-board-card").count()
        print("taskboard cards:", cards)
        await page.screenshot(path=OUT / "taskboard.png")
        print("console errors:", [e for e in errors if "license" not in e.lower() and "trial" not in e.lower()][:4])
        await browser.close()


asyncio.run(main())
