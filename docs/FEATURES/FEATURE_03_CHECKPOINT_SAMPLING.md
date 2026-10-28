# Feature Specification: F03 - Checkpoint Sampling

## Business Goal
Sample weather checkpoints along each route at configurable intervals (10/25/50 miles) with accurate estimated arrival times based on departure time and route travel time.

## User Flow

### Primary Flow (Internal)
1. Route generation completes (F02)
2. Routing Service calls `create_checkpoints()` for each route
3. For each route:
   - Calculate cumulative distance along geometry
   - Place checkpoints at every N miles (10/25/50)
   - Always include origin (mile 0) and destination (final mile)
   - Calculate estimated_arrival = departure_time + (mile_marker / avg_speed * 60)
4. Save checkpoints to database
5. Enqueue weather fetching for all new checkpoints

### User-Controlled
- User selects checkpoint interval: 10, 25, or 50 miles (default: 25)
- Interval can be changed after route generation → Re-sample checkpoints

---

## Service Ownership
**Owner**: Routing Service (part of route generation pipeline)
**Frontend**: Displays checkpoints on map, allows interval selection

---

## Database Requirements

### Tables
- `checkpoints` - One per sampling point per route

### Fields
| Field | Type | Description |
|-------|------|-------------|
| route_id | UUID | FK to routes |
| sequence | Integer | Order along route (0, 1, 2...) |
| mile_marker | Decimal(10,2) | Miles from origin |
| latitude | Float | Checkpoint latitude |
| longitude | Float | Checkpoint longitude |
| location | Geography(Point, 4326) | PostGIS point for spatial queries |
| estimated_arrival | DateTimeTZ | Calculated ETA at this point |

### Indexes
- `(route_id, sequence)` - Ordered fetch
- `(location)` - Spatial queries (future)
- `(estimated_arrival)` - Time-based weather fetching

---

## API Requirements

### Checkpoint Data Included in Route Response
```json
{
  "checkpoints": [
    {
      "id": "uuid",
      "sequence": 0,
      "mile_marker": 0.0,
      "latitude": 39.7817,
      "longitude": -89.6501,
      "estimated_arrival": "2026-10-27T08:00:00-05:00"
    },
    {
      "id": "uuid",
      "sequence": 1,
      "mile_marker": 25.0,
      "latitude": 39.8500,
      "longitude": -89.5000,
      "estimated_arrival": "2026-10-27T08:25:00-05:00"
    }
  ]
}
```

### Re-sample Endpoint (Future)
`POST /api/v1/routes/{route_id}/resample/` with `{ "interval_miles": 10 }`

---

## Validation Requirements

### Checkpoint Generation
- Interval must be 10, 25, or 50 miles
- Minimum 2 checkpoints per route (origin + destination)
- Maximum: Route distance / 10 (e.g., 1000 miles / 10 = 100 checkpoints)
- Sequence numbers contiguous starting at 0
- Mile markers monotonically increasing
- Estimated arrivals monotonically increasing

### Geometry Accuracy
- Checkpoint coordinates must lie ON the route geometry
- Use linear interpolation along LineString
- Precision: 6 decimal places (~0.11m)

---

## Security Requirements
- No direct user input (internal calculation)
- Validate route_id exists and belongs to user (future auth)

---

## Dependencies

### Internal
- Routing Service: Needs route geometry, distance, duration
- Weather Service: Consumes checkpoints for weather fetching

### External
- None (pure computation)

---

## Edge Cases

1. **Short routes** (< interval): Only origin + destination checkpoints
2. **Exact interval match**: Destination may not align with interval → Always include destination
3. **Route geometry gaps**: Handle MultiLineString (ferries, etc.) - skip non-drivable segments
4. **Speed variation**: Use average speed = distance / duration for ETA calculation
5. **Timezone handling**: departure_time is TZ-aware, estimated_arrival preserves TZ
6. **Daylight saving**: Use UTC internally, convert for display

---

## Error Handling Expectations

| Scenario | Handling |
|----------|----------|
| Invalid route geometry | Log error, skip route, alert monitoring |
| Distance calculation fails | Use fallback: equal time intervals |
| Database constraint violation | Retry once, then fail task |
| Interval not in (10,25,50) | Default to 25, log warning |

---

## Acceptance Criteria

1. ✅ Checkpoints at exact mile intervals (10, 25, or 50)
2. ✅ Origin always sequence 0, mile_marker 0.0
3. ✅ Destination always last sequence, mile_marker = route distance
4. ✅ Coordinates lie on route geometry (within 1m)
5. ✅ Estimated arrival times are monotonically increasing
6. ✅ Time calculation: `departure + (mile_marker / total_distance * total_duration)`
7. ✅ Interval change triggers re-sampling
8. ✅ Performance: <100ms per route for checkpoint generation
9. ✅ Handles routes up to 2000 miles
10. ✅ Works with complex geometries (curves, loops)

---

## Success Criteria

- Checkpoint accuracy: <0.1 mile error vs interval
- ETA accuracy: Within 2 minutes of actual (assuming constant speed)
- Zero checkpoint generation failures in production

---

## Implementation Notes

### Distance Along LineString (PostGIS)
```sql
-- Get point at distance along line
SELECT ST_AsText(ST_LineInterpolatePoint(geometry, distance / ST_Length(geometry::geography)))
FROM routes WHERE id = %s;
```

### Python Implementation (Shapely + PyProj)
```python
from shapely.geometry import LineString, Point
from shapely.ops import transform
from pyproj import Transformer

def sample_checkpoints(route_geometry: LineString, total_distance_miles: float, 
                       total_duration_minutes: int, interval_miles: float,
                       departure_time: datetime) -> List[Checkpoint]:
    """Sample checkpoints along route at regular mile intervals."""
    
    # Project to local UTM for accurate distance
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    projected_line = transform(transformer.transform, route_geometry)
    total_distance_m = projected_line.length
    
    interval_m = interval_miles * 1609.34  # miles to meters
    num_intervals = int(total_distance_m / interval_m)
    
    checkpoints = []
    
    # Origin
    checkpoints.append(Checkpoint(
        sequence=0,
        mile_marker=0.0,
        latitude=route_geometry.coords[0][1],
        longitude=route_geometry.coords[0][0],
        estimated_arrival=departure_time
    ))
    
    # Intermediate checkpoints
    for i in range(1, num_intervals + 1):
        distance_m = i * interval_m
        if distance_m >= total_distance_m:
            break
            
        fraction = distance_m / total_distance_m
        point = projected_line.interpolate(distance_m, normalized=False)
        # Convert back to WGS84
        lon, lat = transformer.transform(point.x, point.y, direction='INVERSE')
        
        mile_marker = distance_m / 1609.34
        # ETA: proportional to distance
        elapsed_minutes = (mile_marker / total_distance_miles) * total_duration_minutes
        estimated_arrival = departure_time + timedelta(minutes=elapsed_minutes)
        
        checkpoints.append(Checkpoint(
            sequence=i,
            mile_marker=round(mile_marker, 2),
            latitude=lat,
            longitude=lon,
            estimated_arrival=estimated_arrival
        ))
    
    # Destination (always include)
    last_cp = checkpoints[-1]
    dest_coord = route_geometry.coords[-1]
    if (last_cp.latitude != dest_coord[1] or last_cp.longitude != dest_coord[0]):
        checkpoints.append(Checkpoint(
            sequence=len(checkpoints),
            mile_marker=round(total_distance_miles, 2),
            latitude=dest_coord[1],
            longitude=dest_coord[0],
            estimated_arrival=departure_time + timedelta(minutes=total_duration_minutes)
        ))
    
    return checkpoints
```

### Interval Selection UI
```tsx
// Frontend: Radio group for interval selection
<RadioGroup value={interval} onValueChange={setInterval}>
  <RadioGroupItem value={10}>Every 10 miles (detailed)</RadioGroupItem>
  <RadioGroupItem value={25}>Every 25 miles (balanced)</RadioGroupItem>
  <RadioGroupItem value={50}>Every 50 miles (overview)</RadioGroupItem>
</RadioGroup>

// On change: Call re-sample endpoint, update map markers
```

### Performance Optimization
- Batch insert checkpoints: `Checkpoint.objects.bulk_create()`
- Use `ST_LineInterpolatePoint` in PostGIS for DB-side computation (if available)
- Limit max checkpoints per route: 200 (10mi interval on 2000mi route)