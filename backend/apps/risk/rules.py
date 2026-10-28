"""Risk thresholds, load escalation rules and scoring constants (F05/F06).

Pure computation - no Django imports - so the weather heatmap generator can
reuse it without a circular dependency. Thresholds follow
docs/SERVICES/risk/SERVICE_SPEC.md exactly: a value strictly below a boundary
lands in the lower band and a value at the boundary in the higher band. The
final ``(None, NO_TRAVEL)`` entry makes exactly 1.00 in/hr rain and exactly
3.0 in/hr snow No Travel - the SERVICE_SPEC/TESTING.md boundary decision,
which supersedes FEATURE_05's "> 1.00" / "> 3.0" table rows at those two
values only.
"""

from decimal import Decimal
from enum import IntEnum


class RiskLevel(IntEnum):
    """Ordered risk severity (the numeric value drives max() and sorting)."""

    LOW = 1
    MODERATE = 2
    HIGH = 3
    SEVERE = 4
    NO_TRAVEL = 5

    @classmethod
    def from_value(cls, value: str) -> "RiskLevel":
        """Look up a level from its stored/API value (e.g. ``no_travel``)."""
        return cls[value.upper()]

    @property
    def value_label(self) -> str:
        """Stored/API value for this level (e.g. ``no_travel``)."""
        return self.name.lower()


# Wind thresholds (mph): below the boundary is the listed level.
WIND_THRESHOLDS = [
    (Decimal("25"), RiskLevel.LOW),
    (Decimal("35"), RiskLevel.MODERATE),
    (Decimal("45"), RiskLevel.HIGH),
    (Decimal("55"), RiskLevel.SEVERE),
    (None, RiskLevel.NO_TRAVEL),  # >= 55
]

# Rain thresholds (in/hr): >= 1.00 is No Travel (see module docstring).
RAIN_THRESHOLDS = [
    (Decimal("0.10"), RiskLevel.LOW),
    (Decimal("0.25"), RiskLevel.MODERATE),
    (Decimal("0.50"), RiskLevel.HIGH),
    (Decimal("1.00"), RiskLevel.SEVERE),
    (None, RiskLevel.NO_TRAVEL),
]

# Snow thresholds (in/hr): >= 3.0 is No Travel (see module docstring).
SNOW_THRESHOLDS = [
    (Decimal("0.5"), RiskLevel.LOW),
    (Decimal("1.0"), RiskLevel.MODERATE),
    (Decimal("2.0"), RiskLevel.HIGH),
    (Decimal("3.0"), RiskLevel.SEVERE),
    (None, RiskLevel.NO_TRAVEL),
]

# Numeric scores per F06 (used for the weighted average risk).
RISK_SCORE_MAP = {
    RiskLevel.LOW: Decimal("1.0"),
    RiskLevel.MODERATE: Decimal("2.0"),
    RiskLevel.HIGH: Decimal("3.0"),
    RiskLevel.SEVERE: Decimal("4.0"),
    RiskLevel.NO_TRAVEL: Decimal("5.0"),
}


def _classify(value, thresholds) -> RiskLevel:
    for threshold, level in thresholds:
        if threshold is None or value < threshold:
            return level
    return RiskLevel.NO_TRAVEL


def classify_wind(speed_mph) -> RiskLevel:
    """Wind risk for a speed in mph (F05 wind table)."""
    return _classify(Decimal(str(speed_mph)), WIND_THRESHOLDS)


def classify_rain(rate_in_hr) -> RiskLevel:
    """Rain risk for a rate in in/hr (F05 rain table)."""
    return _classify(Decimal(str(rate_in_hr)), RAIN_THRESHOLDS)


def classify_snow(rate_in_hr) -> RiskLevel:
    """Snow risk for a rate in in/hr (F05 snow table)."""
    return _classify(Decimal(str(rate_in_hr)), SNOW_THRESHOLDS)


def apply_load_rules(wind_risk: RiskLevel, wind_speed, load_lbs: int) -> tuple[RiskLevel, str]:
    """Load-based escalation rules (F05). Returns (escalated_risk, rule_name).

    * Wind >= 55 mph -> No Travel for ANY load (``wind_ge_55_any_load``).
    * Wind 45-54 mph (Severe) + load > 30,000 lbs -> No Travel
      (``wind_45_54_over_30k``).
    * Wind 35-44 mph (High) + load > 40,000 lbs -> Severe
      (``wind_35_44_over_40k``).

    Rain and snow risk is never affected by the load.
    """
    wind_speed = Decimal(str(wind_speed))
    if wind_speed >= Decimal("55"):
        return RiskLevel.NO_TRAVEL, "wind_ge_55_any_load"
    if wind_risk == RiskLevel.SEVERE and load_lbs > 30_000:
        return RiskLevel.NO_TRAVEL, "wind_45_54_over_30k"
    if wind_risk == RiskLevel.HIGH and load_lbs > 40_000:
        return RiskLevel.SEVERE, "wind_35_44_over_40k"
    return wind_risk, ""
