"""Check the hosted demo the way a judge would use it, and optionally put it back to the start first.

Run daily by .github/workflows/live-check.yml until judging ends. Standard library only. Exits 1 when something a
judge would hit is broken (GitHub then emails the repository owner) and prints a table to the job summary.

    python .github/scripts/live_check.py            # check only
    RESET=1 python .github/scripts/live_check.py    # reset the demo, wait for it, then check
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime

API = os.environ.get("API_URL", "https://hearthline-api.onrender.com").rstrip("/")
WEB = os.environ.get("WEB_URL", "https://hearthline-web.onrender.com").rstrip("/")
RESET = os.environ.get("RESET") == "1"
LOW_BALANCE = 7_000  # one first-72-hours aid run pays $6,800 in the sandbox
WARN_BALANCE = 15_000
LICENSE_WARN_DAYS = 7

results: list[tuple[str, str, str]] = []  # (status, check, detail); status is ok | warn | fail


class Fail(Exception):
    pass


class Warn(Exception):
    pass


def request(method: str, url: str, body: dict | None = None, token: str | None = None, timeout: int = 90):
    headers = {"Accept": "application/json, text/event-stream", "User-Agent": "hearthline-live-check"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def api(method: str, path: str, body: dict | None = None, token: str | None = None, expect: int = 200):
    status, raw = request(method, API + path, body, token)
    if status != expect:
        raise Fail(f"{method} {path} answered {status}: {raw[:160].decode(errors='replace')}")
    return json.loads(raw) if raw else None


def check(name: str) -> Callable[[Callable[[], str]], Callable[[], str]]:
    def wrap(fn: Callable[[], str]) -> Callable[[], str]:
        def run() -> str:
            try:
                detail = fn()
                results.append(("ok", name, detail))
            except Warn as e:
                results.append(("warn", name, str(e)))
            except Exception as e:  # any surprise counts as broken
                results.append(("fail", name, f"{type(e).__name__}: {e}" if not isinstance(e, Fail) else str(e)))
            return name

        return run

    return wrap


def wake() -> float:
    """The free plan sleeps after 15 idle minutes; the first request can take about a minute."""
    started = time.monotonic()
    deadline = started + 300
    while time.monotonic() < deadline:
        try:
            status, _ = request("GET", API + "/health", timeout=60)
            if status == 200:
                return time.monotonic() - started
        except OSError:
            pass
        time.sleep(5)
    raise Fail("the API didn't answer for 5 minutes")


tokens: dict[str, str] = {}


def sign_in(prefix: str) -> str:
    if prefix not in tokens:
        personas = api("GET", "/auth/personas")
        persona = next(p for p in personas if p["email"].startswith(prefix + "@"))
        tokens[prefix] = api("POST", "/auth/demo-login", {"user_id": persona["id"]})["token"]
    return tokens[prefix]


@check("API health")
def health() -> str:
    body = api("GET", "/health")
    down = [k for k, ok in body["integrations"].items() if not ok]
    if body["status"] != "ok" or down:
        raise Fail(f"status {body['status']}, not working: {', '.join(down) or 'none'}")
    return f"{body['environment']}; database, AI, Channel3 and PayPal configured"


@check("Demo reset")
def reset() -> str:
    status, raw = request("POST", API + "/demo/reset")
    if status == 429:
        return "skipped: reset less than ten minutes ago"
    if status != 202:
        raise Fail(f"POST /demo/reset answered {status}: {raw[:160]!r}")
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        time.sleep(10)
        state = api("GET", "/demo/reset")
        if not state.get("running"):
            if state.get("error"):
                raise Fail(f"reset failed: {state['error']}")
            return "the demo is back at the start"
    raise Fail("the reset didn't finish in 5 minutes")


@check("Sign-in and personas")
def personas() -> str:
    people = api("GET", "/auth/personas")
    if len(people) < 8:
        raise Fail(f"only {len(people)} demo personas")
    for prefix in ("elena.rivera", "sam.whitfield", "marcus.chen", "priya.nair", "dana.okafor"):
        sign_in(prefix)
    return f"{len(people)} personas; five of them signed in"


@check("Household: inventory and rebuild Gantt")
def household() -> str:
    elena = sign_in("elena.rivera")
    home = api("GET", "/households/me", token=elena)
    if not home["in_disaster_zone"]:
        raise Fail("the Riveras are no longer inside the fire zone")
    items = api("GET", "/households/me/items", token=elena)
    if len(items) < 10:
        raise Fail(f"only {len(items)} inventory items")
    projects = api("GET", "/households/me/projects", token=elena)
    if not projects:
        raise Fail("no rebuild project")
    gantt = api("GET", f"/bryntum/gantt/{projects[0]['id']}/load", token=elena)
    def count(rows: list[dict]) -> int:  # the steps sit under the project's task
        return sum(1 + count(r.get("children") or []) for r in rows)

    tasks = count(gantt.get("tasks", {}).get("rows", []))
    if tasks < 3:
        raise Fail(f"the Gantt loaded {tasks} tasks")
    return f"{len(items)} items; Gantt with {tasks} tasks"


@check("Public pages, Public API and MCP")
def public() -> str:
    registry = api("GET", "/registries/rivera-family")
    if registry["status"] != "active":
        raise Fail(f"the Riveras' registry is {registry['status']}")
    slugs = [r["slug"] for r in api("GET", "/v1/registries")]
    if "rivera-family" not in slugs:
        raise Fail(f"/v1/registries lists {slugs}")
    prices = api("GET", "/price-watch")
    status, raw = request("POST", API + "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    text = raw.decode(errors="replace")
    payload = text[text.find("{") :] if "{" in text else "{}"
    tools = json.loads(payload.split("\n")[0]).get("result", {}).get("tools", []) if status == 200 else []
    if len(tools) < 7:
        raise Fail(f"the MCP server answered {status} with {len(tools)} tools")
    return f"registry active; {len(slugs)} on /v1; {len(prices['rows'])} prices on Price Watch; {len(tools)} MCP tools"


@check("Command Center, Books and crews")
def staff() -> str:
    sam = sign_in("sam.whitfield")
    block = api(
        "POST",
        "/command/households/rows",
        {"startRow": 0, "endRow": 5, "rowGroupCols": [], "groupKeys": [], "valueCols": [], "sortModel": []},
        token=sam,
    )
    rows = block.get("rows") or []
    if not rows:
        raise Fail("the server-side row model returned no households")
    chain = api("GET", "/command/books/audit", token=sam)
    if not chain["intact"]:
        raise Fail(f"the audit chain is broken at event {chain['first_broken_id']}")
    crews = api("GET", "/bryntum/crews/load", token=sam)
    if not crews.get("resources", {}).get("rows"):
        raise Fail("Scheduler Pro loaded no crews")
    return f"{block['lastRow']:,} households; audit chain intact ({chain['events']} events); crews loaded"


@check("PayPal sandbox balance")
def balance() -> str:
    body = api("GET", "/command/books/balance", token=sign_in("sam.whitfield"))
    available = float(body["available"])
    if available < LOW_BALANCE:
        raise Fail(f"${available:,.2f} available: payouts will fail; top up the sandbox merchant account")
    if available < WARN_BALANCE:
        raise Warn(f"${available:,.2f} available: top up soon")
    return f"${available:,.2f} available"


@check("Reviewer: Calendar and TaskBoard")
def reviewer() -> str:
    priya = sign_in("priya.nair")
    api("GET", "/bryntum/calendar/load", token=priya)
    board = api("GET", "/bryntum/board/load", token=priya)
    return f"both loaded; {len(board.get('tasks', {}).get('rows', []))} cases on the board"


@check("Web app and AG Grid license")
def web() -> str:
    status, raw = request("GET", WEB + "/features")
    page = raw.decode(errors="replace")
    if status != 200 or '<div id="root"' not in page:
        raise Fail(f"{WEB}/features answered {status}")
    entry = re.search(r"assets/index-[\w-]+\.js", page)
    if not entry:
        raise Fail("no app script on the page")
    _, main = request("GET", f"{WEB}/{entry.group(0)}")
    chunks = sorted(set(re.findall(r"grid-[\w-]+\.js", main.decode(errors="replace"))))
    for chunk in chunks:
        _, js = request("GET", f"{WEB}/assets/{chunk}")
        found = re.search(r"deactivate_on_\{(\d{1,2} \w+ \d{4})\}", js.decode(errors="replace"))
        if found:
            ends = datetime.strptime(found.group(1), "%d %B %Y").replace(tzinfo=UTC)
            days = (ends - datetime.now(UTC)).days
            if days < 0:
                raise Fail(f"the AG Grid key deactivated on {found.group(1)}: grids show a watermark")
            if days < LICENSE_WARN_DAYS:
                raise Fail(f"the AG Grid key deactivates on {found.group(1)} ({days} days): set the new trial key")
            return f"app loads; AG Grid key good until {found.group(1)} ({days} days)"
    raise Warn("app loads, but no AG Grid license key was found in the build")


def main() -> int:
    started = datetime.now(UTC)
    try:
        woke = wake()
        results.append(("ok", "Wake the API", f"answered after {woke:.0f} s"))
        steps = [reset] if RESET else []
        for step in [*steps, health, personas, household, public, staff, balance, reviewer, web]:
            step()
    except Fail as e:
        results.append(("fail", "Wake the API", str(e)))

    icon = {"ok": "✅", "warn": "⚠️", "fail": "❌"}
    lines = [
        f"### Hearthline live check, {started:%Y-%m-%d %H:%M} UTC",
        "",
        "| | Check | Result |",
        "|---|---|---|",
        *(f"| {icon[s]} | {name} | {detail.replace('|', '/')} |" for s, name, detail in results),
    ]
    report = "\n".join(lines)
    print(report)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as f:
            f.write(report + "\n")
    return 1 if any(s == "fail" for s, _, _ in results) else 0


if __name__ == "__main__":
    sys.exit(main())
