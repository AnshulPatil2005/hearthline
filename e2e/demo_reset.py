"""Reset the demo: after someone has changed shared state (here, a dispute marked answered and a registry closed),
"Put it back to the start" on the sign-in page restores the seeded data for everyone; a second reset right away is
refused. Needs the API and the web app. Takes a minute or two on SQLite (it runs the whole demo seed)."""

import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright
from sqlalchemy import create_engine, text

WEB = os.environ.get("E2E_WEB", "http://localhost:5173")
DB = os.environ.get("DATABASE_URL") or f"sqlite:///{Path(__file__).parent.parent / 'backend' / 'hearthline.db'}"
engine = create_engine(DB.replace("postgresql://", "postgresql+psycopg://", 1))

STATE = """select (select count(*) from payment_disputes where decision is null),
                  (select status from registries where slug = 'riveras-rebuild-fund'),
                  (select count(*) from households)"""


def state():
    with engine.connect() as conn:
        return tuple(conn.execute(text(STATE)).one())


async def main() -> None:
    with engine.begin() as conn:  # what a judge's clicks would have changed
        conn.execute(text("update payment_disputes set decision = 'refunded' where id = 1"))
        conn.execute(text("update registries set status = 'closed' where slug = 'riveras-rebuild-fund'"))
    print("changed:", state())
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1200, "height": 900})
        await page.goto(f"{WEB}/login")
        await page.get_by_role("button", name="Someone changed the demo?").click()
        await page.get_by_role("button", name="Reset the demo").click()
        await page.wait_for_selector("text=Resetting the demo", timeout=10000)
        await page.wait_for_selector("text=The demo is back to the start", timeout=300000)
        print("after reset:", state())
        await page.get_by_role("button", name="Someone changed the demo?").click()
        await page.get_by_role("button", name="Reset the demo").click()
        await page.wait_for_selector("text=Try again in", timeout=10000)
        print("second reset:", (await page.locator("text=Try again in").inner_text())[:80])
        await browser.close()


asyncio.run(main())
