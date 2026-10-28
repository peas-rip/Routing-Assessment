"""Unit conversions and precipitation parsing (docs/SERVICES/weather)."""

METERS_PER_MILE = 1609.344


def classify_precipitation(rain_1h, snow_1h) -> tuple[str, float, float]:
    """Classify provider rain/snow rates (F04 edge cases 5 and 6).

    Returns ``(type, combined rate in/hr, snowfall rate in/hr)``. Mixed
    precipitation sums both rates (docs/SERVICES/weather/TESTING.md).
    """
    rain = float(rain_1h or 0)
    snow = float(snow_1h or 0)
    if rain > 0 and snow > 0:
        precip_type = "mixed"
    elif rain > 0:
        precip_type = "rain"
    elif snow > 0:
        precip_type = "snow"
    else:
        precip_type = "none"
    return precip_type, rain + snow, snow


def meters_to_miles(meters) -> float | None:
    """Convert a provider distance in meters to miles, or None when absent."""
    if meters is None:
        return None
    return round(float(meters) / METERS_PER_MILE, 2)
