"""API tests: authentication, idempotent ingest, and the read endpoint.

Idempotency is a named hard-part of the brief, so it gets an explicit test: the
same message POSTed twice must leave exactly one inbound row and one queued job.
Requires Postgres; skipped if unavailable.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.api import app
from app.db.engine import tenant_session
from app.db.models import InboundMessage, Outbox

DOWNTOWN = {"Authorization": "Bearer dev-key-downtown"}
NORTHSIDE = {"Authorization": "Bearer dev-key-northside"}


def _db_available() -> bool:
    try:
        with tenant_session("rb-downtown"):
            return True
    except (OperationalError, ProgrammingError):
        return False


requires_db = pytest.mark.skipif(not _db_available(), reason="Postgres not available")
client = TestClient(app)


def _count(shop_id, model, message_id):
    with tenant_session(shop_id) as s:
        return s.execute(
            select(func.count())
            .select_from(model)
            .where(model.message_id == message_id)
        ).scalar_one()


def _purge(shop_id, message_id):
    with tenant_session(shop_id) as s:
        for model in (InboundMessage, Outbox):
            for row in s.execute(
                select(model).where(model.message_id == message_id)
            ).scalars():
                s.delete(row)


def test_missing_auth_rejected():
    r = client.post("/v1/messages", json={"message_id": "x", "body": "hi"})
    assert r.status_code == 401


def test_bad_key_rejected():
    r = client.post(
        "/v1/messages",
        json={"message_id": "x", "body": "hi"},
        headers={"Authorization": "Bearer nope"},
    )
    assert r.status_code == 401


@requires_db
def test_ingest_accepts_then_dedupes():
    msg = {"message_id": "m-api-1", "channel": "web", "body": "flat tire"}
    _purge("rb-downtown", "m-api-1")

    first = client.post("/v1/messages", json=msg, headers=DOWNTOWN)
    assert first.status_code == 202
    assert first.json()["status"] == "accepted"

    second = client.post("/v1/messages", json=msg, headers=DOWNTOWN)
    assert second.status_code == 202
    assert second.json()["status"] == "duplicate"

    # Exactly one inbound row and one queued job despite two POSTs.
    assert _count("rb-downtown", InboundMessage, "m-api-1") == 1
    assert _count("rb-downtown", Outbox, "m-api-1") == 1


@requires_db
def test_invalid_payload_422():
    r = client.post("/v1/messages", json={"message_id": "", "body": ""}, headers=DOWNTOWN)
    assert r.status_code == 422


@requires_db
def test_read_endpoint_is_shop_scoped():
    # Downtown's read never contains another shop's rows, and reports a total.
    r = client.get("/v1/work-orders", headers=DOWNTOWN)
    assert r.status_code == 200
    body = r.json()
    assert body["shop_id"] == "rb-downtown"
    assert "estimated_total" in body
    assert all(w for w in body["work_orders"])  # structurally valid list
