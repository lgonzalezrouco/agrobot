# A field is a point, not a boundary

A field is stored as a single latitude/longitude point, not as a polygon of its real boundary. Alerting only needs to know which forecast Location a field belongs to (see ADR-0003). At the 0.1° grid resolution almost every field falls inside one cell, so a boundary would add no value for alerting.

## Considered Options

- **A PostGIS polygon** (`geography(Polygon, 4326)`). The database validates the shape and computes the centroid and area. Rejected for now: it adds a Postgres extension, a different database image, and GeoAlchemy2 for data that nothing uses yet.
- **A GeoJSON polygon in JSONB**, validated in Python with shapely. Rejected: it adds the same complexity, and the database knows nothing about the shape.

## Consequences

A very large field that spans several grid cells gets the forecast for the cell its point falls in. A boundary can be added later as an optional column, and could then map a field to several Locations.
