"""Household requests cash aid; the randomly assigned reviewer approves it; PayPal Payouts sends it.

Uses the real AI (Sentinel summary) and the PayPal sandbox. Needs the API and web app running.
"""

import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(exist_ok=True)
WEB = os.environ.get("E2E_WEB", "http://localhost:5173")
AMOUNT = "300"


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        home = await browser.new_page(viewport={"width": 1280, "height": 1000}, color_scheme="light")
        await home.goto(f"{WEB}/login?as=elena.rivera&next=/aid", wait_until="networkidle")
        await home.get_by_label("Amount").fill(AMOUNT)
        await home.get_by_placeholder("What is it for?").fill("Two weeks at the Sablewood Inn while we find a rental.")
        await home.get_by_role("button", name="Send request").click()
        await home.wait_for_selector(f"text=Cash aid · ${AMOUNT}", timeout=60000)
        print("household: request sent")

        for persona in ("priya.nair", "tom.becker"):
            staff = await browser.new_page(viewport={"width": 1400, "height": 1000}, color_scheme="light")
            await staff.goto(f"{WEB}/login?as={persona}", wait_until="networkidle")
            await staff.wait_for_selector(".ag-root", timeout=20000)
            row = staff.locator(".ag-row", has_text=f"${AMOUNT}")
            if await row.count():
                await row.first.click()
                await staff.wait_for_selector("text=Sentinel's summary", timeout=15000)
                summary = await staff.locator("section", has_text="Sentinel's summary").first.inner_text()
                print(f"{persona} is the assigned reviewer. Sentinel:", summary.split("\n")[1][:160])
                await staff.get_by_role("button", name="Approve").click()
                await staff.wait_for_selector("text=This case was approved.", timeout=60000)
                print(f"{persona}: approved;", (await staff.locator("text=PayPal reference").first.inner_text()))
                await staff.close()
                break
            await staff.close()

        await home.reload(wait_until="networkidle")
        card = home.locator("li", has_text=f"Cash aid · ${AMOUNT}").first
        print("household now sees:", (await card.inner_text()).split("\n")[2])
        await home.screenshot(path=OUT / "aid.png", full_page=True)
        await browser.close()


asyncio.run(main())
