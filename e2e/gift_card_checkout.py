"""Buy a Reopen Fund gift card the way a regular does: through PayPal's popup in the sandbox, then the page shows the
card and its code. The capture that answers with the code needs the buyer's token, so this checks it gets through."""

import asyncio
import os

from paypal_sandbox import confirm, have_buyer, open_checkout, sign_in
from playwright.async_api import async_playwright

WEB = os.environ.get("E2E_WEB", "http://localhost:5173")


async def main() -> None:
    if not have_buyer():
        raise SystemExit("Needs the sandbox buyer login in backend/.env")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 1000})
        captures = []
        page.on(
            "response",
            lambda r: captures.append((r.status, r.url.split("/gift-cards/")[1][:40]))
            if "/gift-cards/" in r.url and r.request.method == "POST"
            else None,
        )
        await page.goto(f"{WEB}/reopen/morenos-bakery", wait_until="networkidle")
        await page.wait_for_selector("paypal-button", timeout=60000)
        await page.wait_for_timeout(2500)
        popup = await open_checkout(page, page.locator("paypal-button").first)
        await sign_in(popup)
        print("confirmed with:", await confirm(popup))
        await page.get_by_text("Thank you for helping").first.wait_for(timeout=120000)
        code = await page.locator("p.font-mono").first.inner_text()
        print("card on the page:", code, "| capture calls:", captures)
        await browser.close()


asyncio.run(main())
