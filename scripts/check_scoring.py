"""Regression check: re-score every live loan in memory with the latest
stored run's assumptions and compare every field of every note with that
run. Run after changing the engine: an intended change shows up as a diff,
an unintended one as a surprise. (Originally the proof that the Python port
matched the Go implementation: 0 differences on 17,369 notes.)

    uv run python scripts/check_scoring.py            # uses $DATABASE_URL
"""

import math
import os
import sys
from collections import Counter
from datetime import date

from cmbs_radar.scoring.assumptions import load_assumptions
from cmbs_radar.scoring.load import Loader, connect
from cmbs_radar.scoring.universe import score_universe

DSN = os.environ.get("DATABASE_URL", "postgres://radar:radar@localhost:5432/radar?sslmode=disable")
NUM = ["balance", "whole_loan_factor", "whole_balance", "current_rate", "cash_flow", "debt_service_annual", "dscr",
       "dscr_at_sec", "debt_yield", "occupancy", "occupancy_at_sec", "market_rate", "max_loan_debt_yield",
       "max_loan_dscr", "max_new_loan", "refi_gap_whole", "refi_gap", "refi_gap_pct"]
OTHER = ["period_end", "property_type", "class", "flags", "reasons", "refi_date", "refi_date_source", "months_to_refi",
         "prepay_open_date", "cash_flow_basis", "cash_flow_source", "financials_end", "prev_class", "changes",
         "whole_loan_key", "group_primary", "group_notes"]


def close(a, b):
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-6)


conn = connect(DSN)
run_id, js = conn.execute("SELECT run_id, assumptions::text FROM scoring.runs WHERE status='succeeded' ORDER BY run_id DESC LIMIT 1").fetchone()
a = load_assumptions(js)  # the exact assumptions the stored run used
cols = NUM + OTHER
stored = {(r[0], r[1]): dict(zip(cols, r[2:])) for r in conn.execute(
    f"SELECT trust_cik, asset_number, {', '.join(cols)} FROM scoring.loan_scores WHERE run_id = %s", (run_id,))}

fresh = {}
for s in score_universe(Loader(conn), a):
    sc = s.score
    fresh[(sc.trust_cik, sc.asset_number)] = {
        **{k: getattr(sc, k) for k in NUM}, "period_end": sc.period_end, "property_type": sc.property_type or None,
        "class": sc.cls, "flags": sc.flags, "reasons": sc.reasons, "refi_date": sc.refi_date,
        "refi_date_source": sc.refi_date_source or None, "months_to_refi": sc.months_to_refi,
        "prepay_open_date": sc.prepay_open_date, "cash_flow_basis": sc.cash_flow_basis or None,
        "cash_flow_source": sc.cash_flow_source or None, "financials_end": sc.financials_end,
        "prev_class": s.prev_period.cls if s.prev_period else None, "changes": s.changes,
        "whole_loan_key": sc.whole_loan_key or None, "group_primary": sc.group_primary,
        "group_notes": s.group.notes if s.group else None}

print(f"stored run {run_id}: {len(stored)} notes; re-scored now: {len(fresh)} notes")
missing, extra = stored.keys() - fresh.keys(), fresh.keys() - stored.keys()
diffs = Counter()
examples = {}
for k in stored.keys() & fresh.keys():
    g, p = stored[k], fresh[k]
    for c in NUM:
        if not close(g[c], p[c]):
            diffs[c] += 1
            examples.setdefault(c, (k, g[c], p[c]))
    for c in OTHER:
        gv, pv = g[c], p[c]
        if isinstance(gv, date) or isinstance(pv, date):
            gv = gv.isoformat() if gv else None
            pv = pv.isoformat() if pv else None
        if c in ("flags", "reasons", "changes"):
            gv, pv = list(gv or []), list(pv or [])
        if gv != pv:
            diffs[c] += 1
            examples.setdefault(c, (k, gv, pv))

print(f"missing now: {len(missing)}, new now: {len(extra)}")
if not diffs and not missing and not extra:
    print("OK: every field of every note matches the stored run.")
    sys.exit(0)
for c, n in diffs.most_common():
    k, gv, pv = examples[c]
    print(f"  {c}: {n} rows differ, e.g. {k}\n     stored: {gv!r}\n     fresh:  {pv!r}")
sys.exit(1)
