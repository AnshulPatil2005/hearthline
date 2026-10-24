"""The readiness fund: Marcus sees what the fund holds, gives $25 a month with PayPal Subscriptions (the sandbox buyer
approves at PayPal), comes back to an active monthly gift, then stops it, which cancels the subscription at PayPal.
The org admin's first-72-hours panel shows the fund and how much of a proposal it covers. Real sandbox subscription;
no AI calls; needs a freshly seeded database.
"""

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
        await page.goto(f"{WEB}/login?as=marcus.chen&next=/giving", wait_until="networkidle")
        fund = page.locator("section[aria-labelledby='readiness-title']")
        await fund.wait_for(timeout=30000)
        stop = fund.get_by_role("button", name="Stop my monthly gift")
        if await stop.count():  # a monthly gift from an earlier run
            await stop.click()
            await fund.get_by_role("button", name="Give monthly with PayPal").wait_for(timeout=30000)
        print("fund:", " | ".join((await fund.locator("dl").inner_text()).split("\n")))
        await page.screenshot(path=OUT / "readiness_giving.png", full_page=False)

        await fund.get_by_role("radio", name="$25 a month").click()
        await fund.get_by_role("button", name="Give monthly with PayPal").click()
        await page.wait_for_url("**paypal.com/**", timeout=60000)
        print("PayPal page:", page.url.split("?")[0])
        await sign_in(page)
        label = await confirm(page)
        if label == "Continue":  # subscriptions add a review step: "Agree & Subscribe"
            label = await confirm(page)
        print("approved with:", label)
        await page.wait_for_url("**/giving/readiness?**", timeout=90000)
        result = page.get_by_text("Thank you. You give $25 a month to the readiness fund.")
        await result.wait_for(timeout=60000)
        print("return page:", " ".join((await page.locator("[aria-live]").inner_text()).split()))
        await page.get_by_role("link", name="Back to my giving").click()
        await fund.get_by_text("You give $25 a month to the readiness fund").wait_for(timeout=30000)
        print("giving page:", (await fund.get_by_text("Since").inner_text()).strip())

        await fund.get_by_role("button", name="Stop my monthly gift").click()
        await fund.get_by_role("button", name="Give monthly with PayPal").wait_for(timeout=30000)
        print("stopped: the subscription was cancelled at PayPal")

        staff = await browser.new_page(viewport={"width": 1400, "height": 1000}, color_scheme="light")
        await staff.goto(f"{WEB}/login?as=sam.whitfield&next=/command", wait_until="networkidle")
        rapid = staff.locator("section[aria-labelledby='rapid-title']")
        await rapid.get_by_text("Readiness fund:").wait_for(timeout=30000)
        print("rapid aid panel:", await rapid.get_by_text("Readiness fund:").inner_text())
        await rapid.get_by_role("button", name="Simulate an evacuation order (demo)").click()
        proposal = rapid.locator("li", has_text="simulated for this demo").first
        await proposal.wait_for(timeout=30000)
        print("proposal:", next(line for line in (await proposal.inner_text()).split("\n") if "Would pay" in line))
        await staff.screenshot(path=OUT / "readiness_rapid_aid.png")
        await browser.close()


asyncio.run(main())
