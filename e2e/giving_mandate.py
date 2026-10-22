"""Giving mandates (PayPal Vault): Marcus sets his limits on the Giving page, saves his PayPal account at PayPal (the
sandbox buyer stands in for him), and comes back to an active mandate whose giving agent has already given to the
Riveras' needs with no checkout, explaining each gift. Then he pauses, resumes, and stops it, which deletes the saved
account at PayPal. Needs the API (demo seed), the web app and the sandbox buyer login in backend/.env; real sandbox
payments and up to one AI call."""

import asyncio
import os
from pathlib import Path

from paypal_sandbox import confirm, have_buyer, sign_in
from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(exist_ok=True)
WEB = os.environ.get("E2E_WEB", "http://localhost:5173")


async def main() -> None:
    if not have_buyer():
        print("skipped: no sandbox buyer login in backend/.env")
        return
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 1100}, color_scheme="light")
        errors: list[str] = []
        page.on(
            "console",
            lambda m: errors.append(m.text[:200]) if m.type == "error" and "paypal.com" not in m.text else None,
        )
        await page.goto(f"{WEB}/login?as=marcus.chen&next=/giving")
        panel = page.locator("section", has_text="Give automatically after disasters")
        await panel.wait_for(timeout=60000)
        stop = panel.get_by_role("button", name="Stop and remove my saved PayPal account")
        if await stop.count():  # a mandate from an earlier run: stop it first
            await stop.click()
            await panel.get_by_role("button", name="Stop giving").click()
            await panel.get_by_role("button", name="Save my PayPal account and start").wait_for(timeout=30000)

        await panel.get_by_label("Most for one gift ($)").fill("40")
        await panel.get_by_label("Most in a month ($)").fill("100")
        await panel.get_by_label("Add a state").select_option("CA")
        await panel.get_by_label("In your own words (optional)").fill("Families with young kids, and pets")
        await page.screenshot(path=OUT / "mandate_form.png", full_page=True)
        await panel.get_by_role("button", name="Save my PayPal account and start").click()

        await page.wait_for_url("**paypal.com/**", timeout=60000)
        print("PayPal page:", page.url.split("?")[0])
        await sign_in(page)
        print("consented with:", await confirm(page))
        await page.wait_for_url("**/giving/mandate?**", timeout=90000)
        await page.get_by_text("Your giving is set up.").wait_for(timeout=180000)
        result = page.locator("[aria-live=polite]").first
        print("return page:", " ".join((await result.inner_text()).split()))
        await page.screenshot(path=OUT / "mandate_return.png", full_page=True)

        await page.get_by_role("link", name="Back to my giving").click()
        panel = page.locator("section", has_text="Give automatically after disasters")
        await panel.get_by_text("Gifts made for you").wait_for(timeout=60000)
        gifts = await panel.locator("li").all_inner_texts()
        print("gifts:", len(gifts))
        for g in gifts:
            print("  ", " ".join(g.split())[:220])
        print("this month:", " ".join((await panel.get_by_text("Given this month").locator("..").inner_text()).split()))
        await page.screenshot(path=OUT / "mandate_active.png", full_page=True)

        await panel.get_by_role("button", name="Pause").click()
        await panel.get_by_text("Paused", exact=True).wait_for(timeout=30000)
        await panel.get_by_role("button", name="Resume").click()
        await panel.get_by_text("Active", exact=True).wait_for(timeout=30000)
        print("paused and resumed")
        await panel.get_by_role("button", name="Stop and remove my saved PayPal account").click()
        await panel.get_by_role("button", name="Stop giving").click()
        await panel.get_by_role("button", name="Save my PayPal account and start").wait_for(timeout=30000)
        print("stopped; the saved account was deleted at PayPal")
        print("console errors:", [e for e in errors if "license" not in e.lower() and "****" not in e][:4])
        await browser.close()


asyncio.run(main())
