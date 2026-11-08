from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.db import get_db
from app.paypal import webhooks

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/paypal", include_in_schema=False, response_model=None)
async def paypal_webhook(request: Request, db: Annotated[Session, Depends(get_db)]) -> dict | JSONResponse:
    try:
        event = await request.json()
    except ValueError:  # not JSON at all
        raise HTTPException(400, "Not a PayPal webhook event") from None
    if not isinstance(event, dict) or "id" not in event or "event_type" not in event:
        raise HTTPException(400, "Not a PayPal webhook event")
    verified = await webhooks.verify_signature({k.lower(): v for k, v in request.headers.items()}, event)
    # The database work runs in a worker thread: blocking here would hold up every request, the health check too.
    stored = await run_in_threadpool(webhooks.handle, db, event, verified)
    if stored.error:
        raise HTTPException(500, "Processing failed; PayPal will retry")  # non-2xx makes PayPal redeliver
    body = {"received": stored.id, "verified": stored.verified}
    if not stored.verified:
        # Stored but not acted on. A non-2xx answer makes PayPal redeliver, so an event whose check failed for a
        # passing reason (PayPal's verify call down, say) is handled once a delivery verifies; a forged one never is.
        return JSONResponse(status_code=401, content=body)
    return body
