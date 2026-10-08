"""The org admin's Command Center: 2,000 households in a server-side AG Grid. Filters, sorting and grouping
run on the server. Then batch cash aid: the admin filters to destroyed, verified homes and prepares a batch;
he can't approve it himself; a supervisor approves it and one PayPal Payouts call pays every household (or,
if the sandbox account's balance is too low, the batch is marked "Not sent" and nothing moves).
Needs the API (fresh demo seed) and the web app running."""

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(exist_ok=True)
WEB = "http://localhost:5173"


async def set_filter(page, col_id: str, label: str) -> None:
    """Open a column's set filter and keep only one value (Enter in the search box selects just the matches)."""
    await page.locator(f'.ag-header-cell[col-id="{col_id}"] .ag-header-cell-filter-button').click()
    search = page.locator(".ag-popup .ag-mini-filter input")
    await search.fill(label)
    await search.press("Enter")
    await page.keyboard.press("Escape")


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1500, "height": 1100}, color_scheme="light")
        errors = []
        page.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)
        requests = []
        page.on("request", lambda r: requests.append(r.post_data) if r.url.endswith("/command/households/rows") else None)

        await page.goto(f"{WEB}/login?as=sam.whitfield", wait_until="networkidle")
        await page.wait_for_url("**/command", timeout=10000)
        await page.wait_for_selector(".ag-row[row-index='0']", timeout=20000)
        print("matching:", await page.get_by_text("households match").inner_text())  # e.g. 2,005
        first = await page.locator(".ag-row[row-index='0']").last.inner_text()
        print("top row:", first.replace("\n", " | ")[:160])
        print("sparklines drawn:", await page.locator(".ag-sparkline-wrapper canvas").count())
        await page.screenshot(path=OUT / "command_center.png")

        # Group by damage: drag the column header into the row-group bar.
        src = await page.locator(".ag-header-cell", has_text="Damage").first.bounding_box()
        dst = await page.get_by_text("Drag here to set row groups").first.bounding_box()
        await page.mouse.move(src["x"] + 30, src["y"] + src["height"] / 2)
        await page.mouse.down()
        await page.mouse.move(dst["x"] + 20, dst["y"] + dst["height"] / 2, steps=15)
        await page.mouse.up()
        await page.wait_for_selector(".ag-row-group", timeout=15000)
        groups = await page.locator(".ag-row-group").all_inner_texts()
        print("groups:", [g.replace("\n", " ")[:70] for g in groups])
        await page.screenshot(path=OUT / "command_center_grouped.png")
        print("server requests:", len(requests))

        # Batch cash aid for destroyed homes verified to level 2.
        await page.locator(".ag-column-drop-rowgroup .ag-column-drop-cell").first.focus()  # ungroup
        await page.keyboard.press("Delete")
        await page.wait_for_selector('.ag-header-cell[col-id="damage_level"]', timeout=10000)
        await set_filter(page, "damage_level", "Destroyed")
        await set_filter(page, "verification_level", "Level 2")
        await page.wait_for_timeout(800)
        print("filtered:", await page.get_by_text("households match").inner_text())
        await page.get_by_role("button", name="Send cash aid").click()
        await page.get_by_role("button", name="Preview").click()
        await page.wait_for_selector("text=Left out, and why", timeout=15000)
        summary = (await page.locator("text=would get").inner_text()).strip()
        reasons = await page.locator("section", has_text="Batch cash aid").locator("ul").last.all_inner_texts()
        print("preview:", summary, "| left out:", "; ".join(reasons[0].splitlines()) if reasons else "none")
        await page.screenshot(path=OUT / "batch_preview.png", full_page=True)
        await page.get_by_role("button", name="for approval").click()
        await page.wait_for_selector("text=Waiting for approval", timeout=15000)
        print("sam sees:", await page.get_by_text("Needs someone else to approve").count(), "batch waiting for someone else")

        await page.goto(f"{WEB}/login?as=grace.alvarez&next=/command", wait_until="networkidle")
        await page.get_by_role("button", name="Approve and pay").click()
        outcome = page.get_by_text("Sent to PayPal").or_(page.get_by_text("Not sent"))
        await outcome.first.wait_for(timeout=60000)
        status = await outcome.first.inner_text()
        print("grace approved ->", status)
        if "Not sent" in status:
            print("  reason:", (await page.locator("p.text-danger").last.inner_text()).strip())
        await page.locator(".ag-row .ag-group-contracted").last.click()  # master/detail: open the batch
        await page.wait_for_selector(".ag-details-row .ag-row", timeout=10000)
        print("batch detail rows shown:", await page.locator(".ag-details-row .ag-row").count())
        await page.screenshot(path=OUT / "batch_approved.png", full_page=True)
        print("console errors:", [e for e in errors if "license" not in e.lower() and "trial" not in e.lower()][:4])
        await browser.close()


asyncio.run(main())
