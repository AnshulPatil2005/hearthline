"""Drive the public registry page: open it, start funding an item, check PayPal buttons render,
click the PayPal button and confirm a real sandbox order is created (the popup needs a buyer login)."""

import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(exist_ok=True)
URL = os.environ.get("E2E_WEB", "http://localhost:5173") + "/r/rivera-family"


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 1000}, color_scheme="light")
        page = await ctx.new_page()
        console = []
        page.on("console", lambda m: console.append(f"{m.type}: {m.text}"))
        donation_calls = []
        page.on(
            "response",
            lambda r: donation_calls.append((r.status, r.url)) if "/donations" in r.url and r.request.method == "POST" else None,
        )

        await page.goto(URL, wait_until="networkidle")
        await page.screenshot(path=OUT / "registry_public.png", full_page=True)

        await page.get_by_role("button", name="Fund this").first.click()
        await page.wait_for_selector("paypal-button", timeout=20000)
        await page.wait_for_timeout(3000)
        await page.screenshot(path=OUT / "registry_donate.png")
        buttons = await page.evaluate(
            "() => ['paypal-button','venmo-button','paypal-pay-later-button'].map(t => "
            "[t, !!document.querySelector(t), document.querySelector(t)?.hidden ?? null])"
        )
        print("buttons (tag, present, hidden):", buttons)

        popup_future = ctx.wait_for_event("page", timeout=15000)
        await page.locator("paypal-button").click()
        try:
            popup = await popup_future
            await popup.wait_for_load_state("domcontentloaded")
            await popup.wait_for_timeout(4000)
            print("popup opened:", popup.url[:90])
            await popup.screenshot(path=OUT / "registry_popup.png")
        except Exception as e:  # noqa: BLE001
            print("no popup:", type(e).__name__)
        await page.wait_for_timeout(2000)
        print("donation calls:", donation_calls)
        print("console errors:", [c for c in console if c.startswith("error")][:5])
        await browser.close()


asyncio.run(main())
