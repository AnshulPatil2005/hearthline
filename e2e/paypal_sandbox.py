"""Signing in and paying on PayPal's sandbox pages, shared by the e2e checks that use the sandbox buyer account
(PAYPAL_SANDBOX_BUYER_EMAIL / PAYPAL_SANDBOX_BUYER_PASSWORD in backend/.env)."""

import re
from pathlib import Path

from dotenv import dotenv_values
from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeout

ENV = dotenv_values(Path(__file__).parent.parent / "backend" / ".env")
BUYER_EMAIL = ENV.get("PAYPAL_SANDBOX_BUYER_EMAIL")
BUYER_PASSWORD = ENV.get("PAYPAL_SANDBOX_BUYER_PASSWORD")
RETURN_URL = ENV.get("PAYPAL_CONNECT_RETURN_URL")

# The button that confirms on PayPal's review or consent page (wording differs by flow).
CONFIRM = re.compile(
    r"^(Pay|Pay Now|Complete Purchase|Agree & Pay|Agree and Continue|Agree & Continue|Agree and Connect|Save and Continue|Agree & Subscribe|Agree and Subscribe|Subscribe|Continue)$"
)
# The sandbox's page for a bad moment on its side (the apostrophe is a curly one)
TROUBLE = re.compile(r"Things don.t appear to be working")


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


async def confirm(page: Page, timeout: int = 90000, retries: int = 2) -> str:
    """Press the review page's confirm button; returns its label. The sandbox sometimes shows "Things don't appear to
    be working at the moment" instead: press its "Try again" (signing in again if it asks)."""
    button = page.get_by_role("button", name=CONFIRM).first
    trouble = page.get_by_text(TROUBLE)
    email = page.locator("#email:visible, input[type=email]:visible").first
    for _ in range(retries):
        await button.or_(trouble).first.wait_for(timeout=timeout)
        if await button.is_visible():
            break
        await page.get_by_role("button", name="Try again").click()
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2000)
        if await email.is_visible():  # it may ask to sign in again
            await sign_in(page)
    await button.wait_for(timeout=timeout)
    await page.wait_for_timeout(1500)  # the page settles its funding choice first
    label = (await button.inner_text()).strip()
    await button.click()
    return label


async def open_checkout(page: Page, button: Locator) -> Page:
    """Click a PayPal button and return PayPal's popup. Headless Chromium sometimes loses the first window; PayPal then
    shows "Click to Continue" over the page, which opens it again."""
    try:
        async with page.context.expect_page(timeout=15000) as popup:
            await button.click()
    except PlaywrightTimeout:
        async with page.context.expect_page(timeout=20000) as popup:
            await page.get_by_text("Click to Continue").click()
    checkout = await popup.value
    await checkout.wait_for_load_state("domcontentloaded")
    return checkout
