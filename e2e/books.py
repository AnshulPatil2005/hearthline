"""Books and PayPal: the org admin opens the reconciliation of Hearthline's ledger against PayPal's Transaction Search
(through APIMatic's PayPal SDK). The PayPal balance, the counts and the grid load; the batch cash-aid preview says
whether that balance covers the batch. Needs the API (demo seed), the web app and Transaction Search on the app."""

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
        page = await browser.new_page(viewport={"width": 1350, "height": 950}, color_scheme="light")
        await page.goto(f"{WEB}/login?as=sam.whitfield&next=/command/books")
        await page.wait_for_selector("text=Books and PayPal", timeout=20000)
        await page.wait_for_selector("text=Checking with PayPal", state="detached", timeout=90000)
        cards = [" ".join(x.split()) for x in await page.locator("dl > div").all_inner_texts()]
        print("cards:", " | ".join(cards))
        assert cards[0].startswith("PayPal balance $"), cards[0]
        await page.locator(".ag-root-wrapper").wait_for(timeout=15000)
        print("grid rows:", await page.locator(".ag-row").count())
        await page.screenshot(path=OUT / "books.png")

        await page.goto(f"{WEB}/command")
        await page.get_by_role("button", name="Send cash aid").first.click()
        await page.get_by_role("button", name="Preview").click()
        line = page.locator("text=/PayPal balance/").first
        await line.wait_for(timeout=60000)
        print("batch preview:", await line.inner_text())
        await browser.close()


asyncio.run(main())
