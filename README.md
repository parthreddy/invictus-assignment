# Riverbend Cycles — message-to-work-order service


 # run all the services with command
docker compose up

## Configuration & secrets

All config is read from the environment in one place ([app/config.py](app/config.py)).
Locally that comes from `.env` (gitignored — a key is never committed); in GCP the
same names are populated from Secret Manager. Key settings:

| Var | Meaning |
|---|---|
| `OPENAI_API_KEY` | provider key (required for real runs) |
| `OPENAI_MODEL` | default `gpt-4o-mini` |
| `MONTHLY_SPEND_CAP_USD` | per-shop monthly LLM cap |
| `LLM_FAULT_MODE` | `none` / `slow` / `down` — simulate provider failure |

## API

All endpoints authenticate with a per-shop bearer token (`dev-key-downtown`,
`dev-key-northside`, `dev-key-lakeshore` locally). The token *is* the tenant.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/messages` | ingest a message (idempotent on `message_id`); returns `202` |
| `POST` | `/v1/replies` | customer answer to a follow-up question; resumes processing |
| `GET` | `/v1/work-orders?status=…` | list work orders (default open; `DEFERRED` / `NEEDS_REVIEW` queues) |
| `GET` | `/v1/messages/{id}` | processing status + the customer-facing message |

```bash
curl -s -X POST http://localhost:8000/v1/messages \
  -H "Authorization: Bearer dev-key-downtown" -H "Content-Type: application/json" \
  -d '{"message_id":"demo-1","channel":"web","body":"rear brake squeals and gears skip, Saturday?"}'
```

