"""Log in with PayPal: the household's Aid page, the contractor portal and the business home show where each
person's money goes and a "Log in with PayPal" button; the button opens PayPal's sign-in page for our app; coming
back without a code (cancelled) changes nothing. With the sandbox buyer login and PAYPAL_CONNECT_RETURN_URL in
backend/.env (the return URL saved in the app's Log in with PayPal settings), the buyer really signs in: PayPal's
redirect to that URL is forwarded to the local app, which exchanges the code and connects the account. Needs the API
(demo seed) and the web app."""

import asyncio
import os
from pathlib import Path

from paypal_sandbox import RETURN_URL, confirm, have_buyer, sign_in
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

        if have_buyer() and RETURN_URL and "not supported" not in await page.locator("body").inner_text():
            # PayPal only saves public https return URLs; send its redirect on to the local return page.
            async def forward(route):
                query = route.request.url.split("?", 1)[1] if "?" in route.request.url else ""
                await route.fulfill(status=302, headers={"location": f"{WEB}/connect/paypal?{query}"})

            await page.route(RETURN_URL.split("?")[0] + "*", forward)
            await sign_in(page)
            try:
                print("consented with:", await confirm(page, timeout=20000))
            except Exception:  # noqa: BLE001 - some accounts go straight back without a consent page
                pass
            await page.wait_for_selector("text=Your PayPal account is connected", timeout=60000)
            print("connected:", " ".join((await page.locator("main").inner_text()).split())[:200])
            await page.screenshot(path=OUT / "connect-paypal-done.png")
        else:
            print("live sign-in skipped: needs the buyer login, PAYPAL_CONNECT_RETURN_URL and the PayPal setting saved")

        await page.goto(f"{WEB}/connect/paypal?error=access_denied")
        await page.wait_for_selector("text=Nothing was changed", timeout=15000)
        print("cancelled: ok")
        print("console errors:", [e for e in errors if all(s not in e.lower() for s in ("license", "trial", "****", "404"))][:4])
        await browser.close()


asyncio.run(main())
