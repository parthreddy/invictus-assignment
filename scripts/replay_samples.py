"""Replay the sample messages through the real system and print a results table.

Drives the actual HTTP path (POST /v1/messages) -> DB outbox -> worker -> work
orders, exactly as production would. This is both the live demo and the source of
the results table the brief asks for (work orders created, follow-ups, failures,
model spend).

Usage:
    python -m scripts.replay_samples [--limit N] [--reset] [--base-url URL]
"""
from __future__ import annotations

import argparse
import json
import pathlib
from collections import Counter
from decimal import Decimal

import httpx
from sqlalchemy import create_engine, func, select, text

from app.config import get_settings
from app.core.catalog import load_catalog
from app.db.engine import tenant_session
from app.db.models import LlmCall, Outbox, SpendLedger, WorkOrder
from app.worker import drain

SAMPLES = pathlib.Path(__file__).resolve().parents[1] / "data" / "samples.json"

DEV_KEYS = {
    "rb-downtown": "dev-key-downtown",
    "rb-northside": "dev-key-northside",
    "rb-lakeshore": "dev-key-lakeshore",
}

TENANT_TABLES = [
    "inbound_message", "work_order", "conversation",
    "outbox", "spend_ledger", "llm_call",
]


def reset_data() -> None:
    admin = create_engine(get_settings().admin_database_url, future=True)
    with admin.begin() as conn:
        for tbl in TENANT_TABLES:
            conn.execute(text(f"TRUNCATE {tbl} RESTART IDENTITY CASCADE"))
    print("Cleared prior run data.")


def post_messages(base_url: str, samples: list[dict]) -> Counter:
    tally: Counter = Counter()
    with httpx.Client(base_url=base_url, timeout=30) as client:
        for m in samples:
            headers = {"Authorization": f"Bearer {DEV_KEYS[m['shop_id']]}"}
            r = client.post(
                "/v1/messages",
                headers=headers,
                json={
                    "message_id": m["message_id"],
                    "channel": m["channel"],
                    "body": m["body"],
                    "received_at": m["received_at"],
                },
            )
            r.raise_for_status()
            tally[r.json()["status"]] += 1
    return tally


def collect_results(catalog) -> dict:
    status_counts: Counter = Counter()
    spend = Decimal("0")
    llm_calls = 0
    dead_jobs = 0

    for shop_id in sorted(catalog.shop_ids()):
        with tenant_session(shop_id) as s:
            for status, count in s.execute(
                select(WorkOrder.status, func.count()).group_by(WorkOrder.status)
            ):
                status_counts[status] += count
            spent = s.execute(
                select(func.coalesce(func.sum(SpendLedger.spent_usd), 0))
            ).scalar_one()
            spend += Decimal(str(spent))
            llm_calls += s.execute(
                select(func.count()).select_from(LlmCall)
            ).scalar_one()
            dead_jobs += s.execute(
                select(func.count()).select_from(Outbox).where(Outbox.status == "DEAD")
            ).scalar_one()

    return {
        "status_counts": status_counts,
        "spend": spend,
        "llm_calls": llm_calls,
        "dead_jobs": dead_jobs,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--base-url", default="http://localhost:8000")
    args = ap.parse_args()

    if args.reset:
        reset_data()

    samples = json.loads(SAMPLES.read_text())
    if args.limit:
        samples = samples[: args.limit]

    catalog = load_catalog()
    print(f"Posting {len(samples)} messages to {args.base_url} ...")
    ingest = post_messages(args.base_url, samples)
    print(f"  ingest: accepted={ingest['accepted']} duplicate={ingest['duplicate']}")

    print("Draining worker (real LLM) ...")
    processed = drain(catalog=catalog)
    print(f"  worker processed {processed} job(s)")

    res = collect_results(catalog)
    sc = res["status_counts"]
    print("\n================ RESULTS ================")
    print(f"Messages posted          : {len(samples)}")
    print(f"  duplicates deduped     : {ingest['duplicate']}")
    print(f"Work orders OPEN         : {sc.get('OPEN', 0)}")
    print(f"Follow-ups asked         : {sc.get('NEEDS_INFO', 0)}")
    print(f"Price/info-only          : {sc.get('INFO_ONLY', 0)}")
    print(f"Parked for review        : {sc.get('NEEDS_REVIEW', 0)}")
    print(f"Deferred (spend cap)     : {sc.get('DEFERRED', 0)}")
    print(f"Dead jobs (outage)       : {res['dead_jobs']}")
    print(f"LLM calls                : {res['llm_calls']}")
    print(f"Total model spend        : ${res['spend']:.4f}")
    print("========================================")


if __name__ == "__main__":
    main()
