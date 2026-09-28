"""Companion-note grouping (trust 1745511: loan 1 carries the property,
1A-1C are notes with "NA" properties and no financials)."""

from datetime import date

from cmbs_radar.scoring.load import group_companions
from cmbs_radar.scoring.model import LoanHistory, LoanObservation, Property

T = date(2025, 9, 30)


def note(asset, fin, bal):
    p = Property(seq=1, name="20 TIMES SQUARE" if fin else "NA", noi_at_sec=30e6 if fin else None)
    return LoanHistory("1", asset, observations=[LoanObservation(period_end=T, current_balance=bal, current_rate=0.05)], properties=[p])


def test_group_companions():
    loans = {a: note(a, fin, b) for a, fin, b in [
        ("1", True, 16e6), ("1A", False, 16e6), ("1B", False, 16e6),
        ("5A", True, 10e6), ("5B", True, 12e6),  # each has its own data: separate loans
        ("7A", False, 1e6), ("7B", False, 1e6),  # nobody has financials
        ("9A", True, 3e6), ("9B", False, 2e6),  # financials on a suffixed note
        ("10", True, 5e6)]}
    group_companions(loans)
    cs = loans["1"].companions
    assert [c.asset_number for c in cs] == ["1A", "1B"] and cs[0].balances[T] == 16e6
    assert loans["1A"].companion_of == "1" and loans["1B"].companion_of == "1"
    for a in ["5A", "5B", "7A", "7B", "10", "1"]:
        assert loans[a].companion_of == ""
        assert a == "1" or not loans[a].companions
    assert loans["9B"].companion_of == "9A" and len(loans["9A"].companions) == 1
