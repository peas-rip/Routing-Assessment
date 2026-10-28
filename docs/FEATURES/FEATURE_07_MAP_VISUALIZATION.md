# Feature Specification: F07 - Map Visualization

## Business Goal
Display all 3 routes on an interactive map with color-coded risk segments, checkpoint markers, route summaries, and smooth pan/zoom performance.

## User Flow

### Primary Flow
1. Route generation completes → Frontend receives 3 routes with checkpoints
2. Frontend calls `/risk/calculate/` for each route → Gets risk per checkpoint
3. Frontend calls `/risk/recommendation/{route_id}/` → Gets scored routes
4. Map renders:
   - All 3 routes as polylines
   - Color-coded by risk level per segment
   - Checkpoint markers with risk icons
   - Recommended route highlighted
4. User interactions:
   - Click route → Show details panel
   - Click checkpoint → Show weather/risk popup
   - Toggle routes on/off
   - Toggle checkpoint visibility
   - Pan/zoom smoothly

---

## Service Ownership
**Owner**: Frontend (React + Mapbox GL JS / Leaflet)
**Backend**: Consumes Routing + Risk APIs

---

## Database Requirements
- None (read-only via APIs)

---

## API Requirements

### Consumes
- `GET /api/v1/routes/{task_id}/` - Routes with geometries + checkpoints
- `POST /api/v1/risk/calculate/` - Risk per checkpoint
- `GET /api/v1/risk/recommendation/{route_id}/` - Scored routes + recommendation

---

## Validation Requirements

### Map Rendering
- All 3 routes visible at initial zoom (fitBounds)
- Route geometries valid GeoJSON LineString
- Checkpoint coordinates on route
- Risk colors match specification

### Performance
- Initial render: <2 seconds
- Pan/zoom: 60fps
- 100+ checkpoints: No visible lag
- Route toggle: <100ms

---

## Security Requirements
- Mapbox token: Public token (style URL) or secret with URL restriction
- No API keys in frontend bundle
- Content Security Policy for map tiles

---

## Dependencies

### External
- **Mapbox GL JS** (preferred) or **Leaflet** + Mapbox tiles
- Mapbox Styles API / OpenStreetMap tiles

### Internal
- Routing Service API
- Risk Service API

---

## Edge Cases

1. **Routes overlap**: Show both, use dash patterns or offset
2. **Many checkpoints**: Cluster at low zoom, show all at high zoom
3. **Long routes**: Simplify geometry for display (keep original for accuracy)
4. **Mobile viewport**: Touch-friendly, responsive legend
5. **Offline/failed tiles**: Graceful degradation, retry
6. **Route geometry crossing antimeridian**: Handle ±180° longitude

---

## Error Handling Expectations

| Scenario | User Feedback |
|----------|---------------|
| Map tiles fail to load | "Map unavailable, retrying..." + retry button |
| Route geometry invalid | "Route display error" + show other routes |
| Risk data missing | Show route in gray, "Risk data loading..." |
| WebGL not supported | Fallback to Leaflet (Canvas 2D) |

---

## Acceptance Criteria

1. ✅ All 3 routes render correctly with Mapbox GL JS
2. ✅ Routes color-coded by risk: Green (Low), Yellow (Moderate), Orange (High), Red (Severe), Dark Red (No Travel)
3. ✅ Checkpoint markers at each sampling point
4. ✅ Click checkpoint → Popup with weather, risk, ETA
5. ✅ Click route segment → Highlight + show segment details
6. ✅ Recommended route visually distinct (thicker, bold, badge)
7. ✅ Route toggle checkboxes (show/hide each)
8. ✅ Checkpoint toggle (show/hide markers)
9. ✅ Legend shows risk color mapping
10. ✅ Route summary panel: Distance, Duration, Risk Breakdown
11. ✅ Fit bounds to show all routes on load
12. ✅ Smooth pan/zoom at 60fps
13. ✅ Responsive: Works on mobile (375px) and desktop (1920px)
14. ✅ Accessible: Keyboard navigation, screen reader labels, high contrast

---

## Success Criteria

- Map load time: <2s (tiles cached), <5s (cold)
- Interaction latency: <100ms
- Zero map crashes
- WCAG 2.1 AA compliance

---

## Implementation Notes

### Tech Choice: Mapbox GL JS vs Leaflet

| Factor | Mapbox GL JS | Leaflet |
|--------|--------------|---------|
| Performance (WebGL) | Excellent | Good (Canvas) |
| Styling | Data-driven styles | Manual |
| Heatmap (F08) | Native | Plugin needed |
| Bundle size | ~500KB | ~40KB |
| Learning curve | Medium | Low |
| **Recommendation** | **Mapbox GL JS** | Fallback |

**Decision**: Mapbox GL JS for native heatmap support and performance.

### Route Layer Styling (Mapbox)
```javascript
// Add route as GeoJSON source with line metrics
map.addSource('routes', {
  type: 'geojson',
  data: routesGeoJSON, // FeatureCollection of 3 LineStrings
  lineMetrics: true  // For gradient along line
});

// Risk color stops
const riskColors = {
  low: '#22c55e',       // green-500
  moderate: '#eab308',  // yellow-500
  high: '#f97316',      // orange-500
  severe: '#ef4444',    // red-500
  no_travel: '#7f1d1d'  // red-900
};

// Data-driven styling per segment
map.addLayer({
  id: 'route-lines',
  type: 'line',
  source: 'routes',
  paint: {
    'line-color': [
      'interpolate', ['linear'], ['line-progress'],
      0, ['get', 'risk_color_start'],
      1, ['get', 'risk_color_end']
    ],
    'line-width': [
      'case',
      ['==', ['get', 'is_recommended'], true], 5,
      3
    ],
    'line-opacity': 0.9
  }
});

// Pre-process: Split routes into segments by risk
function splitRouteByRisk(route, checkpoints) {
  // Creates MultiLineString segments with risk_color properties
}
```

### Checkpoint Markers
```javascript
// Cluster at low zoom
map.addSource('checkpoints', {
  type: 'geojson',
  data: checkpointsGeoJSON,
  cluster: true,
  clusterMaxZoom: 12,
  clusterRadius: 50
});

// Cluster circles
map.addLayer({
  id: 'checkpoint-clusters',
  type: 'circle',
  source: 'checkpoints',
  filter: ['has', 'point_count'],
  paint: {
    'circle-color': ['step', ['get', 'point_count'], '#51bbd6', 10, '#2196f3', 50, '#3f51b5'],
    'circle-radius': ['step', ['get', 'point_count'], 20, 10, 30, 50, 40]
  }
});

// Individual markers at high zoom
map.addLayer({
  id: 'checkpoint-markers',
  type: 'symbol',
  source: 'checkpoints',
  filter: ['!', ['has', 'point_count']],
  layout: {
    'icon-image': ['concat', 'risk-', ['get', 'risk_level']],
    'icon-size': 0.8,
    'icon-allow-overlap': true
  }
});

// Pre-load risk icons
['low', 'moderate', 'high', 'severe', 'no_travel'].forEach(level => {
  map.addImage(`risk-${level}`, createRiskIcon(level));
});
```

### Route Summary Panel
```tsx
const RouteSummary = ({ route, score, isRecommended, onSelect }) => (
  <div className={`route-summary ${isRecommended ? 'recommended' : ''}`}>
    <div className="route-header">
      <span className="route-name">{route.name}</span>
      {isRecommended && <Badge className="recommended-badge">Recommended</Badge>}
    </div>
    <div className="route-stats">
      <Stat label="Distance" value={`${route.distance_miles} mi`} />
      <Stat label="Duration" value={`${route.duration_minutes} min`} />
      <Stat label="Severe mi" value={score.severe_miles} color="severe" />
      <Stat label="High mi" value={score.high_miles} color="high" />
      <Stat label="Avg Risk" value={score.average_risk_score.toFixed(2)} />
    </div>
    <RiskBreakdownBar breakdown={score.risk_breakdown} />
    <Button onClick={() => onSelect(route.id)} variant={isRecommended ? 'primary' : 'outline'}>
      {isRecommended ? 'Selected' : 'Select'}
    </Button>
  </div>
);
```

### Responsive Design
```css
/* Mobile-first */
.map-container { height: 100vh; }
.route-panel { position: fixed; bottom: 0; width: 100%; max-height: 60vh; overflow: auto; }

/* Tablet+ */
@media (min-width: 768px) {
  .route-panel { position: relative; width: 320px; max-height: none; }
}
```

### Performance Optimizations
- Geometry simplification: `turf.simplify(route, {tolerance: 0.001, highQuality: true})`
- Viewport culling: Only render features in viewport (Mapbox does automatically)
- Debounced API calls on viewport change (for heatmap)
- Memoized React components: `React.memo` for RouteSummary, CheckpointPopup