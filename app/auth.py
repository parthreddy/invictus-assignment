"""Per-shop API-key authentication.

Each shop has a bearer token; its SHA-256 is stored in the shop table. The token
resolves to exactly one shop_id, which becomes the tenant context for the whole
request. Staff therefore can only ever act on their own shop -- authn and tenancy
are the same decision.
"""
from __future__ import annotations

import hashlib

from fastapi import Header, HTTPException
from sqlalchemy import text

from app.db.engine import plain_session


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def require_shop(authorization: str = Header(default="")) -> str:
    """FastAPI dependency: validate 'Authorization: Bearer <key>' -> shop_id."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    key = authorization.removeprefix("Bearer ").strip()

    with plain_session() as s:
        row = s.execute(
            text("SELECT id FROM shop WHERE api_key_hash = :h"), {"h": _hash(key)}
        ).first()

    if row is None:
        raise HTTPException(status_code=401, detail="invalid api key")
    return row[0]
