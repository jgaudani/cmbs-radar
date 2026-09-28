"""Scoring inputs: a loan's full history, independent of the database.

Units follow ingest: money in dollars, rates and occupancy as fractions
(0.0466, 0.91), DSCR as a ratio. Statements are as reported (often
year-to-date); the engine annualizes them. Dates are datetime.date.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(slots=True)
class Tenant:
    name: str = ""
    sqft: float | None = None
    lease_exp: date | None = None


@dataclass(slots=True)
class PropertyObservation:
    defeased_status: str = ""
    occupancy: float | None = None
    financials_start: date | None = None
    financials_end: date | None = None
    noi: float | None = None
    ncf: float | None = None
    debt_service: float | None = None  # for the financials period, whole loan
    valuation: float | None = None  # most recent appraisal, if any
    tenants: tuple[Tenant, Tenant, Tenant] = field(default_factory=lambda: (Tenant(), Tenant(), Tenant()))


@dataclass(slots=True)
class Property:
    """A collateral property; rollup marks a portfolio loan's totals row."""

    seq: int
    rollup: bool = False
    name: str = ""
    property_type: str = ""
    city: str = ""
    state: str = ""
    net_rentable: float | None = None
    noi_at_sec: float | None = None
    ncf_at_sec: float | None = None
    dscr_at_sec: float | None = None  # NOI basis
    dscr_ncf_at_sec: float | None = None
    occupancy_at_sec: float | None = None
    valuation_at_sec: float | None = None
    observations: dict[date, PropertyObservation] = field(default_factory=dict)


@dataclass(slots=True)
class LoanObservation:
    """One monthly remittance report for the loan."""

    period_end: date
    maturity_date: date | None = None
    current_balance: float | None = None
    current_rate: float | None = None
    paid_through_date: date | None = None
    payment_status: str = ""
    workout_strategy: str = ""
    special_servicer_transfer_date: date | None = None
    master_servicer_return_date: date | None = None
    pi_advances_outstanding: float | None = None
    liquidation_code: str = ""
    modified: bool | None = None
    # Outcome fields: read by the backtest, not by scoring.
    liquidation_date: date | None = None
    realized_loss: float | None = None
    modification_code: str = ""


@dataclass(slots=True)
class Companion:
    """Another note of the same loan held by the same trust (1A, 1B...)."""

    asset_number: str
    payment_at_sec: float | None = None
    balances: dict[date, float] = field(default_factory=dict)
    rates: dict[date, float] = field(default_factory=dict)


@dataclass(slots=True)
class LoanHistory:
    """Static terms plus monthly observations in ascending period order."""

    trust_cik: str
    asset_number: str
    origination_date: date | None = None
    maturity_date: date | None = None  # latest known; observations carry per-period values
    ard_date: date | None = None
    prepayment_lockout_end: date | None = None
    yield_maintenance_end: date | None = None
    original_amount: float | None = None
    payment_at_sec: float | None = None  # periodic (monthly) P&I of this note
    interest_only: bool | None = None
    # Other SEC trusts reporting a property with the same name and location:
    # evidence of a split (pari passu) loan.
    other_trusts: int = 0
    # Notes of one loan in one trust with financials on one note.
    companion_of: str = ""
    companions: list[Companion] = field(default_factory=list)
    observations: list[LoanObservation] = field(default_factory=list)
    properties: list[Property] = field(default_factory=list)
