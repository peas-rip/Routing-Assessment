# Database Schema

## Overview

PostgreSQL 16 with PostGIS 3.4 extension for geospatial data.

## Extensions Required

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- For geocoding search
```

---

## Tables

### 1. route_requests
Tracks route generation requests for async processing.

```sql
CREATE TABLE route_requests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    origin_address TEXT NOT NULL,
    origin_lat DOUBLE PRECISION NOT NULL,
    origin_lon DOUBLE PRECISION NOT NULL,
    destination_address TEXT NOT NULL,
    destination_lat DOUBLE PRECISION NOT NULL,
    destination_lon DOUBLE PRECISION NOT NULL,
    departure_time TIMESTAMPTZ NOT NULL,
    load_weight_lbs INTEGER NOT NULL CHECK (load_weight_lbs > 0),
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX idx_route_requests_status ON route_requests(status);
CREATE INDEX idx_route_requests_created_at ON route_requests(created_at DESC);
```

### 2. routes
Stores generated route options.

```sql
CREATE TABLE routes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id UUID NOT NULL REFERENCES route_requests(id) ON DELETE CASCADE,
    route_index INTEGER NOT NULL CHECK (route_index IN (0, 1, 2)),  -- 0, 1, 2 for 3 options
    name VARCHAR(100),  -- e.g., "Fastest", "Shortest", "Balanced"
    distance_miles DECIMAL(10, 2) NOT NULL,
    duration_minutes INTEGER NOT NULL,
    geometry GEOMETRY(LINESTRING, 4326) NOT NULL,  -- Full route geometry
    summary JSONB NOT NULL,  -- OSRM summary: {distance, duration, weight, ...}
    is_recommended BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_routes_request_id ON routes(request_id);
CREATE INDEX idx_routes_geometry ON routes USING GIST (geometry);
```

### 3. checkpoints
Weather sampling points along routes.

```sql
CREATE TABLE checkpoints (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    route_id UUID NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,  -- Order along route (0, 1, 2, ...)
    mile_marker DECIMAL(10, 2) NOT NULL,  -- Miles from origin
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    location GEOGRAPHY(POINT, 4326) NOT NULL,  -- For distance queries
    estimated_arrival TIMESTAMPTZ NOT NULL,  -- Based on departure + travel time
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_checkpoints_route_id ON checkpoints(route_id);
CREATE INDEX idx_checkpoints_location ON checkpoints USING GIST (location);
CREATE INDEX idx_checkpoints_arrival ON checkpoints(estimated_arrival);
CREATE UNIQUE INDEX idx_checkpoints_route_seq ON checkpoints(route_id, sequence);
```

### 4. weather_observations
Cached weather data for checkpoints.

```sql
CREATE TABLE weather_observations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    checkpoint_id UUID NOT NULL REFERENCES checkpoints(id) ON DELETE CASCADE,
    forecast_time TIMESTAMPTZ NOT NULL,  -- Time this forecast is valid for
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  -- When we fetched it
    -- Wind
    wind_speed_mph DECIMAL(5, 2),
    wind_direction_deg INTEGER,
    wind_gust_mph DECIMAL(5, 2),
    -- Precipitation
    precipitation_rate_in_hr DECIMAL(5, 3),  -- in/hr (rain/snow equivalent)
    precipitation_type VARCHAR(20)  -- 'rain', 'snow', 'none', 'mixed'
        CHECK (precipitation_type IN ('rain', 'snow', 'none', 'mixed')),
    -- Snow specific
    snowfall_rate_in_hr DECIMAL(5, 3),
    snow_depth_in DECIMAL(5, 2),
    -- General
    temperature_f DECIMAL(5, 2),
    humidity_pct INTEGER,
    visibility_mi DECIMAL(5, 2),
    conditions VARCHAR(100),  -- Human readable: "Light rain", "Heavy snow"
    raw_response JSONB NOT NULL,  -- Full API response for debugging
    source VARCHAR(50) NOT NULL DEFAULT 'openweathermap'
);

CREATE INDEX idx_weather_checkpoint_time ON weather_observations(checkpoint_id, forecast_time);
CREATE INDEX idx_weather_fetched_at ON weather_observations(fetched_at DESC);
CREATE UNIQUE INDEX idx_weather_unique ON weather_observations(checkpoint_id, forecast_time, source);
```

### 5. risk_assessments
Calculated risk per checkpoint.

```sql
CREATE TABLE risk_assessments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    checkpoint_id UUID NOT NULL REFERENCES checkpoints(id) ON DELETE CASCADE,
    weather_observation_id UUID NOT NULL REFERENCES weather_observations(id) ON DELETE CASCADE,
    load_weight_lbs INTEGER NOT NULL,
    -- Individual condition risks
    wind_risk VARCHAR(20) NOT NULL
        CHECK (wind_risk IN ('low', 'moderate', 'high', 'severe', 'no_travel')),
    rain_risk VARCHAR(20) NOT NULL
        CHECK (rain_risk IN ('low', 'moderate', 'high', 'severe', 'no_travel')),
    snow_risk VARCHAR(20) NOT NULL
        CHECK (snow_risk IN ('low', 'moderate', 'high', 'severe', 'no_travel')),
    -- Combined risk (highest of the three, with load escalation)
    combined_risk VARCHAR(20) NOT NULL
        CHECK (combined_risk IN ('low', 'moderate', 'high', 'severe', 'no_travel')),
    -- Load rule flags
    load_rule_applied VARCHAR(50),  -- e.g., 'wind_45_54_over_30k', 'wind_35_44_over_40k'
    -- Mileage at this risk level
    segment_miles DECIMAL(10, 2) NOT NULL,  -- Miles this checkpoint represents
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_risk_checkpoint ON risk_assessments(checkpoint_id);
CREATE INDEX idx_risk_combined ON risk_assessments(combined_risk);
```

### 6. route_scores
Computed scores for route recommendation.

```sql
CREATE TABLE route_scores (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    route_id UUID NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    -- Priority 1: Fewest Severe miles
    severe_miles DECIMAL(10, 2) NOT NULL DEFAULT 0,
    -- Priority 2: Fewest High miles
    high_miles DECIMAL(10, 2) NOT NULL DEFAULT 0,
    -- Priority 3: Lowest average risk (numeric: low=1, moderate=2, high=3, severe=4, no_travel=5)
    average_risk_score DECIMAL(5, 3) NOT NULL,
    -- Priority 4: Shortest travel time
    duration_minutes INTEGER NOT NULL,
    -- Composite score for sorting (lower is better)
    composite_score DECIMAL(10, 3) NOT NULL,
    -- Breakdown for display
    risk_breakdown JSONB NOT NULL,  -- {"low": 120.5, "moderate": 45.2, "high": 10.0, "severe": 0, "no_travel": 0}
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_route_scores_route ON route_scores(route_id);
```

### 7. geocode_cache
Cached geocoding results for autocomplete and reverse geocoding.

```sql
CREATE TABLE geocode_cache (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    query_text TEXT NOT NULL,  -- Search query or "lat,lon" for reverse
    query_type VARCHAR(20) NOT NULL  -- 'forward', 'reverse', 'autocomplete'
        CHECK (query_type IN ('forward', 'reverse', 'autocomplete')),
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    display_name TEXT,  -- Formatted address
    address_components JSONB,  -- Structured: {house_number, road, city, state, postcode, country}
    raw_response JSONB,
    source VARCHAR(50) NOT NULL,  -- 'openrouteservice', 'nominatim'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_geocode_query ON geocode_cache(query_text, query_type);
CREATE INDEX idx_geocode_expires ON geocode_cache(expires_at);
CREATE INDEX idx_geocode_location ON geocode_cache(latitude, longitude);
```

### 8. heatmap_cache
Pre-computed weather heatmap grids for routes.

```sql
CREATE TABLE heatmap_cache (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    route_id UUID NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    forecast_hour INTEGER NOT NULL CHECK (forecast_hour BETWEEN 0 AND 48),
    -- Grid data: array of {lat, lon, risk_level, risk_score}
    grid_data JSONB NOT NULL,
    bounds JSONB NOT NULL,  -- {north, south, east, west}
    resolution_miles DECIMAL(5, 2) NOT NULL,  -- Grid spacing
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_heatmap_route_hour ON heatmap_cache(route_id, forecast_hour);
CREATE INDEX idx_heatmap_expires ON heatmap_cache(expires_at);
```

---

## Views

### route_summary_view
Aggregated route info for listing.

```sql
CREATE VIEW route_summary_view AS
SELECT
    r.id,
    r.request_id,
    r.route_index,
    r.name,
    r.distance_miles,
    r.duration_minutes,
    r.is_recommended,
    rs.severe_miles,
    rs.high_miles,
    rs.average_risk_score,
    rs.risk_breakdown,
    rr.origin_address,
    rr.destination_address,
    rr.departure_time,
    rr.load_weight_lbs
FROM routes r
JOIN route_requests rr ON r.request_id = rr.id
LEFT JOIN route_scores rs ON r.id = rs.route_id;
```

### checkpoint_risk_view
Checkpoints with risk info for map rendering.

```sql
CREATE VIEW checkpoint_risk_view AS
SELECT
    c.id,
    c.route_id,
    c.sequence,
    c.mile_marker,
    c.latitude,
    c.longitude,
    c.estimated_arrival,
    ra.wind_risk,
    ra.rain_risk,
    ra.snow_risk,
    ra.combined_risk,
    ra.load_rule_applied,
    ra.segment_miles,
    wo.temperature_f,
    wo.conditions,
    wo.precipitation_rate_in_hr,
    wo.wind_speed_mph
FROM checkpoints c
JOIN risk_assessments ra ON c.id = ra.checkpoint_id
JOIN weather_observations wo ON ra.weather_observation_id = wo.id;
```

---

## Triggers

### Updated_at Trigger
```sql
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_route_requests_updated_at
    BEFORE UPDATE ON route_requests
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
```

### Auto-expire Cleanup (pg_cron or scheduled task)
```sql
-- Delete expired cache entries (run daily)
DELETE FROM geocode_cache WHERE expires_at < NOW();
DELETE FROM heatmap_cache WHERE expires_at < NOW();
DELETE FROM weather_observations WHERE fetched_at < NOW() - INTERVAL '7 days';
```

---

## Django Models Mapping

```python
# backend/apps/routing/models.py
class RouteRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    origin_address = models.TextField()
    origin_lat = models.FloatField()
    origin_lon = models.FloatField()
    destination_address = models.TextField()
    destination_lat = models.FloatField()
    destination_lon = models.FloatField()
    departure_time = models.DateTimeField()
    load_weight_lbs = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    error_message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

class Route(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(RouteRequest, on_delete=models.CASCADE, related_name='routes')
    route_index = models.IntegerField(choices=[(0, 0), (1, 1), (2, 2)])
    name = models.CharField(max_length=100, blank=True)
    distance_miles = models.DecimalField(max_digits=10, decimal_places=2)
    duration_minutes = models.PositiveIntegerField()
    geometry = models.LineStringField(srid=4326)  # PostGIS
    summary = models.JSONField()
    is_recommended = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

class Checkpoint(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name='checkpoints')
    sequence = models.PositiveIntegerField()
    mile_marker = models.DecimalField(max_digits=10, decimal_places=2)
    latitude = models.FloatField()
    longitude = models.FloatField()
    location = models.PointField(srid=4326, geography=True)
    estimated_arrival = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sequence']
        indexes = [
            models.Index(fields=['route', 'sequence']),
            models.Index(fields=['estimated_arrival']),
        ]
```

```python
# backend/apps/weather/models.py
class WeatherObservation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    checkpoint = models.ForeignKey('routing.Checkpoint', on_delete=models.CASCADE, related_name='weather_observations')
    forecast_time = models.DateTimeField()
    fetched_at = models.DateTimeField(auto_now_add=True)
    wind_speed_mph = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    wind_direction_deg = models.IntegerField(null=True, blank=True)
    wind_gust_mph = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    precipitation_rate_in_hr = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True)
    precipitation_type = models.CharField(max_length=20, choices=PrecipType.choices)
    snowfall_rate_in_hr = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True)
    snow_depth_in = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    temperature_f = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    humidity_pct = models.IntegerField(null=True, blank=True)
    visibility_mi = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    conditions = models.CharField(max_length=100, blank=True)
    raw_response = models.JSONField()
    source = models.CharField(max_length=50, default='openweathermap')

    class Meta:
        indexes = [
            models.Index(fields=['checkpoint', 'forecast_time']),
            models.Index(fields=['fetched_at']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['checkpoint', 'forecast_time', 'source'], name='unique_weather_obs')
        ]
```

```python
# backend/apps/risk/models.py
class RiskAssessment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    checkpoint = models.OneToOneField('routing.Checkpoint', on_delete=models.CASCADE, related_name='risk_assessment')
    weather_observation = models.OneToOneField('weather.WeatherObservation', on_delete=models.CASCADE, related_name='risk_assessment')
    load_weight_lbs = models.PositiveIntegerField()
    wind_risk = models.CharField(max_length=20, choices=RiskLevel.choices)
    rain_risk = models.CharField(max_length=20, choices=RiskLevel.choices)
    snow_risk = models.CharField(max_length=20, choices=RiskLevel.choices)
    combined_risk = models.CharField(max_length=20, choices=RiskLevel.choices)
    load_rule_applied = models.CharField(max_length=50, blank=True)
    segment_miles = models.DecimalField(max_digits=10, decimal_places=2)
    calculated_at = models.DateTimeField(auto_now_add=True)

class RouteScore(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    route = models.OneToOneField('routing.Route', on_delete=models.CASCADE, related_name='score')
    severe_miles = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    high_miles = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    average_risk_score = models.DecimalField(max_digits=5, decimal_places=3)
    duration_minutes = models.PositiveIntegerField()
    composite_score = models.DecimalField(max_digits=10, decimal_places=3)
    risk_breakdown = models.JSONField()
    calculated_at = models.DateTimeField(auto_now_add=True)
```

---

## Migration Strategy

1. **Initial Migration**: Create all tables, indexes, extensions
2. **Data Migrations**: None needed for v1 (empty database)
3. **Future Changes**: 
   - Add columns with defaults (non-breaking)
   - New tables for new features
   - Never drop columns in production without deprecation period

---

## Query Patterns & Optimization

### Common Queries

```sql
-- Get route with checkpoints and risk for map display
SELECT c.*, ra.combined_risk, ra.segment_miles
FROM checkpoints c
JOIN risk_assessments ra ON c.id = ra.checkpoint_id
WHERE c.route_id = $1
ORDER BY c.sequence;

-- Get weather for heatmap (corridor query)
SELECT latitude, longitude, combined_risk
FROM checkpoint_risk_view
WHERE route_id = $1
  AND estimated_arrival BETWEEN $2 AND $3;  -- Time window

-- Route recommendation ranking
SELECT r.*, rs.composite_score
FROM routes r
JOIN route_scores rs ON r.id = rs.route_id
WHERE r.request_id = $1
ORDER BY rs.composite_score ASC;
```

### Indexing Strategy
- **Primary Keys**: UUID (automatic index)
- **Foreign Keys**: Explicit indexes on all FK columns
- **Geospatial**: GIST indexes on geometry/geography columns
- **Time-series**: BRIN indexes on `created_at`/`fetched_at` for large tables
- **Composite**: `(route_id, sequence)` for ordered checkpoint fetching

---

## Data Retention

| Table | Retention | Archive Strategy |
|-------|-----------|------------------|
| route_requests | 90 days | Move to cold storage |
| routes | 90 days | Move with request |
| checkpoints | 90 days | Move with route |
| weather_observations | 7 days | Auto-delete (cache) |
| risk_assessments | 90 days | Move with checkpoint |
| route_scores | 90 days | Move with route |
| geocode_cache | 30 days | Auto-delete (TTL) |
| heatmap_cache | 48 hours | Auto-delete (TTL) |