# Agrobot

Weather alert system: a REST API and background workers on PostgreSQL. The original task statement
(in Spanish) is in [`docs/TASK.md`](docs/TASK.md).

## Run it

Requires Docker.

```bash
docker compose up --build
```

This starts Postgres, applies the migrations, and runs the API plus the `ingest`, `evaluate` and
`notify` workers, each in its own container. No `.env` is needed.

- API docs: http://localhost:8000/docs
- Every endpoint except `/health` requires the `X-API-Key` header. The default key is
  `dev-api-key`; in `/docs`, set it with the *Authorize* button.

The weather provider and the WhatsApp sender are fakes, so nothing calls a third-party service. In
Compose the workers run every minute or less so alerts show up quickly, and each worker reports
healthy while its job keeps succeeding (`docker compose ps`). If port 8000 or 5432 is taken, set
`API_PORT` or `POSTGRES_PORT`.

To change any other setting, create a `compose.override.yaml` next to `compose.yaml`; Compose
merges it automatically:

```yaml
services:
  ingest:
    environment:
      INGEST_INTERVAL_SECONDS: 300
```

## Run it without Docker for the app

Requires [uv](https://docs.astral.sh/uv/) and Docker for the database.

```bash
cp .env.example .env
docker compose up -d --wait db
uv run alembic upgrade head
uv run uvicorn --factory agrobot.api.app:create_app    # API at http://localhost:8000/docs
uv run python -m agrobot.worker ingest                 # each worker in its own terminal
uv run python -m agrobot.worker evaluate
uv run python -m agrobot.worker notify
```

## Test it

```bash
uv run pytest
curl localhost:8000/health   # {"status":"ok","database":"ok"}
```

The tests start their own Postgres with testcontainers (they only need Docker), apply the real
migrations, and run each test in a transaction that is rolled back at the end.

## Decisions

Design decisions are recorded as ADRs in [`docs/adr/`](docs/adr/). The domain vocabulary is in
[`GLOSSARY.md`](GLOSSARY.md).
