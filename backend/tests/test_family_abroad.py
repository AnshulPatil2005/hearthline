"""Family abroad: a gift in the giver's own currency through PayPal, estimated in dollars before checkout and recorded
at PayPal's own rate after it (capture shapes from the sandbox spike, Oct 24 2026)."""

from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from app import fx, ledger, reconcile
from app.db import SessionLocal
from app.models import Donation, RegistryItem
from app.paypal import orders
from app.paypal.orders import in_dollars, parse_capture
from tests.helpers import client, login_as

SLUG = "rivera-family"
RATES = fx.Rates(
    {"MXN": D("18.80"), "PHP": D("63.60"), "EUR": D("0.90"), "CAD": D("1.40"), "GBP": D("0.75")}, "2026-10-23", "ecb"
)


def mxn_capture(order_id: str, capture_id: str, value: str = "5000.00") -> dict:
    """An order PayPal captured in pesos, converted to dollars by the merchant account (as the sandbox did)."""
    gross = D(value)
    fee = (gross * D("0.1249")).quantize(D("0.01"))
    rate = D("0.051687422038138")
    return {
        "id": order_id,
        "payment_source": {"paypal": {}},
        "purchase_units": [
            {
                "payments": {
                    "captures": [
                        {
                            "id": capture_id,
                            "status": "COMPLETED",
                            "amount": {"currency_code": "MXN", "value": f"{gross:.2f}"},
                            "seller_receivable_breakdown": {
                                "gross_amount": {"currency_code": "MXN", "value": f"{gross:.2f}"},
                                "paypal_fee": {"currency_code": "MXN", "value": f"{fee:.2f}"},
                                "net_amount": {"currency_code": "MXN", "value": f"{gross - fee:.2f}"},
                                "receivable_amount": {
                                    "currency_code": "USD",
                                    "value": f"{((gross - fee) * rate).quantize(D('0.01'))}",
                                },
                                "exchange_rate": {
                                    "source_currency": "MXN",
                                    "target_currency": "USD",
                                    "value": str(rate),
                                },
                            },
                        }
                    ]
                }
            }
        ],
    }


@pytest.fixture
def paypal(monkeypatch):
    monkeypatch.setattr(fx, "rates", lambda: RATES)
    created = []

    def create_order(**kwargs):
        created.append(kwargs)
        return f"ORDER-{len(created)}"

    def capture_order(order_id):
        n = order_id.split("-")[1]
        return parse_capture(mxn_capture(order_id, f"CAP-MX-{n}", f"{created[int(n) - 1]['amount']:.2f}"))

    monkeypatch.setattr(orders, "create_order", create_order)
    monkeypatch.setattr(orders, "capture_order", capture_order)
    return created


def test_paypals_conversion_becomes_dollars_that_match_what_it_holds():
    capture = mxn_capture("O-1", "C-1", "100.00")["purchase_units"][0]["payments"]["captures"][0]
    gross, fee, currency, original, rate = in_dollars(capture)
    assert (gross, fee, currency, original) == (D("5.17"), D("0.65"), "MXN", D("100.00"))
    assert gross - fee == D("4.52")  # exactly what PayPal says the merchant receives
    usd = {
        "amount": {"currency_code": "USD", "value": "25.00"},
        "seller_receivable_breakdown": {"paypal_fee": {"value": "1.03"}},
    }
    assert in_dollars(usd) == (D("25.00"), D("1.03"), "USD", None, None)


def test_a_gift_in_pesos_funds_the_item_in_dollars(paypal):
    login_as("Elena Rivera")
    reg = client.get(f"/registries/{SLUG}").json()
    mattresses = next(i for i in reg["items"] if i["name"] == "Twin mattresses")  # $498
    assert client.get("/fx").json()["per_usd"]["MXN"] == "18.80"

    pesos = fx.giver_pays(D("498"), "MXN")
    assert pesos == D("9644")  # 498 x 18.80 x 1.03, rounded up
    bad = {"item_id": mattresses["id"], "amount": str(pesos), "currency": "MXN"}
    assert client.post(f"/registries/{SLUG}/donations", json={**bad, "payment_method": "venmo"}).status_code == 422
    assert client.post(f"/registries/{SLUG}/donations", json={**bad, "currency": "JPY"}).status_code == 422
    too_much = {**bad, "amount": str(pesos * 2)}
    assert client.post(f"/registries/{SLUG}/donations", json=too_much).status_code == 422

    started = client.post(f"/registries/{SLUG}/donations", json={**bad, "donor_name": "Tía Carmen"})
    assert started.status_code == 201, started.text
    assert (paypal[0]["currency"], paypal[0]["amount"]) == ("MXN", pesos)  # PayPal charges the giver in pesos
    donation_id = started.json()["donation_id"]
    with SessionLocal() as db:
        estimate = db.get(Donation, donation_id).amount
        assert estimate == D("498.04")  # what we expect PayPal's conversion to give (pesos were rounded up)

    item = client.post(f"/donations/{donation_id}/capture").json()
    with SessionLocal() as db:
        d = db.get(Donation, donation_id)
        assert (d.currency, d.currency_amount, d.exchange_rate) == ("MXN", pesos, D("0.051687422038"))
        assert d.amount == (pesos * D("0.051687422038138")).quantize(D("0.01")) == D("498.47")
        assert db.get(RegistryItem, mattresses["id"]).funded_amount == d.amount
        home_id = db.get(RegistryItem, mattresses["id"]).rebuild_registry.household_id
        assert ledger.household_available(db, home_id) >= d.amount  # the family's fund is credited in dollars
        books = reconcile.expected(db, datetime(2026, 1, 1, tzinfo=UTC))
        expected = next(e for e in books if e.key == d.paypal_capture_id)
        assert (expected.amount, expected.currency) == (pesos, "MXN")  # PayPal reports it in pesos
    assert item["status"] == "funded"


@pytest.mark.parametrize(("worse_by", "funded"), [(D("0.995"), True), (D("0.95"), False)])
def test_a_gift_for_the_rest_from_abroad_funds_the_item_when_paypals_rate_was_a_little_worse(
    paypal, monkeypatch, worse_by, funded
):
    """The sandbox once converted pesos at a rate 3.5% worse than the ECB's: "the rest" left a bed frame $1.24 short
    and the Shopper never bought it. Within 2% the item is funded; further off it stays open for the rest."""
    login_as("Elena Rivera")
    reg = client.get(f"/registries/{SLUG}").json()
    frames = next(i for i in reg["items"] if i["name"] == "Twin bed frames")
    pesos = fx.giver_pays(D(frames["remaining"]), "MXN")
    started = client.post(
        f"/registries/{SLUG}/donations", json={"item_id": frames["id"], "amount": str(pesos), "currency": "MXN"}
    ).json()

    def worse_rate(order_id):
        capture = mxn_capture(order_id, "CAP-MX-WORSE", f"{pesos:.2f}")
        breakdown = capture["purchase_units"][0]["payments"]["captures"][0]["seller_receivable_breakdown"]
        rate = D(breakdown["exchange_rate"]["value"]) * D(frames["remaining"]) / (pesos * D("0.051687422038138"))
        breakdown["exchange_rate"]["value"] = str(rate * worse_by)
        net = D(breakdown["net_amount"]["value"])
        breakdown["receivable_amount"]["value"] = f"{(net * rate * worse_by).quantize(D('0.01'))}"
        return parse_capture(capture)

    monkeypatch.setattr(orders, "capture_order", worse_rate)
    item = client.post(f"/donations/{started['donation_id']}/capture").json()
    assert D(item["funded_amount"]) < D(frames["target_amount"])  # short of the target either way
    assert (item["status"] == "funded") is funded
