# Give to a family through PayPal

The Public API never charges anyone. Preparing a gift returns a PayPal approval link, and a person approves the
payment on PayPal. Nothing moves before that.

1. **Find a family.** `GET /v1/registries?q=juniper` lists verified families' Rebuild Registries, the ones that
   still need the most first.
2. **Pick what to fund.** `GET /v1/registries/{slug}` returns every item with what it still needs.
3. **Prepare the gift.** `POST /v1/registries/{slug}/donations` with an `item_id`, an `amount` and an optional
   `donor_name` and `message`.
   The response has a PayPal `approval_url` and a `status_url`. Show the link to the person; never ask them for
   payment details.
4. **The person approves on PayPal.** PayPal sends them back to Hearthline's `/paid` page, which completes the
   payment. If they close the tab first, PayPal's webhook completes it instead.
5. **Follow the gift.** `GET /v1/donations/{id}` shows where the money went: paid, bought, shipped, delivered.

Gift cards for local businesses work the same way: `POST /v1/reopen-funds/{slug}/gift-cards` returns an approval
link, and `GET /v1/gift-cards/{code}` shows the card's balance and whether it can be spent yet.

The hosted demo runs in the PayPal sandbox, so no real money moves. The sandbox buyer login is on the demo's
sign-in page.
