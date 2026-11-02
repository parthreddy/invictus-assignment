"""The worker: claims queued jobs and runs them through the orchestrator.

It polls per shop (3 shops,
so a simple loop is fine; at 100 shops this becomes push-based -- see NOT_BUILT).
Claiming uses SELECT ... FOR UPDATE SKIP LOCKED so multiple workers never grab the
same job. Transient LLM failures back off and retry; after MAX_ATTEMPTS a job is
parked as DEAD rather than retried forever.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from sqlalchemy import select

from app.config import get_settings
from app.core.catalog import load_catalog
from app.core.orchestrator import process_message
from app.db import repo
from app.db.engine import tenant_session
from app.db.models import Outbox
from app.llm.client import LLMError, OpenAIProvider

logger = logging.getLogger(__name__)


def _claim_next(session) -> Outbox | None:
    stmt = (
        select(Outbox)
        .where(Outbox.status == "QUEUED", Outbox.run_after <= datetime.now())
        .order_by(Outbox.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = session.execute(stmt).scalars().first()
    if job is not None:
        job.status = "IN_PROGRESS"
    return job


def _resolve(shop_id, job_id, *, status, attempts, error=None, run_after=None):
    with tenant_session(shop_id) as s:
        job = s.get(Outbox, job_id)
        if job is None:
            return
        job.status = status
        job.attempts = attempts
        if error is not None:
            job.last_error = error
        if run_after is not None:
            job.run_after = run_after
        # A job that dies after exhausting retries (e.g. a sustained provider
        # outage) must still be visible to the shop -- surface it for review.
        if status == "DEAD":
            repo.upsert_work_order(s, shop_id, job.message_id, status="NEEDS_REVIEW")


def run_once(provider=None, catalog=None) -> int:
    """One pass over all shops, draining currently-runnable jobs. Returns count."""
    provider = provider or OpenAIProvider()
    catalog = catalog or load_catalog()
    settings = get_settings()
    max_attempts = settings.worker_max_attempts
    backoff_base = settings.worker_backoff_base_seconds
    processed = 0

    for shop_id in sorted(catalog.shop_ids()):
        while True:
            # Claim in its own short transaction, then process outside the lock.
            with tenant_session(shop_id) as s:
                job = _claim_next(s)
                if job is None:
                    break
                job_id, mid, jtype, attempts = (
                    job.id,
                    job.message_id,
                    job.job_type,
                    job.attempts,
                )

            try:
                process_message(
                    shop_id, mid, provider=provider, catalog=catalog, job_type=jtype
                )
                _resolve(shop_id, job_id, status="DONE", attempts=attempts + 1)
            except LLMError as exc:
                # Transient (timeout / outage): back off and retry, then park.
                attempts += 1
                if attempts >= max_attempts:
                    _resolve(
                        shop_id, job_id, status="DEAD", attempts=attempts,
                        error=str(exc),
                    )
                else:
                    _resolve(
                        shop_id, job_id, status="QUEUED", attempts=attempts,
                        error=str(exc),
                        run_after=datetime.now()
                        + timedelta(seconds=backoff_base * attempts),
                    )
            except Exception as exc:  # noqa: BLE001 -- a poison job must not kill the worker
                # Unexpected error (bug, DB hiccup): park this one job as DEAD and
                # keep the worker alive for every other message.
                logger.exception("job %s failed unexpectedly", job_id)
                _resolve(shop_id, job_id, status="DEAD", attempts=attempts + 1,
                         error=f"unexpected: {exc}")
            processed += 1

    return processed


def drain(provider=None, catalog=None, max_passes=50) -> int:
    """Run passes until nothing runnable remains (used by the replay script)."""
    total = 0
    for _ in range(max_passes):
        n = run_once(provider=provider, catalog=catalog)
        total += n
        if n == 0:
            break
    return total


def run_forever(poll_interval: float = 2.0) -> None:
    """Long-lived worker loop (the `worker` container's entrypoint).

    A failure in a single pass (e.g. the DB briefly unreachable) is logged and the
    loop continues after a short sleep -- the worker must not die on a hiccup.
    """
    while True:
        try:
            if run_once() == 0:
                time.sleep(poll_interval)
        except Exception:  # noqa: BLE001 -- keep polling through transient failures
            logger.exception("worker pass failed; retrying")
            time.sleep(poll_interval)


if __name__ == "__main__":
    run_forever()
