"""Crew dispatch in Bryntum Scheduler Pro: the org admin drags a job that has no crew yet onto a crew,
and the assignment is saved. Needs the API (fresh demo seed) and the web app running."""

import asyncio
import json
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(exist_ok=True)
WEB = "http://localhost:5173"
API = "http://localhost:8000"


def load(token: str) -> dict:
    req = urllib.request.Request(f"{API}/bryntum/crews/load", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1500, "height": 1000}, color_scheme="light")
        errors = []
        page.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)

        await page.goto(f"{WEB}/login?as=sam.whitfield&next=/command/crews", wait_until="networkidle")
        await page.wait_for_selector(".b-sch-event", timeout=30000)
        print("jobs drawn:", await page.locator(".b-sch-event").count(), "| travel buffers:", await page.locator(".b-sch-event-buffer-before").count())
        await page.screenshot(path=OUT / "crews.png")

        token = await page.evaluate("localStorage.getItem('hearthline.token')")
        before = load(token)
        unassigned = {a["eventId"] for a in before["assignments"]["rows"] if a["resourceId"] == "unassigned"}
        # Drag the first visible unassigned job down onto the third crew row.
        boxes = """() => [...document.querySelectorAll('.b-sch-event-wrap')].map(e => {
            const r = e.getBoundingClientRect();
            return { id: Number(e.dataset.eventId), x: r.x, y: r.y, width: r.width, height: r.height };
        })"""
        box = None
        for _ in range(8):  # scroll right through the coming days until one is on screen
            box = next((b for b in await page.evaluate(boxes) if b["id"] in unassigned and 400 < b["x"] < 1250), None)
            if box:
                break
            await page.mouse.move(900, 500)
            await page.mouse.wheel(600, 0)
            await page.wait_for_timeout(500)
        assert box is not None, "no unassigned job came into view"
        job_id = box["id"]
        target_row = page.locator(".b-grid-row", has_text="Tarp Team").first  # the crew name column
        row_box = await target_row.bounding_box()
        await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        await page.mouse.down()
        await page.mouse.move(box["x"] + box["width"] / 2, row_box["y"] + row_box["height"] / 2, steps=20)
        await page.mouse.up()
        await page.wait_for_timeout(2500)
        after = load(token)
        new_crew = next(a["resourceId"] for a in after["assignments"]["rows"] if a["eventId"] == job_id)
        crew_name = next(r["name"] for r in after["resources"]["rows"] if r["id"] == new_crew) if new_crew != "unassigned" else "unassigned"
        print(f"job {job_id}: unassigned -> {crew_name}")
        await page.screenshot(path=OUT / "crews_after.png")
        print("console errors:", [e for e in errors if "license" not in e.lower() and "trial" not in e.lower() and "****" not in e][:4])
        await browser.close()


asyncio.run(main())
