# Weather-Aware Truck Routing

A Django + React application that helps a truck driver choose the safest
route based on weather, load weight, and travel time.

## Backend

- **Framework**: Django + Django REST Framework
- **Database**: PostgreSQL + PostGIS (via Docker Compose)
- **Cache/Queue**: Redis + Celery
- **Providers**:
  - Routing: OSRM (keyless, public demo)
  - Geocoding: OpenRouteService (API key required)
  - Weather: National Weather Service / NOAA (keyless, US-only)

### Running the backend

```bash
cd infrastructure
cp ../.env.example .env          # add your OpenRouteService + OpenWeatherMap keys
docker compose up -d
docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.testing django pytest
```

API docs: `http://localhost:8000/api/docs/`

## Frontend

React + Vite skeleton in `frontend/`. See `frontend/.env.example`.

```bash
cd frontend
npm install
npm run dev
```

## Configuration

Copy `backend/.env.example` to `backend/.env`. Keys stay in environment files
and are never committed.

## Tests

- Local (SQLite fallback): `pytest` (weather/routing tests run in Docker).
- Full suite (PostGIS): `docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.testing django pytest`.
