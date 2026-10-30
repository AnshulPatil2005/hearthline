"""Rebuild what-if on Bryntum Gantt: Dana (Okafor Builders) asks what happens if a step runs late. A short roofing delay
fits in the roof's days to spare (the rough-in sets move-in day); a longer one moves move-in by less than the delay.
Then framing runs 14 days late: Bryntum's scheduling engine moves every step that waits for it on the chart, the
server works out the same move-in day, and Dana tells the Riveras why. Elena sees the new move-in day beside the planned
one, the steps and escrow payments that moved, the accepted plan as a baseline under each bar, and a navigator step.
Needs a freshly seeded database; no AI calls, no payments.
"""

import asyncio
import os
import re
from pathlib import Path

from playwright.async_api import Page, async_playwright

OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(exist_ok=True)
WEB = os.environ.get("E2E_WEB", "http://localhost:5173")

ENGINE_MOVE_IN = """() => {
  const g = bryntum.queryAll(w => w.isGantt)[0]
  const m = g.taskStore.allRecords.find(r => r.get('status') === 'move_in')
  return m && m.startDate.toISOString()
}"""
CRITICAL = """() => bryntum.queryAll(w => w.isGantt)[0].taskStore.allRecords
  .filter(t => t.critical && !t.isParent)
  .map(t => t.get('status') === 'move_in' ? 'move-in' : t.name.split(' · ')[0])"""


async def what_if(page: Page, panel, step: str, days: int) -> str:
    await panel.get_by_label("Step").select_option(label=step)
    await panel.get_by_label("Days late").fill(str(days))
    result = panel.locator("[aria-live=polite] p.font-medium").first
    await result.wait_for(timeout=30000)
    await page.wait_for_timeout(1200)  # the engine's preview and the server's answer
    return await panel.locator("[aria-live=polite]").inner_text()


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        errors: list[str] = []

        dana = await browser.new_page(viewport={"width": 1440, "height": 1500}, color_scheme="light")
        dana.on("console", lambda m: errors.append(m.text[:160]) if m.type == "error" else None)
        await dana.goto(f"{WEB}/login?as=dana.okafor&next=/contractor", wait_until="networkidle")
        await dana.wait_for_selector(".b-gantt-task", timeout=30000)
        await dana.wait_for_timeout(1500)
        planned = await dana.evaluate(ENGINE_MOVE_IN)
        print("move-in on the chart:", planned[:10], "| critical path:", await dana.evaluate(CRITICAL))

        await dana.get_by_role("button", name="What if a step runs late?").click()
        panel = dana.locator("section[aria-labelledby=what-if-title]")
        short = await what_if(dana, panel, "5. Roofing", 3)
        print("roofing 3 days late:", short.split("\n")[0])
        longer = await what_if(dana, panel, "5. Roofing", 7)
        print("roofing 7 days late:", " / ".join(longer.split("\n")[:2]))
        framing = await what_if(dana, panel, "4. Framing", 14)
        print("framing 14 days late:", " | ".join(line for line in framing.split("\n") if line.strip())[:400])
        print("  engine's move-in on the chart:", (await dana.evaluate(ENGINE_MOVE_IN))[:10])
        await dana.screenshot(path=OUT / "what_if_preview.png", full_page=True)

        await panel.get_by_label("Why is it late?").fill("The roof trusses arrive two weeks late from the mill")
        await panel.get_by_role("button", name=re.compile("^Tell the")).click()
        await panel.wait_for(state="detached", timeout=30000)
        await dana.wait_for_selector(".b-gantt-task", timeout=30000)
        await dana.wait_for_timeout(2000)
        print("saved; move-in on the chart now:", (await dana.evaluate(ENGINE_MOVE_IN))[:10])

        elena = await browser.new_page(viewport={"width": 1440, "height": 1600}, color_scheme="light")
        elena.on("console", lambda m: errors.append(m.text[:160]) if m.type == "error" else None)
        await elena.goto(f"{WEB}/login?as=elena.rivera&next=/rebuild", wait_until="networkidle")
        await elena.wait_for_selector(".b-gantt-task", timeout=30000)
        await elena.wait_for_timeout(1500)
        notice = elena.locator("div.bg-amber-soft", has_text="moved your move-in day")
        print("Elena sees:", " | ".join((await notice.inner_text()).split("\n"))[:400])
        stat = elena.get_by_text("Move-in day", exact=True).first.locator("..")
        print("move-in stat:", " | ".join((await stat.inner_text()).split("\n")))
        print("critical path for Elena:", await elena.evaluate(CRITICAL))
        print("baseline bars:", await elena.locator(".b-task-baseline").count())
        await elena.screenshot(path=OUT / "what_if_household.png", full_page=True)

        await elena.goto(f"{WEB}/home", wait_until="networkidle")
        step = elena.get_by_text("Your move-in day moved")
        await step.wait_for(timeout=30000)
        print("navigator step:", (await step.locator("..").inner_text()).replace("\n", " | ")[:200])
        print(
            "console errors:",
            [e for e in errors if "license" not in e.lower() and "trial" not in e.lower() and "****" not in e][:4],
        )
        await browser.close()


asyncio.run(main())
