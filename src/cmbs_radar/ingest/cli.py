"""cmbs-ingest: pull CMBS loan-level data (Form ABS-EE, EX-102) from SEC EDGAR
into Postgres. Idempotent: run it on a schedule and it only fetches what it
hasn't seen.

    cmbs-ingest --ua "Jay Doe jay@example.com" --from 2026Q2
    cmbs-ingest --from 2026Q3 --dry-run --limit 20 --coverage
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import signal
import sys
import time
from datetime import date

from .cmbs import Coverage
from .edgar import Client
from .pipeline import Config, Pipeline, current_quarter, parse_quarter, quarter_range
from .store import MemSink, Store

log = logging.getLogger("ingest")


def main(argv: list[str] | None = None) -> int:
    cur = str(current_quarter(date.today()))
    ap = argparse.ArgumentParser(prog="cmbs-ingest", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ua", default=os.environ.get("EDGAR_USER_AGENT", ""), help='SEC User-Agent with contact email (env EDGAR_USER_AGENT)')
    ap.add_argument("--dsn", default=os.environ.get("DATABASE_URL"), help="Postgres DSN (env DATABASE_URL)")
    ap.add_argument("--from", dest="from_", default=cur, help="first quarter, e.g. 2026Q1")
    ap.add_argument("--to", default=cur, help="last quarter (inclusive)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--rps", type=int, default=3, help="EDGAR requests per second (SEC max 10; EDGAR throttled us at 5)")
    ap.add_argument("--name-filter", default="", help="optional regex on filer names to cut requests")
    ap.add_argument("--limit", type=int, default=0, help="stop after about N CMBS filings are ingested (0 = all)")
    ap.add_argument("--raw-dir", default="", help="optional directory to archive raw EX-102 XML (gzipped)")
    ap.add_argument("--dry-run", action="store_true", help="parse but don't write to Postgres")
    ap.add_argument("--coverage", action="store_true", help="print the EX-102 field coverage report at the end")
    ap.add_argument("-v", action="store_true", help="debug logging")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.v else logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    try:
        quarters = quarter_range(parse_quarter(args.from_), parse_quarter(args.to))
        name_filter = re.compile(args.name_filter) if args.name_filter else None
        client = Client(args.ua, args.rps)
        if args.dry_run:
            sink = MemSink()
        else:
            if not args.dsn:
                raise ValueError("no Postgres DSN: set --dsn or DATABASE_URL (or use --dry-run)")
            sink = Store(args.dsn)
            sink.migrate()
    except (ValueError, OSError, re.error) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    cov = Coverage() if args.coverage else None
    p = Pipeline(client, sink, Config(quarters, args.workers, name_filter, args.limit, args.raw_dir), cov)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: p.stop())
    start = time.monotonic()
    try:
        stats = p.run()
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    log.info("run complete stats=%s took=%ds", stats, time.monotonic() - start)
    if cov:
        print(cov.report())
    if stats.failed:
        # Non-zero exit so the scheduler notices; failures retry next run.
        print(f"error: {stats.failed} filings failed (will retry next run)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
