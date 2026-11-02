"""Failure-handling tests: spend cap and provider outage.

These are the brief's hard parts, so they are tested explicitly. They use the REAL
provider (no fakes): the spend-cap gate and LLM_FAULT_MODE=down both short-circuit
BEFORE any network call, so the tests are deterministic and need no API key.
Requires Postgres.
"""
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.config import Settings, get_settings
from app.core.orchestrator import process_message
from app.db import repo
from app.db.engine import tenant_session
from app.db.models import LlmCall, Outbox, WorkOrder
from app.llm.client import LLMError, OpenAIProvider

SHOP = "rb-downtown"


def _db_available() -> bool:
    try:
        with tenant_session(SHOP):
            return True
    except (OperationalError, ProgrammingError):
        return False


requires_db = pytest.mark.skipif(not _db_available(), reason="Postgres not available")


def _admin():
    return create_engine(get_settings().admin_database_url, future=True)


@pytest.fixture(autouse=True)
def _clean():
    if not _db_available():
        yield
        return
    with _admin().begin() as c:
        for t in ("inbound_message", "work_order", "outbox", "llm_call", "spend_ledger"):
            c.execute(text(f"TRUNCATE {t} RESTART IDENTITY CASCADE"))
        c.execute(text("UPDATE shop SET monthly_cap_usd = 5.00"))
    yield
    with _admin().begin() as c:
        c.execute(text("UPDATE shop SET monthly_cap_usd = 5.00"))


def _seed(message_id: str, body: str = "flat tire, fix friday?"):
    with tenant_session(SHOP) as s:
        repo.record_inbound(s, SHOP, message_id, "web", body, datetime.now())


def _down_provider() -> OpenAIProvider:
    # Real provider, fault switch flipped -> raises before any network call.
    return OpenAIProvider(Settings(llm_fault_mode="down"))


@requires_db
def test_at_cap_defers_without_calling_model():
    with _admin().begin() as c:
        c.execute(text(f"UPDATE shop SET monthly_cap_usd = 0 WHERE id = '{SHOP}'"))
    _seed("cap-1")

    # Any real provider would do; the gate must stop us before we ever call it.
    status = process_message(SHOP, "cap-1", provider=_down_provider())

    assert status == "DEFERRED"
    with tenant_session(SHOP) as s:
        wo = repo.get_work_order(s, "cap-1")
        calls = s.execute(select(func.count()).select_from(LlmCall)).scalar_one()
    assert wo.status == "DEFERRED"
    assert calls == 0  # cap enforced BEFORE spending anything


@requires_db
def test_outage_propagates_as_retryable_error():
    _seed("out-1")
    with pytest.raises(LLMError):
        process_message(SHOP, "out-1", provider=_down_provider())


@requires_db
def test_duplicate_api_key_hash_is_rejected():
    # Two shops cannot share a key: the UNIQUE(api_key_hash) constraint blocks it.
    from sqlalchemy.exc import IntegrityError

    existing = _admin().connect().execute(
        text("SELECT api_key_hash FROM shop LIMIT 1")
    ).scalar_one()
    with pytest.raises(IntegrityError):
        with _admin().begin() as c:
            c.execute(
                text(
                    "INSERT INTO shop (id, name, api_key_hash, monthly_cap_usd) "
                    "VALUES ('rb-clone', 'Clone', :h, 5.00)"
                ),
                {"h": existing},
            )


@requires_db
def test_poison_job_is_parked_and_worker_survives(monkeypatch):
    # An unexpected (non-LLM) error in one job must not kill the worker: the job is
    # parked DEAD + NEEDS_REVIEW and run_once returns normally.
    from app import worker

    monkeypatch.setattr(
        worker, "process_message",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    _seed("poison-1")
    with tenant_session(SHOP) as s:
        repo.enqueue(s, SHOP, "poison-1", "PROCESS")

    worker.run_once()  # must NOT raise

    with tenant_session(SHOP) as s:
        job = s.execute(
            select(Outbox).where(Outbox.message_id == "poison-1")
        ).scalars().first()
        wo = repo.get_work_order(s, "poison-1")
    assert job.status == "DEAD"
    assert wo is not None and wo.status == "NEEDS_REVIEW"


@requires_db
def test_worker_parks_message_for_review_after_retries(monkeypatch):
    from app import worker

    # One attempt, zero backoff -> a sustained outage dies immediately in-test.
    monkeypatch.setattr(
        worker,
        "get_settings",
        lambda: Settings(worker_max_attempts=1, worker_backoff_base_seconds=0),
    )
    _seed("out-2")
    with tenant_session(SHOP) as s:
        repo.enqueue(s, SHOP, "out-2", "PROCESS")

    worker.run_once(provider=_down_provider())

    with tenant_session(SHOP) as s:
        job = s.execute(
            select(Outbox).where(Outbox.message_id == "out-2")
        ).scalars().first()
        wo = repo.get_work_order(s, "out-2")
    assert job.status == "DEAD"
    assert wo is not None and wo.status == "NEEDS_REVIEW"
