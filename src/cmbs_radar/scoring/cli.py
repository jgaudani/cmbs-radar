"""cmbs-score: score every live loan and write an atomic run to scoring.*.

    cmbs-score                          # into $DATABASE_URL, built-in assumptions
    cmbs-score --dry-run                # print the class mix, write nothing
    cmbs-score --rate-shift-bps -50 --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from collections import Counter

from . import store
from .assumptions import default_assumptions, load_assumptions
from .load import Loader, connect
from .universe import score_universe

log = logging.getLogger("scoring")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cmbs-score", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dsn", default=os.environ.get("DATABASE_URL"), help="Postgres DSN (env DATABASE_URL)")
    ap.add_argument("--assumptions", default=os.environ.get("SCORING_ASSUMPTIONS"), help="assumptions JSON (default: built-in v1)")
    ap.add_argument("--rate-shift-bps", type=float, default=0, help="shift the base rate, e.g. -50")
    ap.add_argument("--keep-runs", type=int, default=30, help="successful runs to keep")
    ap.add_argument("--dry-run", action="store_true", help="score and summarize, don't write")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        run(args)
    except Exception as e:  # jobs exit non-zero so schedulers alert
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
    if args.rate_shift_bps:
        a = a.with_rate_shift(args.rate_shift_bps)

    conn = connect(args.dsn)
    store.check_ingest_schema(conn)
    if not args.dry_run:
        store.migrate(conn)
    start = time.monotonic()
    results = score_universe(Loader(conn), a)
    classes = Counter(r.score.cls for r in results if r.score.group_primary)
    changed = sum(1 for r in results if r.changes)
    log.info("scoring complete assumptions=%s notes=%d changed_since_last_report=%d took=%.1fs dry_run=%s",
             a.version, len(results), changed, time.monotonic() - start, args.dry_run)
    total = sum(classes.values())
    print(f"\n{'class':<18} {'loans':>7} {'share':>6}   (one row per whole loan)")
    for c, n in classes.most_common():
        print(f"{c:<18} {n:>7} {100 * n / total:5.1f}%")
    if not args.dry_run:
        run_id = store.write_run(conn, a, results)
        log.info("run committed run_id=%d pruned_runs=%d", run_id, store.prune(conn, args.keep_runs))


if __name__ == "__main__":
    sys.exit(main())
