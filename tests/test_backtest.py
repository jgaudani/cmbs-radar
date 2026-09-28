"""Backtest rules: scoring point, point-in-time rates, outcomes, AUC."""

from datetime import date

import pytest

from cmbs_radar.scoring import backtest as bt
from cmbs_radar.scoring import engine as e
from cmbs_radar.scoring.assumptions import default_assumptions
from cmbs_radar.scoring.model import LoanHistory, LoanObservation, Property, PropertyObservation

A = default_assumptions()
RATES = bt.default_rates()
CFG = bt.Config()


def history(n, maturity=date(2023, 7, 1), mutate=None, start=date(2021, 6, 30)) -> LoanHistory:
    """Monthly office loan from start for n reports, full-year statement on each."""
    h = LoanHistory("1", "7", payment_at_sec=4e6 / 12)
    p = Property(seq=1, name="Test Tower", property_type="OF", city="New York", state="NY", ncf_at_sec=10e6, dscr_ncf_at_sec=2.5)
    for i in range(n):
        pe = e.add_months(start, i)
        o = LoanObservation(period_end=pe, maturity_date=maturity, current_balance=100e6, payment_status="0")
        if mutate:
            mutate(i, o)
        h.observations.append(o)
        p.observations[pe] = PropertyObservation(financials_start=date(2021, 1, 1), financials_end=date(2021, 12, 31),
                                                 ncf=10e6, debt_service=4e6, occupancy=0.9)
    h.properties = [p]
    return h


def test_point_in_time_scoring():
    def paid(i, o):
        if o.period_end > date(2023, 7, 15):
            o.current_balance, o.liquidation_code, o.liquidation_date = None, "5", date(2023, 7, 1)

    s = bt.evaluate(history(30, mutate=paid), date(2024, 6, 30), A, RATES, CFG)
    # Reports fall on the 30th: 2021-12-30 is exactly 18 months before
    # 2023-07-01, priced at 2021Q4 rates.
    assert s.score.period_end == date(2021, 12, 30)
    assert s.base_rate == 0.0153 and s.score.assumptions_version == "v1@2021Q4"
    assert s.score.market_rate == pytest.approx(0.0153 + 0.0275)
    assert (s.outcome, s.performing) == (bt.REFINANCED, True)
    # Window ending 2024-01-01 isn't observable by 2023-10-01.
    assert bt.evaluate(history(30, mutate=paid), date(2023, 10, 1), A, RATES, CFG) is None


def at(i0, **kw):
    def m(i, o):
        if i >= i0:
            for k, v in kw.items():
                setattr(o, k, v)
    return m


@pytest.mark.parametrize("n,mutate,want", [
    (26, at(25, current_balance=None, liquidation_code="5"), bt.REFINANCED),
    (21, at(20, current_balance=None, liquidation_code="9"), bt.REFINANCED),
    # Trust 1774801: transferred days after maturity, paid off weeks later.
    (28, lambda i, o: (at(25, special_servicer_transfer_date=date(2023, 7, 4))(i, o),
                       at(27, current_balance=None, liquidation_code="5")(i, o)), bt.REFINANCED_LATE),
    (34, at(22, special_servicer_transfer_date=date(2023, 4, 15)), bt.SPECIAL_SERVICING),
    (29, at(28, current_balance=None, liquidation_code="3", realized_loss=20e6), bt.LOSS),
    (34, at(24, maturity_date=date(2025, 7, 1)), bt.EXTENDED),
    (34, at(25, payment_status="5"), bt.MATURITY_DEFAULT),
    (34, None, bt.PAST_MATURITY),
    (20, None, bt.UNRESOLVED),  # vanished without a code
])
def test_outcomes(n, mutate, want):
    s = bt.evaluate(history(n, mutate=mutate), date(2024, 12, 31), A, RATES, CFG)
    assert s.outcome == want


def test_no_look_ahead():
    h = history(34, mutate=at(24, maturity_date=date(2025, 7, 1)))
    h.maturity_date = date(2025, 7, 1)  # the static table holds the latest maturity
    s = bt.evaluate(h, date(2024, 12, 31), A, RATES, CFG)
    assert s.score.refi_date == date(2023, 7, 1)


def test_auc():
    assert bt.auc([3, 4], [1, 2]) == 1
    assert bt.auc([1, 2], [3, 4]) == 0
    assert bt.auc([1, 1], [1, 1]) == 0.5
    assert bt.auc([2, 4], [1, 3]) == 0.75
    assert bt.auc([], [1]) is None


def test_summarize():
    def mk(cls, gap, outcome, perf=True):
        return bt.Sample(score=e.Score("1", "1", cls=cls, refi_gap_pct=gap, whole_balance=1e6), base_rate=0.04,
                         refi_date=date(2023, 7, 1), performing=perf, outcome=outcome)
    r = bt.summarize([mk(e.CLEAN_REFI, -0.3, bt.REFINANCED), mk(e.CLEAN_REFI, -0.1, bt.REFINANCED),
                      mk(e.GAP_REFI, 0.15, bt.EXTENDED), mk(e.GAP_REFI, 0.05, bt.REFINANCED),
                      mk(e.DISTRESSED, 0.4, bt.LOSS, perf=False), mk(e.DISTRESSED, 0.3, bt.SPECIAL_SERVICING),
                      mk(e.DISTRESSED, 0.5, bt.UNRESOLVED)])
    assert (r["samples"], r["unresolved"], r["trouble_rate"]) == (6, 1, 0.5)
    assert [g["trouble_rate"] for g in r["by_class"]] == [0, 0.5, 1]
    assert r["by_class_performing"][2]["loans"] == 1
    assert r["auc"]["refi_gap_pct"] == 1
    assert r["gap_buckets"][0]["loans"] == 1 and r["gap_buckets"][4]["loans"] == 2
    assert not bt.trouble(bt.REFINANCED_LATE) and bt.trouble(bt.PAST_MATURITY) and not bt.trouble(bt.UNRESOLVED)
