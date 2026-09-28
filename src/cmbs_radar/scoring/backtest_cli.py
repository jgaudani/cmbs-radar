"""cmbs-backtest: score every loan as it looked 12-24 months before its refi
date (that quarter's rates, data reported by then), compare with what
happened, and store the result in scoring.backtest_*."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time

from . import engine, store
from .assumptions import default_assumptions, load_assumptions
from .backtest import Config, default_rates, evaluate, summarize
from .load import Loader, connect

log = logging.getLogger("backtest")


def main(argv: list[str] | None = None) -> int:
    d = Config()
    ap = argparse.ArgumentParser(prog="cmbs-backtest", description=__doc__)
    ap.add_argument("--dsn", default=os.environ.get("DATABASE_URL"))
    ap.add_argument("--assumptions", default=os.environ.get("SCORING_ASSUMPTIONS"))
    ap.add_argument("--dry-run", action="store_true", help="print the report, don't store it")
    ap.add_argument("--min-months", type=int, default=d.min_months)
    ap.add_argument("--max-months", type=int, default=d.max_months)
    ap.add_argument("--target-months", type=int, default=d.target_months)
    ap.add_argument("--grace-months", type=int, default=d.grace_months)
    ap.add_argument("--rates-at", choices=["scoring", "refi"], default=d.rates_at,
                    help='base rate as of the "scoring" date (forecast) or "refi" date (hindsight diagnostic)')
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        run(args)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def run(args: argparse.Namespace) -> None:
    if not args.dsn:
        raise RuntimeError("no Postgres DSN: set --dsn or DATABASE_URL")
    a = default_assumptions()
    if args.assumptions:
        with open(args.assumptions) as f:
            a = load_assumptions(f)
    cfg = Config(args.min_months, args.max_months, args.target_months, args.grace_months, args.rates_at)
    rates = default_rates()
    conn = connect(args.dsn)
    store.check_ingest_schema(conn)
    if not args.dry_run:
        store.migrate(conn)
    ld = Loader(conn, include_inactive=True)
    start = time.monotonic()
    samples, seen, considered, data_end = [], set(), 0, None
    for t in ld.trusts():
        hs = ld.trust(t)
        # A loan's outcome is observable up to its trust's latest report.
        trust_end = max((h.observations[-1].period_end for h in hs if h.observations), default=None)
        if trust_end is None:
            continue
        data_end = max(data_end, trust_end) if data_end else trust_end
        for h in hs:
            considered += 1
            s = evaluate(h, trust_end, a, rates, cfg)
            if s is None:
                continue
            k = engine.whole_loan_key(h, s.score)  # one sample per whole loan
            if k:
                if k in seen:
                    continue
                seen.add(k)
            samples.append(s)
    rep = summarize(samples)
    log.info("backtest complete loans_considered=%d samples=%d resolved=%d took=%.1fs",
             considered, len(samples), rep["samples"], time.monotonic() - start)
    print_report(rep)
    if not args.dry_run:
        bid = store.save_backtest(conn, a, rates.to_dict(), cfg.to_dict(), data_end, samples, rep)
        log.info("backtest stored backtest_id=%d", bid)


def print_report(r: dict) -> None:
    print(f"\nResolved loans: {r['samples']} (unresolved, excluded: {r['unresolved']}); trouble rate {100 * r['trouble_rate']:.1f}%")

    def table(title: str, gs: list[dict]) -> None:
        print(f"\n{title}\n  {'':<22} {'loans':>7} {'trouble':>8} {'rate':>9}")
        for g in gs:
            print(f"  {g['label']:<22} {g['loans']:>7} {g['trouble']:>8} {100 * g['trouble_rate']:8.1f}%")

    table("By predicted class (all loans)", r["by_class"])
    table("By predicted class (performing when scored)", r["by_class_performing"])
    table("By predicted refi gap", r["gap_buckets"])
    table("By refi year", r["by_refi_year"])
    print("\nAUC (0.5 = chance) and outcomes:", json.dumps({"all": r["auc"], "performing": r["auc_performing"], "outcomes": r["by_outcome"]}))


if __name__ == "__main__":
    sys.exit(main())
