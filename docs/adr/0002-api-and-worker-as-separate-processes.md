# The API and each background job run as separate processes

The FastAPI app and the background jobs share code and models but run as separate processes, and each job runs in its own worker process, selected by a subcommand (`python -m agrobot.worker ingest`, `evaluate` or `notify`). The API and each job then scale and deploy independently: `notify` can get more replicas without multiplying forecast ingestion, and periodic work never competes with request handling. `ingest` and `evaluate` run as a single replica: every `evaluate` run reads all Alerts, so extra replicas repeat the work instead of sharing it. The cost is more processes to run, which can coordinate only through the database.

## Considered Options

- **One worker process running every job** on separate loops in an `asyncio.TaskGroup`. Rejected: scaling one job means scaling all of them, and ingestion would repeat calls to the weather provider on every replica.
