"""Record the demo video: narrated, captioned scenes cut into one video under three minutes.

Each scene runs in its own browser context recorded at 1280x720, with a caption bar and a visible cursor. Every
caption is also spoken: the line is synthesized (Microsoft's neural voices through edge-tts, cached in
e2e/video/voice/), shown for as long as it takes to say, and laid into the scene's audio where it appeared. Waiting
(AI calls, the Shopper working in the background, PayPal pages loading) is marked and cut out, and PayPal's checkout
window is spliced in where it opened. Output in e2e/video/ (git-ignored): one mp4 per scene and hearthline-demo.mp4.

    cd backend
    uv run --with playwright --with imageio-ffmpeg --with edge-tts python ../e2e/video_tour.py           # every scene
    uv run --with playwright --with imageio-ffmpeg --with edge-tts python ../e2e/video_tour.py rebuild   # some scenes
    uv run --with imageio-ffmpeg python ../e2e/video_tour.py --join   # join the scene files already recorded

Needs a freshly reset demo (scenes reject the copycat registry, pay, approve), the sandbox buyer login in
backend/.env (real sandbox payments) and E2E_WEB pointing at the web app; the hosted demo's AG Grid key hides the
watermark. Uses about six AI calls.
"""

import asyncio
import hashlib
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

WEB = os.environ.get("E2E_WEB", "https://hearthline-web.onrender.com").rstrip("/")
OUT = Path(__file__).parent / "video"
RAW = OUT / "raw"
VOICES = OUT / "voice"
SIZE = {"width": 1280, "height": 720}
VOICE = "en-US-AndrewMultilingualNeural"
RATE = "+12%"
AFTER_LINE = 0.25  # seconds of quiet after each spoken line

# A caption bar and a cursor dot, added to every page the tour opens (headless video shows no mouse pointer).
OVERLAY = """
(() => {
  const ready = (fn) => (document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', fn) : fn())
  ready(() => {
    const bar = document.createElement('div')
    Object.assign(bar.style, {
      position: 'fixed', left: '50%', bottom: '22px', transform: 'translateX(-50%)', maxWidth: '1060px',
      padding: '10px 18px', borderRadius: '10px', background: 'rgba(17, 24, 39, 0.9)', color: '#fff',
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
      borderRadius: '50%', background: 'rgba(194, 65, 12, 0.35)', border: '2px solid rgba(194, 65, 12, 0.95)',
      zIndex: 2147483647, pointerEvents: 'none', transition: 'transform 120ms',
    })
    document.documentElement.appendChild(dot)
    addEventListener('mousemove', (e) => { dot.style.left = e.clientX + 'px'; dot.style.top = e.clientY + 'px' }, true)
    addEventListener('mousedown', () => { dot.style.transform = 'scale(1.7)' }, true)
    addEventListener('mouseup', () => { dot.style.transform = 'scale(1)' }, true)
  })
})()
"""

CARD = """<html><body style="margin:0;height:100vh;display:grid;place-items:center;background:#f6f7f9;
font-family:'Segoe UI',system-ui,sans-serif;color:#111827"><div style="max-width:980px;padding:0 48px">
<p style="color:#c2410c;letter-spacing:.08em;font-weight:600;margin:0 0 18px">{kicker}</p>
<h1 style="font-size:56px;line-height:1.1;margin:0 0 22px;letter-spacing:-.02em">{title}</h1>
<p style="font-size:24px;line-height:1.45;color:#4b5563;margin:0">{body}</p></div></body></html>"""


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


@dataclass
class Line:
    clip: Clip
    at: float  # on the clip's clock, when the caption appeared
    audio: Path


class Scene:
    current: "Scene | None" = None

    def __init__(self, browser: Browser, name: str):
        self.browser, self.name = browser, name
        self.ctx: BrowserContext | None = None
        self.clip: Clip | None = None
        self.lines: list[Line] = []

    async def __aenter__(self) -> "Scene":
        self.ctx = await self.browser.new_context(
            viewport=SIZE, record_video_dir=str(RAW), record_video_size=SIZE, color_scheme="light"
        )
        await self.ctx.add_init_script(OVERLAY)
        await self.ctx.add_init_script("localStorage.setItem('hearthline.lang', 'en')")
        self.clip = Clip(await self.ctx.new_page())
        Scene.current = self
        return self

    @property
    def page(self) -> Page:
        return self.clip.page

    def clip_for(self, page: Page) -> Clip:
        return next((c for _, c in self.clip.inserts if c.page is page), self.clip)

    async def __aexit__(self, exc_type, *exc) -> None:
        Scene.current = None
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
            cut_scene(self.name, self.clip, self.lines)

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


# Voice ----------------------------------------------------------------------------------------------------------


def voice_file(words: str) -> Path:
    return VOICES / (hashlib.sha1(f"{VOICE}|{RATE}|{words}".encode()).hexdigest()[:16] + ".mp3")


async def voice(words: str) -> Path:
    """The spoken line, synthesized once and cached."""
    import edge_tts

    VOICES.mkdir(parents=True, exist_ok=True)
    path = voice_file(words)
    for attempt in range(5):  # the service now and then answers with no audio
        if path.exists():
            return path
        part = path.with_suffix(".part")
        try:
            await edge_tts.Communicate(words, VOICE, rate=RATE).save(str(part))
        except Exception as e:  # noqa: BLE001 - retried below
            print(f"voice attempt {attempt + 1} failed: {type(e).__name__}")
        if part.exists() and part.stat().st_size > 2000:
            part.replace(path)
        else:
            part.unlink(missing_ok=True)
            await asyncio.sleep(2 + attempt * 2)
    raise RuntimeError(f"No speech for: {words}")


async def say(page: Page, words: str, after: float = AFTER_LINE) -> None:
    """Show a caption and speak it: the page holds while the line is said."""
    scene = Scene.current
    clip = scene.clip_for(page)
    audio = voice_file(words)
    if not audio.exists():
        async with clip.cut():  # synthesizing isn't in the video
            await voice(words)
    length = duration(audio)
    await show_caption(page, words)
    scene.lines.append(Line(clip, clip.now(), audio))
    await page.wait_for_timeout(int((length + after) * 1000))


async def show_caption(page: Page, words: str) -> None:
    """Draw the caption, waiting out a navigation in progress (PayPal's checkout redirects as it opens)."""
    for attempt in range(4):
        try:
            await page.evaluate("(w) => window.__tourCaption && window.__tourCaption(w)", words)
            return
        except Exception as e:  # noqa: BLE001 - only a navigation is retried
            if "context was destroyed" not in str(e) or attempt == 3:
                raise
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(300)


async def quiet(page: Page) -> None:
    await show_caption(page, "")


async def click(page: Page, target, hold: float = 0.4) -> None:
    """Glide the cursor to the target, then click it, so the video shows what was pressed."""
    await target.scroll_into_view_if_needed()
    box = await target.bounding_box()
    if box:
        await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=16)
        await page.wait_for_timeout(200)
    await target.click()
    await page.wait_for_timeout(int(hold * 1000))


async def show(page: Page, target, hold: float = 0.4) -> None:
    await target.scroll_into_view_if_needed()
    await page.wait_for_timeout(int(hold * 1000))


async def glide(page: Page, target, offset: int = 70, hold: float = 0.7) -> None:
    """Scroll smoothly until the target sits near the top of the window."""
    await target.evaluate(
        f"e => window.scrollTo({{top: e.getBoundingClientRect().top + scrollY - {offset}, behavior: 'smooth'}})"
    )
    await page.wait_for_timeout(int(hold * 1000))


async def sign_in_as(scene: Scene, persona: str, path: str, ready: str) -> None:
    async with scene.clip.cut():
        await quiet(scene.page)
        await scene.page.goto(f"{WEB}/login?as={persona}&next={path}")
        await scene.page.wait_for_selector(ready, timeout=180000)
        await scene.page.wait_for_timeout(800)


async def card(scene: Scene, kicker: str, title: str, body: str, line: str) -> None:
    await scene.page.set_content(CARD.format(kicker=kicker, title=title, body=body))
    await scene.page.wait_for_timeout(500)
    await say(scene.page, line, 1.2)


async def pay_in_popup(scene: Scene, button) -> None:
    clip = await scene.popup(button)
    async with clip.cut():
        await clip.page.wait_for_load_state("domcontentloaded")
    w, h = await clip.page.evaluate("() => [innerWidth, innerHeight]")
    fit = min(1, SIZE["width"] / w, SIZE["height"] / h)  # Playwright scales a bigger window down to fit
    clip.box = (int(w * fit) // 2 * 2, int(h * fit) // 2 * 2)
    await say(clip.page, "PayPal checkout, in the sandbox.", 0.2)
    await sign_in(clip.page)
    async with clip.cut():
        await clip.page.wait_for_timeout(3000)
    await confirm(clip.page)
    scene.popup_closed(clip)


# Scenes ---------------------------------------------------------------------------------------------------------


async def hook(scene: Scene) -> None:
    page = scene.page
    async with scene.clip.cut():
        await page.goto(f"{WEB}/login")
        await page.locator("#why").wait_for(timeout=180000)
        await page.wait_for_timeout(1000)
    await say(
        page,
        "This is Hearthline: disaster recovery on PayPal, where AI agents do the legwork and people approve "
        "every dollar.",
    )
    await glide(page, page.locator("#why"), 20)
    await say(page, "It starts from real numbers. After Hurricane Milton, up to 77% of calls to FEMA went unanswered.")


async def prepare(scene: Scene) -> None:
    page = scene.page
    await sign_in_as(scene, "elena.rivera", "/inventory", ".ag-row")
    await say(
        page, "Before the fire, Elena photographed her home. The Inventory agent listed it, and Channel3 priced it."
    )
    await click(page, page.get_by_role("button", name="Value by category"), 0.7)
    await glide(page, page.get_by_role("button", name="Value by category"), 20)
    await say(page, "AG Grid pivots her inventory and charts what each room held.")


async def first72(scene: Scene) -> None:
    page = scene.page
    await sign_in_as(scene, "sam.whitfield", "/command", "#rapid-title")
    rapid = page.locator("section[aria-labelledby='rapid-title']")
    await glide(page, rapid)
    await say(page, "When an evacuation order hits, families who prepared get cash within hours.", 0.1)
    await click(page, rapid.get_by_role("button", name="Simulate an evacuation order (demo)"))
    proposal = rapid.locator("li", has_text="simulated for this demo").first
    async with scene.clip.cut():
        await proposal.wait_for(timeout=60000)
    await say(page, "Rules pick them, and the Sentinel agent holds back a suspicious claim.", 0.1)
    await click(page, proposal.get_by_role("button", name="Approve and pay"))
    async with scene.clip.cut():
        await proposal.get_by_text("Decided by").wait_for(timeout=120000)
    await glide(page, page.locator("section[aria-labelledby='map-title']"))
    await say(page, "One person approves, and a single PayPal Payouts batch pays them all.")


async def respond(scene: Scene) -> None:
    page = scene.page
    async with scene.clip.cut():
        await page.goto(f"{WEB}/r/rivera-family", wait_until="networkidle")
    await say(page, "After the fire, the Riveras list exactly what they need.", 0.1)
    item = page.locator("li", has_text="Twin bed frames")
    await click(page, item.get_by_role("button", name="Fund this"))
    async with scene.clip.cut():
        await page.wait_for_selector("paypal-button", timeout=60000)
        await page.wait_for_timeout(2500)
    await page.locator("select[name=currency]").select_option("MXN")
    async with scene.clip.cut():
        await page.wait_for_timeout(1500)
    await say(page, "Family abroad gives in pesos with PayPal, and the family receives dollars.", 0.1)
    await pay_in_popup(scene, page.locator("paypal-button"))
    async with scene.clip.cut():
        await page.wait_for_selector("text=Thank you! You gave", timeout=120000)
        await page.wait_for_timeout(800)

    await sign_in_as(scene, "elena.rivera", "/registry", "text=What the Shopper bought")
    talk = "How the Shopper and local stores agreed on a price"
    bought = page.locator("li", has_text=talk).first
    async with scene.clip.cut():
        for _ in range(36):  # the Shopper runs in the background: Channel3, the stores' agents, the rules, Payouts
            if await bought.count():
                break
            await page.wait_for_timeout(5000)
            await page.reload(wait_until="networkidle")
    await show(page, bought)
    await say(page, "Then the Shopper agent asks the town's reopened stores for a price.", 0.1)
    await click(page, bought.get_by_text(talk), 0.6)
    await say(page, "Their pricing agents negotiate over MCP, and code, not the AI, enforces the spending rules.", 0.1)
    await click(page, bought.get_by_text("Spending rules"), 1.4)


async def mandate(scene: Scene) -> None:
    page = scene.page
    await sign_in_as(scene, "marcus.chen", "/giving", "text=Give automatically after disasters")
    panel = page.locator("section", has_text="Give automatically after disasters")
    stop = panel.get_by_role("button", name="Stop and remove my saved PayPal account")
    async with scene.clip.cut():
        if await stop.count():  # a mandate from an earlier run
            await stop.click()
            await panel.get_by_role("button", name="Stop giving").click()
            await panel.get_by_role("button", name="Save my PayPal account and start").wait_for(timeout=60000)
        await glide(page, panel, 20, 0.6)
    await panel.get_by_label("Most for one gift ($)").fill("40")
    await panel.get_by_label("Most in a month ($)").fill("100")
    await panel.get_by_label("Add a state").select_option("CA")
    await panel.get_by_label("In your own words (optional)").fill("Families with young kids, and pets")
    await say(page, "Marcus sets his giving limits once, and saves his PayPal account with PayPal Vault.", 0.1)
    await click(page, panel.get_by_role("button", name="Save my PayPal account and start"))
    async with scene.clip.cut():
        await page.wait_for_url("**paypal.com/**", timeout=90000)
        await sign_in(page)
    await confirm(page)
    async with scene.clip.cut():
        await page.wait_for_url("**/giving/mandate?**", timeout=120000)
        await page.get_by_text("Your giving is set up.").wait_for(timeout=240000)
        await page.get_by_role("link", name="Back to my giving").click()
        await panel.get_by_text("Gifts made for you").wait_for(timeout=90000)
    await show(page, panel.get_by_text("Gifts made for you"))
    await say(
        page, "The giving agent gives to verified needs within his limits, with no checkout, and explains each gift."
    )


async def navigator(scene: Scene) -> None:
    page = scene.page
    await scene.ctx.add_init_script("localStorage.setItem('hearthline.lang', 'es')")  # Elena reads Spanish
    await sign_in_as(scene, "elena.rivera", "/home", "#navigator-title")
    nav = page.locator("section[aria-labelledby='navigator-title']")
    await glide(page, nav, 20, 0.3)
    await click(page, nav.get_by_role("button", name="Explícame mi plan"))
    async with scene.clip.cut():
        await nav.get_by_text("Explicado por el navegador").wait_for(timeout=180000)
    await say(page, "The recovery navigator explains Elena's next steps, with real dates, in Spanish.")


async def scam(scene: Scene) -> None:
    page = scene.page
    for persona, reason in (
        ("priya.nair", "Photos copied from the Riveras; the address is outside the fire."),
        ("tom.becker", "Agree: someone is impersonating the Rivera family."),
    ):
        await sign_in_as(scene, persona, "/review", ".ag-row")
        await click(page, page.locator(".ag-row", has_text="Rivera family fund").first)
        async with scene.clip.cut():
            await page.wait_for_selector("text=Sentinel's summary", timeout=60000)
        if persona == "priya.nair":
            await show(page, page.locator("section", has_text="Sentinel's summary").first)
            await say(
                page,
                "A scammer copies the Riveras' story. Sentinel flags copied photos and an address outside the fire, "
                "but people decide.",
                0.1,
            )
        await page.get_by_placeholder("Your reason").fill(reason)
        await click(page, page.get_by_role("button", name="Reject"), 1.0)
    async with scene.clip.cut():
        await page.goto(f"{WEB}/r/riveras-rebuild-fund", wait_until="networkidle")
    await say(page, "Two reviewers reject it, and every donor is refunded through PayPal.")


async def dispatch(scene: Scene) -> None:
    page = scene.page
    await sign_in_as(scene, "sam.whitfield", "/command/crews", "section[aria-labelledby='dispatch-title']")
    panel = page.locator("section[aria-labelledby='dispatch-title']")
    await glide(page, panel, 10, 0.3)
    await panel.get_by_label("Instructions for the dispatch agent").fill(
        "Medical needs first. Give Van 2 both Mesa Dr stops."
    )
    await say(page, "The dispatch agent plans tomorrow's crew visits on Bryntum Scheduler Pro.", 0.1)
    await click(page, panel.get_by_role("button", name="Plan tomorrow"))
    async with scene.clip.cut():
        await page.wait_for_selector(".b-sch-event.job-proposal", timeout=180000)
        await page.wait_for_timeout(3000)
        await glide(page, page.locator(".b-sch-event.job-proposal").first, 330, 0.8)
    await say(page, "Code fits every drive, and nothing moves until a person accepts.", 0.1)
    accept = panel.get_by_role("button", name="Accept", exact=True).first
    await click(page, accept, 1.2)


async def rebuild(scene: Scene) -> None:
    page = scene.page
    await sign_in_as(scene, "dana.okafor", "/contractor", ".b-gantt-task")
    gantt = page.locator(".b-gantt").first
    async with scene.clip.cut():  # open on the chart
        await glide(page, gantt, 70, 1.2)
    await say(page, "Rebuilds run on Bryntum Gantt's scheduling engine, paid from escrow step by step.", 0.1)
    await click(page, page.get_by_role("button", name="What if a step runs late?"), 0.3)
    panel = page.locator("section[aria-labelledby=what-if-title]")
    await panel.get_by_label("Step").select_option(label="4. Framing")
    await click(page, panel.get_by_role("button", name="14 days"), 0.2)
    await panel.get_by_text("Move-in moves").first.wait_for(timeout=60000)
    await glide(page, gantt, 70, 0.8)  # back up to the chart: the steps after framing have moved off their baselines
    await say(page, "If framing runs two weeks late, every step after it moves.")
    await panel.get_by_label("Why is it late?").fill("The roof trusses arrive two weeks late from the mill")
    await click(page, panel.get_by_role("button", name="Tell the Rivera household"), 0.2)
    async with scene.clip.cut():
        await panel.wait_for(state="detached", timeout=60000)
    await sign_in_as(scene, "elena.rivera", "/rebuild", ".b-gantt-task")
    await show(page, page.locator("div.bg-amber-soft", has_text="moved your move-in day"))
    await say(page, "Elena sees her new move-in day, why it moved, and which payments move.")


async def reopen(scene: Scene) -> None:
    page = scene.page
    async with scene.clip.cut():
        await page.goto(f"{WEB}/reopen/morenos-bakery", wait_until="networkidle")
        await page.wait_for_selector(".b-gantt-task", timeout=60000)
    await say(page, "The town's bakery burned too. Regulars buy gift cards now, held in escrow until it reopens.")


async def claim(scene: Scene) -> None:
    page = scene.page
    await sign_in_as(scene, "elena.rivera", "/insurance", "text=Insurance")
    upload = page.locator("text=Upload your policy")
    async with scene.clip.cut():
        await upload.or_(page.locator("text=Send your claim to")).first.wait_for(timeout=60000)
        if await upload.count():
            sample = Path(__file__).parent.parent / "frontend/public/samples/golden-poppy-homeowners-policy.pdf"
            await page.get_by_label("Policy PDF").set_input_files(sample)
            await page.get_by_role("button", name="Read my policy").click()
            await page.get_by_role("button", name="Prepare my claim").wait_for(timeout=240000)
    await say(page, "The Policy agent read Elena's policy, and her claim is built from the inventory.", 0.1)
    await click(page, page.get_by_role("button", name="Prepare my claim"))
    link_box = page.get_by_label("Send this private link to your adjuster")
    async with scene.clip.cut():
        await link_box.wait_for(timeout=90000)
    link = await link_box.input_value()
    async with scene.clip.cut():
        await page.goto(link)
        await page.wait_for_selector(".ag-row", timeout=90000)
    await page.get_by_label("Adjuster's name").fill("Dana Lee, Golden Poppy Claims")
    await say(page, "Her adjuster reviews every item with its evidence, and pays with PayPal.", 0.1)
    await pay_in_popup(scene, page.locator("paypal-button"))
    async with scene.clip.cut():
        await page.wait_for_selector("text=/^Paid \\$/", timeout=150000)
    await say(page, "The money reaches Elena's PayPal account in minutes, not weeks.")


async def command(scene: Scene) -> None:
    page = scene.page
    await sign_in_as(scene, "sam.whitfield", "/command", ".ag-row[row-index='0']")
    await glide(page, page.get_by_label("Ask the grid"), 120, 0.3)
    await page.get_by_label("Ask the grid").fill("destroyed homes on Juniper Lane that have no PayPal account yet")
    await say(page, "Staff ask AG Grid about two thousand households in plain words.", 0.1)
    await click(page, page.get_by_role("button", name="Ask", exact=True))
    async with scene.clip.cut():
        await page.wait_for_selector("text=AI set the filters", timeout=120000)
        await page.wait_for_timeout(1500)
    await page.wait_for_timeout(1200)
    await click(page, page.get_by_role("link", name="Books").first)
    async with scene.clip.cut():
        await page.get_by_text("Audit log:").first.wait_for(timeout=120000)
        await page.wait_for_timeout(2000)
    await say(page, "And every ledger entry is checked against PayPal's own records, through APIMatic's SDK.")


async def close(scene: Scene) -> None:
    await card(
        scene,
        "BUILT ON THE PAYPAL SANDBOX",
        "Help that reaches the family, not a scammer",
        "PayPal Orders, Payouts, Vault, Subscriptions, Disputes, Transaction Search and Log in with PayPal · "
        "AI agents that negotiate and give, with people in charge of the money · "
        "AG Grid · Bryntum · Channel3 · APIMatic · Render",
        "Hearthline: help that reaches the family, built on PayPal.",
    )


SCENES = [
    ("01-hook", hook),
    ("02-prepare", prepare),
    ("03-first72", first72),
    ("04-respond", respond),
    ("05-mandate", mandate),
    ("06-navigator", navigator),
    ("07-scam", scam),
    ("08-dispatch", dispatch),
    ("09-rebuild", rebuild),
    ("10-reopen", reopen),
    ("11-claim", claim),
    ("12-command", command),
    ("13-close", close),
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
    first = min(clip.cuts, default=None)
    if first and first[0] < 0.5:  # a scene that opens by signing in starts where that ends, not on the way there
        at = first[1] + shift
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


def cut_scene(name: str, main: Clip, lines: list[Line]) -> None:
    """Trim the scene's clip, splice in its PayPal windows, lay the narration in, and write e2e/video/<name>.mp4."""

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

    parts, starts, at = [], [], 0.0  # starts: where each kept piece begins in the scene's video
    kept = [p for p in pieces if p[2] - p[1] > 0.3]
    for i, (src, begin, end, box) in enumerate(kept):
        part = RAW / f"{name}-{i:02d}.mp4"
        encode(["-ss", f"{begin:.2f}", "-to", f"{end:.2f}", "-i", str(src)], part, box)
        parts.append(part)
        starts.append(at)
        at += duration(part)
    silent = RAW / f"{name}-video.mp4"
    concat(parts, silent)

    def placed(line: Line) -> float:
        """Where a line's caption appeared in the cut video."""
        t = line.at + lag(line.clip, duration(line.clip.path))
        for (src, begin, end, _), start in zip(kept, starts, strict=True):
            if src == line.clip.path and begin - 0.05 <= t < end:
                return start + max(0.0, t - begin)
        later = [
            start
            for (src, begin, _, _), start in zip(kept, starts, strict=True)
            if src == line.clip.path and begin >= t
        ]
        return min(later, default=at)

    narrate(silent, [(placed(line), line.audio) for line in lines], OUT / f"{name}.mp4")
    print(f"{name}: {len(parts)} pieces, {len(lines)} lines, {duration(OUT / f'{name}.mp4'):.1f} s")


def narrate(video: Path, lines: list[tuple[float, Path]], out: Path) -> None:
    """Put the spoken lines on the video's audio track, each at its time (silence elsewhere)."""
    inputs = ["-i", str(video)]
    if lines:
        for _, audio in lines:
            inputs += ["-i", str(audio)]
        chains = [
            f"[{i}:a]aresample=48000,adelay={int(t * 1000)}:all=1[v{i}]" for i, (t, _) in enumerate(lines, start=1)
        ]
        mixed = "".join(f"[v{i}]" for i in range(1, len(lines) + 1))
        graph = ";".join([*chains, f"{mixed}amix=inputs={len(lines)}:normalize=0:dropout_transition=0,apad[a]"])
    else:
        inputs += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono"]
        graph = "[1:a]apad[a]"
    subprocess.run(
        [
            ffmpeg(),
            "-y",
            "-loglevel",
            "error",
            *inputs,
            "-filter_complex",
            graph,
            "-map",
            "0:v",
            "-map",
            "[a]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "48000",
            "-ac",
            "1",
            "-shortest",
            str(out),
        ],
        check=True,
    )


def encode(inputs: list[str], out: Path, box: tuple[int, int] | None = None) -> None:
    """Re-encode to 1280x720 H.264. A small window (PayPal's checkout) is cropped and enlarged on the page color."""
    fit = "fps=30,scale=1280:720,setsar=1"
    if box:
        fit = (
            f"crop={box[0]}:{box[1]}:0:0,scale=1280:720:force_original_aspect_ratio=decrease,"
            "pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=0xf6f7f9,fps=30,setsar=1"
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


def join() -> None:
    """Join the scenes into hearthline-demo.mp4, re-encoding once so the audio and video line up across scenes."""
    made = [OUT / f"{n}.mp4" for n, _ in SCENES if (OUT / f"{n}.mp4").exists()]
    missing = [n for n, _ in SCENES if not (OUT / f"{n}.mp4").exists()]
    if missing:
        print("missing scenes:", ", ".join(missing))
    inputs = [arg for p in made for arg in ("-i", str(p))]
    streams = "".join(f"[{i}:v][{i}:a]" for i in range(len(made)))
    out = OUT / "hearthline-demo.mp4"
    subprocess.run(
        [
            ffmpeg(),
            "-y",
            "-loglevel",
            "error",
            *inputs,
            "-filter_complex",
            f"{streams}concat=n={len(made)}:v=1:a=1[v][a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(out),
        ],
        check=True,
    )
    print(f"hearthline-demo.mp4: {duration(out):.1f} s from {len(made)} scenes")


async def record(only: list[str]) -> list[str]:
    shutil.rmtree(RAW, ignore_errors=True)
    RAW.mkdir(parents=True)
    chosen = [(n, f) for n, f in SCENES if not only or any(o in n for o in only)]
    for name, _ in chosen:
        (OUT / f"{name}.mp4").unlink(missing_ok=True)
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
    return failed


def main(args: list[str]) -> None:
    if args == ["--join"]:
        join()
        return
    if not have_buyer():
        sys.exit("The tour pays with the sandbox buyer: set PAYPAL_SANDBOX_BUYER_EMAIL and _PASSWORD in backend/.env")
    failed = asyncio.run(record(args))
    join()
    if failed:
        sys.exit(f"Scenes that failed: {', '.join(failed)}")


if __name__ == "__main__":
    main(sys.argv[1:])
