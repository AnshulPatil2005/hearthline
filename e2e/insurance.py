"""Policy agent: the household uploads the sample policy (fictional), the agent reads it, the page compares it
with their inventory (jewelry over its sub-limit) and turns deadlines into dates; then a question is answered
with a quote from the policy. Uses two AI calls. Needs the API (fresh demo seed) and the web app."""

import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(exist_ok=True)
WEB = os.environ.get("E2E_WEB", "http://localhost:5173")
SAMPLE = Path(__file__).parent.parent / "frontend" / "public" / "samples" / "golden-poppy-homeowners-policy.pdf"


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1300, "height": 1100}, color_scheme="light")
        errors = []
        page.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)

        await page.goto(f"{WEB}/login?as=elena.rivera&next=/insurance")
        await page.wait_for_selector("text=Upload your policy", timeout=15000)
        await page.get_by_label("Policy PDF").set_input_files(SAMPLE)
        await page.get_by_role("button", name="Read my policy").click()
        await page.wait_for_selector("text=Your inventory and this policy", timeout=120000)
        print("insurer:", await page.locator("h2.text-xl").first.inner_text())
        claim = await page.locator("section", has_text="Your inventory and this policy").inner_text()
        print("claim:", " | ".join(line for line in claim.split("\n") if line.strip())[:500])
        deadlines = await page.locator("section", has_text="What to do, and by when").inner_text()
        print("deadlines:", " | ".join(line for line in deadlines.split("\n") if line.strip())[:300])

        await page.get_by_label("Ask about your policy").fill("My wedding necklace burned in the fire. How much can I get for it?")
        await page.get_by_role("button", name="Ask", exact=True).click()
        await page.wait_for_selector("blockquote", timeout=90000)
        print("answer:", " ".join((await page.locator("section", has_text="Ask about your policy").locator("p").first.inner_text()).split())[:300])
        print("quote:", (await page.locator("blockquote").inner_text())[:200])
        await page.screenshot(path=OUT / "insurance.png", full_page=True)
        print("console errors:", [e for e in errors if all(s not in e.lower() for s in ("license", "trial", "****", "404"))][:4])
        await browser.close()


asyncio.run(main())
