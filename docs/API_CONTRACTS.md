# API Contracts

## Overview

RESTful API with JSON request/response bodies. All endpoints prefixed with `/api/v1/`.

**Base URL**: `https://api.example.com/api/v1/` (production) / `http://localhost:8000/api/v1/` (dev)

**Authentication**: None for v1 (single-user demo). Future: JWT Bearer tokens.

**Content-Type**: `application/json`

**Error Format**:
```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human readable message",
    "details": {}
  }
}
```

---

## Common Response Patterns

### Success Response
```json
{
  "data": { ... },
  "meta": { ... }
}
```

### Paginated Response
```json
{
  "data": [...],
  "meta": {
    "page": 1,
    "page_size": 20,
    "total_count": 100,
    "total_pages": 5
  }
}
```

### Async Task Response
```json
{
  "data": {
    "task_id": "uuid",
    "status": "pending|processing|completed|failed",
    "result_url": "/api/v1/routes/{task_id}/"
  }
}
```

---

## Geocoding API

### Search/Autocomplete
**GET** `/geocoding/search/`

**Query Parameters**:
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| q | string | Yes | Search query (min 2 chars) |
| limit | integer | No | Max results (default: 5, max: 10) |
| lat | float | No | Bias toward latitude |
| lon | float | No | Bias toward longitude |

**Response**:
```json
{
  "data": [
    {
      "place_id": "osm_12345",
      "display_name": "123 Main St, Springfield, IL 62701, USA",
      "latitude": 39.7817,
      "longitude": -89.6501,
      "address": {
        "house_number": "123",
        "road": "Main St",
        "city": "Springfield",
        "state": "IL",
        "postcode": "62701",
        "country": "USA"
      },
      "type": "address"
    }
  ],
  "meta": {"cached": true}
}
```

### Reverse Geocoding
**GET** `/geocoding/reverse/`

**Query Parameters**:
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| lat | float | Yes | Latitude |
| lon | float | Yes | Longitude |

**Response**:
```json
{
  "data": {
    "place_id": "osm_12345",
    "display_name": "123 Main St, Springfield, IL 62701, USA",
    "latitude": 39.7817,
    "longitude": -89.6501,
    "address": { ... }
  }
}
```

---

## Routing API

### Generate Routes
**POST** `/routes/generate/`

**Request**:
```json
{
  "origin": {
    "address": "123 Main St, Springfield, IL",
    "latitude": 39.7817,
    "longitude": -89.6501
  },
  "destination": {
    "address": "456 Oak Ave, Chicago, IL",
    "latitude": 41.8781,
    "longitude": -87.6298
  },
  "departure_time": "2026-10-27T08:00:00-05:00",
  "load_weight_lbs": 45000
}
```

**Response** (202 Accepted):
```json
{
  "data": {
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "processing",
    "poll_url": "/api/v1/routes/550e8400-e29b-41d4-a716-446655440000/",
    "estimated_wait_seconds": 10
  }
}
```

### Get Route Generation Status
**GET** `/routes/{task_id}/`

**Response** (200 OK - Completed):
```json
{
  "data": {
    "request_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "completed",
    "routes": [
      {
        "id": "route_uuid_1",
        "route_index": 0,
        "name": "Fastest via I-55",
        "distance_miles": 202.5,
        "duration_minutes": 195,
        "geometry": { "type": "LineString", "coordinates": [[...]] },
        "summary": { "distance": 325800, "duration": 11700, "weight": 11700 },
        "checkpoints": [
          {
            "id": "cp_uuid_1",
            "sequence": 0,
            "mile_marker": 0.0,
            "latitude": 39.7817,
            "longitude": -89.6501,
            "estimated_arrival": "2026-10-27T08:00:00-05:00"
          },
          {
            "id": "cp_uuid_2",
            "sequence": 1,
            "mile_marker": 25.0,
            "latitude": 39.8500,
            "longitude": -89.5000,
            "estimated_arrival": "2026-10-27T08:25:00-05:00"
          }
        ]
      },
      { "route_index": 1, "name": "Shortest via US-51", ... },
      { "route_index": 2, "name": "Balanced via I-72", ... }
    ],
    "origin": { "address": "...", "latitude": 39.7817, "longitude": -89.6501 },
    "destination": { "address": "...", "latitude": 41.8781, "longitude": -87.6298 },
    "departure_time": "2026-10-27T08:00:00-05:00",
    "load_weight_lbs": 45000
  }
}
```

**Response** (200 OK - Still Processing):
```json
{
  "data": {
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "processing",
    "progress": 60,
    "message": "Fetching weather for route 2 of 3"
  }
}
```

**Response** (500 - Failed):
```json
{
  "error": {
    "code": "ROUTE_GENERATION_FAILED",
    "message": "Failed to generate routes: External routing service unavailable",
    "details": { "provider": "openrouteservice", "retry_after": 60 }
  }
}
```

### Get Route Details
**GET** `/routes/{route_id}/`

Returns single route with full checkpoints.

---

## Risk API

### Calculate Risk for Route
**POST** `/risk/calculate/`

**Request**:
```json
{
  "route_id": "route_uuid_1",
  "load_weight_lbs": 45000,
  "checkpoint_interval_miles": 25  -- 10, 25, or 50
}
```

**Response** (200 OK):
```json
{
  "data": {
    "route_id": "route_uuid_1",
    "checkpoints": [
      {
        "checkpoint_id": "cp_uuid_1",
        "mile_marker": 0.0,
        "latitude": 39.7817,
        "longitude": -89.6501,
        "estimated_arrival": "2026-10-27T08:00:00-05:00",
        "weather": {
          "temperature_f": 45.2,
          "conditions": "Light rain",
          "wind_speed_mph": 12.5,
          "wind_direction_deg": 230,
          "precipitation_rate_in_hr": 0.08,
          "precipitation_type": "rain"
        },
        "risk": {
          "wind_risk": "low",
          "rain_risk": "low",
          "snow_risk": "low",
          "combined_risk": "low",
          "load_rule_applied": null,
          "segment_miles": 25.0
        }
      },
      {
        "checkpoint_id": "cp_uuid_2",
        "mile_marker": 25.0,
        "latitude": 39.8500,
        "longitude": -89.5000,
        "estimated_arrival": "2026-10-27T08:25:00-05:00",
        "weather": {
          "temperature_f": 32.1,
          "conditions": "Heavy snow",
          "wind_speed_mph": 38.0,
          "wind_direction_deg": 310,
          "precipitation_rate_in_hr": 1.5,
          "precipitation_type": "snow",
          "snowfall_rate_in_hr": 1.5
        },
        "risk": {
          "wind_risk": "high",
          "rain_risk": "low",
          "snow_risk": "high",
          "combined_risk": "high",
          "load_rule_applied": "wind_35_44_over_40k",
          "segment_miles": 25.0
        }
      }
    ]
  }
}
```

### Get Route Recommendation
**GET** `/risk/recommendation/{route_id}/`

**Response**:
```json
{
  "data": {
    "request_id": "req_uuid",
    "recommended_route_id": "route_uuid_1",
    "routes": [
      {
        "route_id": "route_uuid_1",
        "name": "Fastest via I-55",
        "distance_miles": 202.5,
        "duration_minutes": 195,
        "score": {
          "severe_miles": 0.0,
          "high_miles": 25.0,
          "average_risk_score": 1.85,
          "duration_minutes": 195,
          "composite_score": 1.8525,
          "risk_breakdown": {
            "low": 150.0,
            "moderate": 27.5,
            "high": 25.0,
            "severe": 0.0,
            "no_travel": 0.0
          }
        },
        "is_recommended": true
      },
      {
        "route_id": "route_uuid_2",
        "name": "Shortest via US-51",
        "distance_miles": 198.0,
        "duration_minutes": 210,
        "score": { ... },
        "is_recommended": false
      }
    ]
  }
}
```

---

## Weather API

### Get Checkpoint Weather
**GET** `/weather/checkpoints/`

**Query Parameters**:
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| checkpoint_ids | string | Yes | Comma-separated UUIDs |
| forecast_time | datetime | No | Specific forecast time (default: checkpoint ETA) |

**Response**:
```json
{
  "data": [
    {
      "checkpoint_id": "cp_uuid_1",
      "forecast_time": "2026-10-27T08:25:00-05:00",
      "temperature_f": 32.1,
      "conditions": "Heavy snow",
      "wind_speed_mph": 38.0,
      "wind_direction_deg": 310,
      "precipitation_rate_in_hr": 1.5,
      "precipitation_type": "snow",
      "snowfall_rate_in_hr": 1.5,
      "humidity_pct": 85,
      "visibility_mi": 0.5
    }
  ]
}
```

### Get Weather Heatmap
**GET** `/weather/heatmap/`

**Query Parameters**:
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| route_id | uuid | Yes | Route ID |
| hour | integer | Yes | Forecast hour (0-48) |
| resolution_miles | float | No | Grid resolution (default: 10) |

**Response**:
```json
{
  "data": {
    "route_id": "route_uuid_1",
    "forecast_hour": 6,
    "bounds": {
      "north": 42.0,
      "south": 39.5,
      "east": -87.0,
      "west": -90.0
    },
    "resolution_miles": 10.0,
    "grid": [
      { "lat": 39.7817, "lon": -89.6501, "risk_level": "low", "risk_score": 1.0 },
      { "lat": 39.8500, "lon": -89.5000, "risk_level": "high", "risk_score": 3.0 },
      { "lat": 39.9200, "lon": -89.3500, "risk_level": "moderate", "risk_score": 2.0 }
    ],
    "generated_at": "2026-10-27T07:30:00Z"
  }
}
```

---

## Health Check

**GET** `/health/`

**Response**:
```json
{
  "status": "healthy",
  "checks": {
    "database": "ok",
    "redis": "ok",
    "openrouteservice": "ok",
    "openweathermap": "ok"
  },
  "version": "1.0.0",
  "timestamp": "2026-10-27T12:00:00Z"
}
```

---

## Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| VALIDATION_ERROR | 400 | Invalid request parameters |
| GEOCODING_FAILED | 400 | Could not geocode address |
| ROUTE_GENERATION_FAILED | 502 | Routing API error |
| ROUTE_NOT_FOUND | 404 | Route ID not found |
| WEATHER_API_ERROR | 502 | Weather API error |
| WEATHER_NOT_FOUND | 404 | No weather data for checkpoint |
| RISK_CALCULATION_FAILED | 500 | Internal risk calculation error |
| RATE_LIMITED | 429 | Too many requests |
| INTERNAL_ERROR | 500 | Unexpected server error |

---

## Rate Limits

| Endpoint | Limit | Window |
|----------|-------|--------|
| `/geocoding/search/` | 30 req/min | Per IP |
| `/geocoding/reverse/` | 30 req/min | Per IP |
| `/routes/generate/` | 10 req/min | Per IP |
| `/routes/{id}/` | 60 req/min | Per IP |
| `/risk/calculate/` | 30 req/min | Per IP |
| `/risk/recommendation/` | 30 req/min | Per IP |
| `/weather/checkpoints/` | 60 req/min | Per IP |
| `/weather/heatmap/` | 20 req/min | Per IP |

---

## WebSocket (Future)

For real-time updates during long-running route generation:

**Connect**: `wss://api.example.com/ws/routes/{task_id}/`

**Messages**:
```json
// Server → Client: Progress update
{"type": "progress", "data": {"progress": 45, "message": "Fetching weather..."}}

// Server → Client: Complete
{"type": "complete", "data": {"route_id": "..."}}

// Server → Client: Error
{"type": "error", "data": {"code": "...", "message": "..."}}
```

---

## OpenAPI/Swagger

Full OpenAPI 3.0 spec available at `/api/schema/` (drf-spectacular).

Interactive docs: `/api/docs/` (Swagger UI) and `/api/redoc/` (ReDoc).