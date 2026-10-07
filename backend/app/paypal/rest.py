"""Minimal async PayPal REST client.

Used for the APIs the official Server SDK doesn't cover (Payouts, Disputes, webhook
verification) and for the PayPal MCP server's bearer token.
"""

import time
import uuid
from typing import Any

import httpx

from app.config import get_settings

BASE_URLS = {
    "sandbox": "https://api-m.sandbox.paypal.com",
    "live": "https://api-m.paypal.com",
}
# PayPal's remote MCP server speaks the SSE transport; the documented /http endpoint returns 404.
MCP_URLS = {
    "sandbox": "https://mcp.sandbox.paypal.com/sse",
    "live": "https://mcp.paypal.com/sse",
}


class PayPalError(RuntimeError):
    def __init__(self, status: int, body: Any):
        super().__init__(f"PayPal API error {status}: {body}")
        self.status = status
        self.body = body


class PayPalREST:
    def __init__(self, client_id: str, client_secret: str, environment: str = "sandbox"):
        self.base_url = BASE_URLS[environment]
        self.mcp_url = MCP_URLS[environment]
        self._auth = (client_id, client_secret)
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=30)

    @classmethod
    def from_settings(cls) -> "PayPalREST":
        s = get_settings()
        if not s.paypal_configured:
            raise RuntimeError("Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in backend/.env")
        return cls(s.paypal_client_id, s.paypal_client_secret, s.paypal_environment)

    async def access_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        r = await self._http.post("/v1/oauth2/token", data={"grant_type": "client_credentials"}, auth=self._auth)
        if r.is_error:
            raise PayPalError(r.status_code, r.text)
        data = r.json()
        self._token = data["access_token"]
        self._token_expires_at = time.time() + data["expires_in"]
        return self._token

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        headers = {"Authorization": f"Bearer {await self.access_token()}"}
        if method.upper() == "POST":
            headers["PayPal-Request-Id"] = idempotency_key or str(uuid.uuid4())
        r = await self._http.request(method, path, json=json, params=params, headers=headers)
        if r.is_error:
            raise PayPalError(r.status_code, r.json() if r.content else None)
        return r.json() if r.content else None

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "PayPalREST":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()
