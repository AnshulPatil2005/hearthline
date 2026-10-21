from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.db import get_db
from app.paypal import webhooks

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/paypal", include_in_schema=False)
async def paypal_webhook(request: Request, db: Annotated[Session, Depends(get_db)]) -> dict:
    event = await request.json()
    if not isinstance(event, dict) or "id" not in event or "event_type" not in event:
        raise HTTPException(400, "Not a PayPal webhook event")
    verified = await webhooks.verify_signature({k.lower(): v for k, v in request.headers.items()}, event)
    # The database work runs in a worker thread: blocking here would hold up every request, the health check too.
    stored = await run_in_threadpool(webhooks.handle, db, event, verified)
    if stored.error:
        raise HTTPException(500, "Processing failed; PayPal will retry")  # non-2xx makes PayPal redeliver
    return {"received": stored.id, "verified": stored.verified}
