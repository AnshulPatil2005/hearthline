from datetime import UTC, datetime

from app.paypal import payouts
from app.paypal.rest import PayPalError


def test_batch_ids_are_stable_per_record_and_unique_across_databases():
    created = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    assert payouts.batch_id_for("case", 5, created) == payouts.batch_id_for("case", 5, created)
    assert payouts.batch_id_for("case", 5, created) != payouts.batch_id_for(
        "case", 5, datetime(2026, 10, 9, tzinfo=UTC)
    )


def test_already_submitted_batch_is_recognized():
    body = {
        "name": "USER_BUSINESS_ERROR",
        "details": [
            {
                "field": "SENDER_BATCH_ID",
                "issue": "Batch with given sender_batch_id already exists",
                "link": [{"href": "https://api.sandbox.paypal.com/v1/payments/payouts/9HTUD94NJDRL6", "rel": "self"}],
            }
        ],
    }
    assert payouts._existing_batch(PayPalError(400, body)) == "9HTUD94NJDRL6"
    assert payouts._existing_batch(PayPalError(422, {"name": "INSUFFICIENT_FUNDS"})) is None
