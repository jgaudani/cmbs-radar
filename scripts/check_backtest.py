"""Regression check: re-run a stored backtest's configuration and compare
sample by sample (scoring date, rate, class, outcome).

    uv run python scripts/check_backtest.py <backtest_id>
"""

import math
import os
import sys

from cmbs_radar.scoring import engine
from cmbs_radar.scoring.assumptions import load_assumptions
from cmbs_radar.scoring.backtest import Config, Rates, evaluate
from cmbs_radar.scoring.load import Loader, connect

DSN = os.environ.get("DATABASE_URL", "postgres://radar:radar@localhost:5432/radar?sslmode=disable")
conn = connect(DSN)
bid = int(sys.argv[1])
a_js, r_js, c_js = conn.execute("SELECT assumptions::text, rates, config FROM scoring.backtest_runs WHERE backtest_id=%s", (bid,)).fetchone()
a = load_assumptions(a_js)
rates = Rates(r_js["version"], r_js["description"], r_js["quarterly"])
cfg = Config(c_js["MinMonths"], c_js["MaxMonths"], c_js["TargetMonths"], c_js["GraceMonths"], c_js.get("RatesAt", "scoring"))
cols = ["scored_as_of", "base_rate", "refi_date", "class", "performing", "refi_gap_pct", "dscr", "outcome", "outcome_date", "trouble"]
stored = {(r[0], r[1]): r[2:] for r in conn.execute(f"SELECT trust_cik, asset_number, {', '.join(cols)} FROM scoring.backtest_loans WHERE backtest_id=%s", (bid,))}

ld = Loader(conn, include_inactive=True)
py, seen = {}, set()
for t in ld.trusts():
    hs = ld.trust(t)
    end = max((h.observations[-1].period_end for h in hs if h.observations), default=None)
    for h in hs:
        s = evaluate(h, end, a, rates, cfg) if end else None
        if s is None:
            continue
        k = engine.whole_loan_key(h, s.score)
        if k:
            if k in seen:
                continue
            seen.add(k)
        sc = s.score
        py[(sc.trust_cik, sc.asset_number)] = (sc.period_end, s.base_rate, s.refi_date, sc.cls, s.performing,
                                               sc.refi_gap_pct, sc.dscr, s.outcome, s.outcome_date, s.trouble)

bad = 0
for k in stored.keys() | py.keys():
    g, p = stored.get(k), py.get(k)
    same = g is not None and p is not None and all(
        (math.isclose(x, y, rel_tol=1e-9) if isinstance(x, float) and isinstance(y, float) else x == y) for x, y in zip(g, p))
    if not same:
        bad += 1
        if bad <= 5:
            print("differs", k, "\n  stored:", g, "\n  python:", p)
print(f"backtest {bid}: {len(stored)} stored samples, {len(py)} Python samples, {bad} differ")
sys.exit(1 if bad else 0)
