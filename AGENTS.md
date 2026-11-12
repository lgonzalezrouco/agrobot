# Agrobot

FastAPI API plus an async background worker on PostgreSQL. Python 3.13, managed with **uv** — run
everything through `uv run`.

## Commands

```bash
uv run pytest                    # needs Docker running; starts its own Postgres
uv run uvicorn --factory agrobot.api.app:create_app --reload
uv run python -m agrobot.worker
```

## Before writing code

Read `CODING_STANDARDS.md` before adding or changing code: feature layout, async rules,
transactions, models and migrations, logging, and test fixtures.

## Agent skills

### Issue tracker

Issues live in GitHub Issues for `lgonzalezrouco/agrobot`, managed with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
