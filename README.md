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

## Try it

With the stack from `docker compose up --build` running, in another terminal (needs `jq`):

```bash
API=localhost:8000; KEY='X-API-Key: dev-api-key'; JSON='Content-Type: application/json'

USER_ID=$(curl -s -X POST $API/users -H "$KEY" -H "$JSON" \
  -d '{"name": "Ana", "phone_number": "+5491112345678"}' | jq -r .id)
FIELD_ID=$(curl -s -X POST $API/users/$USER_ID/fields -H "$KEY" -H "$JSON" \
  -d '{"name": "Lote 1", "latitude": -34.6, "longitude": -58.4}' | jq -r .id)
ALERT_ID=$(curl -s -X POST $API/fields/$FIELD_ID/alerts -H "$KEY" -H "$JSON" \
  -d '{"weather_event_type": "frost", "threshold": 10}' | jq -r .id)
curl -s -X POST $API/fields/$FIELD_ID/alerts -H "$KEY" -H "$JSON" \
  -d '{"weather_event_type": "rain", "threshold": 10}'
```

Within about two minutes, `ingest` fetches Forecasts for the new Location, `evaluate` creates a
Notification for every day that reaches the Threshold, and `notify` delivers them to Ana as one
grouped Message:

```bash
docker compose logs -f notify | grep fake_sent
```

Then read the Alert's Notification history, newest day first. To get the next page, pass
`before=<the last day received>`:

```bash
curl -s "$API/alerts/$ALERT_ID/notifications?limit=3" -H "$KEY" | jq
```

The fake WhatsApp sender rejects every phone number ending in `0000`. Repeat the steps with
`"phone_number": "+5491100000000"`, and that User's Notifications end up `failed` after one attempt.
`notify` logs `notifications.send_rejected`.

Check the workers' health and their last runs:

```bash
docker compose ps                                  # each worker shows (healthy)
docker compose exec notify python -m agrobot.worker check notify; echo $?   # 0 = healthy
docker compose exec db psql -U agrobot -c \
  "SELECT job, outcome, duration_seconds, counters, last_succeeded_at FROM job_runs"
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

## Known limitations

- Thresholds are probabilities only (0–100). Magnitude thresholds such as °C or mm are not
  supported.
- A Field on a new Location gets its first Forecast on the next `ingest` run, which can be up to
  one ingest interval later.
- There are no Prometheus metrics. Monitoring comes only from `job_runs` and the logs
  ([ADR-0009](docs/adr/0009-workers-report-health-through-job-runs.md)).
- There is no data retention: Forecasts and Notifications are never purged
  ([ADR-0006](docs/adr/0006-notifications-are-an-outbox-deduplicated-per-alert-and-day.md)).
- Messages are not persisted, so there is no provider message id for reconciling delivery
  reports ([ADR-0006](docs/adr/0006-notifications-are-an-outbox-deduplicated-per-alert-and-day.md)).
- All Users share one timezone
  ([ADR-0007](docs/adr/0007-forecast-days-use-one-configured-timezone.md)).
- Scale: on a laptop with 1M Alerts across 50k Locations, the first `evaluate` run takes about 27 s,
  and a run with nothing new to create takes about 7.5 s (2.5× slower than before batching). A Field
  update waits at most 0.06 s for a run in progress
  ([benchmark](https://github.com/lgonzalezrouco/agrobot/pull/54#issuecomment-6855313041),
  [ADR-0006](docs/adr/0006-notifications-are-an-outbox-deduplicated-per-alert-and-day.md)).

## Decisions

Design decisions are recorded as ADRs in [`docs/adr/`](docs/adr/). The domain vocabulary is in
[`GLOSSARY.md`](GLOSSARY.md).
