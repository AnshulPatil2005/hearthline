import re

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.rate_limit import LIMITS, Counter, Limit, RateLimit, client_ip


class Clock:
    now = 1000.0

    def __call__(self) -> float:
        return self.now


def make_client(clock: Clock) -> TestClient:
    ok = Route("/{path:path}", lambda request: PlainTextResponse("ok"), methods=["GET", "POST"])
    limits = (Limit("ai", re.compile(r"POST /ask"), per_client=2, total=3, window=60),)
    return TestClient(RateLimit(Starlette(routes=[ok]), limits, Counter(clock)))


def post(client: TestClient, ip: str):
    return client.post("/ask", headers={"X-Forwarded-For": f"{ip}, 10.0.0.1"})


def test_each_client_gets_its_share_then_waits():
    clock = Clock()
    client = make_client(clock)
    assert [post(client, "1.1.1.1").status_code for _ in range(3)] == [200, 200, 429]
    r = post(client, "1.1.1.1")
    assert r.headers["Retry-After"] == "60" and "Too many requests" in r.json()["detail"]
    assert client.get("/ask").status_code == 200  # only the limited method and path count
    clock.now += 61  # the window slides on
    assert post(client, "1.1.1.1").status_code == 200


def test_a_client_faking_new_addresses_still_meets_the_total():
    client = make_client(Clock())
    codes = [post(client, f"9.9.9.{i}").status_code for i in range(5)]
    assert codes == [200, 200, 200, 429, 429]


def test_the_limits_cover_the_ai_calls_but_not_ordinary_page_loads():
    def limit_for(request: str) -> str | None:
        return next((lim.name for lim in LIMITS if lim.matches.fullmatch(request)), None)

    assert limit_for("POST /households/me/navigator/explain") == "ai"
    assert limit_for("POST /command/dispatch/plan") == "ai"
    assert limit_for("GET /command/reports/grant.pdf") == "ai"
    assert limit_for("POST /auth/demo-login") == "sign_in"
    assert limit_for("GET /v1/registries") == "public_api" and limit_for("POST /mcp") == "public_api"
    assert limit_for("GET /households/me/policy") is None
    assert limit_for("GET /command/dispatch/plan") is None
    assert limit_for("GET /health") is None


def test_the_client_is_who_cloudflare_says():
    """On Render, Cloudflare's CF-Connecting-IP can't be faked; a client-sent X-Forwarded-For can."""
    spoofed = [(b"x-forwarded-for", b"6.6.6.6, 172.71.0.1"), (b"cf-connecting-ip", b"1.2.3.4")]
    assert client_ip({"headers": spoofed, "client": ("10.0.0.9", 1)}) == "1.2.3.4"
    assert client_ip({"headers": spoofed[:1], "client": ("10.0.0.9", 1)}) == "6.6.6.6"  # off Render
    assert client_ip({"headers": [], "client": ("10.0.0.9", 1)}) == "10.0.0.9"
