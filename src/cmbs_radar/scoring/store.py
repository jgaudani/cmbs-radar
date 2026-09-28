"""The scoring schema: runs, loan scores and backtests. Owned by scoring;
read by the api. Scores are derived, so an older schema is dropped and
rebuilt."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from importlib import resources

import psycopg

from .assumptions import Assumptions
from .universe import Scored

SCHEMA_VERSION = 3  # api checks it; bump on incompatible changes and update api in the same change set
INGEST_SCHEMA_VERSION = 4  # the public.* schema this code reads

SCORE_COLUMNS = [
    "run_id", "trust_cik", "asset_number", "period_end", "property_type", "class", "flags", "reasons",
    "balance", "whole_loan_factor", "whole_balance", "current_rate", "refi_date", "refi_date_source",
    "months_to_refi", "prepay_open_date", "cash_flow", "cash_flow_basis", "cash_flow_source", "financials_end",
    "debt_service_annual", "dscr", "dscr_at_sec", "debt_yield", "occupancy", "occupancy_at_sec", "market_rate",
    "max_loan_debt_yield", "max_loan_dscr", "max_new_loan", "refi_gap_whole", "refi_gap", "refi_gap_pct",
    "prev_period_end", "prev_class", "changes", "whole_loan_key", "group_primary", "group_notes", "group_sec_balance",
]


def check_ingest_schema(conn: psycopg.Connection) -> None:
    """Fail fast if ingest's tables aren't the version this code expects."""
    try:
        (v,) = conn.execute("SELECT version FROM public.schema_meta").fetchone()
    except psycopg.Error as e:
        raise RuntimeError(f"reading ingest schema version (has ingest run?): {e}") from e
    if v != INGEST_SCHEMA_VERSION:
        raise RuntimeError(f"ingest schema is v{v}, scoring expects v{INGEST_SCHEMA_VERSION}: update scoring")


def migrate(conn: psycopg.Connection) -> None:
    sql = resources.files("cmbs_radar.scoring").joinpath("schema.sql").read_text()
    with conn.transaction():
        conn.execute("CREATE SCHEMA IF NOT EXISTS scoring")
        conn.execute("CREATE TABLE IF NOT EXISTS scoring.schema_meta (version int NOT NULL)")
        row = conn.execute("SELECT version FROM scoring.schema_meta").fetchone()
        if row is None or row[0] != SCHEMA_VERSION:
            conn.execute("DROP VIEW IF EXISTS scoring.current_scores")
            conn.execute("DROP TABLE IF EXISTS scoring.backtest_loans, scoring.backtest_runs, scoring.loan_scores, scoring.runs")
            conn.execute("DELETE FROM scoring.schema_meta")
            conn.execute("INSERT INTO scoring.schema_meta VALUES (%s)", (SCHEMA_VERSION,))
        conn.execute(sql)


def _row(run_id: int, s: Scored) -> tuple:
    sc = s.score
    p = s.prev_period
    return (run_id, sc.trust_cik, sc.asset_number, sc.period_end, sc.property_type or None, sc.cls, sc.flags, sc.reasons,
            sc.balance, sc.whole_loan_factor, sc.whole_balance, sc.current_rate, sc.refi_date, sc.refi_date_source or None,
            sc.months_to_refi, sc.prepay_open_date, sc.cash_flow, sc.cash_flow_basis or None, sc.cash_flow_source or None,
            sc.financials_end, sc.debt_service_annual, sc.dscr, sc.dscr_at_sec, sc.debt_yield, sc.occupancy,
            sc.occupancy_at_sec, sc.market_rate, sc.max_loan_debt_yield, sc.max_loan_dscr, sc.max_new_loan,
            sc.refi_gap_whole, sc.refi_gap, sc.refi_gap_pct, p.period_end if p else None, p.cls if p else None,
            s.changes, sc.whole_loan_key or None, sc.group_primary, s.group.notes if s.group else None,
            s.group.sec_balance if s.group else None)


def write_run(conn: psycopg.Connection, a: Assumptions, results: list[Scored]) -> int:
    """Record a run and its rows atomically: readers (scoring.current_scores)
    see the new run only once it commits. A failure marks the run failed and
    leaves the previous one current."""
    (run_id,) = conn.execute(
        "INSERT INTO scoring.runs (status, assumptions_version, assumptions, ingest_schema_version) "
        "VALUES ('running', %s, %s, %s) RETURNING run_id",
        (a.version, json.dumps(a.to_dict()), INGEST_SCHEMA_VERSION)).fetchone()
    try:
        with conn.transaction():
            with conn.cursor().copy(f"COPY scoring.loan_scores ({', '.join(SCORE_COLUMNS)}) FROM STDIN") as cp:
                for s in results:
                    cp.write_row(_row(run_id, s))
            conn.execute("UPDATE scoring.runs SET status = 'succeeded', finished_at = now(), loans_scored = %s "
                         "WHERE run_id = %s", (len(results), run_id))
    except Exception as e:
        conn.execute("UPDATE scoring.runs SET status = 'failed', finished_at = now(), error = %s WHERE run_id = %s",
                     (str(e), run_id))
        raise
    return run_id


def prune(conn: psycopg.Connection, keep: int) -> int:
    """Delete all but the newest `keep` successful runs (and failed runs older
    than them). History only serves month-over-month comparison."""
    cur = conn.execute("""
        DELETE FROM scoring.runs WHERE run_id < (
            SELECT coalesce(min(run_id), 0) FROM (
                SELECT run_id FROM scoring.runs WHERE status = 'succeeded' ORDER BY run_id DESC LIMIT %s) k)""", (keep,))
    return cur.rowcount


def save_backtest(conn: psycopg.Connection, a: Assumptions, rates: dict, config: dict, data_end: date | None,
                  samples: list, report: dict) -> int:
    """Store a backtest and its samples atomically; returns its id."""
    with conn.transaction():
        (bid,) = conn.execute(
            "INSERT INTO scoring.backtest_runs (assumptions, rates, config, data_end, report) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING backtest_id",
            (json.dumps(a.to_dict()), json.dumps(rates), json.dumps(config), data_end, json.dumps(report))).fetchone()
        cols = ["backtest_id", "trust_cik", "asset_number", "scored_as_of", "base_rate", "refi_date", "property_type",
                "class", "performing", "refi_gap_pct", "dscr", "debt_yield", "whole_balance", "outcome", "outcome_date",
                "trouble"]
        with conn.cursor().copy(f"COPY scoring.backtest_loans ({', '.join(cols)}) FROM STDIN") as cp:
            for x in samples:
                sc = x.score
                cp.write_row((bid, sc.trust_cik, sc.asset_number, sc.period_end, x.base_rate, x.refi_date,
                              sc.property_type or None, sc.cls, x.performing, sc.refi_gap_pct, sc.dscr, sc.debt_yield,
                              sc.whole_balance, x.outcome, x.outcome_date, x.trouble))
    return bid
