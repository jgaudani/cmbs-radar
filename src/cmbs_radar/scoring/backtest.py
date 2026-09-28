"""Checks the scoring against history: score each loan as it looked 12-24
months before its refi date, with that quarter's rates and only the data
reported by then, and compare with what happened."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from importlib import resources

from . import engine
from .assumptions import Assumptions
from .model import LoanHistory

# ---- point-in-time rates ----------------------------------------------------


@dataclass(slots=True)
class Rates:
    """Base rates (10-year Treasury) by calendar quarter, e.g. "2022Q3": 0.031."""

    version: str
    description: str
    quarterly: dict[str, float]

    def at(self, d: date) -> float | None:
        return self.quarterly.get(quarter(d))

    def to_dict(self) -> dict:
        return {"version": self.version, "description": self.description, "quarterly": self.quarterly}


def default_rates() -> Rates:
    raw = json.loads(resources.files("cmbs_radar.scoring").joinpath("rates.json").read_text())
    return Rates(raw["version"], raw["description"], raw["quarterly"])


def quarter(d: date) -> str:
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


# ---- outcomes -----------------------------------------------------------------
# The question is Newmark's: did the loan pay off by refi date + grace without
# a loss? Some servicers transfer a loan to special servicing when the balloon
# is days late and it pays off weeks later: a late refinance, not a failure.
# Events only count when the loan hasn't paid off by the end of the window.

REFINANCED = "refinanced"  # paid off (codes 2, 5, 8, 9) on time, nothing went wrong
REFINANCED_LATE = "refinanced_late"  # paid off in the window after special servicing, a missed balloon or a short extension
LOSS = "loss"  # liquidation / DPO (codes 3, 6, 7) or a realized loss
SPECIAL_SERVICING = "special_servicing"  # transferred after the scoring date, not paid off
MATURITY_DEFAULT = "maturity_default"  # 90+ days or non-performing matured balloon
EXTENDED = "extended"  # maturity moved later or modified
PAST_MATURITY = "past_maturity"  # still outstanding after refi date + grace
UNRESOLVED = "unresolved"  # left the data without a code: excluded

_SEVERITY = {LOSS: 5, SPECIAL_SERVICING: 4, MATURITY_DEFAULT: 3, EXTENDED: 2, PAST_MATURITY: 1}


def trouble(outcome: str) -> bool:
    """The loan did not pay off within the window, or took a loss."""
    return outcome not in (REFINANCED, REFINANCED_LATE, UNRESOLVED)


@dataclass(slots=True)
class Config:
    min_months: int = 12  # scoring point, months before refi date
    max_months: int = 24
    target_months: int = 18
    grace_months: int = 6  # outcome window after refi date
    # "scoring" (honest forecast: rates known at the scoring date) or "refi"
    # (hindsight: the rate the loan actually faced).
    rates_at: str = "scoring"

    def to_dict(self) -> dict:
        # Keys are part of the stored JSON the api (and UI) read.
        return {"MinMonths": self.min_months, "MaxMonths": self.max_months, "TargetMonths": self.target_months,
                "GraceMonths": self.grace_months, "RatesAt": self.rates_at}


@dataclass(slots=True)
class Sample:
    score: engine.Score  # as of score.period_end, with that quarter's rate
    base_rate: float
    refi_date: date
    performing: bool = True  # not in special servicing or 60+ delinquent when scored
    outcome: str = ""
    outcome_date: date | None = None

    @property
    def trouble(self) -> bool:
        return trouble(self.outcome)


def evaluate(h: LoanHistory, data_end: date, a: Assumptions, rates: Rates, cfg: Config) -> Sample | None:
    """Score h at the report closest to target_months before its refi date and
    classify the outcome. None when there's no such report, the outcome window
    isn't over by data_end, or the loan can't be scored."""
    i, refi = _pick(h, cfg)
    if i < 0:
        return None
    window_end = engine.add_months(refi, cfg.grace_months)
    if data_end < window_end:
        return None  # outcome not known yet
    as_of = h.observations[i].period_end
    rate_date = refi if cfg.rates_at == "refi" else as_of
    pit = dataclasses.replace(a)
    r = rates.at(rate_date)
    if r is not None:
        pit.base_rate = r
        pit.version = f"{a.version}@{quarter(rate_date)}"
    s = engine.score_at(h, i, pit)
    if s.cls in (engine.EXCLUDED, engine.INSUFFICIENT_DATA):
        return None
    smp = Sample(score=s, base_rate=pit.base_rate, refi_date=refi)
    smp.performing = not ({engine.FLAG_SPECIAL_SERVICING, engine.FLAG_DELINQUENT} & set(s.flags))
    smp.outcome, smp.outcome_date = _outcome(h, i, refi, window_end)
    return smp


def _pick(h: LoanHistory, cfg: Config) -> tuple[int, date | None]:
    """The report whose months-to-refi (as reported then) is in [min, max] and
    closest to target, and that refi date."""
    best, best_dist, best_refi = -1, None, None
    for i, o in enumerate(h.observations):
        refi = h.ard_date if h.ard_date is not None else o.maturity_date
        if refi is None:
            continue
        m = engine.months_between(o.period_end, refi)
        if m < cfg.min_months or m > cfg.max_months:
            continue
        d = abs(m - cfg.target_months)
        if best_dist is None or d < best_dist:
            best, best_dist, best_refi = i, d, refi
    return best, best_refi


def _outcome(h: LoanHistory, i: int, refi: date, window_end: date) -> tuple[str, date | None]:
    """Read the reports after the scoring date through window_end."""
    as_of = h.observations[i].period_end
    worst, worst_at = "", None

    def note(o: str, at: date) -> None:
        nonlocal worst, worst_at
        if _SEVERITY.get(o, 0) > _SEVERITY.get(worst, 0):
            worst, worst_at = o, at

    last_seen = as_of
    for o in h.observations[i + 1:]:
        last_seen = o.period_end
        if o.period_end > window_end:
            break
        at = o.liquidation_date or o.period_end
        if o.liquidation_code in ("3", "6", "7"):
            note(LOSS, at)
        if o.realized_loss is not None and o.realized_loss > 0:
            note(LOSS, at)
        t = o.special_servicer_transfer_date
        if t is not None and t > as_of:
            note(SPECIAL_SERVICING, t)
        if o.payment_status in ("3", "5", "6"):
            note(MATURITY_DEFAULT, o.period_end)
        if o.maturity_date is not None and o.maturity_date > refi + timedelta(days=30) and h.ard_date is None:
            note(EXTENDED, o.period_end)
        if o.modification_code and o.modification_code != h.observations[i].modification_code:
            note(EXTENDED, o.period_end)
        if o.liquidation_code in ("2", "5", "8", "9") and (o.current_balance is None or o.current_balance <= 0):
            if worst == LOSS:
                return LOSS, worst_at
            if worst:
                return REFINANCED_LATE, at
            return REFINANCED, at
    if worst:
        return worst, worst_at
    # Still reported, with a balance, after the grace period: it didn't
    # refinance on time.
    if last_seen >= window_end - timedelta(days=45):
        return PAST_MATURITY, window_end
    return UNRESOLVED, None


# ---- report -------------------------------------------------------------------


def _group(label: str, ss: list[Sample]) -> dict:
    n = len(ss)
    t = sum(1 for s in ss if s.trouble)
    return {"label": label, "loans": n, "trouble": t, "trouble_rate": t / n if n else 0.0,
            "whole_balance": sum(s.score.whole_balance or 0.0 for s in ss)}


_METRICS = {  # oriented so that higher means riskier
    "refi_gap_pct": lambda s: s.refi_gap_pct,
    "dscr_now": lambda s: None if s.dscr is None else -s.dscr,
    "debt_yield_now": lambda s: None if s.debt_yield is None else -s.debt_yield,
    "dscr_at_securitized": lambda s: None if s.dscr_at_sec is None else -s.dscr_at_sec,
}


def summarize(samples: list[Sample]) -> dict:
    """The report stored with each backtest (its JSON shape is read by the api).
    "Performing" repeats the analysis for loans with no special servicing or
    delinquency when scored."""
    res = [s for s in samples if s.outcome != UNRESOLVED]
    perf = [s for s in res if s.performing]
    by_outcome: dict[str, int] = {}
    for s in samples:
        by_outcome[s.outcome] = by_outcome.get(s.outcome, 0) + 1
    classes = [engine.CLEAN_REFI, engine.GAP_REFI, engine.DISTRESSED]
    buckets = [("surplus over 25%", float("-inf"), -0.25), ("surplus 0-25%", -0.25, 0.0), ("gap 0-10%", 0.0, 0.10),
               ("gap 10-25%", 0.10, 0.25), ("gap 25%+", 0.25, float("inf"))]
    years = sorted({s.refi_date.year for s in res})
    return {
        "samples": len(res),
        "unresolved": len(samples) - len(res),
        "trouble_rate": _group("all", res)["trouble_rate"],
        "by_outcome": by_outcome,
        "by_class": [_group(c, [s for s in res if s.score.cls == c]) for c in classes],
        "by_class_performing": [_group(c, [s for s in perf if s.score.cls == c]) for c in classes],
        "gap_buckets": [_group(lbl, [s for s in res if s.score.refi_gap_pct is not None and lo <= s.score.refi_gap_pct < hi])
                        for lbl, lo, hi in buckets],
        "by_refi_year": [_group(str(y), [s for s in res if s.refi_date.year == y]) for y in years],
        "auc": _aucs(res),
        "auc_performing": _aucs(perf),
    }


def _aucs(ss: list[Sample]) -> dict[str, float]:
    out = {}
    for name, m in _METRICS.items():
        pos, neg = [], []
        for s in ss:
            v = m(s.score)
            if v is not None:
                (pos if s.trouble else neg).append(v)
        a = auc(pos, neg)
        if a is not None:
            out[name] = a
    return out


def auc(pos: list[float], neg: list[float]) -> float | None:
    """Probability that a random troubled loan scores riskier than a random
    refinanced one (ties count half). None unless both groups are non-empty."""
    if not pos or not neg:
        return None
    pts = sorted([(v, True) for v in pos] + [(v, False) for v in neg], key=lambda p: p[0])
    rank_sum, i = 0.0, 0
    while i < len(pts):
        j = i
        while j < len(pts) and pts[j][0] == pts[i][0]:
            j += 1
        avg = (i + j + 1) / 2  # mean of ranks i+1..j
        rank_sum += avg * sum(1 for k in range(i, j) if pts[k][1])
        i = j
    np_, nn = len(pos), len(neg)
    return (rank_sum - np_ * (np_ + 1) / 2) / (np_ * nn)
