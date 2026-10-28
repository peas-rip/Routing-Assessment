# Implementation Order

## Principle
Build services in dependency order. Each service must be independently testable before integrating.

---

## Service Build Order

### 1. Geocoding Service (Independent)
**Reason**: No dependencies on other services. Pure external API wrapper + cache.
**Estimated**: 2-3 days

**Tasks**:
1. Django app structure + models (`geocode_cache`)
2. OpenRouteService client (autocomplete, reverse)
3. Redis cache layer (TTL 30 days)
4. DRF views + serializers
5. Unit tests (client, cache, views)
6. Integration test with real API

**Validation**: `GET /geocoding/search/?q=Springfield` → Returns suggestions

---

### 2. Routing Service (Depends on: Geocoding for input)
**Reason**: Core domain service. Generates routes + checkpoints. Enqueues downstream work.
**Estimated**: 4-5 days

**Tasks**:
1. Models: `RouteRequest`, `Route`, `Checkpoint`
2. OpenRouteService client (directions, alternatives)
3. Celery task: `generate_routes`
4. Checkpoint sampling algorithm (PostGIS/Shapely)
4. ETA calculation
5. DRF views: generate, status, detail
6. Unit tests: sampling math, ETA, geometry
7. Integration test: full flow with mock API

**Validation**: `POST /routes/generate/` → Returns task_id → Poll → 3 routes with checkpoints

---

### 3. Weather Service (Depends on: Routing for checkpoints)
**Reason**: Consumes checkpoints, produces weather observations. Independent risk logic.
**Estimated**: 3-4 days

**Tasks**:
1. Models: `WeatherObservation`, `HeatmapCache`
2. OpenWeatherMap client (One Call 3.0)
3. Bulk fetch with deduplication
4. Cache layer (Redis 15min + DB)
5. Celery task: `fetch_weather_for_checkpoints`
6. Heatmap grid generation
6. DRF views: checkpoint weather, heatmap
7. Unit tests: cache, batch fetch, heatmap grid
8. Integration test with mock API

**Validation**: `GET /weather/checkpoints/?ids=...` → Returns weather for all

---

### 4. Risk Service (Depends on: Routing + Weather)
**Reason**: Pure business logic. Reads from Routing + Weather, writes risk assessments + scores.
**Estimated**: 3-4 days (highest complexity per line)

**Tasks**:
1. Models: `RiskAssessment`, `RouteScore`
2. Risk threshold implementation (wind/rain/snow)
3. Load escalation rules
4. Route scoring (4-priority algorithm)
5. Recommendation selection
6. Celery task: `calculate_risk_for_checkpoint`, `score_route`
7. DRF views: calculate, recommendation
8. **Comprehensive unit tests** (all thresholds, all load rules, all priorities)
9. Property-based tests for risk calculation
10. Integration test: full pipeline

**Validation**: `POST /risk/calculate/` → Correct risk per checkpoint; `GET /risk/recommendation/` → Correct priority ordering

---

### 5. Frontend Application (Depends on: All backend APIs)
**Reason**: Consumes all services. Built last to integrate against stable APIs.
**Estimated**: 5-6 days

**Tasks**:
1. Project setup: Vite, React, TS, Tailwind, Mapbox
2. API client layer (TanStack Query + Axios)
3. Route Input Form (F01) - Geocoding integration
4. Route Generation UI (F02) - Polling, progress
5. Map View (F07) - Routes, checkpoints, risk colors
6. Risk Calculation UI (F05/F06) - Trigger, display
7. Route Comparison Table (F06)
8. Weather Heatmap (F08) - Slider, animation
9. Responsive design, accessibility
10. E2E tests (Playwright): Critical user flows

**Validation**: Full user flow works end-to-end

---

## Integration Sequence

```
Week 1:  Geocoding ──────────────────────▶ Test standalone
         ↓
Week 2:  Routing ◀──────── Geocoding ────▶ Test with mocked geocoding
         ↓
Week 3:  Weather ◀──────── Routing ──────▶ Test with mocked routing
         ↓
Week 3:  Risk ◀─────────── Routing + Weather ──▶ Test with mocked deps
         ↓
Week 4:  Frontend ◀────── All APIs ───────▶ E2E integration
         ↓
Week 5:  Polish + Deploy
```

---

## Detailed Task Breakdown

### Backend Tasks (by service)

#### Geocoding Service
- [x] `models.py` - GeocodeCache
- [x] `clients/openrouteservice.py` - GeocodingClient
- [x] `services.py` - search, reverse, cache logic
- [x] `views.py` - SearchView, ReverseView
- [x] `serializers.py` - GeocodeResultSerializer
- [x] `urls.py` - /search/, /reverse/
- [x] `tests/test_client.py` - Mock API responses
- [x] `tests/test_services.py` - Cache behavior
- [x] `tests/test_views.py` - API contracts

#### Routing Service
- [x] `models.py` - RouteRequest, Route, Checkpoint
- [x] `clients/openrouteservice.py` - RoutingClient
- [x] `services.py` - generate_routes, create_checkpoints, calculate_etas
- [x] `tasks.py` - generate_routes_task
- [x] `views.py` - GenerateView, StatusView, DetailView
- [x] `serializers.py` - RouteSerializer, CheckpointSerializer
- [x] `urls.py` - /generate/, /{task_id}/, /{route_id}/
- [x] `tests/test_services.py` - Sampling, ETA math
- [x] `tests/test_tasks.py` - Async flow
- [x] `tests/test_views.py` - API contracts
- [x] `tests/test_integration.py` - Full flow tests

#### Weather Service
- [x] `models.py` - WeatherObservation, HeatmapCache
- [x] `clients/openweathermap.py` - WeatherClient
- [x] `services.py` - fetch_batch, deduplication, Redis cache (15min)
- [x] `services.py` - generate_heatmap
- [x] `tasks.py` - fetch_weather_for_checkpoints
- [x] `tasks.py` - generate_heatmap_task
- [x] `views.py` - CheckpointWeatherView
- [x] `views.py` - HeatmapView
- [x] `serializers.py` - WeatherSerializer, checkpoint query validation
- [x] `serializers.py` - HeatmapSerializer
- [x] `urls.py` - /checkpoints/
- [x] `urls.py` - /heatmap/
- [x] `tests/test_client.py` - Mock OWM responses
- [x] `tests/test_services.py` - Deduplication, cache, batch fetch
- [x] `tests/test_services.py` - Heatmap grid
- [x] `tests/test_views.py` - API contracts
- [x] `tests/test_tasks.py` - Async fetch + retry policy
- [x] `tests/test_models.py` - Constraints, precipitation types
- [x] `tests/test_integration.py` - Full flow with mock API

#### Risk Service
- [x] `models.py` - RiskAssessment, RouteScore
- [x] `rules.py` - Thresholds, load rules, scoring
- [x] `services.py` - calculate_risk, score_route, recommend
- [x] `tasks.py` - calculate_risk_task, score_route_task
- [x] `views.py` - CalculateView, RecommendationView
- [x] `serializers.py` - RiskSerializer, ScoreSerializer
- [x] `urls.py` - /calculate/, /recommendation/{route_id}/
- [x] `tests/test_rules.py` - **All threshold boundaries**
- [x] `tests/test_services.py` - Load rules, scoring priority
- [x] `tests/test_views.py` - API contracts

#### Common (Shared)
- [x] `exceptions.py` - APIException subclasses
- [x] `validators.py` - Coordinate, weight validators
- [ ] `pagination.py` - Custom pagination
- [ ] `utils.py` - Geo helpers, date helpers

---

### Frontend Tasks

#### Setup & Infrastructure
- [ ] `package.json` - Dependencies
- [ ] `vite.config.ts` - Config, proxies
- [ ] `tailwind.config.js` - Theme, colors
- [ ] `tsconfig.json` - Strict mode
- [ ] `src/api/client.ts` - Axios instance, interceptors
- [ ] `src/api/*.ts` - API functions per service
- [ ] `src/hooks/*.ts` - TanStack Query hooks
- [ ] `src/stores/*.ts` - Zustand stores
- [ ] `src/types/*.ts` - TypeScript interfaces

#### Components
- [ ] `components/ui/` - Button, Input, Select, Badge, Spinner, Card
- [ ] `components/forms/` - RouteInputForm, AddressAutocomplete, LoadWeightInput
- [ ] `components/map/` - MapView, RouteLayer, CheckpointMarkers, RiskLegend, HeatmapLayer
- [ ] `components/display/` - RouteSummary, RiskBadge, TimeSlider, LoadingSpinner
- [ ] `components/layout/` - Header, Sidebar, Panel

#### Pages
- [ ] `pages/HomePage.tsx` - Input form + map
- [ ] `pages/RouteResultsPage.tsx` - Results + comparison + heatmap

#### Map Integration
- [ ] Mapbox GL JS initialization
- [ ] Route layer with data-driven styling
- [ ] Checkpoint markers (clustered + individual)
- [ ] Risk color coding
- [ ] Heatmap layer
- [ ] Viewport management (fitBounds)

#### State Management
- [ ] Route store: current request, routes, selected route
- [ ] UI store: loading states, errors, sidebar visibility
- [ ] Settings store: checkpoint interval, units

---

## Parallelizable Work

| Can Run in Parallel | Must Be Sequential |
|---------------------|-------------------|
| Geocoding + Routing setup | Routing → Weather (needs checkpoints) |
| Weather client + Risk rules | Weather → Risk (needs observations) |
| Frontend setup + Backend APIs | Frontend integration (needs all APIs) |
| Unit tests per service | E2E tests (needs integrated system) |

---

## Critical Path

```
Geocoding → Routing → Weather → Risk → Frontend
     2d       4d       3d       3d       5d
     ──────────────────────────────────────
     Total: ~17 days (sequential)
     
With parallelization: ~12 days
```

---

## Definition of Done (Per Service)

- [ ] All models created + migrated
- [ ] All API endpoints implemented + documented
- [ ] Unit tests: >90% coverage on business logic
- [ ] Integration tests: Happy path + 2 error paths
- [ ] API contracts match specification
- [ ] No linting errors (Ruff, Black, ESLint)
- [ ] Type checking passes (mypy, tsc)
- [ ] Runs in Docker Compose
- [ ] Deployed to staging (optional)