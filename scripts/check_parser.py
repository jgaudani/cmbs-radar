"""Regression check for the EX-102 parser: re-parse archived filings
(--raw-dir) and compare with the observation rows stored for them.

    uv run python scripts/check_parser.py data/raw 400
"""

import glob
import gzip
import math
import os
import random
import sys
from datetime import date

from cmbs_radar.ingest.cmbs import LOAN_OBS, PROP_OBS, parse_filing
from cmbs_radar.scoring.load import connect

raw_dir, n = sys.argv[1], int(sys.argv[2])
conn = connect(os.environ.get("DATABASE_URL", "postgres://radar:radar@localhost:5432/radar?sslmode=disable"))
files = sorted(glob.glob(f"{raw_dir}/*/*.xml.gz"))
random.Random(7).shuffle(files)

loan_cols = [c for c, _, _ in LOAN_OBS]
prop_cols = [c for c, _, _ in PROP_OBS]


def same(a, b):
    if isinstance(a, float) or isinstance(b, float):
        return a is not None and b is not None and math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-9)
    return (a if a != "" else None) == (b if b != "" else None)


checked = rows = diffs = 0
examples = []
for path in files:
    if checked >= n:
        break
    acc = os.path.basename(path).removesuffix(".xml.gz")
    f = conn.execute("SELECT trust_cik, period_of_report FROM filings WHERE accession_no=%s AND status='ingested'", (acc,)).fetchone()
    if f is None:
        continue  # e.g. an early dry run
    trust, period = f
    loans, _ = parse_filing(gzip.open(path))
    db_loans = {(r[0], r[1]): r[2:] for r in conn.execute(
        f"SELECT asset_number, period_end, {', '.join(loan_cols)} FROM loan_observations WHERE accession_no=%s AND trust_cik=%s",
        (acc, trust))}
    db_props = {(r[0], r[1], r[2]): r[3:] for r in conn.execute(
        f"SELECT asset_number, property_seq, period_end, {', '.join(prop_cols)} FROM property_observations "
        f"WHERE accession_no=%s AND trust_cik=%s", (acc, trust))}
    checked += 1
    for l in loans:
        pe = l.period_end or period
        if (l.asset_number, pe) in db_loans:  # absent if a newer filing superseded this period
            rows += 1
            for c, want in zip(loan_cols, db_loans[(l.asset_number, pe)]):
                if not same(l.obs[c], want):
                    diffs += 1
                    examples.append((acc, l.asset_number, c, want, l.obs[c]))
        for p in l.properties:
            if (l.asset_number, p.seq, pe) in db_props:
                rows += 1
                for c, want in zip(prop_cols, db_props[(l.asset_number, p.seq, pe)]):
                    if not same(p.obs[c], want):
                        diffs += 1
                        examples.append((acc, l.asset_number, p.seq, c, want, p.obs[c]))
    # Nothing stored for this filing may be missing from the parse.
    parsed = {(l.asset_number, l.period_end or period) for l in loans}
    missing = [k for k in db_loans if k not in parsed]
    if missing:
        diffs += len(missing)
        examples.append((acc, "missing in python", missing[:3]))

print(f"{checked} filings, {rows} stored rows compared, {diffs} differences")
for e in examples[:8]:
    print("  ", e)
sys.exit(1 if diffs else 0)
