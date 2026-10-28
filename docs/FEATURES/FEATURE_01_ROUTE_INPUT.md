# Feature Specification: F01 - Route Input & Geocoding

## Business Goal
Enable users to enter origin and destination addresses with autocomplete, select departure date/time, and specify load weight for route planning.

## User Flow

### Primary Flow
1. User opens application
2. User types origin address → Autocomplete suggestions appear
3. User selects origin → Map centers on origin
4. User types destination address → Autocomplete suggestions appear
5. User selects destination → Map shows both points
6. User selects departure date/time (default: now)
7. User enters load weight in lbs (default: 40,000)
8. User clicks "Generate Routes"
9. System validates all inputs
10. System calls route generation API

### Alternative Flows
- **Reverse geocode**: User clicks map → Address populated
- **Current location**: User clicks "Use my location" → Browser geolocation API
- **Recent locations**: Dropdown shows last 5 used addresses
- **Swap origin/destination**: One-click swap button

---

## Service Ownership
**Owner**: Geocoding Service
**Frontend Components**: RouteInputForm, AddressAutocomplete, LoadWeightInput

---

## Database Requirements

### Tables
- `geocode_cache` - Cached geocoding results (TTL: 30 days)

### Queries
- Search cache by query text + type (autocomplete/forward/reverse)
- Insert new cache entries on cache miss
- Cleanup expired entries (daily cron)

---

## API Requirements

### GET /api/v1/geocoding/search/
**Purpose**: Address autocomplete/search

**Parameters**:
| Param | Type | Required | Validation |
|-------|------|----------|------------|
| q | string | Yes | 2-200 chars |
| limit | integer | No | 1-10, default 5 |
| lat | float | No | -90 to 90 |
| lon | float | No | -180 to 180 |

**Response**: Array of suggestions with display_name, lat, lon, address components

**Errors**:
- 400: Query too short (<2 chars)
- 429: Rate limited
- 502: External geocoding service error

### GET /api/v1/geocoding/reverse/
**Purpose**: Reverse geocoding (click on map)

**Parameters**:
| Param | Type | Required | Validation |
|-------|------|----------|------------|
| lat | float | Yes | -90 to 90 |
| lon | float | Yes | -180 to 180 |

**Response**: Single result with display_name, address components

---

## Validation Requirements

### Origin/Destination
- Must be valid geocoded location (lat/lon)
- Cannot be same as destination
- Must be routable (connected to road network)

### Departure Time
- Must be >= current time (no past departures)
- Must be <= 48 hours from now (weather forecast limit)
- Timezone-aware (store as UTC, display in user's TZ)

### Load Weight
- Required, positive integer
- Range: 10,000 - 80,000 lbs (typical truck range)
- Default: 40,000 lbs
- Accept kg input (convert to lbs)

---

## Security Requirements

- Rate limiting: 30 requests/minute per IP on geocoding endpoints
- Input sanitization: Strip HTML/scripts from address strings
- No PII stored in geocode cache (only addresses)
- HTTPS only in production

---

## Dependencies

### External
- **OpenRouteService Geocoding** (primary) - Free tier: 2,000 req/day
- **Nominatim** (fallback) - Self-hosted or public (1 req/s limit)

### Internal
- Redis cache (TTL: 30 days for geocode results)
- PostgreSQL (geocode_cache table)

---

## Edge Cases

1. **Ambiguous addresses**: "Springfield" → Return multiple results with state context
2. **No results**: Show "No matches found", suggest less specific query
3. **API quota exceeded**: Fallback to cached results, show warning
4. **Network timeout**: 5s timeout, retry once, then fallback to cache
5. **Invalid coordinates**: Client-side validation before API call
6. **Special characters**: Handle Unicode, accents in addresses

---

## Error Handling Expectations

| Scenario | User Feedback | System Action |
|----------|---------------|---------------|
| Empty query | "Enter at least 2 characters" | No API call |
| No results | "No locations found for '...'" | Clear suggestions |
| API timeout | "Search timed out, trying cached..." | Retry once, use cache |
| API error | "Unable to search. Using cached results." | Log error, use cache |
| Rate limited | "Too many searches. Please wait." | Show retry countdown |

---

## Acceptance Criteria

1. ✅ Autocomplete shows results within 300ms (cached) / 1s (API)
2. ✅ Minimum 2 characters triggers search
3. ✅ Results show formatted address with city, state
4. ✅ Clicking result populates form field and centers map
5. ✅ Reverse geocode on map click works within 500ms
6. ✅ Departure time picker defaults to current time + 15 min (rounded)
7. ✅ Departure time cannot be in past or >48 hours future
8. ✅ Load weight accepts 10,000-80,000 lbs, shows error outside range
9. ✅ Form validation prevents submission with invalid data
10. ✅ Swap button exchanges origin/destination correctly
11. ✅ Recent locations persist in localStorage (5 entries)

---

## Success Criteria

- Geocoding success rate: >95% for valid addresses
- Autocomplete latency: <300ms (cache hit), <1s (API)
- Zero critical security vulnerabilities
- Accessible: Keyboard navigation, screen reader labels, ARIA attributes

---

## Implementation Notes

### Frontend
- Use `@tanstack/react-query` for caching autocomplete requests
- Debounce input: 250ms
- Cache search results in React Query (staleTime: 5 min)
- Store recent locations in localStorage (not server)

### Backend
- Cache key: `{query_type}:{normalized_query}:{lat}:{lon}`
- Normalize: lowercase, trim, collapse whitespace
- External client: Timeout 5s, retry 1x with exponential backoff
- Circuit breaker: Open after 5 failures in 1 minute

### Map Integration
- On result select: Fly to location, add temporary marker
- On reverse geocode: Add marker at clicked point, show address
- Clear previous markers when new search initiated