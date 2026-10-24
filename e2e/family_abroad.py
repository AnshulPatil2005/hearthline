"""Family abroad: a relative in Mexico opens the Riveras' registry (browser locale es-MX), gives in pesos to fund the
twin mattresses through PayPal (the sandbox buyer pays MXN; Venmo and Pay Later are hidden, they take dollars), and
the family's item is funded in dollars at PayPal's own rate; the gift shows on the donation and in the books in
pesos. Real sandbox payment; the Shopper then buys the mattresses (AI calls); needs a freshly seeded database.
"""

import asyncio
import os
import re
from pathlib import Path

from paypal_sandbox import confirm, have_buyer, open_checkout, sign_in
from playwright.async_api import async_playwright
from sqlalchemy import create_engine, text

OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(exist_ok=True)
WEB = os.environ.get("E2E_WEB", "http://localhost:5173")
DB = os.environ.get("DATABASE_URL") or f"sqlite:///{Path(__file__).parent.parent / 'backend' / 'hearthline.db'}"


async def main() -> None:
    if not have_buyer():
        print("skipped: no sandbox buyer login in backend/.env")
        return
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 1100}, locale="es-MX", color_scheme="light")
        page = await ctx.new_page()
        await page.goto(f"{WEB}/r/rivera-family", wait_until="networkidle")
        await (
            page.locator("li", has_text="Twin mattresses")
            .get_by_role("button", name=re.compile("Fund this|Financiar"))
            .click()
        )
        panel = page.locator("div.rounded-xl", has=page.locator("select[name=currency]")).first
        await panel.wait_for(timeout=30000)
        await page.wait_for_function("document.querySelector('select[name=currency]').value !== 'USD'", timeout=15000)  # rates loaded
        picked = await panel.locator("select[name=currency]").input_value()
        print("currency guessed from es-MX:", picked)
        assert picked == "MXN"
        await page.wait_for_selector("paypal-button", timeout=30000)
        await page.wait_for_timeout(2500)
        estimate = await panel.locator("p[aria-live]").inner_text()
        print("estimate:", estimate)
        print("buttons:", [await page.locator(b).count() for b in ("paypal-button", "venmo-button")])
        await panel.screenshot(path=OUT / "family_abroad_panel.png")

        popup = await open_checkout(page, page.locator("paypal-button"))
        await sign_in(popup)
        print("paid with:", await confirm(popup))
        await page.get_by_text(re.compile(r"Gracias|Thank you")).first.wait_for(timeout=120000)
        print("thanks:", (await page.get_by_role("status").inner_text()).split("\n")[0])
        await browser.close()

    with create_engine(DB.replace("postgresql://", "postgresql+psycopg://", 1)).connect() as conn:
        row = conn.execute(
            text(
                "select currency, currency_amount, amount, exchange_rate, status from donations "
                "where currency <> 'USD' order by id desc limit 1"
            )
        ).one()
        item = conn.execute(
            text(
                "select funded_amount, unit_price * quantity as target, status from registry_items where name = 'Twin mattresses'"
            )
        ).one()
    print("donation:", dict(row._mapping))
    print("item:", dict(item._mapping))
    assert row.status == "captured" and row.currency == "MXN" and item.status in ("funded", "purchased", "delivered")


asyncio.run(main())
