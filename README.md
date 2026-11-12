# Agrobot

Sistema de alertas climáticas: API REST y worker en background sobre PostgreSQL. El enunciado está
en [`docs/TASK.md`](docs/TASK.md).

## Cómo correrlo

Requisitos: [uv](https://docs.astral.sh/uv/) y Docker.

```bash
cp .env.example .env
docker compose up -d --wait db
uv run alembic upgrade head
uv run uvicorn --factory agrobot.api.app:create_app    # API en http://localhost:8000/docs
uv run python -m agrobot.worker ingest                 # cada worker en su propia terminal
uv run python -m agrobot.worker evaluate
uv run python -m agrobot.worker notify
```

Todos los endpoints salvo `/health` piden el header `X-API-Key` con el valor de `API_KEY` de `.env`.
En `/docs` se carga con el botón *Authorize*.

`uv run` instala las dependencias la primera vez. Si el puerto 5432 está ocupado, cambiá
`POSTGRES_PORT` y el puerto de `DATABASE_URL` en `.env`.

## Cómo verificarlo

```bash
uv run pytest
curl localhost:8000/health   # {"status":"ok","database":"ok"}
```

Los tests levantan su propio Postgres con testcontainers (sólo necesitan Docker), aplican las
migraciones reales y corren cada test en una transacción que se revierte al final.

## Pendiente

Quedó afuera a propósito:

- Borrar Forecasts y Notifications viejas: hoy se acumulan sin límite.
- Una zona horaria por Location ([ADR-0007](docs/adr/0007-forecast-days-use-one-configured-timezone.md)).
- Errores de envío permanentes: el estado `failed` existe pero nada lo usa
  ([ADR-0006](docs/adr/0006-notifications-are-an-outbox-deduplicated-per-alert-and-day.md)).
- Cambiar la API key sin downtime ([ADR-0008](docs/adr/0008-the-api-is-internal-called-only-by-the-whatsapp-bot.md)).
- Los adapters reales de WhatsApp y del Weather Provider: los workers usan fakes
  ([`docs/TASK.md`](docs/TASK.md) no pide integración con WhatsApp).

## Decisiones

Las decisiones de diseño están registradas como ADRs en [`docs/adr/`](docs/adr/). El vocabulario del dominio está en [`GLOSSARY.md`](GLOSSARY.md).
