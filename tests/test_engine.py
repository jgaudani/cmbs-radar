"""Business rules and data quirks of the scoring engine."""

import math
from dataclasses import replace
from datetime import date

import pytest

from cmbs_radar.scoring import engine as e
from cmbs_radar.scoring.assumptions import default_assumptions, load_assumptions
from cmbs_radar.scoring.model import Companion, LoanHistory, LoanObservation, Property, PropertyObservation, Tenant

A = default_assumptions()
AS_OF = date(2025, 9, 30)


def months_of(start: date, end: date) -> int:
    return int(e.round_half_away((end - start).days / 30.4375))


def office(balance, maturity, start, end, ncf, ds, as_of=AS_OF) -> LoanHistory:
    """Single-property office loan: one report at as_of with a statement for
    start..end (NCF and debt service for that period)."""
    m = months_of(start, end)
    return LoanHistory(
        trust_cik="1", asset_number="7", payment_at_sec=ds / m,  # this note is the whole loan
        observations=[LoanObservation(period_end=as_of, maturity_date=maturity, current_balance=balance, payment_status="0")],
        properties=[Property(
            seq=1, property_type="OF", city="New York", state="NY", net_rentable=500_000,
            ncf_at_sec=ncf * 12 / m, dscr_ncf_at_sec=1.6, occupancy_at_sec=0.95, valuation_at_sec=200e6,
            observations={as_of: PropertyObservation(occupancy=0.93, financials_start=start, financials_end=end,
                                                     ncf=ncf, noi=ncf / 0.95, debt_service=ds)})],
    )


FY24 = (date(2024, 1, 1), date(2024, 12, 31))


# OF sizing in v1: 11% debt yield, 1.40x DSCR at 4.25%+2.75% = 7.00% on 30
# years. With NCF $12M: debt yield $109.1M, DSCR $107.4M -> max $107.4M.
@pytest.mark.parametrize("balance,want", [(80e6, e.CLEAN_REFI), (120e6, e.GAP_REFI), (150e6, e.DISTRESSED)])
def test_sizing_and_classes(balance, want):
    s = e.score_latest(office(balance, date(2026, 6, 1), *FY24, 12e6, 6e6), A)
    assert s.cls == want, s.reasons
    assert s.max_new_loan == pytest.approx(107.36e6, abs=0.05e6)
    assert s.max_loan_debt_yield == pytest.approx(12e6 / 0.11)
    assert s.refi_gap_pct == pytest.approx((balance - 107.36e6) / balance, abs=0.001)
    assert (s.cash_flow_source, s.cash_flow_basis, s.whole_loan_factor) == ("t12", "NCF", 1)
    assert s.dscr == pytest.approx(2.0)  # computed, not reported
    assert (s.months_to_refi, s.refi_date_source) == (8, "maturity")
    assert "Max new loan $107.4M" in " ".join(s.reasons)


def test_annualizes_year_to_date():
    s = e.score_latest(office(80e6, date(2026, 6, 1), date(2025, 1, 1), date(2025, 6, 30), 6e6, 3e6), A)
    assert s.cash_flow == pytest.approx(12e6) and s.debt_service_annual == pytest.approx(6e6)
    assert s.cash_flow_source == "ytd_annualized" and e.FLAG_ANNUALIZED_YTD in s.flags


def test_prefers_recent_full_year_and_no_look_ahead():
    h = office(80e6, date(2026, 6, 1), *FY24, 12e6, 6e6, as_of=date(2025, 3, 31))
    h.observations.append(LoanObservation(period_end=AS_OF, maturity_date=date(2026, 6, 1), current_balance=80e6))
    h.properties[0].observations[AS_OF] = PropertyObservation(  # weak H1 (seasonal)
        financials_start=date(2025, 1, 1), financials_end=date(2025, 6, 30), ncf=4e6, debt_service=3e6)
    s = e.score_latest(h, A)
    assert s.cash_flow_source == "t12" and s.financials_end == date(2024, 12, 31)
    first = e.score_at(h, 0, A)
    assert first.period_end == date(2025, 3, 31) and first.cash_flow == 12e6


def test_underwriting_fallback():
    h = office(80e6, date(2026, 6, 1), *FY24, 12e6, 6e6)
    h.properties[0].observations[AS_OF] = PropertyObservation()
    s = e.score_latest(h, A)
    assert s.cash_flow_source == "underwriting"
    assert {e.FLAG_STALE_FINANCIALS, e.FLAG_UNDERWRITING_FIGURE} <= set(s.flags)
    assert s.cash_flow == pytest.approx(12e6) and s.debt_service_annual == pytest.approx(12e6 / 1.6)


def test_split_loan_sized_on_whole_loan():
    h = office(50e6, date(2026, 6, 1), *FY24, 30e6, 24e6)
    h.payment_at_sec = 250_000  # $3M/yr note vs $24M/yr whole: factor 8
    s = e.score_latest(h, A)
    assert s.whole_loan_factor == 8 and e.FLAG_SPLIT_LOAN in s.flags
    assert s.whole_balance == pytest.approx(400e6)
    assert s.refi_gap_whole == pytest.approx(400e6 - 268.4e6, abs=0.1e6)
    assert s.refi_gap == pytest.approx((400e6 - 268.4e6) / 8, abs=0.02e6)
    assert s.cls == e.DISTRESSED  # naive sizing against the $50M note would say clean

    # 1.1-1.5x without another trust holding the property: an IO period
    # ending, not a split. With other trusts: a split.
    h2 = office(80e6, date(2026, 6, 1), *FY24, 12e6, 6e6)
    h2.payment_at_sec = 6e6 / 12 / 1.3
    assert e.score_latest(h2, A).whole_loan_factor == 1
    h2.other_trusts = 2
    assert e.score_latest(h2, A).whole_loan_factor == pytest.approx(1.3)


def test_split_loan_without_reported_debt_service():
    """Backtest 1719195/1: no debt service in the statement; underwritten
    coverage still reveals the whole loan."""
    h = office(40e6, date(2026, 6, 1), *FY24, 30e6, 24e6)
    h.payment_at_sec = 250_000
    h.properties[0].observations[AS_OF].debt_service = None
    h.properties[0].ncf_at_sec, h.properties[0].dscr_ncf_at_sec = 36e6, 1.5
    s = e.score_latest(h, A)
    assert s.whole_loan_factor == pytest.approx(8) and s.cls != e.CLEAN_REFI


def test_note_debt_service_floor():
    """A near-zero reported payment must not hide a split loan."""
    h = office(36.8e6, date(2026, 6, 1), *FY24, 57e6, 13.5e6)
    h.payment_at_sec = 10
    h.observations[0].current_rate = 0.04
    s = e.score_latest(h, A)
    assert s.whole_loan_factor == pytest.approx(13.5e6 / (36.8e6 * 0.04)) and e.FLAG_SPLIT_LOAN in s.flags


def base():
    return office(80e6, date(2030, 6, 1), *FY24, 12e6, 6e6)


def test_distress_and_exclusions():
    h = base()
    h.observations[0].special_servicer_transfer_date = date(2025, 5, 1)
    assert e.score_latest(h, A).cls == e.DISTRESSED
    h.observations[0].master_servicer_return_date = date(2025, 8, 1)  # returned
    assert e.score_latest(h, A).cls != e.DISTRESSED

    h = base()
    h.observations[0].payment_status = "5"  # non-performing matured balloon
    assert e.score_latest(h, A).cls == e.DISTRESSED

    h = base()
    h.observations[0].liquidation_code, h.observations[0].current_balance = "2", None
    assert e.score_latest(h, A).cls == e.EXCLUDED
    h = base()
    h.observations[0].liquidation_code = "1"  # partial payoff, still outstanding
    assert e.score_latest(h, A).cls != e.EXCLUDED

    h = base()
    h.properties[0].observations[AS_OF].defeased_status = "F"
    assert e.score_latest(h, A).cls == e.EXCLUDED
    # Many filers rename the property instead of setting the status.
    for name, typ in [("Defeased", ""), ("DEFEASED - Collateral", ""), ("x", "SE")]:
        h = base()
        h.properties[0].name, h.properties[0].property_type = name, typ
        assert e.score_latest(h, A).cls == e.EXCLUDED, (name, typ)

    h = base()
    h.observations[0].current_balance = None
    assert e.score_latest(h, A).cls == e.INSUFFICIENT_DATA


def test_watch_and_flags():
    # Five years out, DSCR 1.1x vs 1.6x at securitization, occupancy on the
    # 0-100 scale one trust uses, an anchor tenant leaving soon.
    h = office(80e6, date(2030, 6, 1), *FY24, 6.6e6, 6e6)
    p = h.properties[0]
    p.occupancy_at_sec = 95
    o = p.observations[AS_OF]
    o.occupancy = 0.80
    o.tenants = (Tenant("Big Law LLP", 150_000, date(2026, 12, 31)), Tenant("Small Co", 10_000, date(2026, 12, 31)), Tenant())
    h.observations[0].paid_through_date = date(2025, 6, 1)
    s = e.score_latest(h, A)
    assert s.cls == e.WATCH, s.reasons
    for f in (e.FLAG_DSCR_BELOW_FLOOR, e.FLAG_DSCR_DECLINED, e.FLAG_OCCUPANCY_DECLINED, e.FLAG_TENANT_ROLLOVER, e.FLAG_PAID_THROUGH_LAG):
        assert f in s.flags
    assert s.occupancy_at_sec == pytest.approx(0.95)

    # A big lease rolling in 4 years is normal: only near-term rollover counts.
    healthy = base()
    healthy.properties[0].observations[AS_OF].tenants = (Tenant("Big Law LLP", 150_000, date(2029, 12, 31)), Tenant(), Tenant())
    assert e.score_latest(healthy, A).cls == e.NO_ACTION


def test_ard_is_refi_date():
    h = office(80e6, date(2035, 6, 1), *FY24, 12e6, 6e6)
    h.ard_date = date(2026, 6, 1)
    s = e.score_latest(h, A)
    assert (s.refi_date_source, s.cls) == ("ard", e.CLEAN_REFI)


def test_companion_notes():
    h = office(40e6, date(2026, 6, 1), *FY24, 12e6, 6e6)
    h.payment_at_sec = 6e6 / 12 / 3
    h.companions = [Companion("1A", 6e6 / 12 / 3, {AS_OF: 40e6}), Companion("1B", 6e6 / 12 / 3, {AS_OF: 40e6})]
    s = e.score_latest(h, A)
    assert s.balance == pytest.approx(120e6) and s.whole_loan_factor == 1
    assert s.cls == e.GAP_REFI and "companion notes 1A, 1B" in " ".join(s.reasons)
    c = LoanHistory("1", "1A", companion_of="1", observations=[LoanObservation(period_end=AS_OF, current_balance=40e6)])
    s = e.score_latest(c, A)
    assert s.cls == e.EXCLUDED and "loan 1" in s.reasons[0]


def test_rate_scenario():
    """Demo step 3: rates -50bp move a loan from gap refi to clean."""
    h = office(110e6, date(2026, 6, 1), *FY24, 12e6, 6e6)
    base_s, low = e.score_latest(h, A), e.score_latest(h, A.with_rate_shift(-50))
    assert (base_s.cls, low.cls) == (e.GAP_REFI, e.CLEAN_REFI)
    assert low.assumptions_version == "v1-50bp" and low.market_rate == pytest.approx(0.065)
    assert A.base_rate == 0.0425  # the original is untouched
    ch = e.changes(base_s, low, A)
    assert "class gap_refi -> clean_refi" in ch and "refi gap moved below 0.02" in ch


def test_consolidate_groups():
    """245 Park Avenue: one whole loan, a note in several trusts; the median
    whole-balance estimate represents it; ties broken by trust and asset."""
    def mk(trust, bal, ds):
        h = office(bal, date(2027, 6, 1), *FY24, 90e6, ds)
        h.trust_cik, h.other_trusts = trust, 2
        h.properties[0].name = "245 Park Avenue"
        h.payment_at_sec = bal * 0.04 / 12
        return h, e.score_latest(h, A)

    (h1, s1), (h2, s2), (h3, s3) = mk("1", 38e6, 45e6), mk("2", 94e6, 58e6), mk("3", 80e6, 43e6)
    other = base()
    so = e.score_latest(other, A)
    h1.properties[0].name = "245 PARK AVENUE"
    keys = [e.whole_loan_key(h, s) for h, s in ((h1, s1), (h2, s2), (h3, s3), (other, so))]
    assert keys[0] == keys[1] == keys[2] == "245 park avenue|new york|NY|2027-06" and keys[3] == ""
    groups = e.consolidate_groups([s1, s2, s3, so], keys)
    assert [s1.group_primary, s2.group_primary, s3.group_primary, so.group_primary] == [True, False, False, True]
    g = groups[keys[0]]
    assert (g.notes, g.sec_balance) == (3, 212e6)
    assert "3 notes of this loan are in SEC trusts, $212.0M combined" in " ".join(s1.reasons)

    # Equal estimates sort by trust then asset, so reruns agree: ["8", "9"],
    # and the median of two is index 1, trust "9". (An unstable sort once
    # picked arbitrarily; a field-by-field rerun comparison caught it.)
    t9, t8 = replace(s2, trust_cik="9", group_primary=False), replace(s2, trust_cik="8", group_primary=False)
    e.consolidate_groups([t9, t8], ["k", "k"])
    assert t9.group_primary and not t8.group_primary


def test_assumptions_validation():
    assert A.sizing_for("OF").debt_yield == 0.11 and A.sizing_for("??") == A.default
    bad = ('{"version":"x","base_rate":4.25,"default":{"debt_yield":0.1,"dscr":1.3,"spread":0.02,"amort_years":30},'
           '"horizon_months":24,"gap_tolerance":0.02,"distress_gap":0.25,"t12_max_age_months":15,"stale_financials_months":18}')
    with pytest.raises(ValueError, match="base_rate"):
        load_assumptions(bad)
    with pytest.raises(ValueError, match="unknown"):
        load_assumptions('{"version":"x","typo_field":1}')


@pytest.mark.parametrize("a,b,want", [
    ("2025-09-30", "2026-06-01", 8), ("2025-09-11", "2025-10-11", 1), ("2025-09-11", "2025-10-10", 0),
    ("2025-09-30", "2025-06-01", -3), ("2025-09-11", "2025-09-11", 0)])
def test_months_between(a, b, want):
    assert e.months_between(date.fromisoformat(a), date.fromisoformat(b)) == want


def test_date_and_rounding_semantics():
    assert e.add_months(date(2021, 1, 31), 1) == date(2021, 3, 3)  # rolls over, doesn't clamp
    assert e.add_months(date(2024, 12, 15), 2) == date(2025, 2, 15)
    assert e.round_half_away(2.5) == 3 and e.round_half_away(-2.5) == -3  # round() gives 2 / -2
    assert e.money(1_080_000_000) == "$1.08B" and e.money(-190.8e6) == "-$190.8M"
