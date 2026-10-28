# Feature Specification: F06 - Route Scoring & Recommendation

## Business Goal
Score and rank the 3 generated routes based on weather risk and travel time, recommending the optimal route per the defined priority rules.

## Route Recommendation Priority (From Requirements)

1. **Fewest Severe miles** (primary)
2. **Fewest High miles** (secondary)
3. **Lowest average risk** (tertiary)
4. **Shortest travel time** (quaternary)

## Risk Score Mapping
| Risk Level | Numeric Score |
|------------|---------------|
| Low | 1.0 |
| Moderate | 2.0 |
| High | 3.0 |
| Severe | 4.0 |
| No Travel | 5.0 |

**Average Risk** = Σ(risk_score × segment_miles) / total_miles

---

## Service Ownership
**Owner**: Risk Service
**Frontend**: Consumes via `/risk/recommendation/{route_id}/`

---

## Database Requirements

### Table: route_scores
| Field | Type | Description |
|-------|------|-------------|
| route_id | UUID | FK to routes (OneToOne) |
| severe_miles | Decimal(10,2) | Total miles with Severe/No Travel risk |
| high_miles | Decimal(10,2) | Total miles with High risk |
| average_risk_score | Decimal(5,3) | Weighted average risk score |
| duration_minutes | Integer | Route travel time |
| composite_score | Decimal(10,3) | Computed for sorting (lower better) |
| risk_breakdown | JSONB | {"low": 120.5, "moderate": 45.2, "high": 10.0, "severe": 0, "no_travel": 0} |

---

## API Requirements

### GET /api/v1/risk/recommendation/{route_id}/
**Response**:
```json
{
  "data": {
    "request_id": "uuid",
    "recommended_route_id": "route_uuid_1",
    "routes": [
      {
        "route_id": "route_uuid_1",
        "name": "Fastest via I-55",
        "distance_miles": 202.5,
        "duration_minutes": 195,
        "score": {
          "severe_miles": 0.0,
          "high_miles": 25.0,
          "average_risk_score": 1.85,
          "duration_minutes": 195,
          "composite_score": 1.8525,
          "risk_breakdown": {
            "low": 150.0,
            "moderate": 27.5,
            "high": 25.0,
            "severe": 0.0,
            "no_travel": 0.0
          }
        },
        "is_recommended": true
      },
      {
        "route_id": "route_uuid_2",
        "name": "Shortest via US-51",
        "distance_miles": 198.0,
        "duration_minutes": 210,
        "score": { ... },
        "is_recommended": false
      },
      {
        "route_id": "route_uuid_3",
        "name": "Balanced via I-72",
        "distance_miles": 210.0,
        "duration_minutes": 200,
        "score": { ... },
        "is_recommended": false
      }
    ]
  }
}
```

---

## Validation Requirements

### Scoring Logic
- All 3 routes scored
- Scores comparable (same units)
- Composite score enables total ordering
- Tie-breaking: Lower composite_score wins
- Recommended flag on exactly one route

### Data Integrity
- severe_miles + high_miles + moderate_miles + low_miles + no_travel_miles = route distance
- average_risk_score ∈ [1.0, 5.0]
- composite_score computation deterministic

---

## Security Requirements
- Pure computation, no external calls
- Read-only access to risk_assessments, routes
- Rate limit: 30 req/min per IP

---

## Dependencies

### Internal
- Risk Service: Reads risk_assessments (from F05)
- Routing Service: Reads routes, checkpoints

### External
- None

---

## Edge Cases

1. **Route has No Travel segments**: severe_miles includes No Travel miles
2. **All routes have identical scores**: Tie-break by duration (priority 4)
3. **One route missing risk data**: Score with available data, flag incomplete
4. **Zero-length route**: Handle division by zero in average risk
5. **Risk data stale**: Use latest risk_assessments for route
6. **Multiple routes tie on all 4 criteria**: Pick first (route_index 0)

---

## Error Handling Expectations

| Scenario | Handling |
|----------|----------|
| Route not found | 404 |
| Less than 2 routes with scores | 400 "Insufficient route data" |
| Risk data missing | Score available, mark incomplete |
| Calculation error | 500, log, alert |

---

## Acceptance Criteria

1. ✅ Priority 1: Route with fewest Severe+No Travel miles ranked highest
2. ✅ Priority 2: Tie on Severe → Fewest High miles wins
3. ✅ Priority 3: Tie on Severe+High → Lowest average risk wins
4. ✅ Priority 4: Tie on all above → Shortest duration wins
5. ✅ composite_score enables correct sorting (ascending)
6. ✅ Exactly one route marked `is_recommended: true`
7. ✅ risk_breakdown sums to route distance (±0.1 mile)
8. ✅ average_risk_score weighted by segment_miles
9. ✅ Scores computed for all 3 routes
10. ✅ Response includes all routes with scores for comparison
11. ✅ Performance: <100ms for scoring 3 routes

---

## Success Criteria

- Recommendation logic matches specification 100%
- Deterministic: Same inputs → Same recommended route
- Transparent: User can see why route was recommended
- All edge cases handled

---

## Implementation Notes

### Scoring Algorithm
```python
def calculate_route_score(route: Route, risk_assessments: List[RiskAssessment]) -> RouteScore:
    # Aggregate by risk level
    breakdown = defaultdict(float)
    for ra in risk_assessments:
        breakdown[ra.combined_risk] += ra.segment_miles
    
    # Priority 1: Severe + No Travel miles
    severe_miles = breakdown.get('severe', 0) + breakdown.get('no_travel', 0)
    
    # Priority 2: High miles
    high_miles = breakdown.get('high', 0)
    
    # Priority 3: Average risk score (weighted)
    total_miles = sum(breakdown.values())
    if total_miles == 0:
        avg_risk = 1.0
    else:
        weighted_sum = sum(
            RISK_SCORE_MAP[risk] * miles 
            for risk, miles in breakdown.items()
        )
        avg_risk = weighted_sum / total_miles
    
    # Priority 4: Duration
    duration = route.duration_minutes
    
    # Composite score: Lexicographic ordering encoded numerically
    # severe_miles * 10000 + high_miles * 100 + avg_risk * 10 + duration/1000
    # This ensures correct priority ordering
    composite = (
        severe_miles * 10000 +
        high_miles * 100 +
        avg_risk * 10 +
        duration / 1000
    )
    
    return RouteScore(
        route=route,
        severe_miles=severe_miles,
        high_miles=high_miles,
        average_risk_score=round(avg_risk, 3),
        duration_minutes=duration,
        composite_score=round(composite, 3),
        risk_breakdown=dict(breakdown)
    )
```

### Recommendation Selection
```python
def get_recommendation(routes: List[Route]) -> RecommendationResponse:
    scored = []
    for route in routes:
        risks = RiskAssessment.objects.filter(checkpoint__route=route)
        score = calculate_route_score(route, risks)
        scored.append((score.composite_score, route, score))
    
    # Sort by composite score (ascending = better)
    scored.sort(key=lambda x: x[0])
    
    return RecommendationResponse(
        request_id=routes[0].request_id,
        recommended_route_id=scored[0][1].id,
        routes=[
            RouteScoreResponse(
                route_id=r.id,
                name=r.name,
                distance_miles=r.distance_miles,
                duration_minutes=r.duration_minutes,
                score=s,
                is_recommended=(i == 0)
            )
            for i, (_, r, s) in enumerate(scored)
        ]
    )
```

### Risk Score Map
```python
RISK_SCORE_MAP = {
    'low': 1.0,
    'moderate': 2.0,
    'high': 3.0,
    'severe': 4.0,
    'no_travel': 5.0,
}
```

### Test Cases
```python
# Scenario 1: Route A has 0 severe, 10 high | Route B has 5 severe, 0 high
# → Route A wins (Priority 1)

# Scenario 2: Both 0 severe | Route A: 10 high | Route B: 5 high
# → Route B wins (Priority 2)

# Scenario 3: Both 0 severe, 0 high | Route A: avg 1.5 | Route B: avg 2.0
# → Route A wins (Priority 3)

# Scenario 4: All equal | Route A: 195 min | Route B: 210 min
# → Route A wins (Priority 4)

# Composite score verification
# Route A: severe=0, high=10, avg=1.8, duration=195
# composite = 0*10000 + 10*100 + 1.8*10 + 195/1000 = 1000 + 18 + 0.195 = 1018.195

# Route B: severe=5, high=0, avg=1.5, duration=190
# composite = 5*10000 + 0*100 + 1.5*10 + 190/1000 = 50000 + 15 + 0.19 = 50015.19

# Route A (1018) < Route B (50015) ✓ Correct: fewer severe miles wins
```

### Frontend Display
```tsx
// Route comparison table
<Table>
  <thead>
    <tr>
      <th></th>
      <th>Route</th>
      <th>Distance</th>
      <th>Time</th>
      <th>Severe mi</th>
      <th>High mi</th>
      <th>Avg Risk</th>
      <th>Status</th>
    </tr>
  </thead>
  <tbody>
    {routes.map((route, i) => (
      <tr key={route.route_id} className={route.is_recommended ? 'bg-green-50' : ''}>
        <td>{route.is_recommended ? '✓ Recommended' : ''}</td>
        <td>{route.name}</td>
        <td>{route.distance_miles} mi</td>
        <td>{route.duration_minutes} min</td>
        <td><RiskBadge level="severe">{route.score.severe_miles}</RiskBadge></td>
        <td><RiskBadge level="high">{route.score.high_miles}</RiskBadge></td>
        <td>{route.score.average_risk_score.toFixed(2)}</td>
        <td>{route.is_recommended ? '🏆 Best' : 'Alternative'}</td>
      </tr>
    ))}
  </tbody>
</Table>
```