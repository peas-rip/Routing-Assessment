# Development Roadmap

## Overview
Service-driven incremental delivery. Each phase delivers working, testable, deployable functionality.

---

## Phase 1: Foundation (Week 1-2)
**Objective**: Establish infrastructure, core models, and basic API

### Deliverables
- [ ] Django project with config (settings, URLs, Docker)
- [ ] PostgreSQL + PostGIS + Redis containers
- [ ] React + Vite + TypeScript + Tailwind setup
- [ ] Nginx reverse proxy config
- [ ] CI/CD pipeline (lint, test, build)
- [ ] Geocoding Service (F01) - MVP
  - Address autocomplete (OpenRouteService)
  - Reverse geocoding
  - Cache layer (Redis + DB)
- [ ] Basic map display (Mapbox GL JS)

### Dependencies
- None (starts from scratch)

### Risks
- PostGIS setup complexity
- Mapbox token/configuration
- External API rate limits during dev

### Validation
- `docker compose up` runs all services
- Geocoding API returns results
- Map renders with search box

---

## Phase 2: Routing Core (Week 2-3)
**Objective**: Generate and display 3 routes with checkpoints

### Deliverables
- [ ] Routing Service (F02, F03)
  - OpenRouteService integration
  - Async route generation (Celery)
  - 3 route alternatives
  - Checkpoint sampling (10/25/50 miles)
  - ETA calculation
- [ ] Route display on map
  - 3 routes with different colors
  - Checkpoint markers
  - Route summary panel
- [ ] Polling UI for async generation

### Dependencies
- Phase 1 complete
- OpenRouteService API key

### Risks
- Routing API response format changes
- Complex geometry handling
- Celery task debugging

### Validation
- Submit origin/dest → Get 3 routes in <10s
- Routes render on map
- Checkpoints at correct intervals
- ETAs calculate correctly

---

## Phase 3: Weather & Risk (Week 3-4)
**Objective**: Fetch weather, calculate risk, score routes

### Deliverables
- [ ] Weather Service (F04)
  - OpenWeatherMap integration
  - Bulk fetching with deduplication
  - Cache layer (15 min TTL)
  - Heatmap grid generation
- [ ] Risk Service (F05, F06)
  - Risk threshold implementation
  - Load-based escalation rules
  - Route scoring (4-priority)
  - Recommendation logic
- [ ] Risk visualization on map
  - Color-coded route segments
  - Checkpoint risk popups
  - Route comparison table

### Dependencies
- Phase 2 complete
- OpenWeatherMap API key

### Risks
- Weather API rate limits (60/min)
- Risk calculation edge cases
- Data synchronization (route → weather → risk)

### Validation
- Weather fetches for all checkpoints
- Risk matches specification tables exactly
- Load rules apply correctly
- Recommended route follows priority rules
- Route scores displayed correctly

---

## Phase 4: Heatmap & Polish (Week 4-5)
**Objective**: Weather heatmap with slider, UI polish, performance

### Deliverables
- [ ] Heatmap (F08)
  - 0-48 hour slider
  - Smooth animation
  - Opacity control
  - Route switching
- [ ] UI Polish
  - Loading states, error handling
  - Mobile responsive
  - Accessibility (WCAG AA)
  - Legend, tooltips, help text
- [ ] Performance optimization
  - Geometry simplification
  - Bundle size optimization
  - Caching strategies

### Dependencies
- Phase 3 complete

### Risks
- Heatmap performance on mobile
- Animation smoothness
- Cross-browser compatibility

### Validation
- Heatmap renders <3s
- Slider 60fps
- Animation smooth
- Mobile usable
- Accessibility audit passes

---

## Phase 5: Deployment & Documentation (Week 5-6)
**Objective**: Production deployment, documentation, walkthrough

### Deliverables
- [ ] Production deployment
  - VPS provisioning
  - SSL certificates (Let's Encrypt)
  - Environment configuration
  - Backup strategy
- [ ] Documentation
  - README with setup instructions
  - API documentation (Swagger)
  - Architecture decision log
- [ ] Loom walkthrough (5-10 min)
- [ ] GitHub repository (public)

### Dependencies
- Phase 4 complete
- VPS credentials

### Risks
- Deployment environment differences
- SSL/HTTPS configuration
- External API keys in production

### Validation
- App accessible at domain
- HTTPS works
- All features functional in prod
- Walkthrough recorded

---

## Milestone Summary

| Milestone | Target Week | Key Deliverable |
|-----------|-------------|-----------------|
| M1: Foundation | 2 | Running stack, geocoding, map |
| M2: Routes | 3 | 3 routes + checkpoints on map |
| M3: Weather/Risk | 4 | Risk-calculated routes + recommendation |
| M4: Heatmap | 5 | Interactive weather heatmap |
| M5: Production | 6 | Deployed app + docs + walkthrough |

---

## Resource Allocation

| Role | Phase 1 | Phase 2 | Phase 3 | Phase 4 | Phase 5 |
|------|---------|---------|---------|---------|---------|
| Backend | 100% | 100% | 100% | 50% | 50% |
| Frontend | 50% | 100% | 50% | 100% | 50% |
| DevOps | 50% | 20% | 20% | 20% | 100% |

---

## Go/No-Go Criteria

### Phase 1 → 2
- [ ] All services start with `docker compose up`
- [ ] Geocoding returns valid lat/lon
- [ ] Map renders without errors

### Phase 2 → 3
- [ ] 3 distinct routes generated
- [ ] Checkpoints at correct mile intervals
- [ ] Async polling works end-to-end

### Phase 3 → 4
- [ ] Risk calculation 100% matches spec
- [ ] Load rules verified with test cases
- [ ] Route recommendation deterministic

### Phase 4 → 5
- [ ] Heatmap slider smooth
- [ ] All features work on mobile
- [ ] No critical bugs

### Phase 5 → Done
- [ ] Production deployment successful
- [ ] Loom walkthrough recorded
- [ ] GitHub repo public with README