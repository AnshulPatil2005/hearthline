"""The recovery navigator: Elena's home shows her next steps soonest first, with dates and links (the rebuild step
waiting for her, today's crew visit, FEMA's 60-day window); the navigator explains the plan in Spanish; she asks a
question in English and the answer is about her own steps; she marks FEMA done and it moves to "done". Uses two
AI calls; needs a freshly seeded database.
"""

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
        ctx = await browser.new_context(viewport={"width": 1280, "height": 1100}, color_scheme="light")
        await ctx.add_init_script("localStorage.setItem('hearthline.lang', 'es')")
        page = await ctx.new_page()
        await page.goto(f"{WEB}/login?as=elena.rivera&next=/home", wait_until="networkidle")
        nav = page.locator("section[aria-labelledby='navigator-title']")
        await nav.wait_for(timeout=30000)
        steps = await nav.locator("ul > li").all_inner_texts()
        print("steps:", [" | ".join(s.split("\n")[:1] + s.split("\n")[2:3]) for s in steps])

        await nav.get_by_role("button", name="Explícame mi plan").click()
        await nav.get_by_text("Explicado por el navegador de Hearthline").wait_for(timeout=120000)
        print("explained (es):", (await nav.locator("[aria-live] p.text-sm").first.inner_text())[:240], "…")
        await nav.screenshot(path=OUT / "navigator_es.png")
        await ctx.close()

        ctx = await browser.new_context(viewport={"width": 1280, "height": 1100}, color_scheme="light")
        await ctx.add_init_script("localStorage.setItem('hearthline.lang', 'en')")
        page = await ctx.new_page()
        await page.goto(f"{WEB}/login?as=elena.rivera&next=/home", wait_until="networkidle")
        nav = page.locator("section[aria-labelledby='navigator-title']")
        await nav.wait_for(timeout=30000)
        await nav.get_by_placeholder("Ask about your recovery").fill("When do I have to apply to FEMA?")
        await nav.get_by_role("button", name="Ask", exact=True).click()
        await nav.get_by_text("From your steps only").wait_for(timeout=120000)
        print("answer:", (await nav.locator("div.border p.text-sm").last.inner_text())[:240])

        fema = nav.get_by_label("Mark done: Apply for FEMA disaster assistance")
        await fema.click()  # the box follows the server's answer
        await nav.get_by_text("1 done").wait_for(timeout=30000)
        print("FEMA marked done; open now:", await nav.locator("p", has_text="open").first.inner_text())
        await nav.get_by_text("1 done").click()
        await fema.click()  # put it back for the next run
        await nav.get_by_text("1 done").wait_for(state="detached", timeout=30000)
        await browser.close()


asyncio.run(main())
