# Feature Specification: F02 - Route Generation

## Business Goal
Generate 3 distinct route options between origin and destination using a routing API, returning geometry, distance, duration, and turn-by-turn instructions.

## User Flow

### Primary Flow
1. User submits valid route request (origin, destination, departure, load weight)
2. Frontend calls `POST /api/v1/routes/generate/`
3. Backend creates RouteRequest record, returns task_id immediately
4. Frontend polls `GET /api/v1/routes/{task_id}/` every 2 seconds
5. Backend Celery worker:
   - Calls external routing API for 3 route alternatives
   - Parses and validates responses
   - Saves routes + checkpoints to database
   - Enqueues weather fetching tasks
6. Polling returns completed routes with geometries
7. Frontend displays 3 route options on map

### Alternative Flows
- **Routing API fails**: Return cached routes if available, else error
- **Only 1-2 routes found**: Return what's available, mark missing
- **User cancels**: Frontend stops polling, task continues in background

---

## Service Ownership
**Owner**: Routing Service
**Frontend Components**: RouteResultsPage, useRoutes hook

---

## Database Requirements

### Tables
- `route_requests` - Track generation status
- `routes` - Store 3 route options with geometry
- `checkpoints` - Sampled points along each route (for F03)

### Queries
- Insert RouteRequest on generation start
- Bulk insert Routes + Checkpoints on completion
- Update RouteRequest status (pending → processing → completed/failed)
- Select routes by request_id for polling

---

## API Requirements

### POST /api/v1/routes/generate/
**Request**:
```json
{
  "origin": {"address": "...", "latitude": 39.78, "longitude": -89.65},
  "destination": {"address": "...", "latitude": 41.88, "longitude": -87.63},
  "departure_time": "2026-10-27T08:00:00-05:00",
  "load_weight_lbs": 45000
}
```

**Response** (202):
```json
{
  "task_id": "uuid",
  "status": "processing",
  "poll_url": "/api/v1/routes/{task_id}/",
  "estimated_wait_seconds": 10
}
```

### GET /api/v1/routes/{task_id}/
**Response** (Processing):
```json
{"task_id": "uuid", "status": "processing", "progress": 60, "message": "Fetching weather..."}
```

**Response** (Completed):
```json
{
  "request_id": "uuid",
  "status": "completed",
  "routes": [
    {
      "id": "uuid",
      "route_index": 0,
      "name": "Fastest via I-55",
      "distance_miles": 202.5,
      "duration_minutes": 195,
      "geometry": {"type": "LineString", "coordinates": [[...]]},
      "summary": {"distance": 325800, "duration": 11700, "weight": 11700},
      "checkpoints": [...]
    },
    ...
  ]
}
```

**Response** (Failed):
```json
{"error": {"code": "ROUTE_GENERATION_FAILED", "message": "...", "details": {...}}}
```

---

## Validation Requirements

### Input Validation
- Origin/destination: Valid lat/lon, not identical
- Departure time: Within 48 hours, timezone-aware
- Load weight: 10,000-80,000 lbs

### Route Validation (Post-Generation)
- Minimum 3 distinct routes (different geometries)
- Each route: Valid LineString, distance > 0, duration > 0
- Checkpoints: At least 2 per route (origin + destination)

---

## Security Requirements
- Rate limit: 10 requests/minute per IP
- Input sanitization on all string fields
- No SQL injection (Django ORM)
- Task IDs are UUIDs (unguessable)

---

## Dependencies

### External
- **OpenRouteService** (primary) - `/v2/directions/driving-hgv` with `alternative_routes.target_count=3`
- **OSRM** (fallback) - Self-hosted, `/route/v1/driving/`

### Internal
- PostgreSQL + PostGIS (route storage)
- Redis (Celery broker)
- Celery (async task processing)

---

## Edge Cases

1. **No route found**: Locations not connected by drivable roads
2. **Identical routes**: Routing API returns duplicates → Filter by geometry similarity
3. **Partial failure**: 1 of 3 routes fails → Return 2 routes with warning
4. **Very long routes**: >1000 miles → Increase checkpoint interval automatically
5. **Routing API changes**: Version pinning, response validation
6. **Coordinates out of bounds**: Validate before API call

---

## Error Handling Expectations

| Scenario | HTTP Status | User Message | System Action |
|----------|-------------|--------------|---------------|
| Invalid input | 400 | "Invalid origin/destination" | Return validation errors |
| Routing API timeout | 504 | "Routing service slow, retrying..." | Retry 2x, then fail |
| Routing API error | 502 | "Unable to generate routes" | Log, return error |
| No routes found | 404 | "No drivable route between locations" | Return error |
| Only 1 route | 200 + warning | "Only 1 route available" | Return available routes |
| DB error | 500 | "Server error, please retry" | Log, alert |

---

## Acceptance Criteria

1. ✅ Returns 3 distinct routes for typical city-to-city trips
2. ✅ Route geometry is valid GeoJSON LineString (WGS84)
3. ✅ Distance in miles (2 decimals), duration in minutes (integer)
4. ✅ Routes ordered: Fastest, Shortest, Balanced (or API default)
4. ✅ Each route has unique name/identifier
5. ✅ Async processing: Returns task_id immediately (<500ms)
6. ✅ Polling updates progress: 0% → 30% (routing) → 60% (checkpoints) → 90% (weather queue) → 100%
7. ✅ Completion within 10 seconds for routes <500 miles
8. ✅ Failed routes don't block other routes
9. ✅ Route geometries render correctly on Mapbox/Leaflet
10. ✅ Turn-by-turn instructions available in summary

---

## Success Criteria

- Route generation success rate: >98% for valid inputs
- P95 latency: <10 seconds (routing + checkpoints)
- Zero data loss on failures
- Graceful degradation: Show partial results if possible

---

## Implementation Notes

### Routing API Integration (OpenRouteService)
```python
# Request parameters
params = {
    'coordinates': [[origin_lon, origin_lat], [dest_lon, dest_lat]],
    'profile': 'driving-hgv',  # Heavy goods vehicle
    'alternative_routes': {
        'target_count': 3,
        'share_factor': 0.6,
        'weight_factor': 1.5
    },
    'instructions': True,
    'geometry': True,
    'elevation': False,
    'units': 'mi'
}
```

### Route Naming Heuristic
```python
def name_route(route, index, all_routes):
    if index == 0: return "Fastest"
    if index == 1: return "Shortest"
    if index == 2: return "Balanced"
    # Fallback: compare to others
    fastest = min(all_routes, key=lambda r: r.duration)
    shortest = min(all_routes, key=lambda r: r.distance)
    if route == fastest: return "Fastest"
    if route == shortest: return "Shortest"
    return f"Alternative {index + 1}"
```

### Checkpoint Sampling (Delegated to F03)
- Called after routes saved
- Interval: User-selected (10/25/50 miles) or default 25
- Uses `estimated_arrival = departure_time + cumulative_duration`

### Celery Task Structure
```python
@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def generate_routes(self, request_id):
    request = RouteRequest.objects.get(id=request_id)
    request.status = 'processing'
    request.save()
    
    try:
        routes_data = call_routing_api(request)
        routes = save_routes(request, routes_data)
        create_checkpoints(routes, request.checkpoint_interval)
        enqueue_weather_fetching(routes)
        request.status = 'completed'
    except RoutingAPIError as e:
        request.status = 'failed'
        request.error_message = str(e)
        raise self.retry(exc=e)
    finally:
        request.save()
```

### Geometry Simplification
- For routes >200 miles: Simplify geometry (Douglas-Peucker, tolerance 0.001°)
- Reduces payload size, improves map render performance
- Store both original + simplified, use simplified for display