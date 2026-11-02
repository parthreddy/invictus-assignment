"""The per-shop monthly LLM spend cap.

Enforced in the worker BEFORE each model call: if a shop has already spent its
monthly cap, we do not call the model at all -- the message is deferred to manual
handling. Cost is the thing we are protecting, so the gate sits in front of the
only thing that costs money (the LLM call).

Tradeoff (intentional, documented): the check compares ALREADY-accumulated spend
to the cap, so the single call that crosses the cap still runs. Overshoot is
bounded by one call. The stricter alternative is to reserve an estimated cost
before calling; not worth the complexity for this prototype.
"""
from __future__ import annotations

from app.db import repo


def is_over_cap(session, shop_id: str, month: str) -> bool:
    """True if this shop has reached/exceeded its monthly cap and must be deferred."""
    cap = repo.get_cap(session, shop_id)
    if cap is None:
        return False  # no cap configured -> never blocked
    spent = repo.current_month_spend(session, shop_id, month)
    return spent >= cap
