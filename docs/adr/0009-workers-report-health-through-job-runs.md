# Workers report health through `job_runs`

Each worker records every run of its job in the `job_runs` table: one row per job, overwritten by each run, holding when the last run started and finished, its outcome (`succeeded`, `failed` or `timed_out`), its duration, the counters the job returns (for example created, sent or retried) and when the job last succeeded. `python -m agrobot.worker check <job>` reads that row and exits non-zero when the last success is older than 3 × max(interval, run time limit) or the job never succeeded; Compose uses it as each worker's healthcheck, with `start_period` as the start-up grace. The workers coordinate only through the database (ADR-0002), so their health lives there too: any process with database access can see it, and the check needs nothing from the worker process itself. Writing the row is best effort: a failure is logged and never turns a successful run into a failed one. The API's `/health` does not look at workers.

Every run is bounded so a hang shows up as a stale row instead of a worker that is silently stuck: each run has a per-job time limit after which it is cancelled and recorded as `timed_out`, and every database connection sets `statement_timeout` and `lock_timeout`.

## Considered Options

- **Prometheus metrics.** Deferred: it needs a scrape target and a server this project does not run yet. It can be added later on top of the same counters.
- **Logs only.** Rejected: nothing can tell from logs alone that a worker stopped running, and a healthcheck cannot read them.
- **A history row per run.** Rejected: health only needs the latest run, and an append-only table would need purging.

## Consequences

A run that returns normally counts as succeeded even if every Location or Message inside it failed; those failures show up in its counters, not in the healthcheck. Docker Compose marks a stale worker unhealthy but does not restart it; an orchestrator that acts on health (or a person) has to. The row survives restarts, so a worker that succeeded recently before restarting stays healthy until its last success goes stale.
