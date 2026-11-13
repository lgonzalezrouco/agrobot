# Compose settings are fixed values

`compose.yaml` sets every application setting to a fixed value instead of interpolating `${VAR:-default}`. Only `API_PORT` and `POSTGRES_PORT` stay interpolated, because a port already taken on the host is a property of that machine. The `.env` created for running without Docker is also read by Compose for interpolation, so with interpolated settings it silently changed the Compose run: copying `.env.example` turned the 60-second ingest interval into an hour and swapped the API key. Overrides go in a `compose.override.yaml`, which Compose merges automatically and which is not committed.

## Considered Options

- **Keep interpolation with a separate env file name for the no-Docker path.** Rejected: pydantic-settings reads `.env`, and every developer would still be one `cp` away from the same surprise.

## Consequences

`docker compose up` behaves the same on every machine. Changing a setting for Compose takes a few lines of YAML instead of an environment variable.
