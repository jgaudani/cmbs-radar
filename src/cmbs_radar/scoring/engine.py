"""Scores CMBS loans for refinance opportunity. Pure: no database, no clock.

The scoring job, the api's scenario re-scoring and the backtest all call the
same functions with different inputs. scripts/check_scoring.py re-scores
the universe and compares it with the stored run, field by field.
"""

from __future__ import annotations

import calendar
import math
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from .assumptions import Assumptions, round_half_away
from .model import LoanHistory, LoanObservation, Property


# Classes route an opportunity to the Newmark team that monetizes it.
CLEAN_REFI = "clean_refi"  # in window, no equity gap: Debt & Structured Finance
GAP_REFI = "gap_refi"  # in window, equity shortfall: mezz / pref equity / recap
DISTRESSED = "distressed"  # special servicing, delinquent, or large gap: sales / advisory
WATCH = "watch"  # deteriorating, refi further out: early outreach
NO_ACTION = "none"  # healthy, refi further out
EXCLUDED = "excluded"  # left the pool or fully defeased
INSUFFICIENT_DATA = "insufficient_data"  # can't size: no balance or no cash flow

# Flag codes. Stable strings: the api filters on them.
FLAG_SPECIAL_SERVICING = "special_servicing"
FLAG_DELINQUENT = "delinquent_60_plus"
FLAG_PAST_MATURITY = "past_maturity"
FLAG_PAID_THROUGH_LAG = "paid_through_lag"
FLAG_PI_ADVANCES = "pi_advances"
FLAG_INTEREST_ONLY = "interest_only"
FLAG_MODIFIED = "modified"
FLAG_DSCR_BELOW_FLOOR = "dscr_below_floor"
FLAG_DSCR_DECLINED = "dscr_declined"
FLAG_OCCUPANCY_DECLINED = "occupancy_declined"
FLAG_VALUATION_DECLINED = "valuation_declined"
FLAG_TENANT_ROLLOVER = "tenant_rollover"
FLAG_STALE_FINANCIALS = "stale_financials"
FLAG_ANNUALIZED_YTD = "annualized_ytd"
FLAG_UNDERWRITING_FIGURE = "underwriting_financials"
FLAG_SPLIT_LOAN = "split_loan"
FLAG_SPLIT_LOAN_UNSIZED = "split_loan_unsized"


@dataclass(slots=True)
class Score:
    """One loan's result as of one reporting period."""

    trust_cik: str
    asset_number: str
    period_end: date | None = None
    assumptions_version: str = ""
    property_type: str = ""
    cls: str = ""
    flags: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)  # plain language, most important first

    balance: float | None = None  # this trust's note(s)
    whole_loan_factor: float = 1.0  # whole loan / this note (1 unless split)
    whole_balance: float | None = None
    current_rate: float | None = None
    refi_date: date | None = None  # ARD if present, else maturity
    refi_date_source: str = ""  # "ard" | "maturity"
    months_to_refi: int | None = None
    prepay_open_date: date | None = None  # lockout / yield maintenance end
    cash_flow: float | None = None  # annual, whole property
    cash_flow_basis: str = ""  # "NCF" | "NOI"
    cash_flow_source: str = ""  # "t12" | "ytd_annualized" | "underwriting"
    financials_end: date | None = None
    debt_service_annual: float | None = None  # whole loan
    dscr: float | None = None  # computed: cash_flow / debt_service_annual
    dscr_at_sec: float | None = None
    debt_yield: float | None = None  # cash_flow / whole_balance
    occupancy: float | None = None
    occupancy_at_sec: float | None = None

    market_rate: float = 0.0
    max_loan_debt_yield: float | None = None  # whole loan
    max_loan_dscr: float | None = None
    max_new_loan: float | None = None
    refi_gap_whole: float | None = None  # whole_balance - max_new_loan; negative = surplus
    refi_gap: float | None = None  # this trust's pro rata share
    refi_gap_pct: float | None = None  # of whole balance

    # Set by consolidate_groups: one primary row per whole loan across trusts.
    whole_loan_key: str = ""
    group_primary: bool = False


def score_latest(h: LoanHistory, a: Assumptions) -> Score:
    """Score the loan as of its latest observation."""
    return score_at(h, len(h.observations) - 1, a)


def score_at(h: LoanHistory, i: int, a: Assumptions) -> Score:
    """Score using only observations[0..i]: no look-ahead, so the backtest
    can score history exactly as it looked at the time."""
    s = Score(trust_cik=h.trust_cik, asset_number=h.asset_number, assumptions_version=a.version)
    if i < 0 or i >= len(h.observations):
        s.cls, s.reasons = INSUFFICIENT_DATA, ["No remittance data."]
        return s
    obs = h.observations[i]
    as_of = obs.period_end
    s.period_end = as_of
    s.current_rate = obs.current_rate
    if h.companion_of:
        s.cls = EXCLUDED
        s.reasons = [f"Companion note of loan {h.companion_of} in this trust; scored with it."]
        return s
    s.balance = _positive(obs.current_balance)
    if s.balance is not None:
        for c in h.companions:
            s.balance += c.balances.get(as_of, 0.0)

    fin = _financial_properties(h)
    s.property_type = _loan_property_type(h, fin)
    s.market_rate = a.rate(s.property_type)

    # Left the pool: liquidation code and nothing outstanding. (Code 1 with a
    # balance is a partial payoff; the loan is still live.)
    if obs.liquidation_code and s.balance is None:
        s.cls = EXCLUDED
        s.reasons = [f"Left the pool (liquidation/prepayment code {obs.liquidation_code})."]
        return s
    if _fully_defeased(fin, as_of):
        s.cls = EXCLUDED
        s.reasons = ["Fully defeased: collateral replaced by Treasuries, no refinance needed."]
        return s

    s.refi_date, s.refi_date_source = _refi_date(h, obs)
    if s.refi_date is not None:
        s.months_to_refi = months_between(as_of, s.refi_date)
    s.prepay_open_date = _latest(h.prepayment_lockout_end, h.yield_maintenance_end)

    flags: set[str] = set()
    _status_flags(s, h, obs, a, flags)
    st = _choose_statement(h, fin, i, a)
    _apply_statement(s, h, fin, st, a, flags)
    _trend_flags(s, fin, i, h, a, flags)
    _size(s, a)

    s.cls, reasons = _classify(s, a, flags)
    s.reasons = reasons + _explain(s, st, a, h)
    s.flags = sorted(flags)
    return s


# ---- status -----------------------------------------------------------------


def _status_flags(s: Score, h: LoanHistory, obs: LoanObservation, a: Assumptions, flags: set[str]) -> None:
    if _in_special_servicing(obs):
        flags.add(FLAG_SPECIAL_SERVICING)
    if obs.payment_status in ("2", "3", "5", "6"):  # 60+ days, non-performing matured balloon
        flags.add(FLAG_DELINQUENT)
    if s.months_to_refi is not None and s.months_to_refi < 0:
        flags.add(FLAG_PAST_MATURITY)
    if obs.paid_through_date is not None and obs.period_end - obs.paid_through_date > timedelta(days=a.watch.paid_through_lag_days):
        flags.add(FLAG_PAID_THROUGH_LAG)
    if obs.pi_advances_outstanding is not None and obs.pi_advances_outstanding > 0:
        flags.add(FLAG_PI_ADVANCES)
    if h.interest_only:
        flags.add(FLAG_INTEREST_ONLY)
    if obs.modified:
        flags.add(FLAG_MODIFIED)


def _in_special_servicing(o: LoanObservation) -> bool:
    """Transferred and not returned since."""
    if o.special_servicer_transfer_date is None:
        return False
    return o.master_servicer_return_date is None or o.master_servicer_return_date < o.special_servicer_transfer_date


def _refi_date(h: LoanHistory, o: LoanObservation) -> tuple[date | None, str]:
    if h.ard_date is not None:
        return h.ard_date, "ard"
    if o.maturity_date is not None:
        return o.maturity_date, "maturity"
    if h.maturity_date is not None:
        return h.maturity_date, "maturity"
    return None, ""


# ---- financials -------------------------------------------------------------


def _financial_properties(h: LoanHistory) -> list[Property]:
    """Properties whose statements describe the whole loan: the rollup of a
    portfolio loan, else every property."""
    rollups = [p for p in h.properties if p.rollup]
    return rollups or list(h.properties)


def _loan_property_type(h: LoanHistory, fin: list[Property]) -> str:
    for p in fin:
        if p.rollup and p.property_type:
            return p.property_type
    counts: dict[str, int] = {}
    best = ""
    for p in h.properties:
        if p.rollup or not p.property_type:
            continue
        counts[p.property_type] = counts.get(p.property_type, 0) + 1
        n, nb = counts[p.property_type], counts.get(best, 0)
        if n > nb or (n == nb and p.property_type < best):
            best = p.property_type
    return best


def _fully_defeased(fin: list[Property], as_of: date) -> bool:
    """Every financial property is defeased. Filers signal it inconsistently:
    DefeasedStatusCode "F", or the property renamed "Defeased" / typed SE."""
    n = 0
    for p in fin:
        o = p.observations.get(as_of)
        if not (o is not None and o.defeased_status == "F") and not _defeased_by_name(p):
            return False
        n += 1
    return n > 0


def _defeased_by_name(p: Property) -> bool:
    return p.property_type == "SE" or p.name.strip().lower().startswith("defeas")


@dataclass(slots=True)
class _Statement:
    """One loan-level statement: the sum over the financial properties for
    one reporting period."""

    source: str = ""  # "t12" | "ytd_annualized" | "underwriting"
    start: date | None = None
    end: date | None = None
    months: int = 0
    noi: float | None = None  # as reported for the period
    ncf: float | None = None
    ds: float | None = None

    def annual(self, v: float | None) -> float | None:
        if v is None or self.months <= 0:
            return v
        return v * 12 / self.months


def _choose_statement(h: LoanHistory, fin: list[Property], i: int, a: Assumptions) -> _Statement | None:
    """Most recent full-year statement ending within t12_max_age_months, else
    the latest statement annualized, else underwriting at securitization.
    Only observations[0..i] are considered."""
    as_of = h.observations[i].period_end
    latest: _Statement | None = None
    t12: _Statement | None = None
    seen: set[date] = set()
    for j in range(i, -1, -1):
        st = _statement_at(fin, h.observations[j].period_end)
        if st is None or st.end in seen:
            continue
        seen.add(st.end)
        if latest is None or st.end > latest.end:
            latest = st
        if st.months >= 12 and months_between(st.end, as_of) <= a.t12_max_age_months and (t12 is None or st.end > t12.end):
            t12 = st
    if t12 is not None:
        t12.source = "t12"
        return t12
    if latest is not None:
        latest.source = "ytd_annualized"
        return latest
    return _underwriting_statement(fin)


def _statement_at(fin: list[Property], period: date) -> _Statement | None:
    st = _Statement()
    for p in fin:
        o = p.observations.get(period)
        if o is None or o.financials_end is None or (o.noi is None and o.ncf is None):
            return None  # all financial properties must report
        if st.end is None or o.financials_end > st.end:
            st.end = o.financials_end
        if o.financials_start is not None and (st.start is None or o.financials_start < st.start):
            st.start = o.financials_start
        st.noi = _add(st.noi, o.noi)
        st.ncf = _add(st.ncf, o.ncf)
        st.ds = _add(st.ds, o.debt_service)
    if st.end is None or st.start is None:
        return None
    st.months = int(round_half_away((st.end - st.start).days / 30.4375))
    if st.months < 1:
        return None
    return st


def _underwriting_statement(fin: list[Property]) -> _Statement | None:
    st = _Statement(source="underwriting", months=12)
    for p in fin:
        st.noi = _add(st.noi, p.noi_at_sec)
        st.ncf = _add(st.ncf, p.ncf_at_sec)
        # Whole-loan debt service implied by underwritten coverage.
        if p.ncf_at_sec is not None and p.dscr_ncf_at_sec is not None and p.dscr_ncf_at_sec > 0:
            st.ds = _add(st.ds, p.ncf_at_sec / p.dscr_ncf_at_sec)
        elif p.noi_at_sec is not None and p.dscr_at_sec is not None and p.dscr_at_sec > 0:
            st.ds = _add(st.ds, p.noi_at_sec / p.dscr_at_sec)
    if st.noi is None and st.ncf is None:
        return None
    return st


def _apply_statement(s: Score, h: LoanHistory, fin: list[Property], st: _Statement | None, a: Assumptions,
                     flags: set[str]) -> None:
    """Set cash flow, debt service and the whole-loan factor."""
    if st is None:
        return
    s.cash_flow_source = st.source
    s.financials_end = st.end
    # Size on NCF (after reserves) when reported, as lenders do.
    if st.ncf is not None:
        s.cash_flow, s.cash_flow_basis = st.annual(st.ncf), "NCF"
    else:
        s.cash_flow, s.cash_flow_basis = st.annual(st.noi), "NOI"
    s.debt_service_annual = st.annual(st.ds)
    if st.source == "ytd_annualized" and st.months < 12:
        flags.add(FLAG_ANNUALIZED_YTD)
    elif st.source == "underwriting":
        flags.add(FLAG_UNDERWRITING_FIGURE)
    if st.source == "underwriting" or (st.end is not None and months_between(st.end, s.period_end) > a.stale_financials_months):
        flags.add(FLAG_STALE_FINANCIALS)

    # Whole-loan factor. Property statements cover the whole loan; this note
    # may be one pari passu piece. 1.1-1.5x without another trust holding the
    # property is more likely an interest-only period ending. With no debt
    # service in the statement, underwritten coverage still gives the whole
    # loan's debt service.
    whole_ds = s.debt_service_annual
    if whole_ds is None:
        uw = _underwriting_statement(fin)
        if uw is not None:
            whole_ds = uw.ds
    note_ds = _notes_debt_service(h, s.period_end, s.current_rate)
    if whole_ds is not None and note_ds > 0:
        f = whole_ds / note_ds
        if f >= 1.1 and (f >= 1.5 or h.other_trusts > 0):
            s.whole_loan_factor = f
            flags.add(FLAG_SPLIT_LOAN)
    elif h.other_trusts > 0:
        flags.add(FLAG_SPLIT_LOAN_UNSIZED)
    if s.balance is not None:
        s.whole_balance = s.balance * s.whole_loan_factor
    if s.cash_flow is not None and s.debt_service_annual is not None and s.debt_service_annual > 0:
        s.dscr = s.cash_flow / s.debt_service_annual
    if s.cash_flow is not None and s.whole_balance is not None and s.whole_balance > 0:
        s.debt_yield = s.cash_flow / s.whole_balance
    # Coverage at securitization on the same basis as today's.
    s.dscr_at_sec = _sum_coverage(fin, s.cash_flow_basis)


def _notes_debt_service(h: LoanHistory, as_of: date, rate: float | None) -> float:
    """Annual debt service of the notes this trust holds: the scheduled
    payment at securitization, never less than interest on the balance (some
    filers report a near-zero payment, which would hide a split loan)."""

    def note(pay: float | None, bal: float, r: float | None) -> float:
        v = pay * 12 if pay is not None else 0.0
        if r is not None and bal * r > v:
            v = bal * r
        return v

    bal = 0.0
    for o in h.observations:
        if o.period_end == as_of and o.current_balance is not None:
            bal = o.current_balance
    total = note(h.payment_at_sec, bal, rate)
    for c in h.companions:
        total += note(c.payment_at_sec, c.balances.get(as_of, 0.0), c.rates.get(as_of, rate))
    return total


def _sum_coverage(fin: list[Property], basis: str) -> float | None:
    cf: float | None = None
    ds: float | None = None
    for p in fin:
        c, d = p.noi_at_sec, p.dscr_at_sec
        if basis == "NCF" and p.ncf_at_sec is not None and p.dscr_ncf_at_sec is not None:
            c, d = p.ncf_at_sec, p.dscr_ncf_at_sec
        if c is None or d is None or d <= 0:
            return None
        cf = _add(cf, c)
        ds = _add(ds, c / d)
    if cf is None or ds is None or ds == 0:
        return None
    return cf / ds


# ---- trends -----------------------------------------------------------------


def _trend_flags(s: Score, fin: list[Property], i: int, h: LoanHistory, a: Assumptions, flags: set[str]) -> None:
    w = a.watch
    if s.dscr is not None and s.dscr < w.dscr_floor:
        flags.add(FLAG_DSCR_BELOW_FLOOR)
    if s.dscr is not None and s.dscr_at_sec is not None and s.dscr < s.dscr_at_sec * (1 - w.dscr_decline):
        flags.add(FLAG_DSCR_DECLINED)

    as_of = h.observations[i].period_end
    occ = occ_sec = val = val_sec = None
    for p in fin:
        o = p.observations.get(as_of)
        v = _norm_pct(o.occupancy if o else None)
        if v is not None:
            occ = v  # rollup or single property: one value; else last wins
        v = _norm_pct(p.occupancy_at_sec)
        if v is not None:
            occ_sec = v
        val = _add(val, o.valuation if o else None)
        val_sec = _add(val_sec, p.valuation_at_sec)
    s.occupancy, s.occupancy_at_sec = occ, occ_sec
    if occ is not None and occ_sec is not None and occ_sec - occ >= w.occupancy_decline:
        flags.add(FLAG_OCCUPANCY_DECLINED)
    if val is not None and val_sec is not None and val_sec > 0 and val < val_sec * (1 - w.valuation_decline):
        flags.add(FLAG_VALUATION_DECLINED)

    # A large tenant whose lease ends before the refi date (plus a window)
    # makes the loan hard to refinance. Near-term only: a lease rolling years
    # from now is normal, not a signal.
    if s.refi_date is not None:
        cutoff = add_months(s.refi_date, w.tenant_window_months)
        near = add_months(as_of, a.horizon_months)
        if near < cutoff:
            cutoff = near
        for p in h.properties:
            if p.rollup:
                continue
            o = p.observations.get(as_of)
            if o is None:
                continue
            for t in o.tenants:
                if not t.name or t.lease_exp is None or t.lease_exp > cutoff or t.lease_exp < as_of:
                    continue
                if t.sqft is not None and p.net_rentable is not None and p.net_rentable > 0 and t.sqft / p.net_rentable < w.tenant_share:
                    continue
                flags.add(FLAG_TENANT_ROLLOVER)


def _norm_pct(v: float | None) -> float | None:
    """One trust reports occupancy on 0-100 instead of 0-1."""
    if v is None:
        return None
    return v / 100 if v > 1.5 else v


# ---- sizing -----------------------------------------------------------------


def _size(s: Score, a: Assumptions) -> None:
    if s.cash_flow is None or s.cash_flow <= 0:
        if s.cash_flow is not None:  # negative cash flow supports no loan
            s.max_new_loan = 0.0
    else:
        z = a.sizing_for(s.property_type)
        dy = s.cash_flow / z.debt_yield
        dscr = s.cash_flow / z.dscr / loan_constant(s.market_rate, z.amort_years)
        s.max_loan_debt_yield, s.max_loan_dscr = dy, dscr
        s.max_new_loan = min(dy, dscr)
    if s.max_new_loan is not None and s.whole_balance is not None:
        g = s.whole_balance - s.max_new_loan
        s.refi_gap_whole = g
        s.refi_gap = g / s.whole_loan_factor
        if s.whole_balance > 0:
            s.refi_gap_pct = g / s.whole_balance


def loan_constant(rate: float, amort_years: int) -> float:
    """Annual debt service per dollar of loan: monthly-pay amortizing, or the
    rate for interest-only."""
    if amort_years == 0:
        return rate
    r, n = rate / 12, float(amort_years * 12)
    return 12 * r / (1 - math.pow(1 + r, -n))


# ---- classification ---------------------------------------------------------

_DETERIORATION = [FLAG_DSCR_BELOW_FLOOR, FLAG_DSCR_DECLINED, FLAG_OCCUPANCY_DECLINED, FLAG_VALUATION_DECLINED,
                  FLAG_PAID_THROUGH_LAG, FLAG_PI_ADVANCES, FLAG_TENANT_ROLLOVER, FLAG_MODIFIED]


def _classify(s: Score, a: Assumptions, flags: set[str]) -> tuple[str, list[str]]:
    in_window = s.months_to_refi is not None and s.months_to_refi <= a.horizon_months
    if FLAG_SPECIAL_SERVICING in flags:
        return DISTRESSED, ["In special servicing."]
    if FLAG_DELINQUENT in flags:
        return DISTRESSED, ["60+ days delinquent or non-performing past maturity."]
    if s.balance is None:
        return INSUFFICIENT_DATA, ["No current balance reported."]
    if s.max_new_loan is None:
        return INSUFFICIENT_DATA, ["No cash flow reported, current or at securitization."]
    if s.months_to_refi is None:
        return INSUFFICIENT_DATA, ["No maturity date."]
    gap = s.refi_gap_pct
    window = (f"Refi date {s.refi_date.isoformat()} ({_months_phrase(s.months_to_refi)}): "
              f"{'inside' if in_window else 'outside'} the {a.horizon_months}-month window.")
    if in_window and gap >= a.distress_gap:
        return DISTRESSED, [f"Refi gap is {100 * gap:.0f}% of the loan, at or above the {100 * a.distress_gap:.0f}% distress threshold.", window]
    if in_window and gap > a.gap_tolerance:
        return GAP_REFI, [f"Equity gap at refinance: {100 * gap:.0f}% of the loan.", window]
    if in_window:
        return CLEAN_REFI, ["Refinanceable at today's terms without new equity.", window]
    why = [f.replace("_", " ") for f in _DETERIORATION if f in flags]
    if why:
        return WATCH, ["Deteriorating: " + ", ".join(why) + ".", window]
    return NO_ACTION, [window]


def _explain(s: Score, st: _Statement | None, a: Assumptions, h: LoanHistory) -> list[str]:
    """The numbers behind the class."""
    out: list[str] = []
    if s.max_new_loan is not None and s.whole_balance is not None and s.max_loan_debt_yield is not None:
        z = a.sizing_for(s.property_type)
        out.append(
            f"Max new loan {money(s.max_new_loan)} = lower of {money(s.max_loan_debt_yield)} at a "
            f"{100 * z.debt_yield:.1f}% debt yield and {money(s.max_loan_dscr)} at {z.dscr:.2f}x DSCR "
            f"({100 * s.market_rate:.2f}% rate, {_amort_phrase(z.amort_years)}); loan {money(s.whole_balance)}, "
            f"gap {money(s.refi_gap_whole)}.")
    if s.cash_flow is not None and st is not None:
        src = {"t12": "full-year statement", "ytd_annualized": f"{st.months}-month statement, annualized",
               "underwriting": "underwriting at securitization"}[st.source]
        line = f"Cash flow: {s.cash_flow_basis} {money(s.cash_flow)} from {src}"
        if st.end is not None and st.source != "underwriting":
            line += " ending " + st.end.isoformat()
        if s.dscr is not None:
            line += f"; DSCR {s.dscr:.2f}x"
            if s.dscr_at_sec is not None:
                line += f" ({s.dscr_at_sec:.2f}x at securitization)"
        out.append(line + ".")
    if h.companions:
        out.append(f"Balance includes companion notes {', '.join(c.asset_number for c in h.companions)} held by this trust.")
    if s.whole_loan_factor > 1 and s.balance is not None:
        line = (f"Split loan: this trust's note ({money(s.balance)}) is about 1/{s.whole_loan_factor:.1f} "
                f"of the whole loan ({money(s.whole_balance)}).")
        if h.other_trusts > 0:
            line += f" {h.other_trusts} other SEC trust(s) report the same property."
        out.append(line)
    return out


# ---- change detection -------------------------------------------------------


def changes(prev: Score, cur: Score, a: Assumptions) -> list[str]:
    """What moved between two scores of the same loan: class changes and
    threshold crossings."""
    out: list[str] = []
    if prev.cls != cur.cls:
        out.append(f"class {prev.cls} -> {cur.cls}")
    had = set(prev.flags)
    out += [f"new flag {f}" for f in cur.flags if f not in had]

    def cross(name: str, p: float | None, c: float | None, level: float) -> None:
        if p is not None and c is not None and (p >= level) != (c >= level):
            out.append(f"{name} moved {'above' if c >= level else 'below'} {level:.2f}")

    cross("DSCR", prev.dscr, cur.dscr, 1.0)
    cross("DSCR", prev.dscr, cur.dscr, a.watch.dscr_floor)
    cross("refi gap", prev.refi_gap_pct, cur.refi_gap_pct, a.gap_tolerance)
    cross("refi gap", prev.refi_gap_pct, cur.refi_gap_pct, a.distress_gap)
    return out


# ---- whole-loan grouping across trusts ------------------------------------

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def whole_loan_key(h: LoanHistory, s: Score) -> str:
    """Identifies the whole loan a split note belongs to: property name, city,
    state and refi month. "" for loans that aren't split."""
    split = h.other_trusts > 0 or FLAG_SPLIT_LOAN in s.flags or FLAG_SPLIT_LOAN_UNSIZED in s.flags
    if not split or s.refi_date is None:
        return ""
    name = city = state = ""
    for p in h.properties:
        n = _NON_ALNUM.sub(" ", p.name.lower()).strip(" ")
        if len(n) > 3:
            name, city, state = n, p.city.lower(), p.state.upper()
            if not p.rollup:
                break  # prefer a physical property over a portfolio name
    if not name:
        return ""
    return f"{name}|{city}|{state}|{s.refi_date:%Y-%m}"


@dataclass(slots=True)
class Group:
    """A whole loan across the SEC trusts holding its notes."""

    key: str
    notes: int
    sec_balance: float  # combined note balances: a floor for the whole loan


def consolidate_groups(scores: list[Score], keys: list[str]) -> dict[str, Group]:
    """Mark one primary score per whole loan (the note whose whole-balance
    estimate is the group median) and return group totals by key."""
    by_key: dict[str, list[int]] = {}
    for i, s in enumerate(scores):
        if not keys[i] or s.cls == EXCLUDED:
            s.group_primary = s.cls != EXCLUDED
            continue
        by_key.setdefault(keys[i], []).append(i)
    groups: dict[str, Group] = {}
    for k, idx in by_key.items():
        g = Group(key=k, notes=len(idx), sec_balance=sum(scores[i].balance or 0.0 for i in idx))
        # Deterministic: equal estimates (common for pari passu notes) are
        # broken by trust and asset, so reruns pick the same primary.
        idx.sort(key=lambda i: (scores[i].whole_balance or 0.0, scores[i].trust_cik, scores[i].asset_number))
        median = scores[idx[len(idx) // 2]]
        median.group_primary = True
        if g.notes > 1:
            for i in idx:
                scores[i].reasons.append(
                    f"{g.notes} notes of this loan are in SEC trusts, {money(g.sec_balance)} combined; "
                    f"estimated whole loan {money(median.whole_balance or 0.0)}.")
        groups[k] = g
    return groups


# ---- helpers ----------------------------------------------------------------


def _positive(v: float | None) -> float | None:
    return None if v is None or v <= 0 else v


def _add(total: float | None, v: float | None) -> float | None:
    if v is None:
        return total
    return v if total is None else total + v


def _latest(*ds: date | None) -> date | None:
    vals = [d for d in ds if d is not None]
    return max(vals) if vals else None


def months_between(a: date, b: date) -> int:
    """Whole calendar months from a to b (negative if b is earlier)."""
    m = (b.year - a.year) * 12 + b.month - a.month
    if m > 0 and b.day < a.day:
        m -= 1
    elif m < 0 and b.day > a.day:
        m += 1
    return m


def add_months(d: date, n: int) -> date:
    """Add n calendar months; day overflow rolls into the next month
    (Jan 31 + 1 month = Mar 3) rather than clamping. Stored results depend
    on this, so it is pinned by a test."""
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    dim = calendar.monthrange(y, m)[1]
    if d.day <= dim:
        return date(y, m, d.day)
    return date(y, m, dim) + timedelta(days=d.day - dim)


def _months_phrase(m: int) -> str:
    return f"{-m} months ago" if m < 0 else f"in {m} months"


def _amort_phrase(years: int) -> str:
    return "interest-only" if years == 0 else f"{years}-year amortization"


def money(v: float) -> str:
    sign = ""
    if v < 0:
        sign, v = "-", -v
    if v >= 1e9:
        return f"{sign}${v / 1e9:.2f}B"
    if v >= 1e6:
        return f"{sign}${v / 1e6:.1f}M"
    if v >= 1e3:
        return f"{sign}${v / 1e3:.0f}K"
    return f"{sign}${v:.0f}"
