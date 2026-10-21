"""Record the demo video's scenes (PLAN.md section 13) as captioned clips, then cut them into a rough video.

Each scene runs in its own browser context recorded at 1280x720, with a caption bar and a visible cursor. Waiting
(AI calls, the Shopper working in the background, PayPal pages loading) is marked and cut out, and PayPal's checkout
window is spliced in where it opened. Output in e2e/video/ (git-ignored): one trimmed mp4 per scene, so they can be
reordered or narrated over, and rough_cut.mp4 with all of them.

    cd backend
    uv run --with playwright --with imageio-ffmpeg python ../e2e/video_tour.py            # every scene
    uv run --with playwright --with imageio-ffmpeg python ../e2e/video_tour.py rebuild    # only some scenes

Needs a freshly seeded database, the sandbox buyer login in backend/.env (real sandbox payments), and the API and
web app (E2E_WEB, E2E_API and DATABASE_URL work as in the other checks). Uses about five AI calls.
"""

import asyncio
import os
import shutil
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from paypal_sandbox import confirm, have_buyer, open_checkout, sign_in
from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from sqlalchemy import create_engine, text

WEB = os.environ.get("E2E_WEB", "http://localhost:5173")
DB = os.environ.get("DATABASE_URL") or f"sqlite:///{Path(__file__).parent.parent / 'backend' / 'hearthline.db'}"
OUT = Path(__file__).parent / "video"
RAW = OUT / "raw"
SIZE = {"width": 1280, "height": 720}
PACE = 0.93  # scales every caption's hold; the outline's target is under 3:00

# A caption bar and a cursor dot, added to every page the tour opens (headless video shows no mouse pointer).
OVERLAY = """
(() => {
  const ready = (fn) => (document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', fn) : fn())
  ready(() => {
    const bar = document.createElement('div')
    Object.assign(bar.style, {
      position: 'fixed', left: '50%', bottom: '22px', transform: 'translateX(-50%)', maxWidth: '1040px',
      padding: '10px 18px', borderRadius: '12px', background: 'rgba(28, 25, 23, 0.88)', color: '#fff',
      font: '500 19px/1.4 system-ui, sans-serif', textAlign: 'center', zIndex: 2147483647, pointerEvents: 'none',
      display: 'none',
    })
    document.documentElement.appendChild(bar)
    window.__tourCaption = (words) => {
      try { sessionStorage.setItem('tour-caption', words || '') } catch {}
      bar.textContent = words || ''
      bar.style.display = words ? 'block' : 'none'
    }
    let saved = ''
    try { saved = sessionStorage.getItem('tour-caption') || '' } catch {}
    window.__tourCaption(saved)
    const dot = document.createElement('div')
    Object.assign(dot.style, {
      position: 'fixed', left: '-40px', top: '-40px', width: '20px', height: '20px', margin: '-10px 0 0 -10px',
      borderRadius: '50%', background: 'rgba(234, 88, 12, 0.35)', border: '2px solid rgba(234, 88, 12, 0.95)',
      zIndex: 2147483647, pointerEvents: 'none', transition: 'transform 120ms',
    })
    document.documentElement.appendChild(dot)
    addEventListener('mousemove', (e) => { dot.style.left = e.clientX + 'px'; dot.style.top = e.clientY + 'px' }, true)
    addEventListener('mousedown', () => { dot.style.transform = 'scale(1.7)' }, true)
    addEventListener('mouseup', () => { dot.style.transform = 'scale(1)' }, true)
  })
})()
"""

CARD = """<html><body style="margin:0;height:100vh;display:grid;place-items:center;background:#faf6f1;
font-family:system-ui,sans-serif;color:#1c1917"><div style="max-width:960px;padding:0 48px">
<p style="color:#c2410c;letter-spacing:.08em;font-weight:600;margin:0 0 18px">{kicker}</p>
<h1 style="font-size:54px;line-height:1.1;margin:0 0 22px">{title}</h1>
<p style="font-size:24px;line-height:1.45;color:#57534e;margin:0">{body}</p></div></body></html>"""


@dataclass
class Clip:
    """One page's recording: when it started, the stretches to cut, and other clips spliced in."""

    page: Page
    start: float = field(default_factory=time.monotonic)
    cuts: list[tuple[float, float]] = field(default_factory=list)
    inserts: list[tuple[float, "Clip"]] = field(default_factory=list)
    path: Path | None = None
    box: tuple[int, int] | None = None  # a window smaller than the video: the area it fills (top left)
    end: float | None = None  # our clock when the page closed; with the video's length, gives the start offset

    def now(self) -> float:
        return time.monotonic() - self.start

    @asynccontextmanager
    async def cut(self):
        begin = self.now()
        try:
            yield
        finally:
            self.cuts.append((begin, self.now()))


class Scene:
    def __init__(self, browser: Browser, name: str):
        self.browser, self.name = browser, name
        self.ctx: BrowserContext | None = None
        self.clip: Clip | None = None

    async def __aenter__(self) -> "Scene":
        self.ctx = await self.browser.new_context(
            viewport=SIZE, record_video_dir=str(RAW), record_video_size=SIZE, color_scheme="light"
        )
        await self.ctx.add_init_script(OVERLAY)
        self.clip = Clip(await self.ctx.new_page())
        return self

    @property
    def page(self) -> Page:
        return self.clip.page

    async def __aexit__(self, exc_type, *exc) -> None:
        clips = [self.clip, *(c for _, c in self.clip.inserts)]
        for c in clips:
            c.end = c.now()
        if exc_type is not None:  # keep what each window showed, to see why
            for i, page in enumerate(self.ctx.pages):
                await page.screenshot(path=RAW / f"{self.name}-failed-{i}.png")
        await self.ctx.close()  # finishes the video files
        if exc_type is None:
            for c in clips:
                c.path = Path(await c.page.video.path())
            cut_scene(self.name, self.clip)

    async def popup(self, button) -> Clip:
        """Open PayPal's checkout from `button`; its window is recorded and spliced in where it opened."""
        opened = self.clip.now()
        popup = await open_checkout(self.page, button)
        clip = Clip(popup)
        self.clip.inserts.append((opened, clip))
        return clip

    def popup_closed(self, clip: Clip) -> None:
        opened = next(t for t, c in self.clip.inserts if c is clip)
        self.clip.cuts.append((opened, self.clip.now()))  # the main page sat behind the window meanwhile


async def caption(page: Page, words: str, hold: float = 2.5) -> None:
    await page.evaluate("(w) => window.__tourCaption && window.__tourCaption(w)", words)
    await page.wait_for_timeout(int(hold * PACE * 1000))


async def click(page: Page, target, hold: float = 0.6) -> None:
    """Glide the cursor to the target, then click it, so the video shows what was pressed."""
    await target.scroll_into_view_if_needed()
    box = await target.bounding_box()
    if box:
        await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=18)
        await page.wait_for_timeout(250)
    await target.click()
    await page.wait_for_timeout(int(hold * 1000))


async def show(page: Page, target, hold: float = 2.0) -> None:
    await target.scroll_into_view_if_needed()
    await page.wait_for_timeout(int(hold * 1000))


async def sign_in_as(scene: Scene, persona: str, path: str, ready: str) -> None:
    async with scene.clip.cut():
        await scene.page.evaluate("() => window.__tourCaption && window.__tourCaption('')")
        await scene.page.goto(f"{WEB}/login?as={persona}&next={path}")
        await scene.page.wait_for_selector(ready, timeout=60000)
        await scene.page.wait_for_timeout(800)


async def card(scene: Scene, kicker: str, title: str, body: str, hold: float = 5) -> None:
    await scene.page.set_content(CARD.format(kicker=kicker, title=title, body=body))
    await scene.page.wait_for_timeout(int(hold * 1000))


async def pay_in_popup(scene: Scene, button) -> None:
    clip = await scene.popup(button)
    async with clip.cut():
        await clip.page.wait_for_load_state("domcontentloaded")
    w, h = await clip.page.evaluate("() => [innerWidth, innerHeight]")
    fit = min(1, SIZE["width"] / w, SIZE["height"] / h)  # Playwright scales a bigger window down to fit
    clip.box = (int(w * fit) // 2 * 2, int(h * fit) // 2 * 2)
    await caption(clip.page, "PayPal checkout, in the sandbox: the donor signs in and pays", 1.5)
    await sign_in(clip.page)
    async with clip.cut():
        await clip.page.wait_for_timeout(3000)
    await confirm(clip.page)
    scene.popup_closed(clip)


# Scenes ---------------------------------------------------------------------------------------------------------


async def hook(scene: Scene) -> None:
    await card(
        scene,
        "PREPARE · RESPOND · REBUILD · REOPEN",
        "Hearthline",
        "Disaster recovery for the people who live through it. The Sablewood Fire, its town and its people are "
        "made up; every payment runs in the PayPal sandbox.",
        5,
    )


async def prepare(scene: Scene) -> None:
    page = scene.page
    await sign_in_as(scene, "elena.rivera", "/home", "text=Coverage check")
    await caption(page, "Elena Rivera photographed her home before the fire. The Inventory agent listed what it saw")
    await show(page, page.locator("section", has_text="Coverage check").first)
    await caption(page, "Channel3 priced every item, and the total is checked against her policy's limit", 3)
    simulate = page.get_by_role("button", name="Simulate an evacuation warning (demo)")
    if await simulate.count():
        await click(page, simulate, 1.5)
        await page.evaluate("() => window.scrollTo({ top: 0, behavior: 'smooth' })")
        await caption(page, "National Weather Service alerts warn her when a fire nears (simulated here)", 3)
    await click(page, page.get_by_role("link", name="Inventory").first)
    await page.wait_for_selector(".ag-row", timeout=30000)
    await caption(page, "A dated, priced inventory in AG Grid, grouped by room, ready to export for a claim", 3.5)


async def respond(scene: Scene) -> None:
    page = scene.page
    async with scene.clip.cut():
        await page.goto(f"{WEB}/r/rivera-family", wait_until="networkidle")
    await caption(page, "Instead of cash, the family lists exactly what they need on a Rebuild Registry")
    item = page.locator("li", has_text="Dog crate and bed for Pepper")
    await click(page, item.get_by_role("button", name="Fund this"))
    async with scene.clip.cut():
        await page.wait_for_selector("paypal-button", timeout=30000)
        await page.wait_for_timeout(2500)
    await caption(page, "A donor gives with PayPal, Venmo or Pay Later", 2.5)
    await pay_in_popup(scene, page.locator("paypal-button"))
    async with scene.clip.cut():
        await page.wait_for_selector("text=Thank you! You gave", timeout=90000)
    await caption(page, "The item is fully funded, so Hearthline's Shopper agent goes to work", 3)

    await sign_in_as(scene, "elena.rivera", "/registry", "text=What the Shopper bought")
    bought = page.locator("li", has_text="Local business").first
    async with scene.clip.cut():
        for _ in range(24):  # the Shopper runs in the background: Channel3, the AI's pick, the rules, Payouts
            if await bought.count():
                break
            await page.wait_for_timeout(5000)
            await page.reload(wait_until="networkidle")
    await show(page, bought, 0.5)
    await caption(page, "It checked the town's reopened stores first and bought from Sablewood Mercantile", 3.5)
    await click(page, bought.get_by_text("Spending rules"), 0.8)
    rules = "Code, not the AI, enforces the rules: the budget, approved stores, the family's address, fair prices"
    await caption(page, rules, 4)

    await sign_in_as(scene, "rosa.delgado", "/business", "text=Orders from Hearthline's Shopper")
    orders = page.locator("section", has_text="Orders from Hearthline's Shopper")
    await show(page, orders, 0.5)
    await caption(page, "The store was paid through PayPal Payouts. Rosa hands the crate to the family", 3)
    await click(page, orders.get_by_role("button", name="Mark delivered").first, 1.5)


async def scam(scene: Scene) -> None:
    page = scene.page
    for persona, reason in (
        ("priya.nair", "Photos copied from the Riveras; the address is outside the fire."),
        ("tom.becker", "Agree: someone is impersonating the Rivera family."),
    ):
        await sign_in_as(scene, persona, "/review", ".ag-row")
        if persona == "priya.nair":
            await caption(page, "Someone copied the Riveras' story to raise money for themselves", 3)
        await click(page, page.locator(".ag-row", has_text="Rivera family fund").first)
        async with scene.clip.cut():
            await page.wait_for_selector("text=Sentinel's summary", timeout=30000)
        if persona == "priya.nair":
            await show(page, page.locator("section", has_text="Sentinel's summary").first, 0.5)
            await caption(page, "The Sentinel agent flags the copied photos and the address. People decide", 4)
        else:
            await caption(page, "A second reviewer, picked at random, has to agree", 2.5)
        await page.get_by_placeholder("Your reason").fill(reason)
        await click(page, page.get_by_role("button", name="Reject"), 1.5)
    async with scene.clip.cut():
        await page.goto(f"{WEB}/r/riveras-rebuild-fund", wait_until="networkidle")
    await caption(page, "The copycat registry closes and every donor is refunded through PayPal", 3.5)


async def review(scene: Scene) -> None:
    page = scene.page
    await sign_in_as(scene, "elena.rivera", "/aid", "text=Cash aid")
    await caption(page, "Elena asks for cash aid for two weeks at the Sablewood Inn", 2)
    await page.get_by_label("Amount").fill("300")
    await page.get_by_placeholder("What is it for?").fill("Two weeks at the Sablewood Inn while we find a rental.")
    await click(page, page.get_by_role("button", name="Send request"))
    async with scene.clip.cut():
        await page.wait_for_selector("text=Cash aid · $300", timeout=90000)
    for persona in ("priya.nair", "tom.becker"):  # the reviewer is assigned at random
        async with scene.clip.cut():
            await page.goto(f"{WEB}/login?as={persona}&next=/review")
            await page.wait_for_selector(".ag-row", timeout=60000)
            row = page.locator(".ag-row", has_text="$300")
            found = await row.count() > 0
        if found:
            break
    await caption(page, "A reviewer picked at random gets the case, with the AI's evidence packet", 2.5)
    await click(page, row.first)
    async with scene.clip.cut():
        await page.wait_for_selector("text=Sentinel's summary", timeout=30000)
    await show(page, page.locator("section", has_text="Sentinel's summary").first, 0.5)
    await caption(page, "The AI prepares the evidence; a person approves before any money moves", 3)
    await click(page, page.get_by_role("button", name="Approve"))
    async with scene.clip.cut():
        await page.wait_for_selector("text=This case was approved.", timeout=90000)
    await caption(page, "Approved, and paid to Elena's PayPal account through PayPal Payouts", 3.5)


async def rebuild(scene: Scene) -> None:
    page = scene.page
    await sign_in_as(scene, "elena.rivera", "/rebuild", ".b-gantt-task")
    await caption(page, "The rebuild: a licensed contractor's plan in a Bryntum Gantt, with the money in escrow", 3.5)
    step = page.locator("li", has_text="Debris removal and demolition")
    await show(page, step.get_by_text("Photo check").first, 0.5)
    await caption(page, "The Site agent checked the contractor's photos against what this step should look like", 3.5)
    await click(page, step.get_by_role("button", name="Approve and pay"))
    async with scene.clip.cut():
        done = step.get_by_text("Paid", exact=True).or_(step.get_by_text("balance can't cover"))
        await done.first.wait_for(timeout=60000)
    await caption(page, "Elena approves, and the milestone is paid from escrow with PayPal Payouts", 3.5)


async def reopen(scene: Scene) -> None:
    page = scene.page
    async with scene.clip.cut():
        await page.goto(f"{WEB}/reopen/morenos-bakery", wait_until="networkidle")
        await page.wait_for_selector(".b-gantt-task", timeout=30000)
    await caption(page, "Moreno's Bakery burned too. Regulars buy gift cards now, to spend when it reopens", 3.5)
    await show(page, page.get_by_text("What your money pays for").first, 0.5)
    escrow = (
        "The money waits in escrow and is released step by step; if the bakery misses its date, buyers are refunded"
    )
    await caption(page, escrow, 4)
    await sign_in_as(scene, "luis.moreno", "/business", "text=We're open again")
    await caption(page, "Luis reopens", 1.5)
    await click(page, page.get_by_role("button", name="We're open again"))
    await click(page, page.get_by_role("button", name="Yes, we're open"))
    async with scene.clip.cut():
        await page.wait_for_selector("text=You're open again", timeout=30000)
    with create_engine(DB.replace("postgresql://", "postgresql+psycopg://", 1)).connect() as conn:
        code = conn.execute(
            text("select code from gift_cards where campaign_id = 1 and status = 'active' order by id limit 1")
        ).scalar_one()
    await caption(page, "The first regular is back; Luis takes $12.50 from their card", 1.5)
    await page.get_by_label("Card code").fill(code)
    await click(page, page.get_by_role("button", name="Check card"))
    await page.get_by_label("Purchase amount").fill("12.50")
    await click(page, page.get_by_role("button", name="Take from card"), 2.5)


async def claim(scene: Scene) -> None:
    page = scene.page
    await sign_in_as(scene, "elena.rivera", "/insurance", "text=Insurance")
    upload = page.locator("text=Upload your policy")
    async with scene.clip.cut():
        await upload.or_(page.locator("text=Send your claim to")).first.wait_for(timeout=30000)
        if await upload.count():
            sample = Path(__file__).parent.parent / "frontend/public/samples/golden-poppy-homeowners-policy.pdf"
            await page.get_by_label("Policy PDF").set_input_files(sample)
            await page.get_by_role("button", name="Read my policy").click()
            await page.get_by_role("button", name="Prepare my claim").wait_for(timeout=180000)
    await caption(page, "The Policy agent read her policy. Hearthline builds the contents claim from her inventory", 3)
    await click(page, page.get_by_role("button", name="Prepare my claim"))
    link_box = page.get_by_label("Send this private link to your adjuster")
    async with scene.clip.cut():
        await link_box.wait_for(timeout=60000)
    link = await link_box.input_value()
    await caption(page, "She sends her insurer a private link", 2)
    async with scene.clip.cut():
        await page.goto(link)
        await page.wait_for_selector(".ag-row", timeout=60000)
    await caption(page, "The adjuster sees every item with its photo and date, and the policy's limits applied", 4)
    await page.get_by_label("Adjuster's name").fill("Dana Lee, Golden Poppy Claims")
    await caption(page, "and pays the claim with PayPal", 1.5)
    await pay_in_popup(scene, page.locator("paypal-button"))
    async with scene.clip.cut():
        await page.wait_for_selector("text=/^Paid \\$/", timeout=120000)
    await caption(page, "Hearthline passes it straight on to Elena's PayPal account: minutes, not a mailed check", 4)


async def command(scene: Scene) -> None:
    page = scene.page
    await sign_in_as(scene, "sam.whitfield", "/command", ".ag-row[row-index='0']")
    await caption(page, "The relief organization's Command Center: 2,000 households, AG Grid's server-side rows", 3.5)
    src = await page.locator(".ag-header-cell", has_text="Damage").first.bounding_box()
    dst = await page.get_by_text("Drag here to set row groups").first.bounding_box()
    if src and dst:
        await page.mouse.move(src["x"] + 30, src["y"] + src["height"] / 2, steps=15)
        await page.mouse.down()
        await page.mouse.move(dst["x"] + 20, dst["y"] + dst["height"] / 2, steps=25)
        await page.mouse.up()
        await page.wait_for_selector(".ag-row-group", timeout=20000)
        await caption(page, "Grouped on the server, with totals of what each group still needs", 3)
        await page.locator(".ag-column-drop-rowgroup .ag-column-drop-cell").first.focus()
        await page.keyboard.press("Delete")
        await page.wait_for_timeout(1500)
    await page.get_by_label("Ask the grid").fill("destroyed homes on Juniper Lane that have no PayPal account yet")
    await caption(page, "Or ask in plain words, in any of five languages", 1.5)
    await click(page, page.get_by_role("button", name="Ask", exact=True))
    async with scene.clip.cut():
        await page.wait_for_selector("text=AI set the filters", timeout=90000)
    await caption(page, "AG Grid's AI Toolkit turns the question into the grid's filters", 3.5)
    await click(page, page.get_by_role("link", name="Books").first)
    async with scene.clip.cut():
        await page.get_by_text("PayPal balance").first.wait_for(timeout=90000)
        await page.wait_for_timeout(2000)
    await caption(page, "Every ledger entry, checked against PayPal's own records through APIMatic's PayPal SDK", 3.5)


async def close(scene: Scene) -> None:
    await card(
        scene,
        "BUILT ON THE PAYPAL SANDBOX",
        "Help that reaches the family, not a scammer",
        "PayPal Orders, Payouts, Subscriptions, Disputes, Transaction Search and Log in with PayPal · AI agents with "
        "people in charge of the money · AG Grid · Bryntum · Channel3 · APIMatic · Render",
        6,
    )


SCENES = [
    ("01-hook", hook),
    ("02-prepare", prepare),
    ("03-respond", respond),
    ("04-scam", scam),
    ("05-review", review),
    ("06-rebuild", rebuild),
    ("07-reopen", reopen),
    ("08-claim", claim),
    ("09-command", command),
    ("10-close", close),
]


# Cutting -------------------------------------------------------------------------------------------------------


def ffmpeg() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def lag(clip: Clip, length: float) -> float:
    """The video starts a little before our clock does: shift our timestamps by the difference."""
    return max(0.0, length - clip.end) if clip.end else 0.0


def keep(clip: Clip, length: float) -> list[tuple[float, float]]:
    """The stretches of a clip left after its cuts (merged and clamped), in order."""
    spans, at, shift = [], 0.0, lag(clip, length)
    for begin, end in sorted((b + shift, e + shift) for b, e in clip.cuts):
        if begin > at + 0.2:
            spans.append((at, min(begin, length)))
        at = max(at, end)
    if at < length - 0.2:
        spans.append((at, length))
    return spans


def duration(path: Path) -> float:
    probe = subprocess.run([ffmpeg(), "-i", str(path)], capture_output=True, text=True).stderr
    h, m, s = probe.split("Duration: ")[1].split(",")[0].split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def cut_scene(name: str, main: Clip) -> None:
    """Trim the scene's clip, splice in its PayPal windows, and write e2e/video/<name>.mp4."""

    def pieces_of(clip: Clip) -> list[tuple[Path, float, float, tuple[int, int] | None]]:
        return [(clip.path, b, e, clip.box) for b, e in keep(clip, duration(clip.path))]

    pieces: list[tuple[Path, float, float, tuple[int, int] | None]] = []
    shift = lag(main, duration(main.path))
    pending = sorted(((at + shift, c) for at, c in main.inserts), key=lambda x: x[0])
    for begin, end in keep(main, duration(main.path)):
        while pending and pending[0][0] <= end:  # a window opened before or during this stretch
            at, clip = pending.pop(0)
            if at > begin:
                pieces.append((main.path, begin, at, None))
                begin = at
            pieces += pieces_of(clip)
        pieces.append((main.path, begin, end, None))
    for _, clip in pending:
        pieces += pieces_of(clip)
    parts = []
    for i, (src, begin, end, box) in enumerate(p for p in pieces if p[2] - p[1] > 0.3):
        part = RAW / f"{name}-{i:02d}.mp4"
        encode(["-ss", f"{begin:.2f}", "-to", f"{end:.2f}", "-i", str(src)], part, box)
        parts.append(part)
    concat(parts, OUT / f"{name}.mp4")
    print(f"{name}: {len(parts)} pieces, {duration(OUT / f'{name}.mp4'):.0f} s")


def encode(inputs: list[str], out: Path, box: tuple[int, int] | None = None) -> None:
    """Re-encode to 1280x720 H.264. A small window (PayPal's checkout) is cropped and enlarged on the page color."""
    fit = "fps=30,scale=1280:720,setsar=1"
    if box:
        fit = (
            f"crop={box[0]}:{box[1]}:0:0,scale=1280:720:force_original_aspect_ratio=decrease,"
            "pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=0xfaf6f1,fps=30,setsar=1"
        )
    subprocess.run(
        [
            ffmpeg(),
            "-y",
            "-loglevel",
            "error",
            *inputs,
            "-vf",
            fit,
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            str(out),
        ],
        check=True,
    )


def concat(parts: list[Path], out: Path) -> None:
    listing = out.with_suffix(".txt")
    listing.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf-8")
    subprocess.run(
        [
            ffmpeg(),
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            "-c",
            "copy",
            str(out),
        ],
        check=True,
    )
    listing.unlink()


async def main(only: list[str]) -> None:
    if not have_buyer():
        sys.exit("The tour pays with the sandbox buyer: set PAYPAL_SANDBOX_BUYER_EMAIL and _PASSWORD in backend/.env")
    shutil.rmtree(RAW, ignore_errors=True)
    RAW.mkdir(parents=True)
    chosen = [(n, f) for n, f in SCENES if not only or any(o in n for o in only)]
    for stale in [*(OUT / f"{n}.mp4" for n, _ in chosen), OUT / "rough_cut.mp4"]:
        stale.unlink(missing_ok=True)
    failed = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for name, play in chosen:
            try:
                async with Scene(browser, name) as scene:
                    await play(scene)
            except Exception as e:  # noqa: BLE001 - keep going; the rest of the video still gets recorded
                failed.append(name)
                print(f"{name} failed: {type(e).__name__}: {str(e).splitlines()[0][:200]}")
        await browser.close()
    made = [OUT / f"{n}.mp4" for n, _ in SCENES if (OUT / f"{n}.mp4").exists()]
    if not only and made:
        concat(made, OUT / "rough_cut.mp4")
        print(f"rough_cut.mp4: {duration(OUT / 'rough_cut.mp4'):.0f} s from {len(made)} scenes")
    if failed:
        sys.exit(f"Scenes that failed: {', '.join(failed)}")


asyncio.run(main(sys.argv[1:]))
