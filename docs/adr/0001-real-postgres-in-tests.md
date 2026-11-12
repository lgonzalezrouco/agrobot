# Tests run against real Postgres, not SQLite

Tests start their own PostgreSQL with testcontainers, apply the real Alembic migrations, and run each test in a transaction that is rolled back. We chose this over an in-memory SQLite database so that tests exercise the same SQL dialect, constraints, and migrations as production. The cost is that running the suite requires Docker.
