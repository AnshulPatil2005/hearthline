"""Log in with PayPal: the household's Aid page, the contractor portal and the business home show where each
person's money goes and a "Log in with PayPal" button; the button opens PayPal's sign-in page for our app; coming
back without a code (cancelled) changes nothing. Finishing the sign-in needs the app's return URL set in the PayPal
developer dashboard. Needs the API (demo seed) and the web app."""

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
        page = await browser.new_page(viewport={"width": 1300, "height": 1000}, color_scheme="light")
        errors = []
        page.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)

        for persona, path in (("elena.rivera", "/aid"), ("dana.okafor", "/contractor"), ("luis.moreno", "/business")):
            await page.goto(f"{WEB}/login?as={persona}&next={path}")
            card = page.locator("section", has_text="Your PayPal account").first
            await card.wait_for(timeout=15000)
            print(f"{persona}:", " ".join((await card.inner_text()).split())[:220])
            await card.screenshot(path=OUT / f"connect-{persona.split('.')[0]}.png")

        await page.goto(f"{WEB}/login?as=elena.rivera&next=/aid")
        await page.get_by_role("button", name="Log in with PayPal").click()
        await page.wait_for_url("**paypal.com/**", timeout=30000)
        print("PayPal page:", page.url.split("?")[0])
        await page.wait_for_timeout(4000)
        print("PayPal says:", " ".join((await page.locator("body").inner_text()).split())[:200])
        await page.screenshot(path=OUT / "connect-paypal-signin.png")

        await page.goto(f"{WEB}/connect/paypal?error=access_denied")
        await page.wait_for_selector("text=Nothing was changed", timeout=15000)
        print("cancelled: ok")
        print("console errors:", [e for e in errors if all(s not in e.lower() for s in ("license", "trial", "****", "404"))][:4])
        await browser.close()


asyncio.run(main())
