import inspect

from fastapi.routing import APIRoute

from app.main import app

# Endpoints that may be async: they await network calls and send their blocking work to a worker thread.
ASYNC_OK = {"app.api.webhooks.paypal_webhook"}


def endpoints(routes):
    for r in routes:
        if isinstance(r, APIRoute):
            yield r.endpoint
        elif hasattr(r, "original_router"):  # FastAPI keeps included routers nested
            yield from endpoints(r.original_router.routes)


def test_endpoints_never_block_the_event_loop():
    """An async endpoint runs on the server's one event loop, so a blocking call inside it (an AI call, image
    processing, a sync database query) holds up every other request, the health check included. On Render that
    once failed the health check and restarted the API. Plain `def` endpoints run in a worker thread instead."""
    found = list(endpoints(app.routes))
    assert len(found) > 100  # the walk reached the routers
    async_ones = {f"{fn.__module__}.{fn.__name__}" for fn in found if inspect.iscoroutinefunction(fn)}
    assert async_ones == ASYNC_OK, f"make these plain def, or move their blocking work off the loop: {async_ones}"
