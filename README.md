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
uv run python -m agrobot.worker                        # worker, en otra terminal
```

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

- **Postgres real en los tests** (testcontainers) en lugar de SQLite: el comportamiento de la base
  y las migraciones es el mismo que en producción.
- **SQLAlchemy async + asyncpg**: la API y el worker comparten el mismo modelo y son async de punta
  a punta.
- **API y worker como procesos separados**: escalan y se despliegan de forma independiente.
- **structlog**: logs legibles en local y JSON (`LOG_JSON=true`) para un agregador en producción.
- **uv**: entorno y lockfile reproducibles con un solo comando.
