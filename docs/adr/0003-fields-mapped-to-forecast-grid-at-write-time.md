# Fields are mapped to a 0.1° forecast grid when they are written

Forecasts are issued per **Location**, a point on a fixed grid with a 0.1° step (about 11 km). When a field is created or its coordinates change, its latitude and longitude are rounded to the nearest grid point, and the field references the Location for that point, fetched or created. Matching fields to forecasts once, at write time, instead of searching for nearby forecasts on every evaluation gives ingestion an explicit list of points (only Locations that have fields), lets neighboring fields share one forecast, keeps the evaluation join a simple equality, gives every field a Location that ingestion fetches from its next run on, and needs no geospatial extension.

## Considered Options

- **Proximity search at evaluation time** (find the forecast nearest the field on every run). Rejected: it needs PostGIS or unindexable distance math in SQL and a maximum distance, and alerts with no forecast in range fail silently.
- **Rounded coordinates repeated on fields and forecasts, with no Location table.** Rejected: the relationship would be implicit, and ingestion would have to derive its list of points.
- **A finer grid (0.01°).** Rejected: finer than real forecast models, so it multiplies provider calls without adding information.

## Consequences

The grid step is a code constant, not runtime configuration. Changing it means remapping every field to new Locations with a data migration. It should follow the resolution of the real weather provider.
