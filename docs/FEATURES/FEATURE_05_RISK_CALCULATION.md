# Feature Specification: F05 - Risk Calculation

## Business Goal
Calculate weather risk at each checkpoint using defined thresholds for wind, rain, and snow, applying load-based escalation rules to produce a combined risk level.

## Risk Thresholds (From Requirements)

### Wind Risk
| Risk Level | Wind Speed (mph) |
|------------|------------------|
| Low | < 25 |
| Moderate | 25–34 |
| High | 35–44 |
| Severe | 45–54 |
| No Travel | ≥ 55 |

### Rain Risk
| Risk Level | Precipitation Rate (in/hr) |
|------------|---------------------------|
| Low | < 0.10 |
| Moderate | 0.10–0.25 |
| High | 0.25–0.50 |
| Severe | 0.50–1.00 |
| No Travel | > 1.00 |

### Snow Risk
| Risk Level | Snowfall Rate (in/hr) |
|------------|----------------------|
| Low | < 0.5 |
| Moderate | 0.5–1.0 |
| High | 1.0–2.0 |
| Severe | 2.0–3.0 |
| No Travel | > 3.0 |

---

## Load-Based Escalation Rules

1. **Wind ≥55 mph** → **No Travel** for ANY load weight
2. **Wind 45–54 mph** + **Load >30,000 lbs** → **No Travel**
3. **Wind 35–44 mph** + **Load >40,000 lbs** → **Severe** (escalates from High)

*Note: Rain and snow thresholds are NOT affected by load weight.*

---

## Combined Risk Calculation

**Base Risk** = Maximum of (wind_risk, rain_risk, snow_risk)
- Risk levels ordered: Low < Moderate < High < Severe < No Travel

**Load Escalation** (applied after base risk):
- If wind_risk == 'severe' (45-54 mph) AND load > 30,000 → combined = 'no_travel'
- If wind_risk == 'high' (35-44 mph) AND load > 40,000 → combined = 'severe'
- If wind_risk == 'no_travel' (≥55 mph) → combined = 'no_travel' (any load)

**Segment Miles**: Distance this checkpoint represents (typically interval_miles, except last segment)

---

## Service Ownership
**Owner**: Risk Service
**Frontend**: Consumes via `/risk/calculate/` endpoint

---

## Database Requirements

### Table: risk_assessments
| Field | Type | Description |
|-------|------|-------------|
| checkpoint_id | UUID | FK to checkpoints (OneToOne) |
| weather_observation_id | UUID | FK to weather_observations (OneToOne) |
| load_weight_lbs | Integer | Load weight for this calculation |
| wind_risk | Enum | low/moderate/high/severe/no_travel |
| rain_risk | Enum | low/moderate/high/severe/no_travel |
| snow_risk | Enum | low/moderate/high/severe/no_travel |
| combined_risk | Enum | low/moderate/high/severe/no_travel |
| load_rule_applied | String | Which load rule triggered (if any) |
| segment_miles | Decimal(10,2) | Miles this checkpoint represents |

---

## API Requirements

### POST /api/v1/risk/calculate/
**Request**:
```json
{
  "route_id": "uuid",
  "load_weight_lbs": 45000,
  "checkpoint_interval_miles": 25
}
```

**Response**:
```json
{
  "data": {
    "route_id": "uuid",
    "checkpoints": [
      {
        "checkpoint_id": "uuid",
        "mile_marker": 0.0,
        "latitude": 39.7817,
        "longitude": -89.6501,
        "estimated_arrival": "2026-10-27T08:00:00-05:00",
        "weather": { ... },
        "risk": {
          "wind_risk": "low",
          "rain_risk": "low",
          "snow_risk": "low",
          "combined_risk": "low",
          "load_rule_applied": null,
          "segment_miles": 25.0
        }
      }
    ]
  }
}
```

---

## Validation Requirements

### Input Validation
- route_id: Valid UUID, route exists
- load_weight_lbs: 10,000–80,000
- checkpoint_interval_miles: 10, 25, or 50

### Business Logic Validation
- All three risk levels calculated
- Combined risk >= each individual risk
- Load rules applied correctly per specification
- No Travel overrides all other risks

---

## Security Requirements
- No external dependencies (pure computation)
- Input validation on all parameters
- Rate limit: 30 req/min per IP

---

## Dependencies

### Internal
- Routing Service: Reads routes, checkpoints
- Weather Service: Reads weather_observations

### External
- None (pure business logic)

---

## Edge Cases

1. **Missing weather data**: Skip checkpoint, log warning, don't block route
2. **Precipitation type 'mixed'**: Calculate both rain and snow risk, take max
3. **Wind gusts**: Use sustained wind_speed, not gust (per spec)
4. **Zero precipitation**: Both rain_risk and snow_risk = 'low'
5. **Temperature near 32°F**: Use precipitation_type from API, not temp
6. **Load weight exactly at threshold**: >30,000 means 30,001+, so 30,000 is safe
7. **Multiple load rules**: Apply most restrictive (No Travel > Severe > High...)
8. **Checkpoint at destination**: segment_miles = remaining distance to end

---

## Error Handling Expectations

| Scenario | Handling |
|----------|----------|
| Route not found | 404, return error |
| No checkpoints | 400, "Route has no checkpoints" |
| Weather missing | Skip, log, continue others |
| Invalid load weight | 400, validation error |
| Calculation error | 500, log full context, alert |

---

## Acceptance Criteria

1. ✅ Wind risk matches threshold table exactly
2. ✅ Rain risk matches threshold table exactly
3. ✅ Snow risk matches threshold table exactly
4. ✅ Load rule 1: Wind ≥55 → No Travel (any load) ✅
5. ✅ Load rule 2: Wind 45-54 + Load >30k → No Travel ✅
6. ✅ Load rule 3: Wind 35-44 + Load >40k → Severe ✅
7. ✅ Rain/snow NOT affected by load weight
8. ✅ Combined risk = max(base risks) with load escalation
9. ✅ load_rule_applied field documents which rule triggered
10. ✅ Unit tests cover all threshold boundaries
11. ✅ Unit tests cover all load rule combinations
12. ✅ Performance: <50ms per checkpoint

---

## Success Criteria

- Risk calculation accuracy: 100% match to specification
- Zero calculation errors in production
- All edge cases handled without crashes
- Comprehensive test coverage (>95%)

---

## Implementation Notes

### Risk Level Enum (Ordered)
```python
from enum import IntEnum

class RiskLevel(IntEnum):
    LOW = 1
    MODERATE = 2
    HIGH = 3
    SEVERE = 4
    NO_TRAVEL = 5
    
    @classmethod
    def from_wind(cls, speed_mph: float) -> 'RiskLevel':
        if speed_mph >= 55: return cls.NO_TRAVEL
        if speed_mph >= 45: return cls.SEVERE
        if speed_mph >= 35: return cls.HIGH
        if speed_mph >= 25: return cls.MODERATE
        return cls.LOW
    
    @classmethod
    def from_rain(cls, rate_in_hr: float) -> 'RiskLevel':
        if rate_in_hr > 1.00: return cls.NO_TRAVEL
        if rate_in_hr >= 0.50: return cls.SEVERE
        if rate_in_hr >= 0.25: return cls.HIGH
        if rate_in_hr >= 0.10: return cls.MODERATE
        return cls.LOW
    
    @classmethod
    def from_snow(cls, rate_in_hr: float) -> 'RiskLevel':
        if rate_in_hr > 3.0: return cls.NO_TRAVEL
        if rate_in_hr >= 2.0: return cls.SEVERE
        if rate_in_hr >= 1.0: return cls.HIGH
        if rate_in_hr >= 0.5: return cls.MODERATE
        return cls.LOW
```

### Load Escalation Logic
```python
def apply_load_rules(wind_risk: RiskLevel, wind_speed: float, 
                     load_lbs: int) -> tuple[RiskLevel, str]:
    """Apply load-based escalation rules. Returns (escalated_risk, rule_name)."""
    
    # Rule 1: Wind ≥55 mph → No Travel (any load)
    if wind_speed >= 55:
        return RiskLevel.NO_TRAVEL, "wind_ge_55_any_load"
    
    # Rule 2: Wind 45-54 mph + Load >30,000 → No Travel
    if wind_risk == RiskLevel.SEVERE and load_lbs > 30000:
        return RiskLevel.NO_TRAVEL, "wind_45_54_over_30k"
    
    # Rule 3: Wind 35-44 mph + Load >40,000 → Severe
    if wind_risk == RiskLevel.HIGH and load_lbs > 40000:
        return RiskLevel.SEVERE, "wind_35_44_over_40k"
    
    return wind_risk, ""
```

### Combined Risk Calculation
```python
def calculate_combined_risk(weather: WeatherObservation, load_lbs: int) -> RiskAssessment:
    # Individual risks
    wind_risk = RiskLevel.from_wind(weather.wind_speed_mph or 0)
    rain_risk = RiskLevel.from_rain(weather.precipitation_rate_in_hr or 0)
    snow_risk = RiskLevel.from_snow(weather.snowfall_rate_in_hr or 0)
    
    # Base combined = max of three
    combined = max(wind_risk, rain_risk, snow_risk)
    load_rule = ""
    
    # Apply load escalation (only wind-based per spec)
    if wind_risk in (RiskLevel.HIGH, RiskLevel.SEVERE, RiskLevel.NO_TRAVEL):
        combined, load_rule = apply_load_rules(wind_risk, weather.wind_speed_mph, load_lbs)
    
    return RiskAssessment(
        wind_risk=wind_risk.name.lower(),
        rain_risk=rain_risk.name.lower(),
        snow_risk=snow_risk.name.lower(),
        combined_risk=combined.name.lower(),
        load_rule_applied=load_rule,
        segment_miles=...  # From checkpoint
    )
```

### Precipitation Type Handling
```python
def get_precip_rates(weather: WeatherObservation) -> tuple[float, float]:
    """Extract rain and snow rates from weather observation."""
    precip_type = weather.precipitation_type
    total_rate = weather.precipitation_rate_in_hr or 0
    
    if precip_type == 'rain':
        return total_rate, 0.0
    elif precip_type == 'snow':
        return 0.0, weather.snowfall_rate_in_hr or total_rate
    elif precip_type == 'mixed':
        # API may provide both rain.1h and snow.1h
        rain = weather.raw_response.get('rain', {}).get('1h', 0)
        snow = weather.raw_response.get('snow', {}).get('1h', 0)
        return rain, snow
    else:  # 'none'
        return 0.0, 0.0
```

### Test Cases (Critical)
```python
# Wind thresholds
assert RiskLevel.from_wind(24.9) == RiskLevel.LOW
assert RiskLevel.from_wind(25.0) == RiskLevel.MODERATE
assert RiskLevel.from_wind(34.9) == RiskLevel.MODERATE
assert RiskLevel.from_wind(35.0) == RiskLevel.HIGH
assert RiskLevel.from_wind(44.9) == RiskLevel.HIGH
assert RiskLevel.from_wind(45.0) == RiskLevel.SEVERE
assert RiskLevel.from_wind(54.9) == RiskLevel.SEVERE
assert RiskLevel.from_wind(55.0) == RiskLevel.NO_TRAVEL

# Load rules
assert apply_load_rules(RiskLevel.SEVERE, 50, 25000) == (RiskLevel.SEVERE, "")  # Under 30k
assert apply_load_rules(RiskLevel.SEVERE, 50, 30001) == (RiskLevel.NO_TRAVEL, "wind_45_54_over_30k")
assert apply_load_rules(RiskLevel.HIGH, 40, 35000) == (RiskLevel.HIGH, "")  # Under 40k
assert apply_load_rules(RiskLevel.HIGH, 40, 40001) == (RiskLevel.SEVERE, "wind_35_44_over_40k")
assert apply_load_rules(RiskLevel.NO_TRAVEL, 60, 10000) == (RiskLevel.NO_TRAVEL, "wind_ge_55_any_load")

# Rain/snow not affected by load
assert calculate_combined_risk(rain=1.5, wind=10, load=80000).combined_risk == RiskLevel.NO_TRAVEL
# Wind low, rain no_travel → combined no_travel regardless of load
```