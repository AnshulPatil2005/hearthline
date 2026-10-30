"""The AI crew dispatcher: on the Crews page the org admin gives the dispatch agent an instruction and plans
tomorrow; every job without a crew gets a proposal (a ghost bar on the crew's row in Bryntum Scheduler Pro, with
the agent's reason) or is left for another day; the crew load view (Bryntum ResourceUtilization) shares the
project; the admin accepts one proposal from the bar's menu, rejects one in the panel, and accepts the rest, and the
jobs move onto the crews. One AI call; needs a freshly seeded database.
"""

import asyncio
import os
import re
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(exist_ok=True)
WEB = os.environ.get("E2E_WEB", "http://localhost:5173")


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 1300}, color_scheme="light")
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text[:160]) if m.type == "error" else None)
        await page.goto(f"{WEB}/login?as=sam.whitfield&next=/command/crews", wait_until="networkidle")
        await page.wait_for_selector(".b-sch-event", timeout=30000)
        print("crews loaded; utilization rows:", await page.locator("section[aria-labelledby=load-title] .b-grid-row").count())

        panel = page.locator("section[aria-labelledby='dispatch-title']")
        await panel.get_by_label("Instructions for the dispatch agent").fill(
            "Medical needs first. Keep Van 2 near Juniper Lane if you can."
        )
        await panel.get_by_role("button", name="Plan tomorrow").click()
        await panel.get_by_text(re.compile(r"^Plan for ")).wait_for(timeout=120000)
        rows = await panel.locator("li").all_inner_texts()
        proposed = [r for r in rows if "Accept" in r]
        print(
            f"plan: {len(rows)} jobs, {len(proposed)} proposed;",
            (await panel.get_by_text(re.compile(r"^Plan for ")).locator("..").inner_text())[:300],
        )
        for r in rows[:4]:
            print("   ", " | ".join(r.split("\n"))[:200])
        ghosts = page.locator(".b-sch-event.job-proposal")
        await ghosts.first.wait_for(timeout=30000)
        print("ghost bars on the Scheduler:", await ghosts.count())
        await page.screenshot(path=OUT / "dispatch_plan.png", full_page=True)

        # Accept one from its ghost bar's menu
        await ghosts.first.scroll_into_view_if_needed()
        await ghosts.first.click(button="right")
        await page.get_by_role("menuitem", name="Accept").click()
        await panel.get_by_text("Accepted").first.wait_for(timeout=30000)
        print("accepted from the Scheduler's menu")
        # Reject one in the panel, then accept the rest
        await (
            panel.locator("li", has=page.get_by_role("button", name="Reject"))
            .first.get_by_role("button", name="Reject")
            .click()
        )
        await panel.get_by_text("Rejected").first.wait_for(timeout=30000)
        await panel.get_by_role("button", name=re.compile(r"^Accept (all|\d)")).click()
        await page.wait_for_function(
            "() => !document.querySelector('section[aria-labelledby=dispatch-title] li button')", timeout=60000
        )
        statuses = [r.split("\n")[-1] for r in await panel.locator("li").all_inner_texts()]
        print("after deciding:", {s: statuses.count(s) for s in set(statuses)})
        await page.wait_for_timeout(1500)
        print(
            "ghost bars left:",
            await ghosts.count(),
            "| jobs still without a crew (the rejected one):",
            await page.locator(".b-sch-event-wrap[data-resource-id=unassigned]").count(),
        )
        await page.screenshot(path=OUT / "dispatch_after.png", full_page=True)
        print(
            "console errors:",
            [e for e in errors if "license" not in e.lower() and "trial" not in e.lower() and "****" not in e][:4],
        )
        await browser.close()


asyncio.run(main())
