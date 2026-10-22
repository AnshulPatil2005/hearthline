"""Real disasters: the org admin opens the Disasters page, picks a recent FEMA declaration (live OpenFEMA data),
sees its zone drawn from the Census Bureau's county shapes, and opens it in Hearthline; the Command Center's
first-72-hours aid panel then offers the new disaster and shows the declaration's proposal; the weather warnings tab
lists live National Weather Service warnings with their zones; closing the disaster puts it back. No AI calls, no
payments.
"""

import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(exist_ok=True)
WEB = os.environ.get("E2E_WEB", "http://localhost:5173")
STATES = {"AS", "GU", "MP", "PR", "VI", "FM", "MH", "PW"}  # territories: pick a state, where county shapes exist


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 1100}, color_scheme="light")
        await page.goto(f"{WEB}/login?as=sam.whitfield&next=/command/disasters", wait_until="networkidle")
        await page.get_by_role("heading", name="Open in Hearthline").wait_for(timeout=20000)
        demo = page.locator("li", has_text="Fictional demo")
        print("in Hearthline:", (await demo.first.inner_text()).split("\n")[0])

        await page.wait_for_selector(".ag-row", timeout=30000)
        rows = page.locator(".ag-grid-scrolling-container .ag-row")
        print("FEMA declarations listed:", await rows.count(), "(rendered)")
        chosen = None
        for i in range(await rows.count()):
            state = await rows.nth(i).locator("[col-id='state']").inner_text()
            opened = await rows.nth(i).locator("[col-id='opened_event_id']").inner_text()
            if state not in STATES and not opened.strip():
                chosen = rows.nth(i)
                break
        assert chosen is not None, "no declaration for a state"
        code = await chosen.locator("[col-id='code']").inner_text()
        title = await chosen.locator("[col-id='title']").inner_text()
        await chosen.click()
        preview = page.locator("section[aria-labelledby='preview-title']")
        await preview.locator("svg[role='img']").wait_for(timeout=60000)
        print(f"preview {code} ({title}):", (await preview.inner_text()).split("\n")[2:4])
        await page.screenshot(path=OUT / "disasters_preview.png")

        await preview.get_by_role("button", name="Open in Hearthline").click()
        note = page.get_by_role("status")
        await note.wait_for(timeout=60000)
        print("opened:", (await note.inner_text()).split("Review")[0].strip())
        card = page.locator("li", has_text=f"FEMA {code}")
        await card.wait_for(timeout=20000)

        await page.get_by_role("tab", name="Weather warnings").click()
        await page.wait_for_selector(".ag-row [col-id='severity']", timeout=30000)  # the warnings grid's own rows
        warnings = page.locator(".ag-grid-scrolling-container .ag-row")
        count = await warnings.count()
        print("NWS warnings listed:", count)
        if count:
            await warnings.first.click()
            await preview.locator("svg[role='img'], .text-danger").first.wait_for(timeout=60000)
            print("warning preview:", (await preview.inner_text()).split("\n")[0])

        await page.goto(f"{WEB}/command", wait_until="networkidle")
        rapid = page.locator("section[aria-labelledby='rapid-title']")
        await rapid.wait_for(timeout=20000)
        options = await rapid.get_by_label("Disaster").locator("option").all_inner_texts()
        print("rapid aid disasters:", options)
        proposal = rapid.locator("li", has_text=f"FEMA {code}")
        await proposal.wait_for(timeout=20000)
        print("rapid aid proposal:", (await proposal.inner_text()).split("\n")[:3])
        await page.screenshot(path=OUT / "disasters_rapid_aid.png")

        await page.goto(f"{WEB}/command/disasters", wait_until="networkidle")
        card = page.locator("li", has_text=f"FEMA {code}")
        await card.get_by_role("button", name="Close").click()
        await card.get_by_text("Closed").wait_for(timeout=20000)
        print("closed again")
        await page.screenshot(path=OUT / "disasters.png", full_page=True)
        await browser.close()


asyncio.run(main())
