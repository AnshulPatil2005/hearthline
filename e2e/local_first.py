"""The Shopper buys local first: a donor finishes funding Pepper's dog crate on the Riveras' public registry with a
real sandbox payment; Hearthline's Shopper checks Sablewood Mercantile (reopened after the fire) before web stores and
buys there, paying the store's PayPal account; Elena sees the local purchase; Rosa, the store's owner, sees the order
with the family's address and marks it delivered. Needs the API (demo seed), the web app and the sandbox buyer login in
backend/.env; uses up to two AI calls."""

import asyncio
import os
from pathlib import Path

from paypal_sandbox import confirm, have_buyer, open_checkout, sign_in
from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(exist_ok=True)
WEB = os.environ.get("E2E_WEB", "http://localhost:5173")
ITEM = "Dog crate and bed for Pepper"


async def main() -> None:
    if not have_buyer():
        print("skipped: no sandbox buyer login in backend/.env")
        return
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        donor = await browser.new_page(viewport={"width": 1280, "height": 1000}, color_scheme="light")
        await donor.goto(f"{WEB}/r/rivera-family", wait_until="networkidle")
        await donor.locator("li", has_text=ITEM).get_by_role("button", name="Fund this").click()
        await donor.wait_for_selector("paypal-button", timeout=20000)
        await donor.wait_for_timeout(3000)
        popup = await open_checkout(donor, donor.locator("paypal-button"))
        await sign_in(popup)
        print("donor confirmed with:", await confirm(popup))
        await donor.wait_for_selector("text=Thank you! You gave", timeout=90000)
        print("donor:", await donor.locator("text=Thank you! You gave").first.inner_text())

        family = await browser.new_page(viewport={"width": 1280, "height": 1100}, color_scheme="light")
        await family.goto(f"{WEB}/login?as=elena.rivera&next=/registry")
        row = family.locator("li", has_text="Local business").first
        for _ in range(12):  # the Shopper runs in the background: Channel3, the AI's pick, policy, PayPal Payouts
            await family.wait_for_timeout(5000)
            await family.reload()
            await family.wait_for_load_state("networkidle")
            if await row.count():
                break
        print("family sees:", " ".join((await row.inner_text()).split())[:300])
        await row.scroll_into_view_if_needed()
        await family.screenshot(path=OUT / "local_first_family.png", full_page=True)

        store = await browser.new_page(viewport={"width": 1280, "height": 1100}, color_scheme="light")
        await store.goto(f"{WEB}/login?as=rosa.delgado&next=/business")
        orders = store.locator("section", has_text="Orders from Hearthline's Shopper")
        await orders.wait_for(timeout=20000)
        print("store sees:", " ".join((await orders.inner_text()).split())[:300])
        await store.screenshot(path=OUT / "local_first_store.png", full_page=True)
        await orders.get_by_role("button", name="Mark delivered").first.click()
        await orders.get_by_text("Delivered", exact=True).first.wait_for(timeout=10000)
        print("store marked it delivered")

        await family.reload()
        await family.wait_for_load_state("networkidle")
        print("family now:", " ".join((await row.inner_text()).split())[:200])
        await browser.close()


asyncio.run(main())
