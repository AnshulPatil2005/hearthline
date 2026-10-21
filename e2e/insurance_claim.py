"""Insurers pay claims through PayPal: Elena prepares her contents claim from the pre-disaster inventory and her policy
(uploading the sample policy first if needed: one AI call), the insurer's adjuster opens the private link, sees the
items with their evidence and the policy math, decides the amount and pays with PayPal (the sandbox buyer account
stands in for the insurer's), and Hearthline passes the money on to Elena's PayPal account. Needs the API (demo seed),
the web app and the sandbox buyer login in backend/.env."""

import asyncio
import os
from pathlib import Path

from paypal_sandbox import confirm, have_buyer, open_checkout, sign_in
from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(exist_ok=True)
WEB = os.environ.get("E2E_WEB", "http://localhost:5173")
SAMPLE = Path(__file__).parent.parent / "frontend" / "public" / "samples" / "golden-poppy-homeowners-policy.pdf"


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        household = await browser.new_page(viewport={"width": 1300, "height": 1000}, color_scheme="light")
        await household.goto(f"{WEB}/login?as=elena.rivera&next=/insurance")
        upload_form = household.locator("text=Upload your policy")
        await upload_form.or_(household.locator("text=Send your claim to")).first.wait_for(timeout=20000)
        if await upload_form.count():
            await household.get_by_label("Policy PDF").set_input_files(SAMPLE)
            await household.get_by_role("button", name="Read my policy").click()
        await household.get_by_role("button", name="Prepare my claim").click(timeout=120000)
        link_box = household.get_by_label("Send this private link to your adjuster")
        await link_box.wait_for(timeout=20000)
        link = await link_box.input_value()
        section = household.locator("section", has_text="Send your claim to")
        print("household:", " ".join((await section.inner_text()).split())[:200])

        adjuster = await browser.new_page(viewport={"width": 1350, "height": 1100}, color_scheme="light")
        await adjuster.goto(link)
        await adjuster.wait_for_selector("text=Contents claim", timeout=20000)
        print("figures:", " | ".join(" ".join(x.split()) for x in await adjuster.locator("dl > div").all_inner_texts()))
        await adjuster.locator(".ag-grid-scrolling-container .ag-row").first.wait_for(timeout=30000)
        print("rows:", await adjuster.locator(".ag-grid-scrolling-container .ag-row").count())
        await adjuster.screenshot(path=OUT / "claim_adjuster.png", full_page=True)

        if not have_buyer():
            print("payment skipped: no sandbox buyer login in backend/.env")
            await browser.close()
            return
        await adjuster.get_by_label("Adjuster's name").fill("Dana Lee, Golden Poppy Claims")
        await adjuster.get_by_label("Note to the policyholder (optional)").fill("Contents claim approved in full.")
        amount = await adjuster.get_by_label("Amount to pay (USD)").input_value()
        await adjuster.locator("paypal-button").wait_for(timeout=30000)
        await adjuster.wait_for_timeout(2000)
        popup = await open_checkout(adjuster, adjuster.locator("paypal-button"))
        await sign_in(popup)
        print("adjuster confirmed with:", await confirm(popup))
        await adjuster.wait_for_selector("text=/^Paid \\$/", timeout=120000)
        print("adjuster sees:", " ".join((await adjuster.get_by_role("status").inner_text()).split()), "| amount", amount)
        await adjuster.screenshot(path=OUT / "claim_paid.png", full_page=True)

        await household.reload()
        await household.wait_for_selector("text=/paid \\$/", timeout=20000)
        print("household sees:", " ".join((await section.inner_text()).split())[:220])
        await browser.close()


asyncio.run(main())
