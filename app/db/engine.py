"""Database engine + sessions.

`tenant_session(shop_id)` is the ONLY sanctioned way to touch tenant data: it
opens a transaction and sets the `app.shop_id` Postgres variable the RLS policies
read, so a query that forgets its WHERE clause still cannot see another shop.

`plain_session()` is for the one global, non-tenant table (shop), used to
authenticate an API key -> shop.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_settings = get_settings()

# Runtime engine connects as the non-superuser app role, so RLS is enforced.
engine = create_engine(_settings.database_url, future=True, pool_pre_ping=True)
SessionFactory = sessionmaker(bind=engine, future=True, expire_on_commit=False)


@contextmanager
def tenant_session(shop_id: str) -> Iterator[Session]:
    """A transaction bound to one shop. All reads/writes are RLS-filtered to it."""
    session = SessionFactory()
    try:
        # set_config(..., is_local=true) scopes the setting to this transaction.
        session.execute(
            text("SELECT set_config('app.shop_id', :sid, true)"), {"sid": shop_id}
        )
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def plain_session() -> Iterator[Session]:
    """Un-scoped session for the global `shop` table (no tenant data here)."""
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
