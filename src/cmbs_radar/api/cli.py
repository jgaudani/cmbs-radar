"""cmbs-api: serve the CMBS Radar HTTP API and demo UI.

    cmbs-api                              # :8080, $DATABASE_URL, briefs via ANTHROPIC_API_KEY
    cmbs-api --addr 127.0.0.1:9090 --no-briefs
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import uvicorn
from psycopg.types.numeric import FloatLoader
from psycopg_pool import ConnectionPool

from . import service
from .app import create_app
from .brief import DEFAULT_MODEL, Generator


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cmbs-api", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--addr", default=os.environ.get("ADDR", ":8080"), help="listen address (env ADDR)")
    ap.add_argument("--dsn", default=os.environ.get("DATABASE_URL"), help="Postgres DSN (env DATABASE_URL)")
    ap.add_argument("--no-briefs", action="store_true", help="disable LLM briefs")
    ap.add_argument("--model", default=os.environ.get("BRIEF_MODEL", DEFAULT_MODEL), help="Claude model for briefs")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not args.dsn:
        print("error: no Postgres DSN: set --dsn or DATABASE_URL", file=sys.stderr)
        return 1

    def configure(conn):
        conn.adapters.register_loader("numeric", FloatLoader)

    pool = ConnectionPool(args.dsn, min_size=1, max_size=8, kwargs={"autocommit": True}, configure=configure, open=True)
    try:
        service.check_schemas(pool)
        service.migrate(pool)
        svc = service.Service(pool)
        svc.refresh()
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    svc.watch(60)
    host, _, port = args.addr.rpartition(":")
    app = create_app(svc, None if args.no_briefs else Generator(args.model))
    logging.getLogger("api").info("listening addr=%s briefs=%s model=%s", args.addr, not args.no_briefs, args.model)
    uvicorn.run(app, host=host or "0.0.0.0", port=int(port), log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
