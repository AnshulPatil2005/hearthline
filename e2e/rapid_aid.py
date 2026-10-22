"""First-72-hours aid: the org admin checks official warnings for the fire zone (the National Weather Service, live),
then simulates an evacuation order; the panel shows who prepared and would be paid, who Sentinel holds back and who
is left out; one approval pays everyone in one PayPal Payouts call (or, with a low sandbox balance, the batch shows
"Not sent" and nothing moves). Needs a freshly seeded database; no AI calls.
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
        page = await browser.new_page(viewport={"width": 1400, "height": 1000}, color_scheme="light")
        await page.goto(f"{WEB}/login?as=sam.whitfield", wait_until="networkidle")
        panel = page.locator("section", has=page.get_by_role("heading", name="First-72-hours aid"))
        await panel.wait_for(timeout=20000)
        print("panel:", (await panel.locator("p").first.inner_text())[:140], "…")

        async with page.expect_response(lambda r: r.url.endswith("/command/rapid-aid/check"), timeout=30000) as answer:
            await panel.get_by_role("button", name="Check official warnings").click()
        response = await answer.value
        warnings = [t for t in (await response.json()).get("triggers", []) if t["source"] == "nws"]
        print(f"official check: HTTP {response.status},", f"{len(warnings)} NWS warning(s) for the zone")

        await panel.get_by_role("button", name="Simulate an evacuation order (demo)").click()
        card = panel.locator("li", has_text="simulated for this demo").first
        await card.wait_for(timeout=30000)
        plan = await card.inner_text()
        assert "Would pay" in plan and "Sentinel is holding 1 household" in plan, plan
        print("proposed:", next(line for line in plan.split("\n") if line.startswith("Would pay")))
        print("held:", next(line for line in plan.split("\n") if "Jackson" in line))
        await page.screenshot(path=OUT / "rapid_aid_proposed.png", full_page=False)

        await card.get_by_role("button", name="Approve and pay").click()
        await card.get_by_text("Decided by Sam Whitfield").wait_for(timeout=90000)
        done = await card.inner_text()
        outcome = next(line for line in done.split("\n") if line.startswith(("Paid", "Not sent")))
        print("after approval:", outcome)
        assert "Approved" in done
        await card.screenshot(path=OUT / "rapid_aid_paid.png")
        await browser.close()


asyncio.run(main())
