"""Signing in and paying on PayPal's sandbox pages, shared by the e2e checks that use the sandbox buyer account
(PAYPAL_SANDBOX_BUYER_EMAIL / PAYPAL_SANDBOX_BUYER_PASSWORD in backend/.env)."""

import re
from pathlib import Path

from dotenv import dotenv_values
from playwright.async_api import Page

ENV = dotenv_values(Path(__file__).parent.parent / "backend" / ".env")
BUYER_EMAIL = ENV.get("PAYPAL_SANDBOX_BUYER_EMAIL")
BUYER_PASSWORD = ENV.get("PAYPAL_SANDBOX_BUYER_PASSWORD")
RETURN_URL = ENV.get("PAYPAL_CONNECT_RETURN_URL")

# The button that confirms on PayPal's review or consent page (wording differs by flow).
CONFIRM = re.compile(r"^(Pay|Pay Now|Complete Purchase|Agree & Pay|Agree and Continue|Agree & Continue|Continue)$")


def have_buyer() -> bool:
    return bool(BUYER_EMAIL and BUYER_PASSWORD)


async def sign_in(page: Page) -> None:
    """Email, Next, then the visible password field (a hidden copy exists), then Log In."""
    email = page.locator("#email:visible, input[type=email]:visible").first
    await email.wait_for(timeout=60000)
    await email.fill(BUYER_EMAIL)
    await page.locator("button:visible", has_text="Next").first.click()
    password = page.locator("input[type=password]:visible").first
    await password.wait_for(timeout=60000)
    await password.click()
    await password.press_sequentially(BUYER_PASSWORD, delay=40)
    await page.locator("button:visible", has_text="Log In").first.click()


async def confirm(page: Page, timeout: int = 90000) -> str:
    """Press the review page's confirm button; returns its label."""
    button = page.get_by_role("button", name=CONFIRM).first
    await button.wait_for(timeout=timeout)
    await page.wait_for_timeout(1500)  # the page settles its funding choice first
    label = (await button.inner_text()).strip()
    await button.click()
    return label
