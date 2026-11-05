"""Request limits for the hosted demo: plenty for anyone exploring it, not enough to run up the AI bill, flood the
public API or hammer sign-in.

Each limit counts per client (by IP) and in total, so even a client that somehow varies its address meets the total.
The counts live in memory on the one API instance and a restart forgets them: a guard rail against floods and
runaway cost, not a defence against a determined attacker (see SECURITY.md).
"""

import re
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from math import ceil

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


@dataclass(frozen=True)
class Limit:
    name: str
    matches: re.Pattern  # against "METHOD /path"
    per_client: int
    total: int
    window: int  # seconds


LIMITS = (
    # Every request here calls the AI (or Channel3), which costs money per call
    Limit(
        "ai",
        re.compile(
            r"POST .*/(ask|explain|draft|scans|policy|shop|campaign|refresh)"
            r"|POST /command/dispatch/plan|POST /households/me/cases"
            r"|GET /donors/me/giving/note|GET /command/reports/grant(\.pdf)?"
        ),
        per_client=40,
        total=600,
        window=600,
    ),
    Limit("sign_in", re.compile(r"POST /auth/.*"), per_client=60, total=1500, window=600),
    Limit("public_api", re.compile(r"[A-Z]+ /(v1|mcp)(/.*)?"), per_client=300, total=6000, window=600),
)


# Render runs every service behind Cloudflare, which overwrites CF-Connecting-IP with the caller's address, so a
# client can't fake it. X-Forwarded-For is only appended to, so its first entry is whatever the client sent.
CLIENT_HEADERS = (b"cf-connecting-ip", b"true-client-ip", b"x-forwarded-for")


def client_ip(scope: Scope) -> str:
    headers = dict(scope.get("headers", []))
    for name in CLIENT_HEADERS:
        if value := headers.get(name):
            return value.decode("latin-1").split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else "unknown"


class Counter:
    """Sliding windows of request times, one per key."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.hits: dict[str, deque[float]] = {}

    def _recent(self, key: str, window: int, now: float) -> deque[float]:
        q = self.hits.setdefault(key, deque())
        while q and q[0] <= now - window:
            q.popleft()
        return q

    def take(self, limit: Limit, client: str) -> int | None:
        """Count one request; None if it may go ahead, else the seconds until it may."""
        now = self.clock()
        if len(self.hits) > 50_000:  # forget clients that have gone quiet
            self.hits = {k: q for k, q in self.hits.items() if q and q[-1] > now - limit.window}
        mine = self._recent(f"{limit.name}:{client}", limit.window, now)
        everyone = self._recent(limit.name, limit.window, now)
        for q, most in ((mine, limit.per_client), (everyone, limit.total)):
            if len(q) >= most:
                return max(1, ceil(q[0] + limit.window - now))
        mine.append(now)
        everyone.append(now)
        return None


class RateLimit:
    """ASGI middleware, so streamed responses (the MCP server's) pass through untouched."""

    def __init__(self, app: ASGIApp, limits: tuple[Limit, ...] = LIMITS, counter: Counter | None = None) -> None:
        self.app = app
        self.limits = limits
        self.counter = counter or Counter()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            request = f"{scope['method']} {scope['path']}"
            limit = next((lim for lim in self.limits if lim.matches.fullmatch(request)), None)
            wait = limit and self.counter.take(limit, client_ip(scope))
            if wait:
                response = JSONResponse(
                    {"detail": f"Too many requests. Try again in {wait} seconds."},
                    status_code=429,
                    headers={"Retry-After": str(wait)},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
