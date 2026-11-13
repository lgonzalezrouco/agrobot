# Fields are mapped to a 0.1° forecast grid when they are written

Forecasts are issued per **Location**, which is a point on a fixed grid with a 0.1° step (about 11 km). When a field is created or its coordinates change, its exact latitude and longitude are rounded to the nearest grid point. The Location for that point is fetched or created, and the field keeps a reference to it. We match fields to forecasts once, at write time, instead of searching for nearby forecasts every time alerts are evaluated. This gives ingestion an explicit list of points to fetch (only Locations that have fields), lets neighboring fields share a single forecast, keeps the evaluation join a simple equality, and means every field has a Location that ingestion fetches forecasts for, from its next run on. It also requires no geospatial extension.

## Considered Options

- **Proximity search at evaluation time** (find the forecast nearest the field's coordinates on every run). Rejected: it needs PostGIS or unindexable distance math in SQL, it needs a maximum distance, and alerts with no forecast in range fail silently.
- **Rounded coordinates repeated on fields and forecasts, with no Location table.** Rejected: the relationship would be implicit, and ingestion would have to derive its list of points.
- **A finer grid (0.01°).** Rejected: this is finer than real forecast models, so it would multiply provider calls without adding information.

## Consequences

The grid step is a code constant, not runtime configuration. Changing it means remapping every field to new Locations with a data migration. It should follow the resolution of the real weather provider.
