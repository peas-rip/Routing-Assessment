# Video Walkthrough Script — Weather-Aware Truck Routing (10 min)

## 0:00–0:45 — Intro (Problem & Solution)
**Say:**
"Hi, I'm presenting the Weather-Aware Truck Routing app. It helps a truck driver choose the safest route based on weather, load weight, and travel time. Traditional routing ignores weather; this app generates 3 route options, samples weather every 10/25/50 miles, calculates risk using the provided rules, and recommends the best route."

**Show:** Title screen / README.

## 0:45–1:30 — Requirements coverage
**Say:** "Let me walk through how each requirement is met."
- Origin & destination (geocoded autocomplete)
- Departure date/time (must be within 48h — forecast limit)
- Load weight (10,000–80,000 lb)
- 3 route options via a routing API
- Weather sampled at checkpoints using estimated arrival time
- Risk calculated with the provided wind/rain/snow thresholds and load rules
- Best route recommended (fewest severe miles → high miles → avg risk → travel time)
- Map shows all routes, checkpoints, risk levels, ETAs, summaries
- Weather heatmap along the corridor with 0-48h forecast

**APIs used:** OSRM (routing), OpenRouteService/Photon (geocoding), NWS/NOAA (weather) - all free tier.

## 1:30–2:15 — Architecture & tech stack
**Say:** "The backend is Django + DRF with Celery/Redis and PostgreSQL+PostGIS. The frontend is React + Vite + Leaflet."

**APIs used (all free tier):**
- **Routing**: OSRM (keyless, public demo) — `router.project-osrm.org`
- **Geocoding**: OpenRouteService (key required) or Photon (keyless) — toggle via `GEOCODING_PROVIDER`
- **Weather**: National Weather Service / NOAA (keyless, US-only) — `api.weather.gov`

**Show:** `docs/SYSTEM_ARCHITECTURE.md` diagram + `TECHNOLOGY_DECISIONS.md`.

## 2:15–3:00 — Code quality & tests
**Say:** "The backend has 360+ tests covering clients, services, tasks, and views. Linting via ruff/black. Graceful degradation on provider errors, rate limits, and missing keys."

**Show:** Run `docker compose exec ... pytest` → pass count. Show ruff check.

## 3:00–4:30 — Live demo: short route (3 routes)
1. Open frontend: `http://127.0.0.1:5173`
2. Info popup appears → walk through it → "Got it".
3. Enter Origin: "New York, NY, USA" → pick suggestion.
4. Enter Destination: "Newark, NJ, USA" → pick suggestion.
5. Departure: now +2h. Load: 30000 lb. Interval: 10 mi.
6. Click "Generate Routes".
7. Show polling → 3 routes on map, recommended highlighted green.
8. Click a route → checkpoints list with weather + risk.
9. Change heatmap dropdown → 0h / +6h / +24h → grid updates.

## 4:30–6:00 — Live demo: long route (single route fallback)
1. New Search → "New York, NY, USA" → "Chicago, IL, USA".
2. Load 30000 lb, interval 25 mi, departure now +2h.
3. Generate → 2 routes (Fastest + Shortest). Explain: OSRM returns up to 3 alternatives depending on the road network; long corridors may return fewer.
4. Show route summary (distance, duration, checkpoints).
5. Show heatmap dropdown changing risk over hours.

## 6:00–7:00 — Live demo: high-risk scenario
1. Origin: "Chicago, IL, USA" → Destination: "Milwaukee, WI, USA".
2. Load 50000 lb, interval 10 mi, departure now +12h.
3. Generate → show risk levels on checkpoints.
4. Explain load rules: ≥45 mph + >30k lb → No Travel.
5. Show risk breakdown (low/moderate/high/severe/no_travel miles).

## 7:00–7:45 — Risk rules & recommendation
**Say:** "Risk is classified per checkpoint using wind/rain/snow thresholds. Routes are scored by fewest severe miles, then high miles, then average risk, then travel time. The recommendation endpoint returns the best route."

**Show:** `docs/SERVICES/risk/SERVICE_SPEC.md` or the API response JSON.

## 7:45–8:30 — Map & heatmap
**Say:** "The Leaflet map shows route polylines, checkpoint markers colored by risk, and a weather heatmap grid. The forecast dropdown lets you see how risk evolves over 0–48 hours."

**Show:** Origin (green A) and destination (red B) pins, checkpoint tooltips, heatmap colors.

## 8:30–9:15 — Edge cases & robustness
- Long routes: graceful single-route fallback (no crash).
- Rate limits: 429 handling with retry-after.
- Missing keys: clear provider errors (NWS is keyless, ORS key optional via toggle).
- Network failures: connection/timeout mapping to provider errors.
- Geocoding toggle: `GEOCODING_PROVIDER=openrouteservice|photon`.

## 9:15–9:45 — Documentation & deliverables
- README, SERVICE_SPEC, API_CONTRACTS, DATABASE_SCHEMA, IMPLEMENTATION_ORDER
- GitHub repo, hosted app, walkthrough
- `docs/VIDEO_WALKTHROUGH_SCRIPT.md` (this script)

## 9:45–10:00 — Conclusion & next steps
- Backend complete and tested (360+ tests).
- Frontend skeleton + integration working (info popup, polished UI).
- Remaining: UI polish by a design agent, hosting, walkthrough.
- Thank you.

## Notes for recording
- Keep the terminal visible during test runs.
- Redact any API keys in the recording.
- Use short routes for fast demos, long routes to show fallback.
- Mention keyless providers (OSRM/Photon/NWS) to highlight cost-free operation.
- Use the dropdown (not a slider) to change forecast hours.
- The app is fully functional end-to-end: geocoding → routing → weather → risk → recommendation → heatmap.
