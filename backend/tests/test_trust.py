import io
from decimal import Decimal as D

from PIL import Image, ImageDraw

from app import ai, trust
from app.agents import sentinel
from app.db import SessionLocal
from app.media import prepare_image
from app.models import EvidenceLevel, Household, Item, Media
from tests.helpers import client, login_as


def photo_bytes(seed: int) -> bytes:
    """A deterministic test picture with some structure for the perceptual hash."""
    img = Image.new("RGB", (320, 240), "white")
    draw = ImageDraw.Draw(img)
    for i in range(8):
        x, y = (seed * 13 + i * 37) % 260, (seed * 7 + i * 29) % 180
        draw.rectangle([x, y, x + 40 + i * 5, y + 30 + i * 4], fill=(i * 30, seed * 40 % 255, 90))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def add_photo(db, household_id: int, raw: bytes) -> Media:
    img = prepare_image(raw)
    media = Media(
        household_id=household_id,
        content_type="image/jpeg",
        data=img.jpeg,
        width=img.width,
        height=img.height,
        sha256=img.sha256,
        phash=img.phash,
    )
    db.add(media)
    db.flush()
    return media


def rivera(db) -> Household:
    return db.query(Household).filter_by(name="Rivera household").one()


def test_levels_and_caseworker_vouch():
    h = login_as("Elena Rivera")
    assert client.get("/households/me/verification", headers=h).json()["level"] == 1  # inside the fire zone
    with SessionLocal() as db:
        hid = rivera(db).id

    assert (
        client.post(f"/trust/households/{hid}/vouch", headers=h, json={"note": "I know them well"}).status_code == 403
    )
    vouched = client.post(
        f"/trust/households/{hid}/vouch",
        headers=login_as("Priya Nair"),
        json={"note": "Met Elena at the Sablewood shelter; neighbors confirm the address."},
    ).json()
    assert vouched["level"] == 2 and vouched["next_step"] == "scan_before_disaster"

    with SessionLocal() as db:
        db.add(Item(household_id=hid, name="Sofa", evidence_level=EvidenceLevel.PRE_DISASTER_SCAN))
        db.commit()
    assert client.get("/households/me/verification", headers=h).json()["level"] == 3


def test_cloned_registry_is_flagged_high_risk():
    login_as("Elena Rivera")
    with SessionLocal() as db:
        real = rivera(db)
        real.payout_email = "elena@personal.example.com"
        add_photo(db, real.id, photo_bytes(1))
        clone = Household(
            name="Rivera family fund",
            address_line="1 Elsewhere Rd",
            city="Far",
            state="NV",
            postal_code="89001",
            lat=36.0,
            lng=-115.0,
            payout_email="scam@personal.example.com",
        )
        accomplice = Household(
            name="Another account",
            address_line="2 Elsewhere Rd",
            city="Far",
            state="NV",
            postal_code="89001",
            lat=36.0,
            lng=-115.0,
            payout_email="scam@personal.example.com",
        )
        db.add_all([clone, accomplice])
        db.flush()
        add_photo(db, clone.id, photo_bytes(1))  # the real family's photo, re-uploaded
        db.commit()
        clone_id, real_id = clone.id, real.id

    staff = login_as("Priya Nair")
    report = client.get(f"/trust/households/{clone_id}", headers=staff).json()
    codes = {f["code"] for f in report["flags"]}
    assert codes == {"outside_zone", "duplicate_photo", "shared_payout_account"}
    assert report["risk_tier"] == "high" and report["level"] == 0
    dupe = next(f for f in report["flags"] if f["code"] == "duplicate_photo")
    assert dupe["evidence"]["matches"][0]["other_household_id"] == real_id

    honest = client.get(f"/trust/households/{real_id}", headers=staff).json()
    assert {f["code"] for f in honest["flags"]} == {"duplicate_photo"}  # someone copied *their* photo
    assert client.get(f"/trust/households/{clone_id}", headers=login_as("Elena Rivera")).status_code == 403


def test_price_and_evidence_flags():
    login_as("Elena Rivera")
    with SessionLocal() as db:
        home = rivera(db)
        db.add_all(
            [
                Item(household_id=home.id, name="Watch", unit_price=D("5000"), price_high=D("900"), quantity=1),
                Item(
                    household_id=home.id,
                    name="Painting",
                    unit_price=D("2500"),
                    quantity=1,
                    evidence_level=EvidenceLevel.MEMORY,
                ),
            ]
        )
        db.commit()
        flags = {f.code for f in trust.sentinel_flags(db, home)}
    assert flags == {"price_outlier", "high_value_no_evidence"}


def test_sentinel_falls_back_without_ai(monkeypatch):
    def down(*args, **kwargs):
        raise RuntimeError("AI quota exhausted")

    monkeypatch.setattr(ai, "parse", down)
    flags = [trust.Flag("outside_zone", "high", "The home address is not inside any active disaster area.", {})]
    note = sentinel.explain({"household": "x"}, flags)
    assert note.recommendation == "escalate" and "not inside" in note.summary
    assert sentinel.explain({}, []).recommendation == "approve"
