"""The agent marketplace: a donor funds the Riveras' twin bed frames with a real sandbox payment; Hearthline's Shopper
asks both town stores' pricing agents (Sablewood Mercantile and Juniper Hardware & Home) for quotes over MCP, may
counter, and buys the best price within its limit; Elena reads the negotiation on her purchase, and the winning
store sees the order. Needs the API (demo seed), the web app and the sandbox buyer login in backend/.env; real
sandbox payments and several AI calls (the Shopper's picks and each store's agent)."""

import asyncio
import os
from pathlib import Path

from paypal_sandbox import confirm, have_buyer, open_checkout, sign_in
from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(exist_ok=True)
WEB = os.environ.get("E2E_WEB", "http://localhost:5173")
ITEM = "Twin bed frames"


async def main() -> None:
    if not have_buyer():
        print("skipped: no sandbox buyer login in backend/.env")
        return
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        donor = await browser.new_page(viewport={"width": 1280, "height": 1000}, color_scheme="light")
        await donor.goto(f"{WEB}/r/rivera-family", wait_until="networkidle")
        await donor.locator("li", has_text=ITEM).get_by_role("button", name="Fund this").click()
        await donor.wait_for_selector("paypal-button", timeout=30000)
        await donor.wait_for_timeout(3000)
        popup = await open_checkout(donor, donor.locator("paypal-button"))
        await sign_in(popup)
        print("donor confirmed with:", await confirm(popup))
        await donor.wait_for_selector("text=Thank you! You gave", timeout=90000)
        print("donor:", await donor.locator("text=Thank you! You gave").first.inner_text())

        family = await browser.new_page(viewport={"width": 1280, "height": 1300}, color_scheme="light")
        await family.goto(f"{WEB}/login?as=elena.rivera&next=/registry")
        card = family.locator("li", has_text="How the Shopper and local stores agreed on a price").first
        for _ in range(36):  # the Shopper runs in the background: Channel3, the AI's picks, the stores' agents, Payouts
            await family.wait_for_timeout(5000)
            await family.reload()
            await family.wait_for_load_state("networkidle")
            if await card.count():
                break
        print("purchase:", " ".join((await card.locator("p").first.inner_text()).split())[:300])
        await card.get_by_text("How the Shopper and local stores agreed on a price").click()
        for line in await card.locator("details ol li").all_inner_texts():
            print("   ", " ".join(line.split())[:220])
        await card.scroll_into_view_if_needed()
        await family.screenshot(path=OUT / "marketplace_family.png", full_page=True)
        await browser.close()


asyncio.run(main())
