# Agrobot

Weather alert system: a REST API and background workers on PostgreSQL. The original task statement
(in Spanish) is in [`docs/TASK.md`](docs/TASK.md).

## Run it

Requires Docker. No `.env` is needed.

```bash
docker compose up --build
```

This starts Postgres, applies the migrations, and runs the API plus the `ingest`, `evaluate` and
`notify` workers, each in its own container. The weather provider and the WhatsApp sender are fakes,
and the workers run every minute or less so alerts show up quickly.

- API docs: <http://localhost:8000/docs>. Every endpoint except `/health` requires the header
  `X-API-Key: dev-api-key` (in `/docs`, use _Authorize_).
- If port 8000 or 5432 is taken, set `API_PORT` or `POSTGRES_PORT`.
- To change any other setting, add a `compose.override.yaml`
  ([ADR-0010](docs/adr/0010-compose-settings-are-fixed-values.md)):

```yaml
services:
  ingest:
    environment:
      INGEST_INTERVAL_SECONDS: 300
```

## Try it

With the stack running, in another terminal (needs `jq`):

```bash
API=localhost:${API_PORT:-8000}; KEY='X-API-Key: dev-api-key'; JSON='Content-Type: application/json'

USER_ID=$(curl -s -X POST $API/users -H "$KEY" -H "$JSON" \
  -d '{"name": "Ana", "phone_number": "+5491112345678"}' | jq -r .id)
FIELD_ID=$(curl -s -X POST $API/users/$USER_ID/fields -H "$KEY" -H "$JSON" \
  -d '{"name": "Lote 1", "latitude": -34.6, "longitude": -58.4}' | jq -r .id)
ALERT_ID=$(curl -s -X POST $API/fields/$FIELD_ID/alerts -H "$KEY" -H "$JSON" \
  -d '{"weather_event_type": "frost", "threshold": 10}' | jq -r .id)
```

Within about two minutes `ingest` fetches Forecasts for the new Location, `evaluate` creates a
Notification for every day that reaches the Threshold, and `notify` sends them to Ana as one
grouped Message:

```bash
docker compose logs -f notify | grep fake_sent
```

Read the Alert's Notification history, newest day first (for the next page, pass
`before=<the last day received>`):

```bash
curl -s "$API/alerts/$ALERT_ID/notifications?limit=3" -H "$KEY" | jq
```

The fake sender rejects phone numbers ending in `0000`: repeat the steps with
`"phone_number": "+5491100000000"` and that User's Notifications end up `failed` after one attempt,
with `notifications.send_rejected` in the `notify` logs.

Check the workers' health and last runs:

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
curl localhost:8000/health                             # {"status":"ok","database":"ok"}
```

## Test it

```bash
uv run pytest   # needs Docker; starts its own Postgres (ADR-0001)
```

## Known limitations

- Thresholds are probabilities only (0–100), not magnitudes such as °C or mm
  ([GLOSSARY](GLOSSARY.md)).
- A Field on a new Location gets its first Forecast on the next `ingest` run, up to one ingest
  interval later
  ([ADR-0003](docs/adr/0003-fields-mapped-to-forecast-grid-at-write-time.md)).
- No Prometheus metrics. Monitoring is `job_runs` and the logs
  ([ADR-0009](docs/adr/0009-workers-report-health-through-job-runs.md)).
- No data retention: Forecasts and Notifications are never purged.
- Messages are not persisted, so there is no provider message id to reconcile delivery reports
  ([ADR-0006](docs/adr/0006-notifications-are-an-outbox-deduplicated-per-alert-and-day.md)).
- All Users share one timezone
  ([ADR-0007](docs/adr/0007-forecast-days-use-one-configured-timezone.md)).

## Decisions

- [Tests run on real Postgres, not SQLite](docs/adr/0001-real-postgres-in-tests.md)
- [API and each job are separate processes](docs/adr/0002-api-and-worker-as-separate-processes.md)
- [Fields snap to a 0.1° Location grid on write](docs/adr/0003-fields-mapped-to-forecast-grid-at-write-time.md)
- [One Alert per Field and event type](docs/adr/0004-one-alert-per-field-and-weather-event-type.md)
- [A Field is a point, not a boundary](docs/adr/0005-field-is-a-point-not-a-boundary.md)
- [Notifications are the outbox, one per Alert and day](docs/adr/0006-notifications-are-an-outbox-deduplicated-per-alert-and-day.md)
- [One configured timezone for forecast days](docs/adr/0007-forecast-days-use-one-configured-timezone.md)
- [Internal API behind one shared key](docs/adr/0008-the-api-is-internal-called-only-by-the-whatsapp-bot.md)
- [Worker health lives in `job_runs`](docs/adr/0009-workers-report-health-through-job-runs.md)
- [Compose settings are fixed values](docs/adr/0010-compose-settings-are-fixed-values.md)

Details and rejected options are in [`docs/adr/`](docs/adr/). The domain vocabulary is in
[`GLOSSARY.md`](GLOSSARY.md).
