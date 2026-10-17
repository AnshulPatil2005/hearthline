"""Two reviewers reject the seeded impersonation registry; donors are refunded and it disappears.

Needs the API (with the demo seed) and the web app running. See README.md.
"""

import asyncio
import json
import os
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(exist_ok=True)
WEB = os.environ.get("E2E_WEB", "http://localhost:5173")
API = os.environ.get("E2E_API", "http://localhost:8000")
SCAM_SLUG = "riveras-rebuild-fund"


def api_get(path: str) -> dict:
    with urllib.request.urlopen(API + path) as r:
        return json.load(r)


async def review_as(browser, persona: str, case_title: str, reason: str, shot: str) -> None:
    page = await browser.new_page(viewport={"width": 1400, "height": 1000}, color_scheme="light")
    await page.goto(f"{WEB}/login?as={persona}", wait_until="networkidle")
    await page.wait_for_selector(".ag-row", timeout=20000)
    if shot == "queue":
        await page.screenshot(path=OUT / "review_queue.png")
    await page.locator(".ag-row", has_text=case_title).first.click()
    await page.wait_for_selector("text=Sentinel's summary", timeout=15000)
    if shot == "case":
        await page.screenshot(path=OUT / "review_case.png", full_page=True)
    await page.get_by_placeholder("Your reason").fill(reason)
    await page.get_by_role("button", name="Reject").click()
    await page.wait_for_timeout(1500)
    print(f"{persona}: {(await page.locator('h1 + span, h1 ~ span').all_inner_texts())}")
    await page.close()


async def main() -> None:
    before = api_get(f"/registries/{SCAM_SLUG}")
    print("scam registry before:", before["status"], "funded", before["total_funded"])
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        await review_as(browser, "priya.nair", "Rivera family fund", "Photos copied from the Riveras; address outside the fire.", "queue")
        await review_as(browser, "tom.becker", "Rivera family fund", "Agree: impersonation of the Rivera family.", "case")
        await browser.close()
    after = api_get(f"/registries/{SCAM_SLUG}")
    print("scam registry after:", after["status"], "funded", after["total_funded"], "| recent gifts:", len(after["recent_donations"]))


asyncio.run(main())
