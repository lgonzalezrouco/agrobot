# Workers report health through `job_runs`

Each worker keeps one `job_runs` row per job, overwritten by every run: when the last run started and finished, its outcome (`succeeded`, `failed` or `timed_out`), its duration, the counters the job returns (for example created, sent or retried) and when the job last succeeded. `python -m agrobot.worker check <job>` exits non-zero when the job never succeeded or its last success is older than 3 × max(interval, run time limit). Compose uses it as each worker's healthcheck, with `start_period` as the start-up grace. The workers coordinate only through the database (ADR-0002), so their health lives there too: any process with database access can read it, and the check needs nothing from the worker process. Writing the row is best effort: a failure is logged and never turns a successful run into a failed one. The API's `/health` does not look at workers.

Every run is bounded, so a hang shows up as a stale row instead of a silently stuck worker: a per-job time limit cancels the run and records it as `timed_out`, and every connection the API and workers open sets `statement_timeout` and `lock_timeout`. Alembic builds its own engine without them, so a long migration is not cut off.

## Considered Options

- **Prometheus metrics.** Deferred: it needs a scrape target and a server this project does not run yet. It can be added later on top of the same counters.
- **Logs only.** Rejected: logs alone cannot tell that a worker stopped running, and a healthcheck cannot read them.
- **A history row per run.** Rejected: health only needs the latest run, and an append-only table would need purging.

## Consequences

A run that returns normally counts as succeeded even if every Location or Message in it failed; those failures show in its counters, not in the healthcheck. Compose marks a stale worker unhealthy but does not restart it; an orchestrator that acts on health, or a person, has to. The row survives restarts, so a worker that succeeded shortly before restarting stays healthy until that success goes stale.
