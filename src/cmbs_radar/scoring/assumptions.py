"""Versioned market assumptions. Every run records the version and the full
set, so results are reproducible; the api re-scores scenarios from a
modified copy (with_rate_shift)."""

from __future__ import annotations

import copy
import json
import math
from dataclasses import asdict, dataclass, field
from importlib import resources
from typing import IO, Any


@dataclass(slots=True)
class Sizing:
    """How a lender would size a new loan on a property type today."""

    debt_yield: float  # minimum cash flow / loan
    dscr: float  # minimum cash flow / debt service
    spread: float  # over base_rate
    amort_years: int  # 0 = interest-only


@dataclass(slots=True)
class WatchThresholds:
    dscr_floor: float
    dscr_decline: float  # fraction below securitization
    occupancy_decline: float  # absolute points below securitization
    valuation_decline: float  # fraction below securitization
    paid_through_lag_days: int
    tenant_share: float  # of net rentable area
    tenant_window_months: int  # lease expiring before refi date + window


@dataclass(slots=True)
class Assumptions:
    version: str
    description: str
    base_rate: float
    default: Sizing
    by_property_type: dict[str, Sizing]
    horizon_months: int  # clean/gap refi window
    gap_tolerance: float  # gap share of whole loan still called clean
    distress_gap: float  # gap share at which a loan is distressed
    t12_max_age_months: int
    stale_financials_months: int
    watch: WatchThresholds = field(default=None)  # type: ignore[assignment]

    def sizing_for(self, property_type: str) -> Sizing:
        return self.by_property_type.get(property_type, self.default)

    def rate(self, property_type: str) -> float:
        """Assumed new-loan rate for a property type."""
        return self.base_rate + self.sizing_for(property_type).spread

    def with_rate_shift(self, bps: float) -> Assumptions:
        """A copy with the base rate moved by bps basis points (e.g. -50),
        versioned so results can't be confused with the base run."""
        b = copy.deepcopy(self)
        b.base_rate = self.base_rate + bps / 10000
        b.version = f"{self.version}{round_half_away(bps):+g}bp"
        return b

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> None:
        errs: list[str] = []
        if not self.version:
            errs.append("version is required")
        if not 0 < self.base_rate <= 0.25:
            errs.append(f"base_rate {self.base_rate} out of range (fraction, e.g. 0.0425)")

        def check(name: str, s: Sizing) -> None:
            if not (0 < s.debt_yield <= 0.5 and 1 <= s.dscr <= 5 and 0 <= s.spread <= 0.2 and 0 <= s.amort_years <= 50):
                errs.append(f"sizing {name} out of range: {s}")

        check("default", self.default)
        for k, s in self.by_property_type.items():
            check(k, s)
        if self.horizon_months <= 0 or self.t12_max_age_months <= 0 or self.stale_financials_months <= 0:
            errs.append("horizon_months, t12_max_age_months and stale_financials_months must be positive")
        if not (0 <= self.gap_tolerance < self.distress_gap < 1):
            errs.append(f"need 0 <= gap_tolerance ({self.gap_tolerance}) < distress_gap ({self.distress_gap}) < 1")
        if errs:
            raise ValueError("assumptions: " + "; ".join(errs))


_TOP = {"version", "description", "base_rate", "default", "by_property_type", "horizon_months", "gap_tolerance",
        "distress_gap", "t12_max_age_months", "stale_financials_months", "watch"}


def load_assumptions(f: IO[str] | str) -> Assumptions:
    """Parse and validate assumptions JSON. Unknown fields are rejected."""
    raw = json.loads(f if isinstance(f, str) else f.read())
    unknown = set(raw) - _TOP
    if unknown:
        raise ValueError(f"assumptions: unknown fields {sorted(unknown)}")
    try:
        a = Assumptions(
            version=raw.get("version", ""),
            description=raw.get("description", ""),
            base_rate=raw.get("base_rate", 0),
            default=Sizing(**raw["default"]),
            by_property_type={k: Sizing(**v) for k, v in raw.get("by_property_type", {}).items()},
            horizon_months=raw.get("horizon_months", 0),
            gap_tolerance=raw.get("gap_tolerance", 0),
            distress_gap=raw.get("distress_gap", 0),
            t12_max_age_months=raw.get("t12_max_age_months", 0),
            stale_financials_months=raw.get("stale_financials_months", 0),
            watch=WatchThresholds(**raw["watch"]) if "watch" in raw else WatchThresholds(0, 0, 0, 0, 0, 0, 0),
        )
    except (KeyError, TypeError) as e:
        raise ValueError(f"assumptions: {e}") from e
    a.validate()
    return a


def default_assumptions() -> Assumptions:
    """The built-in v1 assumptions."""
    text = resources.files("cmbs_radar.scoring").joinpath("assumptions/v1.json").read_text()
    return load_assumptions(text)


def round_half_away(x: float) -> float:
    """Round halves away from zero (Python's round() rounds half to even).
    Statement lengths and scenario versions depend on it."""
    return math.copysign(math.floor(abs(x) + 0.5), x)
