# Agrobot

Weather alert system: a REST API and background workers on PostgreSQL. The original task statement
(in Spanish) is in [`docs/TASK.md`](docs/TASK.md).

## How it works

A User adds Fields and creates Alerts for them. Agrobot gets weather Forecasts for each Field. When
a Forecast reaches the Threshold of an Alert, Agrobot tells the User in a WhatsApp Message.

Three workers and the API do the work. Each one is a separate process. They share only the
Postgres database.

```text
ingest    Weather Provider → Forecasts for every Location with Fields, 7 days ahead
evaluate  Alerts × Forecasts → one Notification per Alert and day that reaches the Threshold
notify    pending Notifications → Messages grouping each User's Notifications (up to 20)
API       Users, Fields, Alerts and each Alert's Notification history
```

1. `ingest` gets Forecasts from the Weather Provider for the next 7 days. It does this only for
   Locations that have Fields. Near Fields share one Location, so they share one request.
2. `evaluate` compares each Forecast with the Threshold of each Alert at that Location. It creates
   one Notification for each Alert and day when the probability is at or above the Threshold.
3. `notify` puts the pending Notifications of each User into Messages, with a maximum of 20
   Notifications in each Message. Then it sends the Messages.

### When delivery fails

- **The sender has a temporary problem:** the Notifications stay `pending`. `notify` tries again
  later. The wait time doubles after each failed attempt, up to a maximum.
- **The sender rejects the Message permanently:** for example, the phone number does not exist.
  The Notifications become `failed`, and `notify` does not try again.
- **The day passes before delivery:** the Notifications become `expired`. A Forecast for a past
  day is not useful.
- **A `notify` worker stops during a delivery:** before it sends, `notify` reserves the
  Notifications for a limited time (a lease). When the lease ends, a different run can send them.
  Thus you can run more than one `notify` worker, and two workers never send the same Message at
  the same time.

Each worker records each run in the `job_runs` table. The healthcheck marks a worker unhealthy if
it has no recent successful run.

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

These steps create one User with one Field and one Alert. Then they show the Message that the
User receives. The stack must be running, and you need `jq`.

### 1. Create a User, a Field and an Alert

In a different terminal, run:

```bash
API=localhost:${API_PORT:-8000}; KEY='X-API-Key: dev-api-key'; JSON='Content-Type: application/json'

USER_ID=$(curl -s -X POST $API/users -H "$KEY" -H "$JSON" \
  -d '{"name": "Ana", "phone_number": "+5491112345678"}' | jq -r .id)
FIELD_ID=$(curl -s -X POST $API/users/$USER_ID/fields -H "$KEY" -H "$JSON" \
  -d '{"name": "Lote 1", "latitude": -34.6, "longitude": -58.4}' | jq -r .id)
ALERT_ID=$(curl -s -X POST $API/fields/$FIELD_ID/alerts -H "$KEY" -H "$JSON" \
  -d '{"weather_event_type": "frost", "threshold": 10}' | jq -r .id)
```

This Alert tells Ana about each day when the probability of frost at "Lote 1" is 10% or more.

If you run the steps again, `POST /users` returns `409` because the phone number is already
registered. Then `USER_ID` is `null` and all the subsequent requests fail. To use the User that
exists, get its ID from the phone number:

```bash
USER_ID=$(curl -s -G $API/users -H "$KEY" --data-urlencode 'phone_number=+5491112345678' | jq -r .id)
```

### 2. Wait for the workers

Three workers do these steps, one after the other. In Docker Compose, each worker runs at least
once every 60 seconds, so the full sequence takes approximately two minutes.

1. `ingest` gets the Forecasts for the Location of "Lote 1" for the next 7 days. The fake Weather
   Provider calculates each probability from the Location, the day and the Weather Event Type.
   Thus the same Location always gets the same Forecast for a given day.
2. `evaluate` compares each frost Forecast with the Threshold of the Alert. It creates one
   Notification for each day when the probability is at or above the Threshold.
3. `notify` puts the pending Notifications of Ana into one Message, with a maximum of 20. The fake
   sender does not send the Message. It writes the Message to the `notify` log.

### 3. Read the Message

```bash
docker compose logs -f notify | grep fake_sent
```

Each `notifications.fake_sent` line is one Message. The `text` field is the Message as Ana reads
it, for example:

```text
Weather alert
- Lote 1: frost on Sat 2026-11-14, 80% chance (your threshold: 10%)
- Lote 1: frost on Mon 2026-11-16, 35% chance (your threshold: 10%)
```

In the log, `\n` shows each line break. The `notifications` field has the same data as separate
values.

If no line appears, no Forecast reached the Threshold. Use step 4 to make sure.

### 4. Read the Notification history

```bash
curl -s "$API/alerts/$ALERT_ID/notifications?limit=3" -H "$KEY" | jq
```

The API returns the Notifications of the Alert, newest day first. Each Notification shows its
`status`:

- `pending`: not delivered yet. `notify` tries again later.
- `sent`: delivered in a Message.
- `failed`: the sender rejected the Message permanently. `notify` does not try again.
- `expired`: the day passed before delivery.

To get the next page, set `before` to the last `day` that you received.

### 5. See a failed delivery

The fake sender rejects all phone numbers that end in `0000`. To see this, do steps 1 and 2 again
with `"phone_number": "+5491100000000"`. Step 3 shows no `fake_sent` line for this User, because
no Message is sent. Instead, the `notify` log shows the rejection:

```bash
docker compose logs notify | grep send_rejected
```

In step 4, each Notification of the new Alert shows `"status": "failed"` and `"attempts": 1`.
`notify` does not try again.

### 6. Check the workers

Each worker records each run in the `job_runs` table. The healthcheck reads this table.

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
