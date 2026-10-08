"""Impact reports: the donor (Marcus) sees each gift's journey and a short note from the Funds agent; the org
admin downloads the grant report PDF. Uses up to two AI calls. Needs the API (demo seed) and the web app."""

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(exist_ok=True)
WEB = "http://localhost:5173"


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1400, "height": 1100}, color_scheme="light", accept_downloads=True)
        page = await ctx.new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)

        await page.goto(f"{WEB}/login?as=marcus.chen")
        await page.wait_for_url("**/giving", timeout=10000)
        await page.wait_for_selector("text=Delivered to the family", timeout=15000)  # gifts show at once
        await page.wait_for_selector("p.rounded-xl span:text-is('AI')", timeout=90000)  # then the agent's note
        stats = await page.locator(".rounded-lg.bg-sunken").all_inner_texts()
        print("stats:", [" ".join(s.split()) for s in stats[:4]])
        note = await page.locator("p.rounded-xl").first.inner_text()
        print("note:", " ".join(note.split())[:300])
        await page.screenshot(path=OUT / "giving.png", full_page=True)

        await page.goto(f"{WEB}/login?as=sam.whitfield")
        await page.wait_for_selector("text=Grant report (PDF)", timeout=15000)
        async with page.expect_download(timeout=120000) as download:
            await page.get_by_role("button", name="Grant report (PDF)").click()
        pdf = await download.value
        path = OUT / pdf.suggested_filename
        await pdf.save_as(path)
        print("grant report:", pdf.suggested_filename, path.stat().st_size, "bytes", path.read_bytes()[:5])
        print("console errors:", [e for e in errors if all(s not in e.lower() for s in ("license", "trial", "****"))][:4])
        await browser.close()


asyncio.run(main())
