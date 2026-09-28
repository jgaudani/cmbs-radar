"""Persists CMBS filings, loans and monthly observations (ingest owns
public.*). Scoring and the api read these tables and check SCHEMA_VERSION.

Design:
- trust_cik is always the issuing trust from the filing header.
- Newest filing wins: observation upserts only overwrite when the incoming
  filing is at least as new (amendments supersede originals; backfills never
  clobber newer data). Static tables COALESCE so omitted fields keep prior
  values.
- One transaction per filing; loans written in asset-number order so two
  filings of one trust saved concurrently lock rows in the same order, and a
  deadlock is still retried.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timezone
from importlib import resources
from typing import Any

import psycopg
from psycopg import errors

from .cmbs import LOAN_OBS, LOAN_STATIC, PROP_OBS, PROP_STATIC, Loan
from .edgar import IndexEntry

SCHEMA_VERSION = 4  # bump on incompatible changes; update scoring and api in the same change set

INGESTED, NOT_CMBS, NO_EX102, FAILED = "ingested", "skipped_not_cmbs", "no_ex102", "failed"

HANDLED, NON_CMBS_ISSUER = "handled", "non_cmbs_issuer"  # skip reasons


class _Table:
    """INSERT ... ON CONFLICT built from column names, so SQL and values can't
    drift out of positional sync."""

    def __init__(self, name: str, keys: list[str], cols: list[str], coalesce: bool, version: str = "",
                 insert_only: tuple[str, ...] = ()):
        self.cols = cols
        sets = [f"{c} = COALESCE(EXCLUDED.{c}, t.{c})" if coalesce else f"{c} = EXCLUDED.{c}"
                for c in cols if c not in keys and c not in insert_only]
        self.sql = (f"INSERT INTO {name} AS t ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
                    f"ON CONFLICT ({', '.join(keys)}) DO UPDATE SET {', '.join(sets)}")
        if version:
            self.sql += f" WHERE EXCLUDED.{version} >= t.{version}"


_FILINGS = _Table("filings", ["accession_no"], ["accession_no", "trust_cik", "trust_name", "depositor_cik", "form_type",
                                                "filed_date", "period_of_report", "status", "loan_count", "error", "ingested_at"],
                  coalesce=False)
_LOANS = _Table("loans", ["trust_cik", "asset_number"],
                ["trust_cik", "asset_number", *[c for c, _, _ in LOAN_STATIC], "first_seen_accession", "last_seen_accession",
                 "last_filed_date"], coalesce=True, version="last_filed_date", insert_only=("first_seen_accession",))
_LOAN_OBS = _Table("loan_observations", ["trust_cik", "asset_number", "period_end"],
                   ["trust_cik", "asset_number", "period_end", "accession_no", "filed_date", *[c for c, _, _ in LOAN_OBS]],
                   coalesce=False, version="filed_date")
_PROPS = _Table("properties", ["trust_cik", "asset_number", "property_seq"],
                ["trust_cik", "asset_number", "property_seq", "is_rollup", "source_asset_number",
                 *[c for c, _, _ in PROP_STATIC], "last_filed_date"], coalesce=True, version="last_filed_date")
_PROP_OBS = _Table("property_observations", ["trust_cik", "asset_number", "property_seq", "period_end"],
                   ["trust_cik", "asset_number", "property_seq", "period_end", "accession_no", "filed_date",
                    *[c for c, _, _ in PROP_OBS]], coalesce=False, version="filed_date")


def _null(v: Any) -> Any:
    return None if v == "" else v


class Store:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.conn = psycopg.connect(dsn, autocommit=True)

    def close(self) -> None:
        self.conn.close()

    def migrate(self) -> None:
        """Bring the database to SCHEMA_VERSION. Everything here derives from
        EDGAR (or the raw archive), so an older schema is dropped and rebuilt."""
        sql = resources.files("cmbs_radar.ingest").joinpath("schema.sql").read_text()
        with self.conn.transaction():
            self.conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (version int NOT NULL)")
            row = self.conn.execute("SELECT version FROM schema_meta").fetchone()
            if row is not None and row[0] == SCHEMA_VERSION:
                self.conn.execute(sql)  # idempotent; picks up new indexes
                return
            self.conn.execute("DROP TABLE IF EXISTS property_observations, properties, loan_observations, loans, filings")
            self.conn.execute(sql)
            self.conn.execute("DELETE FROM schema_meta")
            self.conn.execute("INSERT INTO schema_meta VALUES (%s)", (SCHEMA_VERSION,))

    def should_skip(self, accession: str, ciks: list[str], conn: psycopg.Connection | None = None) -> str | None:
        """HANDLED if already ingested or classified (failed filings retry);
        NON_CMBS_ISSUER if a CIK it is indexed under (trust or depositor) has
        filed non-CMBS data; else None. filings.trust_cik only holds issuing
        trusts, so a CMBS depositor never causes a skip."""
        handled, non_cmbs = (conn or self.conn).execute("""
            SELECT EXISTS (SELECT 1 FROM filings WHERE accession_no = %s AND status <> %s),
                   EXISTS (SELECT 1 FROM filings WHERE trust_cik = ANY(%s) AND status = %s)
                OR EXISTS (SELECT 1 FROM filings WHERE depositor_cik = ANY(%s) AND status = %s)""",
            (accession, FAILED, ciks, NOT_CMBS, ciks, NOT_CMBS)).fetchone()
        return HANDLED if handled else NON_CMBS_ISSUER if non_cmbs else None

    def record_filing(self, e: IndexEntry, period: date | None, status: str, err: str = "",
                      conn: psycopg.Connection | None = None, loan_count: int | None = None) -> None:
        (conn or self.conn).execute(_FILINGS.sql, (
            e.accession_no, e.cik, e.company_name, _null(e.depositor_cik), e.form_type, e.date_filed, period, status,
            loan_count, _null(err), datetime.now(timezone.utc)))

    def save_filing(self, e: IndexEntry, period: date | None, loans: list[Loan]) -> None:
        """All loans of one filing atomically, then the filing marked
        ingested. A crash leaves nothing half-written; the filing retries."""
        ordered = sorted(loans, key=lambda l: l.asset_number)
        for attempt in range(4):
            try:
                with psycopg.connect(self.dsn) as conn, conn.transaction():
                    self._save(conn, e, period, ordered)
                return
            except (errors.DeadlockDetected, errors.SerializationFailure):
                if attempt == 3:
                    raise
                time.sleep((attempt + 1) * 0.1)

    def _save(self, conn: psycopg.Connection, e: IndexEntry, period: date | None, loans: list[Loan]) -> None:
        cik, acc, filed = e.cik, e.accession_no, e.date_filed
        loan_rows, obs_rows, prop_rows, pobs_rows = [], [], [], []
        for l in loans:
            pe = l.period_end or period
            if pe is None:
                raise ValueError(f"loan {l.asset_number}: no reporting period end and no period of report")
            loan_rows.append((cik, l.asset_number, *[_null(l.static[c]) for c, _, _ in LOAN_STATIC], acc, acc, filed))
            obs_rows.append((cik, l.asset_number, pe, acc, filed, *[_null(l.obs[c]) for c, _, _ in LOAN_OBS]))
            for p in l.properties:
                prop_rows.append((cik, l.asset_number, p.seq, p.rollup, _null(p.source_asset),
                                  *[_null(p.static[c]) for c, _, _ in PROP_STATIC], filed))
                pobs_rows.append((cik, l.asset_number, p.seq, pe, acc, filed, *[_null(p.obs[c]) for c, _, _ in PROP_OBS]))
        with conn.cursor() as cur:
            for t, rows in ((_LOANS, loan_rows), (_LOAN_OBS, obs_rows), (_PROPS, prop_rows), (_PROP_OBS, pobs_rows)):
                if rows:
                    cur.executemany(t.sql, rows)
        self.record_filing(e, period, INGESTED, conn=conn, loan_count=len(loans))


class MemSink:
    """In-memory sink for --dry-run and tests; mirrors the Postgres skip
    logic so dry runs make the same requests."""

    def __init__(self) -> None:
        import threading
        self._mu = threading.Lock()
        self.statuses: dict[str, str] = {}
        self.loans: dict[str, list[Loan]] = {}
        self.trusts: dict[str, str] = {}  # accession -> trust CIK it was saved under
        self._not_cmbs: set[str] = set()  # trust and depositor CIKs of non-CMBS filings

    def should_skip(self, accession: str, ciks: list[str]) -> str | None:
        with self._mu:
            if self.statuses.get(accession, FAILED) != FAILED:
                return HANDLED
            return NON_CMBS_ISSUER if any(c in self._not_cmbs for c in ciks) else None

    def record_filing(self, e: IndexEntry, period: date | None, status: str, err: str = "") -> None:
        with self._mu:
            self.statuses[e.accession_no] = status
            if status == NOT_CMBS:
                self._not_cmbs.update(c for c in (e.cik, e.depositor_cik) if c)

    def save_filing(self, e: IndexEntry, period: date | None, loans: list[Loan]) -> None:
        with self._mu:
            self.statuses[e.accession_no] = INGESTED
            self.loans[e.accession_no] = loans
            self.trusts[e.accession_no] = e.cik
