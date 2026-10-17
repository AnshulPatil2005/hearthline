"""Log in with PayPal (OpenID Connect): a person signs in at PayPal and we learn which PayPal account is theirs.

We use it once, to connect the account that receives their money; we don't keep PayPal's tokens.
"""

import asyncio
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.paypal.rest import BASE_URLS, PayPalError

AUTHORIZE_URLS = {
    "sandbox": "https://www.sandbox.paypal.com/signin/authorize",
    "live": "https://www.paypal.com/signin/authorize",
}
# Name, email, and PayPal's account attributes (payer id, whether PayPal has verified the account).
SCOPES = "openid profile email https://uri.paypal.com/services/paypalattributes"


@dataclass
class PayPalPerson:
    payer_id: str
    email: str | None
    name: str
    verified: bool


def authorize_url(state: str, redirect_uri: str) -> str:
    s = get_settings()
    query = {
        "flowEntry": "static",
        "client_id": s.paypal_client_id,
        "response_type": "code",
        "scope": SCOPES,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{AUTHORIZE_URLS[s.paypal_environment]}?{urlencode(query)}"


def person_from(info: dict) -> PayPalPerson:
    emails = info.get("emails") or []
    primary = next((e for e in emails if e.get("primary")), emails[0] if emails else {})
    return PayPalPerson(
        payer_id=info.get("payer_id") or info.get("user_id", "").rsplit("/", 1)[-1],
        email=primary.get("value") or info.get("email"),
        name=info.get("name") or " ".join(x for x in (info.get("given_name"), info.get("family_name")) if x),
        verified=str(info.get("verified_account", "false")).lower() == "true",
    )


async def _exchange(code: str) -> PayPalPerson:
    s = get_settings()
    async with httpx.AsyncClient(base_url=BASE_URLS[s.paypal_environment], timeout=30) as http:
        token = await http.post(
            "/v1/oauth2/token",
            data={"grant_type": "authorization_code", "code": code},
            auth=(s.paypal_client_id, s.paypal_client_secret),
        )
        if token.is_error:
            raise PayPalError(token.status_code, token.json() if token.content else None)
        info = await http.get(
            "/v1/identity/oauth2/userinfo",
            params={"schema": "paypalv1.1"},
            headers={"Authorization": f"Bearer {token.json()['access_token']}"},
        )
        if info.is_error:
            raise PayPalError(info.status_code, info.json() if info.content else None)
    return person_from(info.json())


def exchange(code: str) -> PayPalPerson:
    """Trade the one-time code from PayPal's redirect for the person's PayPal identity."""
    return asyncio.run(_exchange(code))
