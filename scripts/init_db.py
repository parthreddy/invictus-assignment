"""One-shot database bootstrap.

Run as the admin role. It (1) creates the non-superuser app role, (2) creates all
tables, (3) applies RLS policies, (4) seeds the three shops. Idempotent: safe to
re-run. Invoked by `make up` after Postgres is healthy.
"""
from __future__ import annotations

import hashlib
import pathlib

from sqlalchemy import create_engine, text

from app.config import get_settings
from app.db.models import Base

RLS_SQL = pathlib.Path(__file__).resolve().parents[1] / "app" / "db" / "rls.sql"

# Dev API keys -> shops. Real keys would come from Secret Manager; these are only
# for local runs and are safe to live in source.
SHOPS = [
    ("rb-downtown", "Riverbend Cycles Downtown", "dev-key-downtown"),
    ("rb-northside", "Riverbend Cycles Northside", "dev-key-northside"),
    ("rb-lakeshore", "Riverbend Cycles Lakeshore", "dev-key-lakeshore"),
]


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def main() -> None:
    settings = get_settings()
    admin = create_engine(settings.admin_database_url, future=True)

    with admin.begin() as conn:
        # 1. App role (non-superuser -> RLS binds to it).
        conn.execute(
            text(
                "DO $$ BEGIN "
                "IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='riverbend_app') "
                "THEN CREATE ROLE riverbend_app LOGIN PASSWORD 'riverbend_app'; "
                "END IF; END $$;"
            )
        )

    # 2. Tables (owned by the admin role).
    Base.metadata.create_all(admin)

    with admin.begin() as conn:
        # 3. RLS policies + grants.
        conn.execute(text(RLS_SQL.read_text()))

        # 4. Seed shops (global table).
        for shop_id, name, key in SHOPS:
            conn.execute(
                text(
                    "INSERT INTO shop (id, name, api_key_hash, monthly_cap_usd) "
                    "VALUES (:id, :name, :hash, :cap) "
                    "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name"
                ),
                {
                    "id": shop_id,
                    "name": name,
                    "hash": _sha256(key),
                    "cap": settings.monthly_spend_cap_usd,
                },
            )

    print("DB bootstrap complete: role, tables, RLS, and 3 shops seeded.")


if __name__ == "__main__":
    main()
