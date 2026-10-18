"""Put the demo back where it starts, for everyone using it.

Judges try flows that change shared state (reject the copycat registry, answer the disputes), and Render's free plan
has no cron to reset the data. Anyone may reset, at most once every ten minutes. It wipes every table and runs the
demo seed again in the background. It doesn't touch PayPal: sandbox payouts already sent stay sent.
"""

import logging
import threading
import time
from collections.abc import Callable

from sqlalchemy import text

from app.db import Base, engine

log = logging.getLogger(__name__)
COOLDOWN_SECONDS = 600
_lock = threading.Lock()
_state = {"last": 0.0, "running": False, "error": None}


class TooSoon(Exception):
    def __init__(self, seconds: int):
        super().__init__(f"The demo was reset recently. Try again in {seconds // 60 + 1} minutes.")
        self.seconds = seconds


def wipe() -> None:
    """Empty every table (ids start again from 1, so persona logins stay the same)."""
    tables = Base.metadata.sorted_tables
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE " + ", ".join(f'"{t.name}"' for t in tables) + " RESTART IDENTITY CASCADE"))
        return
    with engine.connect() as conn:  # SQLite: foreign keys off while deleting, back on for the pooled connection
        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        for table in reversed(tables):
            conn.execute(table.delete())
        conn.commit()
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")


def _seed() -> None:
    from app import seed

    seed.main()


def status() -> dict:
    left = max(0, int(COOLDOWN_SECONDS - (time.monotonic() - _state["last"]))) if _state["last"] else 0
    return {"running": _state["running"], "available_in_seconds": left, "error": _state["error"]}


def start(reseed: Callable[[], None] | None = None, background: bool = True) -> None:
    """Wipe and reseed (by default in a background thread; the full demo seed takes a while on SQLite)."""
    with _lock:
        if _state["running"]:
            raise TooSoon(60)
        left = status()["available_in_seconds"]
        if left:
            raise TooSoon(left)
        _state.update(running=True, last=time.monotonic(), error=None)

    def work() -> None:
        try:
            wipe()
            (reseed or _seed)()
            log.info("Demo reset finished")
        except Exception as e:  # shown on the sign-in page; the next reset can try again
            log.exception("Demo reset failed")
            _state["error"] = str(e)[:200]
        finally:
            _state["running"] = False

    if background:
        threading.Thread(target=work, name="demo-reset", daemon=True).start()
    else:
        work()
