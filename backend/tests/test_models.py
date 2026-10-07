from decimal import Decimal

from app.db import SessionLocal
from app.models import DisasterEvent, Household, Item, Role, Room, User


def test_household_with_rooms_items_and_member():
    with SessionLocal() as db:
        event = DisasterEvent(
            slug="test-fire", name="Test Fire", kind="wildfire", zone={"type": "Polygon", "coordinates": []}
        )
        home = Household(
            name="Test family",
            address_line="1 Main St",
            city="Town",
            state="CA",
            postal_code="90000",
            disaster_event=event,
        )
        room = Room(household=home, name="Living room")
        home.items.append(Item(room=room, name="Sofa", quantity=1, unit_price=Decimal("899.99")))
        db.add_all([home, User(email="t@example.com", name="T", role=Role.HOUSEHOLD, household=home)])
        db.commit()

        saved = db.get(Household, home.id)
        assert saved.members[0].role == Role.HOUSEHOLD
        assert saved.items[0].unit_price == Decimal("899.99")
        assert saved.items[0].room.name == "Living room"
