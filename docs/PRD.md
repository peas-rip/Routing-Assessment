# Product Requirements Document (PRD)

## Project Overview

**Project Name**: Weather-Aware Truck Routing (Spotter)
**Type**: React + Django Web Application
**Target Users**: Truck drivers, fleet dispatchers, logistics coordinators
**Scale**: Small (100-1,000 users)
**Timeline**: 5-10 minute Loom walkthrough + hosted application + GitHub repository

---

## Business Goals

### Primary Goal
Enable truck drivers to select the safest route based on real-time weather conditions, load weight, and travel time, reducing weather-related accidents and delays.

### Success Criteria
- Generate 3 viable route options within 5 seconds
- Display weather risk at checkpoints every 10/25/50 miles
- Calculate risk accurately per defined thresholds
- Recommend optimal route per priority rules
- Render interactive map with routes, checkpoints, risk levels, ETAs
- Display weather heatmap with 0-48 hour forecast slider
- Achieve <2 second map interaction response time

### Key Metrics
- Route generation latency: <5 seconds (p95)
- Map render time: <2 seconds
- API uptime: 99.5%
- Risk calculation accuracy: 100% per specification

---

## User Personas

### 1. Truck Driver (Primary)
- **Needs**: Quick route comparison, clear risk visualization, offline-capable display
- **Workflow**: Enter origin/destination → select departure time → enter load weight → view 3 routes → pick safest → navigate
- **Pain Points**: Unexpected weather, unclear risk levels, complex interfaces

### 2. Fleet Dispatcher (Secondary)
- **Needs**: Batch route planning, driver assignment, historical route analysis
- **Workflow**: Plan multiple routes → assign to drivers → monitor conditions
- **Pain Points**: Manual weather checking, no centralized view

---

## Core Features

### F01: Route Input & Geocoding
- Origin/destination address autocomplete
- Departure date/time picker (with timezone)
- Load weight input (lbs/kg)
- Input validation & error handling

### F02: Route Generation
- Call routing API for 3 distinct route options
- Return: geometry, distance, duration, turn-by-turn instructions
- Handle routing API failures gracefully

### F03: Checkpoint Sampling
- Sample points every 10/25/50 miles along each route
- Calculate estimated arrival time at each checkpoint
- Based on departure time + cumulative travel time

### F04: Weather Fetching & Caching
- Fetch weather forecast for each checkpoint at estimated arrival time
- Cache weather data (TTL: 15 minutes)
- Handle API rate limits and failures

### F05: Risk Calculation
- Classify wind/rain/snow at each checkpoint per thresholds
- Apply load-based escalation rules
- Output: risk level per checkpoint (Low/Moderate/High/Severe/No Travel)

### F06: Route Scoring & Recommendation
- Score routes per priority:
  1. Fewest Severe miles
  2. Fewest High miles
  3. Lowest average risk
  4. Shortest travel time
- Mark recommended route
- Provide route summary statistics

### F07: Map Visualization
- Display all 3 routes with color-coded risk segments
- Show checkpoints with risk markers
- Display route summaries (distance, time, risk breakdown)
- Interactive: click route/checkpoint for details

### F08: Weather Heatmap
- Corridor-based heatmap along route paths
- 0-48 hour forecast slider
- Color-coded by risk severity
- Smooth animation between time steps

---

## Non-Functional Requirements

### Performance
- Route generation: <5 seconds (3 routes + weather + risk)
- Map load: <2 seconds initial render
- Heatmap slider: 60fps animation
- API response: <500ms for cached data

### Reliability
- Graceful degradation: show cached data if APIs fail
- Retry logic for external APIs (3 retries, exponential backoff)
- Circuit breaker for failing external services

### Security
- HTTPS only in production
- JWT authentication (if multi-user)
- Rate limiting on API endpoints
- Input sanitization for geocoding

### Usability
- Mobile-responsive (drivers use tablets/phones)
- High contrast for daylight visibility
- Keyboard navigation support
- Clear error messages

### Accessibility
- WCAG 2.1 AA compliance
- Screen reader compatible risk announcements
- Color-blind safe palettes

---

## Technical Constraints

### External API Limits
- **OpenRouteService**: 2,000 requests/day free tier
- **National Weather Service (NWS)**: 1,000 calls/day, 60/min free tier
- **Nominatim**: 1 req/s (self-hosted unlimited)

### Data Freshness
- Weather forecasts: 48 hours max
- Cache TTL: 15 minutes for weather, 1 hour for routes
- Route geometry: cached per origin/destination pair

### Browser Support
- Chrome 90+, Firefox 88+, Safari 14+, Edge 90+
- Mobile: iOS Safari 14+, Chrome Android 90+

---

## Out of Scope (v1)

- User accounts/authentication (single-user demo)
- Historical route analytics
- Driver tracking/telemetry
- Offline mode (PWA)
- Multi-stop routing
- Traffic data integration
- Push notifications
- Fleet management dashboard
- Mobile native apps

---

## Dependencies

### External Services
1. **OpenRouteService** - Routing + Geocoding (primary)
2. **National Weather Service (NWS)** - Weather forecasts
3. **Mapbox** or **Leaflet** - Map tiles (if not self-hosted)

### Internal Services
1. **Django API** - Business logic, orchestration
2. **PostgreSQL + PostGIS** - Data persistence
3. **Redis** - Caching + Celery broker
4. **Celery Workers** - Async route/weather processing
5. **React Frontend** - UI rendering

---

## Acceptance Criteria Summary

| Feature | Criteria |
|---------|----------|
| F01 | Address autocomplete works, validates input, shows errors |
| F02 | 3 distinct routes returned, geometry valid, <5s |
| F03 | Checkpoints at correct intervals, ETAs accurate |
| F04 | Weather fetched per checkpoint, cached, rate-limited |
| F05 | Risk matches specification tables exactly |
| F06 | Recommendation follows 4-level priority correctly |
| F07 | Map shows all routes, checkpoints, legends, summaries |
| F08 | Heatmap renders, slider 0-48hr works, performant |

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| External API rate limits | High | High | Caching, fallback to cached data, request queuing |
| Weather API cost at scale | Medium | Medium | Monitor usage, implement stricter caching |
| Map rendering performance | Medium | High | Simplify geometries, use canvas/WebGL, virtualize |
| Geocoding accuracy | Low | Medium | Multiple providers, manual override |
| Risk calculation bugs | Medium | High | Comprehensive unit tests, property-based testing |