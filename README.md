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
uv run python -m agrobot.worker ingest                 # worker de ingesta, en otra terminal
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

## Decisiones

Las decisiones de diseño están registradas como ADRs en [`docs/adr/`](docs/adr/). El vocabulario del dominio está en [`GLOSSARY.md`](GLOSSARY.md).
