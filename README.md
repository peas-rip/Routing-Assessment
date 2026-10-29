# Weather-Aware Truck Routing

A Django + React application that helps a truck driver choose the safest
route by balancing weather risk and travel time.

## Backend

- **Framework**: Django + Django REST Framework
- **Database**: PostgreSQL + PostGIS (via Docker Compose)
- **Cache/Queue**: Redis + Celery
- **Providers**:
  - Routing: OSRM (keyless)
  - Geocoding: Nominatim (keyless, OpenStreetMap)
  - Weather: Open-Meteo (no API key; see licensing below)

### Running the backend

```bash
cd infrastructure
cp ../.env.example .env          # add your OpenRouteService key
docker compose up -d
docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.testing django pytest
```

API docs: `http://localhost:8000/api/docs/` · Health: `http://localhost:8000/health/`

### Configuration

Copy `backend/.env.example` to `backend/.env` for local development. Keys and
secrets stay in environment files and are never committed.

## Frontend

React + Vite skeleton in `frontend/`. See `frontend/.env.example` for the API
base URL.

```bash
cd frontend
npm install
npm run dev
```

## Weather provider: Open-Meteo (licensing)

The weather service uses the free **Open-Meteo** Forecast API, which requires
no API key. Per Open-Meteo's terms, this free API is licensed for
**non-commercial use only**. Commercial deployments must arrange a paid
Open-Meteo plan or swap the provider. Details in
`docs/SERVICES/weather/SERVICE_SPEC.md`.

## Tests

- Local (SQLite fallback): `pytest` (weather/routing tests run in Docker).
- Full suite (PostGIS): `docker compose exec -e DJANGO_SETTINGS_MODULE=config.settings.testing django pytest`.

## Documentation

- `docs/SERVICES/weather/` — weather service spec, development, testing, deployment.
- `docs/FEATURES/` — feature specifications.
- `TECHNOLOGY_DECISIONS.md` — architecture and technology decisions.
