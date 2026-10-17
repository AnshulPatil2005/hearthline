"""The contractor reschedules a milestone in Bryntum Gantt; the homeowner reviews the Site agent's photo
check and approves the demolition milestone, which pays the contractor from escrow through PayPal Payouts.
Needs the API (fresh demo seed) and the web app running. Sends one real sandbox payout."""

import asyncio
import json
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "screenshots"
OUT.mkdir(exist_ok=True)
WEB = "http://localhost:5173"
API = "http://localhost:8000"


def api(path: str, token: str) -> dict | list:
    req = urllib.request.Request(f"{API}{path}", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def slab_photo() -> bytes:
    """A stand-in site photo with no camera date, like a screenshot or a downloaded image."""
    import io

    from PIL import Image, ImageDraw

    img = Image.new("RGB", (800, 600), (175, 200, 225))
    ImageDraw.Draw(img).rectangle([0, 320, 800, 600], fill=(165, 165, 160))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


async def token(page) -> str:
    return await page.evaluate("localStorage.getItem('hearthline.token')")


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1400, "height": 1100}, color_scheme="light")
        page = await ctx.new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text[:200]) if m.type == "error" else None)

        # Contractor: the portal opens on their projects, with a Gantt for the active one.
        await page.goto(f"{WEB}/login?as=dana.okafor", wait_until="networkidle")
        await page.wait_for_url("**/contractor", timeout=10000)
        await page.wait_for_selector(".b-gantt-task", timeout=30000)
        bars = await page.locator(".b-gantt-task").count()
        planning = await page.get_by_role("button", name="Send the plan to the family").count()
        print("contractor gantt bars:", bars, "| plan editor for the invited project:", bool(planning))

        dana = await token(page)
        project = next(p for p in api("/contractors/me/projects", dana) if p["status"] == "active")
        foundation = next(m for m in project["milestones"] if m["title"] == "Foundation repair")
        bar = page.locator(f'.b-gantt-task-wrap[data-task-id="{foundation["id"]}"] .b-gantt-task')
        await bar.scroll_into_view_if_needed()
        box = await bar.bounding_box()
        await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        await page.mouse.down()
        await page.mouse.move(box["x"] + box["width"] / 2 + 60, box["y"] + box["height"] / 2, steps=12)
        await page.mouse.up()
        await page.wait_for_timeout(2500)
        moved = next(m for m in api(f"/projects/{project['id']}", dana)["milestones"] if m["id"] == foundation["id"])
        print("foundation start:", foundation["start_date"][:10], "->", moved["start_date"][:10])
        await page.screenshot(path=OUT / "contractor_portal.png", full_page=True)

        # Homeowner: sees the same schedule read-only, the photo check, and approves the demolition milestone.
        await page.goto(f"{WEB}/login?as=elena.rivera&next=/rebuild", wait_until="networkidle")
        await page.wait_for_url("**/rebuild", timeout=10000)
        await page.wait_for_selector(".b-gantt-task", timeout=30000)
        await page.wait_for_selector("text=Photo check", timeout=10000)
        await page.screenshot(path=OUT / "rebuild_before.png", full_page=True)
        card = page.locator("li", has_text="Debris removal and demolition")
        await card.get_by_role("button", name="Approve and pay").click()
        # A sandbox merchant without enough balance is reported plainly and nothing moves.
        outcome = card.get_by_text("Paid", exact=True).or_(card.get_by_text("balance can't cover"))
        await outcome.first.wait_for(timeout=30000)
        elena = await token(page)
        mine = api("/households/me/projects", elena)[0]
        demolition = next(m for m in mine["milestones"] if m["seq"] == 2)
        print("demolition:", demolition["status"], demolition["paypal_ref"], "| escrow now", mine["escrow_balance"])
        if demolition["status"] != "paid":
            print("NOT PAID:", (await card.locator(".text-danger").inner_text()).strip())
        await page.screenshot(path=OUT / "rebuild_after.png", full_page=True)

        # Contractor submits the next milestone with a photo; the Site agent (live AI) checks it.
        await page.goto(f"{WEB}/login?as=dana.okafor", wait_until="networkidle")
        work = page.locator("li", has_text="Foundation repair")
        await work.locator("input[type=file]").set_input_files(
            {"name": "slab.jpg", "mimeType": "image/jpeg", "buffer": slab_photo()}
        )
        await work.get_by_role("button", name="Submit for approval").click()
        await work.get_by_text("Photo check").wait_for(timeout=90000)
        print("site check:", (await work.locator(".rounded-lg.border").last.inner_text()).replace("\n", " | ")[:200])

        # Homeowner approves; the weak or undated photo sends it to a human instead of paying.
        await page.goto(f"{WEB}/login?as=elena.rivera&next=/rebuild", wait_until="networkidle")
        card = page.locator("li", has_text="Foundation repair")
        await card.get_by_role("button", name="Approve and send to a reviewer").click()
        await card.get_by_text("With a reviewer").wait_for(timeout=30000)
        case_id = next(m for m in api("/households/me/projects", await token(page))[0]["milestones"] if m["seq"] == 3)[
            "case_id"
        ]

        # A supervisor sees the milestone, the contractor's photos and the photo check on the case.
        await page.goto(f"{WEB}/login?as=grace.alvarez&next=/review/cases/{case_id}", wait_until="networkidle")
        await page.wait_for_selector("text=Milestone 3: Foundation repair", timeout=15000)
        await page.screenshot(path=OUT / "milestone_case.png", full_page=True)
        risk = " ".join((await page.locator("h1 + span").first.inner_text()).split())
        print("milestone case risk:", risk, "|", (await page.get_by_text("Assigned:").inner_text()).strip())
        print("milestone case", case_id, "shows the photo check:", await page.get_by_text("Photo check", exact=True).count() == 1)
        print("console errors:", [e for e in errors if "license" not in e.lower() and "trial" not in e.lower()][:4])
        await browser.close()


asyncio.run(main())
