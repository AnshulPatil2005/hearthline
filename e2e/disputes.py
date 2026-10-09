"""Payment disputes desk: Sam (relief org admin) answers the three demo disputes the way the rules recommend:
a message for the bakery gift card inquiry, a refund for the gift to the copycat registry, and evidence for the
Ridge Outfitters card that was already refunded. Then "Ask PayPal" reads PayPal through PayPal's MCP server
and refuses a refund. Uses about eight AI calls. Needs the API (fresh demo seed) and the web app."""

import asyncio
from pathlib import Path

from playwright.async_api import Page, async_playwright

OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(exist_ok=True)
WEB = "http://localhost:5173"


async def drafted(page: Page) -> str:
    await page.wait_for_selector("text=The Funds agent is drafting", state="detached", timeout=120000)
    await page.wait_for_function("document.querySelector('#dispute-note')?.value.length > 40", timeout=10000)
    return await page.locator("#dispute-note").input_value()


async def open_dispute(page: Page, subject: str) -> None:
    await page.get_by_role("button", name=subject).first.click()
    await page.locator("h2", has_text=subject).wait_for(timeout=10000)


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1300, "height": 1150}, color_scheme="light")
        errors = []
        page.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)

        await page.goto(f"{WEB}/login?as=sam.whitfield&next=/command/disputes")
        await page.wait_for_selector("text=Payment disputes", timeout=15000)
        print("queue:", await page.locator("p", has_text="need an answer").first.inner_text())

        # 1. Bakery gift card inquiry: the rules say explain the escrow.
        await open_dispute(page, "Gift card from Moreno's Bakery")
        print("bakery rule:", (await page.locator("section", has_text="Recommended by the rules").inner_text())[:300])
        print("bakery draft:", (await drafted(page))[:400])
        print("by:", await page.locator("text=/Drafted by the Funds agent|Template draft/").inner_text())
        await page.screenshot(path=OUT / "disputes-bakery.png", full_page=True)
        await page.get_by_role("button", name="Message the payer").click()
        await page.wait_for_selector("text=messaged the payer", timeout=15000)

        # 2. Gift to the copycat registry: refund it.
        await open_dispute(page, "Help the Rivera family rebuild")
        print("scam rule:", (await page.locator("section", has_text="Recommended by the rules").inner_text())[:300])
        print("scam draft:", (await drafted(page))[:400])
        await page.get_by_role("button", name="Refund $75.00").click()
        await page.get_by_role("button", name="Refund", exact=True).click()
        await page.wait_for_selector("text=refunded the payer", timeout=15000)
        await page.screenshot(path=OUT / "disputes-refunded.png", full_page=True)

        # 3. Ridge Outfitters card, already refunded: send proof.
        await open_dispute(page, "Gift card from Ridge Outfitters")
        print("ridge rule:", (await page.locator("section", has_text="Recommended by the rules").inner_text())[:300])
        print("ridge draft:", (await drafted(page))[:400])
        await page.get_by_role("button", name="Send evidence").click()
        await page.wait_for_selector("text=sent evidence", timeout=15000)
        await page.screenshot(path=OUT / "disputes-evidence.png", full_page=True)

        # 4. Ask PayPal: the Funds agent reads PayPal through PayPal's MCP server, and refuses to move money.
        panel = page.locator("#ask-paypal")
        for example in ("Which subscription plans", "Refund Jordan"):
            await panel.get_by_role("button", name=example).click()
            asking = panel.get_by_role("button", name="Asking PayPal…")
            await asking.wait_for(timeout=5000)
            await asking.wait_for(state="detached", timeout=180000)
            await panel.locator("p.whitespace-pre-line").wait_for(timeout=10000)
            print(f"ask '{example}':", (await panel.locator("p.whitespace-pre-line").inner_text())[:300])
            steps = await panel.locator("ol li").all_inner_texts()
            print("   steps:", [" ".join(x.split())[:110] for x in steps])
        await panel.screenshot(path=OUT / "ask-paypal.png")

        pills = await page.locator("ul li button span.rounded-full").all_inner_texts()
        print("statuses:", pills)
        print("console errors:", [e for e in errors if all(s not in e.lower() for s in ("license", "trial", "****", "404"))][:4])
        await browser.close()


asyncio.run(main())
