import io
from decimal import Decimal

import pytest
from PIL import Image

from app.agents import inventory, valuation
from app.agents.inventory import DetectedItem, RoomInventory
from app.agents.valuation import Valuation
from tests.helpers import client, login_as


def jpeg(color: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def fake_agents(monkeypatch):
    def detect(jpegs, room_name):
        assert len(jpegs) == 2
        return RoomInventory(
            room_type=room_name,
            items=[
                DetectedItem(
                    name="Grey sofa",
                    category="furniture",
                    quantity=1,
                    brand=None,
                    condition="good",
                    search_query="grey sofa",
                    confidence=0.9,
                    photo_index=1,
                ),
                DetectedItem(
                    name="Table lamp",
                    category="lighting",
                    quantity=2,
                    brand=None,
                    condition="good",
                    search_query="table lamp",
                    confidence=0.8,
                    photo_index=0,
                ),
                DetectedItem(
                    name="Mystery object",
                    category="other",
                    quantity=1,
                    brand=None,
                    condition="unknown",
                    search_query="???",
                    confidence=0.3,
                    photo_index=0,
                ),
            ],
        )

    def value(queries):
        table = {
            "grey sofa": Valuation(
                Decimal("900.00"), Decimal("600.00"), Decimal("1200.00"), "p1", "Sofa", "https://x/p1", "shop.com", 3
            ),
            "table lamp": Valuation(
                Decimal("50.00"), Decimal("40.00"), Decimal("60.00"), "p2", "Lamp", "https://x/p2", "shop.com", 2
            ),
        }
        return [table.get(q) for q in queries]

    monkeypatch.setattr(inventory, "detect_items", detect)
    monkeypatch.setattr(valuation, "value_items", value)


def test_scan_to_priced_inventory(fake_agents):
    h = login_as("Elena Rivera")
    room = client.post("/households/me/rooms", headers=h, json={"name": "Living room"}).json()
    files = [("files", ("a.jpg", jpeg("red"), "image/jpeg")), ("files", ("b.jpg", jpeg("blue"), "image/jpeg"))]
    scan = client.post(f"/households/me/rooms/{room['id']}/scans", headers=h, files=files)
    assert scan.status_code == 202

    done = client.get(f"/scans/{scan.json()['id']}", headers=h).json()  # background task already ran
    assert done["status"] == "done", done
    assert (done["photo_count"], done["item_count"]) == (2, 3)

    items = {i["name"]: i for i in client.get("/households/me/items", headers=h).json()}
    sofa = items["Grey sofa"]
    assert sofa["unit_price"] == "900.00" and sofa["price_low"] == "600.00" and sofa["room_name"] == "Living room"
    assert sofa["evidence_level"] == "photo"  # the Riveras are already inside the fire zone
    assert items["Table lamp"]["total_value"] == "100.00"
    assert items["Mystery object"]["unit_price"] is None

    photo = client.get(sofa["photo_url"])
    assert photo.status_code == 200 and photo.headers["content-type"] == "image/jpeg"

    summary = client.get("/households/me/inventory-summary", headers=h).json()
    assert summary["total_value"] == "1000.00"
    assert summary["unpriced_count"] == 1
    assert summary["coverage_gap"] == "0.00"  # $80k policy covers $1k of contents


def test_edit_confirm_delete_and_manual_items():
    h = login_as("Elena Rivera")
    item = client.post("/households/me/items", headers=h, json={"name": "Wedding album", "unit_price": "250"}).json()
    assert item["evidence_level"] == "memory" and item["price_source"] == "user"

    patched = client.patch(f"/items/{item['id']}", headers=h, json={"quantity": 2, "unit_price": "300.5"}).json()
    assert patched["total_value"] == "601.00"

    client.patch("/households/me", headers=h, json={"insured_contents_value": "500"})
    assert client.get("/households/me/inventory-summary", headers=h).json()["coverage_gap"] == "101.00"

    assert client.delete(f"/items/{item['id']}", headers=h).status_code == 204
    assert client.get("/households/me/items", headers=h).json() == []


def test_other_users_cannot_touch_items():
    h = login_as("Elena Rivera")
    item = client.post("/households/me/items", headers=h, json={"name": "Bike"}).json()
    donor = login_as("Marcus Chen")
    assert client.patch(f"/items/{item['id']}", headers=donor, json={"quantity": 9}).status_code == 404


def test_bad_uploads_and_bad_media_tokens():
    h = login_as("Elena Rivera")
    room = client.post("/households/me/rooms", headers=h, json={"name": "Garage"}).json()
    bad = client.post(
        f"/households/me/rooms/{room['id']}/scans",
        headers=h,
        files=[("files", ("x.jpg", b"not an image", "image/jpeg"))],
    )
    assert bad.status_code == 422
    assert client.get("/media/1?t=forged").status_code == 404
