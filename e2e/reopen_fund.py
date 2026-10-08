"""Reopen Fund end to end:
- a buyer opens Moreno's Bakery's public page; PayPal, Venmo and Pay Later buttons render; choosing PayPal
  creates a gift-card order and opens the PayPal sandbox checkout
- the owner (Luis) asks for the "Restock" step's money; a supervisor (Grace) verifies the diner and
  releases the step through Payouts (or sees the low sandbox balance message)
- Luis marks the bakery reopened and takes $12.50 from a seeded card; the card page shows the new balance
- the outfitter that missed its date shows as refunded
Needs the API (fresh demo seed) and the web app running."""

import asyncio
import sqlite3
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(exist_ok=True)
WEB = "http://localhost:5173"
DB = Path(__file__).parent.parent / "backend" / "hearthline.db"


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1400, "height": 1100}, color_scheme="light")
        page = await ctx.new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)

        # Public page and checkout.
        await page.goto(f"{WEB}/reopen/morenos-bakery", wait_until="networkidle")
        await page.wait_for_selector("text=What your money pays for", timeout=15000)
        await page.wait_for_selector("paypal-button", timeout=20000)
        print("raised:", " ".join((await page.locator("p:has-text('of $15,000')").first.inner_text()).split()))
        print("buttons:", [await page.locator(t).count() for t in ("paypal-button", "venmo-button", "paypal-pay-later-button")])
        await page.wait_for_selector(".b-gantt-task", timeout=30000)
        await page.screenshot(path=OUT / "reopen_public.png", full_page=True)
        is_order = lambda r: r.url.endswith("/reopen/morenos-bakery/cards") and r.request.method == "POST"  # noqa: E731
        async with page.expect_response(is_order, timeout=20000) as order:
            async with ctx.expect_page(timeout=20000) as popup:
                await page.locator("paypal-button").click()
        checkout = await popup.value
        print("card order:", (await order.value).status, "| PayPal window:", checkout.url[:60])
        await checkout.close()

        # The owner asks for the restock money.
        await page.goto(f"{WEB}/login?as=luis.moreno", wait_until="networkidle")
        await page.wait_for_url("**/business", timeout=10000)
        step = page.locator("li", has_text="Restock flour")
        await step.get_by_placeholder("What it's for").fill("Invoice #4471 from Valley Flour Co.")
        await step.get_by_role("button", name="Ask for this money").click()
        await step.get_by_text("Being checked", exact=True).wait_for(timeout=10000)
        await page.screenshot(path=OUT / "business_home.png", full_page=True)
        print("owner asked for the restock money")

        # A supervisor verifies the diner and releases the step.
        await page.goto(f"{WEB}/login?as=grace.alvarez&next=/command/businesses", wait_until="networkidle")
        diner = page.locator("li", has_text="Pine Hollow Diner")
        await diner.get_by_placeholder("Note for the record").fill("License SBW-BL-18832 checked with the city")
        await diner.get_by_role("button", name="Verify business").click()
        await diner.get_by_text("Verified", exact=True).wait_for(timeout=10000)
        bakery = page.locator("li", has_text="Moreno's Bakery")
        await bakery.get_by_role("button", name="Release $3,000").click()
        # A real Payouts call: wait until the request is gone (paid) or the low-balance message shows.
        outcome = page.get_by_text("balance can't cover").or_(page.locator("li", has_text="Moreno's Bakery").filter(has_not_text="Asks for $3,000"))
        await outcome.first.wait_for(timeout=60000)
        released = await bakery.get_by_text("Asks for $3,000").count() == 0
        print("restock released:", released, "|", (await page.locator("p.text-danger").all_inner_texts())[:1])
        await page.screenshot(path=OUT / "businesses_review.png", full_page=True)


        # Reopen and take a card.
        code = sqlite3.connect(DB).execute(
            "select code from gift_cards where campaign_id = 1 and status = 'active' order by id limit 1"
        ).fetchone()[0]
        await page.goto(f"{WEB}/login?as=luis.moreno", wait_until="networkidle")
        await page.get_by_role("button", name="We're open again").click()
        await page.get_by_role("button", name="Yes, we're open").click()
        await page.wait_for_selector("text=You're open again", timeout=10000)
        await page.get_by_label("Card code").fill(code)
        await page.get_by_role("button", name="Check card").click()
        await page.get_by_label("Purchase amount").fill("12.50")
        await page.get_by_role("button", name="Take from card").click()
        print("redeemed:", await page.locator("text=Took $12.50").inner_text())
        await page.goto(f"{WEB}/card/{code}", wait_until="networkidle")
        await page.wait_for_selector("img[alt^='QR code']", timeout=10000)
        print("card page:", " ".join((await page.locator("main").inner_text()).split())[:160])
        await page.screenshot(path=OUT / "gift_card.png", full_page=True)

        await page.goto(f"{WEB}/reopen/ridge-outfitters", wait_until="networkidle")
        print("outfitters:", await page.get_by_text("couldn't reopen in time").count() == 1)
        print("console errors:", [e for e in errors if all(s not in e.lower() for s in ("license", "trial", "****", "paypal"))][:4])
        await browser.close()


asyncio.run(main())
