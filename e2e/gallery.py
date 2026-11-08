"""Screenshots for the Devpost gallery and the README, from the hosted demo (its AG Grid key hides the watermark).

Each image is 3:2 (1440 x 960 at 2x). Nothing is saved: the what-if is only previewed, no proposal is accepted and
no case is decided.

    cd backend
    uv run --with playwright python ../e2e/gallery.py          # E2E_WEB=http://localhost:5173 for a local run
"""

import asyncio
import os
import re
from pathlib import Path

from playwright.async_api import Browser, Page, async_playwright

WEB = os.environ.get("E2E_WEB", "https://hearthline-web.onrender.com").rstrip("/")
OUT = Path(__file__).resolve().parent.parent / "docs" / "gallery"
VIEW = {"width": 1440, "height": 960}
LONG = 180_000  # the free API can take a minute to wake, and the AI a while to answer


async def open_as(browser: Browser, persona: str | None, path: str) -> Page:
    ctx = await browser.new_context(viewport=VIEW, device_scale_factor=2, color_scheme="light")
    await ctx.add_init_script("localStorage.setItem('hearthline.lang', 'en')")
    page = await ctx.new_page()
    url = f"{WEB}/login?as={persona}&next={path}" if persona else f"{WEB}{path}"
    await page.goto(url, wait_until="networkidle", timeout=LONG)
    return page


async def save(page: Page, name: str) -> None:
    await page.wait_for_timeout(1200)
    await page.screenshot(path=OUT / f"{name}.jpg", type="jpeg", quality=86)
    print("saved", name)
    await page.context.close()


async def landing(browser: Browser) -> None:
    page = await open_as(browser, None, "/login")
    await page.locator("#why").wait_for(timeout=LONG)
    await page.locator("main").evaluate("m => window.scrollTo(0, m.offsetTop - 8)")
    await save(page, "01-landing")


async def open_in(browser: Browser, lang: str, persona: str, path: str) -> Page:
    ctx = await browser.new_context(viewport=VIEW, device_scale_factor=2, color_scheme="light")
    await ctx.add_init_script(f"localStorage.setItem('hearthline.lang', '{lang}')")
    page = await ctx.new_page()
    await page.goto(f"{WEB}/login?as={persona}&next={path}", wait_until="networkidle", timeout=LONG)
    return page


async def navigator(browser: Browser) -> None:
    """Elena reads Spanish: her steps and the navigator's explanation of them."""
    page = await open_in(browser, "es", "elena.rivera", "/home")
    nav = page.locator("section[aria-labelledby='navigator-title']")
    await nav.get_by_role("button", name="Explícame mi plan").click(timeout=LONG)
    await nav.get_by_text("Explicado por el navegador").wait_for(timeout=LONG)
    await nav.evaluate("n => window.scrollTo(0, n.getBoundingClientRect().top + window.scrollY - 16)")
    await save(page, "02-recovery-navigator")


async def inventory(browser: Browser) -> None:
    page = await open_as(browser, "elena.rivera", "/inventory")
    button = page.get_by_role("button", name="Value by category")
    await button.wait_for(timeout=LONG)
    await page.wait_for_selector(".ag-row", timeout=LONG)
    await button.click()
    await page.wait_for_timeout(2500)
    await button.evaluate("b => window.scrollTo(0, b.getBoundingClientRect().top + window.scrollY - 90)")
    await save(page, "03-inventory-pivot-chart")


async def registry(browser: Browser) -> None:
    page = await open_as(browser, None, "/r/rivera-family")
    await page.get_by_role("button", name="Fund this").first.click(timeout=LONG)
    await page.wait_for_selector("paypal-button", timeout=LONG)
    await page.locator("paypal-button").first.scroll_into_view_if_needed()
    await page.mouse.wheel(0, -260)
    await page.wait_for_timeout(2500)  # the PayPal, Venmo and Pay Later buttons render
    await save(page, "04-registry-paypal")


async def command_center(browser: Browser) -> None:
    page = await open_as(browser, "sam.whitfield", "/command")
    await page.wait_for_selector(".ag-row", timeout=LONG)
    await page.get_by_label("Ask the grid").fill("destroyed homes on Juniper Lane that have no PayPal account yet")
    await page.get_by_role("button", name="Ask", exact=True).click()
    await page.get_by_role("button", name="Ask", exact=True).wait_for(timeout=LONG)  # done thinking
    await page.wait_for_timeout(3000)
    await page.get_by_label("Ask the grid").scroll_into_view_if_needed()
    await page.mouse.wheel(0, -120)
    await save(page, "05-command-center-ask-the-grid")


async def dispatch(browser: Browser) -> None:
    page = await open_as(browser, "sam.whitfield", "/command/crews")
    panel = page.locator("section[aria-labelledby='dispatch-title']")
    await panel.get_by_label("Instructions for the dispatch agent").fill(
        "Medical needs first. Give Van 2 both Mesa Dr stops.", timeout=LONG
    )
    await panel.get_by_role("button", name="Plan tomorrow").click()
    await panel.get_by_text(re.compile(r"^Plan for ")).wait_for(timeout=LONG)
    ghost = page.locator(".b-sch-event.job-proposal").first
    await ghost.wait_for(timeout=60000)
    await page.wait_for_timeout(3000)  # the scheduler and the load view reload after the plan
    await page.locator(".b-mask:visible").first.wait_for(state="hidden", timeout=60000)
    await panel.evaluate("p => window.scrollTo(0, p.getBoundingClientRect().top + window.scrollY - 10)")
    await save(page, "06-crew-dispatch-scheduler-pro")


async def what_if(browser: Browser) -> None:
    page = await open_as(browser, "dana.okafor", "/contractor")
    await page.wait_for_selector(".b-gantt-task", timeout=LONG)
    await page.get_by_role("button", name="What if a step runs late?").click()
    panel = page.locator("section[aria-labelledby=what-if-title]")
    await panel.get_by_label("Step").select_option(label="4. Framing")
    await panel.get_by_label("Days late").fill("14")
    await panel.locator("[aria-live=polite] p.font-medium").first.wait_for(timeout=60000)
    await page.wait_for_timeout(2500)  # the engine reschedules the chart
    # The chart at the top, the what-if and its answer under it
    await page.locator(".b-gantt").first.evaluate("g => window.scrollTo(0, g.getBoundingClientRect().top + window.scrollY - 10)")
    await save(page, "07-rebuild-what-if-gantt")


async def scam_review(browser: Browser) -> None:
    page = await open_as(browser, "priya.nair", "/review")
    await page.wait_for_selector(".ag-row", timeout=LONG)
    await page.locator(".ag-row", has_text="Rivera family fund").first.click()
    await page.wait_for_selector("text=Sentinel's summary", timeout=60000)
    await page.get_by_text("Sentinel's summary").scroll_into_view_if_needed()
    await page.mouse.wheel(0, -200)
    await save(page, "08-scam-review-sentinel")


async def giving(browser: Browser) -> None:
    page = await open_as(browser, "marcus.chen", "/giving")
    mandate = page.get_by_text("Give automatically after disasters").first
    await mandate.wait_for(timeout=LONG)
    await page.wait_for_timeout(1500)
    await mandate.evaluate("h => window.scrollTo(0, h.getBoundingClientRect().top + window.scrollY - 40)")
    await save(page, "09-giving-mandate")


async def price_watch(browser: Browser) -> None:
    page = await open_as(browser, None, "/price-watch")
    chart = page.locator("figure", has_text="biggest price rises")
    await chart.wait_for(timeout=LONG)
    await page.wait_for_timeout(2500)
    await chart.evaluate("f => window.scrollTo(0, f.getBoundingClientRect().bottom + window.scrollY - 940)")
    await save(page, "10-price-watch-chart")


async def architecture(browser: Browser) -> None:
    ctx = await browser.new_context(viewport=VIEW, device_scale_factor=2)
    page = await ctx.new_page()
    await page.goto((OUT / "architecture.html").as_uri())
    await save(page, "11-architecture")


async def thumbnail(browser: Browser) -> None:
    """Devpost's project thumbnail: 3:2, made from two of the screenshots above."""
    ctx = await browser.new_context(viewport={"width": 1500, "height": 1000})
    page = await ctx.new_page()
    await page.goto((OUT / "thumbnail.html").as_uri())
    await page.evaluate("document.fonts.ready")
    await page.wait_for_timeout(500)
    await page.screenshot(path=OUT / "thumbnail.png")
    print("saved thumbnail")
    await ctx.close()


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        shots = [landing, navigator, inventory, registry, command_center, dispatch, what_if, scam_review, giving, price_watch, architecture, thumbnail]
        only = set(os.environ.get("ONLY", "").split(",")) - {""}  # e.g. ONLY=dispatch,giving to retake some
        for shot in [s for s in shots if not only or s.__name__ in only]:
            try:
                await shot(browser)
            except Exception as e:  # keep going; rerun just the ones that failed
                print("FAILED", shot.__name__, type(e).__name__, str(e)[:200])
        await browser.close()


asyncio.run(main())
