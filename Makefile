.PHONY: up down logs replay test clean

# One-command local run: db + migrate + api + worker.
up:
	docker compose up --build -d
	@echo "API on http://localhost:8000  (try: curl localhost:8000/healthz)"

down:
	docker compose down

logs:
	docker compose logs -f api worker

# Replay the 40 sample messages and print the results table (runs in the api
# container so it shares the compose network and config).
replay:
	docker compose exec -T api python -m scripts.replay_samples --reset --base-url http://localhost:8000

# Tests run against the compose Postgres published on localhost:5432.
test:
	.venv/bin/python -m pytest -q

clean:
	docker compose down -v
