# Feature Specification: F08 - Weather Heatmap

## Business Goal
Display a weather risk heatmap along the trip corridor with a 0-48 hour forecast slider, enabling drivers to visualize how conditions evolve over time.

## User Flow

### Primary Flow
1. User views route results on map (F07)
2. Heatmap panel/tab appears below/beside map
3. Heatmap renders for current forecast hour (0 = now)
4. User drags slider (0-48 hours) → Heatmap updates smoothly
5. Heatmap shows risk intensity along route corridor
6. User can play/pause animation (auto-advance slider)
7. User can toggle heatmap opacity
8. User can switch between routes (heatmap updates per route)

---

## Service Ownership
**Owner**: Weather Service (data) + Frontend (visualization)
**Backend API**: `/weather/heatmap/`
**Frontend**: HeatmapLayer component, TimeSlider component

---

## Database Requirements

### Table: heatmap_cache
| Field | Type | Description |
|-------|------|-------------|
| route_id | UUID | FK to routes |
| forecast_hour | Integer | 0-48 |
| grid_data | JSONB | Array of {lat, lon, risk_level, risk_score} |
| bounds | JSONB | {north, south, east, west} |
| resolution_miles | Decimal(5,2) | Grid spacing |
| expires_at | DateTimeTZ | Cache expiry (TTL: 10 min) |

---

## API Requirements

### GET /api/v1/weather/heatmap/
**Query Parameters**:
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| route_id | UUID | Yes | Route to visualize |
| hour | Integer | Yes | Forecast hour (0-48) |
| resolution_miles | Float | No | Grid resolution (default: 10) |

**Response**:
```json
{
  "data": {
    "route_id": "uuid",
    "forecast_hour": 6,
    "bounds": {"north": 42.0, "south": 39.5, "east": -87.0, "west": -90.0},
    "resolution_miles": 10.0,
    "grid": [
      {"lat": 39.78, "lon": -89.65, "risk_level": "low", "risk_score": 1.0},
      {"lat": 39.85, "lon": -89.50, "risk_level": "high", "risk_score": 3.0}
    ],
    "generated_at": "2026-10-27T07:30:00Z"
  }
}
```

---

## Validation Requirements

### Heatmap Data
- forecast_hour: 0-48 integer
- resolution_miles: 5-50 (default 10)
- Grid points: Max 5000 (performance)
- Risk levels: low/moderate/high/severe/no_travel
- risk_score: 1.0-5.0 matching risk level

### Visualization
- Smooth color interpolation between grid points
- Opacity slider: 0-100%
- Animation: 1 hour/second, loop or stop at 48
- Legend matches route risk colors

---

## Security Requirements
- Rate limit: 20 req/min per IP (heatmap is expensive)
- Cache aggressively (10 min TTL)
- No sensitive data in heatmap

---

## Dependencies

### External
- National Weather Service (NWS) (via Weather Service)
- Mapbox GL JS heatmap layer (frontend)

### Internal
- Weather Service: Generates heatmap grids
- Routing Service: Provides route geometry for corridor
- Risk Service: Risk calculation logic (reused)

---

## Edge Cases

1. **Route > 1000 miles**: Reduce resolution automatically (max 5000 points)
2. **Heatmap extends beyond route**: Clip to route corridor buffer
3. **Slider at hour 48**: Stop animation, disable forward
4. **No weather data for hour**: Show "Data unavailable" overlay
5. **Rapid slider drag**: Debounce API calls (200ms), show loading
6. **Mobile touch**: Slider works with touch, not just mouse
7. **Color blind**: Use colorblind-safe palette (viridis or custom)

---

## Error Handling Expectations

| Scenario | Handling |
|----------|----------|
| Heatmap generation fails | Show error, allow retry |
| Cache miss + API slow | Show spinner, use previous hour if available |
| Route not found | 404, clear heatmap |
| Grid too large | Auto-reduce resolution, log warning |

---

## Acceptance Criteria

1. ✅ Heatmap renders as colored overlay along route corridor
2. ✅ Colors match risk levels: Green→Yellow→Orange→Red→Dark Red
3. ✅ Slider 0-48 hours works smoothly
4. ✅ Drag slider → Updates within 200ms (cached) / 2s (fresh)
5. ✅ Play/pause animation button works
6. ✅ Animation speed: 1 hour/second, loops at 48
7. ✅ Opacity control (0-100%)
8. ✅ Legend shows risk color mapping
9. ✅ Switching routes updates heatmap
10. ✅ Performance: 60fps slider drag, 60fps animation
11. ✅ Mobile: Touch slider works, responsive layout
12. ✅ Accessible: Keyboard slider (Arrow keys), screen reader announces hour/risk

---

## Success Criteria

- Heatmap generation: <3s for new hour, <200ms cached
- Animation smoothness: 60fps, no jank
- Color accuracy: Matches risk specification
- Zero memory leaks during animation

---

## Implementation Notes

### Backend: Heatmap Generation
```python
def generate_heatmap_grid(route: Route, hour: int, resolution_miles: float = 10) -> HeatmapGrid:
    """Generate risk grid along route corridor."""
    
    # 1. Create corridor buffer around route
    corridor_buffer_miles = max(20, resolution_miles * 2)
    corridor = route.geometry.buffer(corridor_buffer_miles * 1609.34)
    
    # 2. Generate grid points within corridor bounds
    bounds = corridor.bounds  # (minx, miny, maxx, maxy) in Web Mercator
    grid_points = []
    
    # Convert resolution to degrees (approximate)
    lat_step = resolution_miles / 69.0  # 1 deg lat ≈ 69 miles
    lon_step = resolution_miles / (69.0 * math.cos(math.radians((bounds[1] + bounds[3]) / 2)))
    
    lat = bounds[1]
    while lat <= bounds[3]:
        lon = bounds[0]
        while lon <= bounds[2]:
            pt = Point(lon, lat)
            if corridor.contains(pt):
                # Convert back to WGS84
                wgs84_pt = transform(web_mercator_to_wgs84, pt)
                grid_points.append((wgs84_pt.y, wgs84_pt.x))  # lat, lon
            lon += lon_step
        lat += lat_step
    
    # 3. Limit grid points
    if len(grid_points) > 5000:
        # Subsample or increase resolution
        resolution_miles *= math.sqrt(len(grid_points) / 5000)
        return generate_heatmap_grid(route, hour, resolution_miles)
    
    # 4. Fetch weather for all grid points at target hour
    target_time = route.request.departure_time + timedelta(hours=hour)
    weather_data = fetch_weather_batch_for_coords(grid_points, target_time)
    
    # 5. Calculate risk for each point
    grid = []
    for (lat, lon), weather in zip(grid_points, weather_data):
        risk = calculate_risk(weather, route.request.load_weight_lbs)
        grid.append({
            'lat': lat,
            'lon': lon,
            'risk_level': risk.combined_risk,
            'risk_score': RISK_SCORE_MAP[risk.combined_risk]
        })
    
    return HeatmapGrid(
        route_id=route.id,
        forecast_hour=hour,
        bounds=corridor.bounds,
        resolution_miles=resolution_miles,
        grid=grid
    )
```

### Frontend: Mapbox GL JS Heatmap Layer
```javascript
// Heatmap source (GeoJSON points with risk_score as weight)
const heatmapSource = {
  type: 'geojson',
  data: {
    type: 'FeatureCollection',
    features: grid.map(pt => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [pt.lon, pt.lat] },
      properties: { weight: pt.risk_score }  // 1-5
    }))
  }
};

// Heatmap layer
map.addLayer({
  id: 'weather-heatmap',
  type: 'heatmap',
  source: 'weather-heatmap',
  maxzoom: 12,
  paint: {
    // Weight = risk_score (1-5)
    'heatmap-weight': ['get', 'weight'],
    
    // Intensity
    'heatmap-intensity': 1.0,
    
    // Color gradient matching risk levels
    'heatmap-color': [
      'interpolate', ['linear'], ['heatmap-density'],
      0.0, 'rgba(34,197,94,0)',      // Low - transparent
      0.2, 'rgba(34,197,94,0.6)',    // Low
      0.4, 'rgba(234,179,8,0.7)',    // Moderate
      0.6, 'rgba(249,115,22,0.8)',   // High
      0.8, 'rgba(239,68,68,0.9)',    // Severe
      1.0, 'rgba(127,29,29,1)'       // No Travel
    ],
    
    // Radius in pixels
    'heatmap-radius': 30,
    
    // Opacity controlled by slider
    'heatmap-opacity': ['get', 'heatmap-opacity']
  }
});

// Opacity control
map.setPaintProperty('weather-heatmap', 'heatmap-opacity', opacity);
```

### Time Slider Component
```tsx
const TimeSlider = ({ hour, onHourChange, isPlaying, onPlayPause }) => (
  <div className="time-slider-container">
    <div className="slider-header">
      <span className="hour-display">
        {hour === 0 ? 'Now' : `+${hour}h`}
        {hour > 0 && <span className="forecast-time">
          {format(addHours(departureTime, hour), 'EEE MMM d, h:mm a')}
        </span>}
      </span>
      <Button onClick={onPlayPause} variant="ghost" size="sm">
        {isPlaying ? <PauseIcon /> : <PlayIcon />}
      </Button>
    </div>
    
    <input
      type="range"
      min={0}
      max={48}
      value={hour}
      onChange={(e) => onHourChange(Number(e.target.value))}
      onMouseUp={() => onHourChange(hour)} // Debounced in handler
      className="slider"
      aria-label="Forecast hour"
      aria-valuenow={hour}
      aria-valuemin={0}
      aria-valuemax={48}
    />
    
    <div className="slider-labels">
      <span>Now</span>
      <span>+12h</span>
      <span>+24h</span>
      <span>+36h</span>
      <span>+48h</span>
    </div>
    
    <OpacityControl value={opacity} onChange={setOpacity} />
  </div>
);

// Animation logic
useEffect(() => {
  if (!isPlaying) return;
  const interval = setInterval(() => {
    setHour(h => h >= 48 ? 0 : h + 1); // Loop
  }, 1000);
  return () => clearInterval(interval);
}, [isPlaying]);
```

### Debounced Hour Change
```tsx
const useDebouncedHour = (hour: number, delay = 200) => {
  const [debouncedHour, setDebouncedHour] = useState(hour);
  
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedHour(hour), delay);
    return () => clearTimeout(timer);
  }, [hour, delay]);
  
  return debouncedHour;
};

// In component
const debouncedHour = useDebouncedHour(hour, 200);
useEffect(() => {
  if (debouncedHour !== lastFetchedHour) {
    fetchHeatmap(routeId, debouncedHour);
  }
}, [debouncedHour]);
```

### Colorblind-Safe Palette
```javascript
// Viridis-like palette adapted for risk levels
const colorblindSafeGradient = [
  'interpolate', ['linear'], ['heatmap-density'],
  0.0, '#fde725',   // Yellow (Low) - visible to all
  0.25, '#7ad151',  // Green
  0.5, '#22a884',   // Teal
  0.75, '#2a788e',  // Blue
  1.0, '#440154'    // Purple (Severe) - distinct from yellow
];

// Or use Mapbox's built-in 'viridis' expression if available
```

### Performance Optimization
- **Pre-fetch adjacent hours**: When hour H requested, also fetch H-1, H+1
- **Web Workers**: Offload color interpolation to worker (if needed)
- **Canvas rendering**: Mapbox heatmap is GPU-accelerated
- **Grid resolution**: Dynamic based on zoom level
  - Zoom < 6: 25 miles
  - Zoom 6-10: 10 miles
  - Zoom > 10: 5 miles