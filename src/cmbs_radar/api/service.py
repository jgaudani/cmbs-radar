"""The api's data layer: an in-memory snapshot of the latest scoring run,
filters, summaries, loan detail, rate scenarios and the brief cache.

JSON field names are the UI's contract (web/app.js); keep them stable.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime

from psycopg_pool import ConnectionPool

from ..scoring import engine
from ..scoring.assumptions import Assumptions, load_assumptions
from ..scoring.load import Loader
from ..scoring.universe import score_universe
from . import geo
from .brief import PROMPT_VERSION

log = logging.getLogger("api")

# Schema versions this code reads; checked at startup.
INGEST_SCHEMA_VERSION = 4
SCORING_SCHEMA_VERSION = 3
API_SCHEMA_VERSION = 1

TEAMS = {
    engine.CLEAN_REFI: "Debt & Structured Finance",
    engine.GAP_REFI: "Structured Finance (mezz, pref equity, recap)",
    engine.DISTRESSED: "Investment Sales / Note Sales / Advisory",
    engine.WATCH: "Early relationship outreach",
}

PROPERTY_TYPES = {
    "OF": "Office", "RT": "Retail", "MF": "Multifamily", "LO": "Lodging", "IN": "Industrial", "WH": "Warehouse",
    "SS": "Self storage", "MU": "Mixed use", "MH": "Manufactured housing", "HC": "Health care", "CH": "Co-op housing",
    "SE": "Securities", "98": "Other", "ZZ": "Mixed",
}

LIMITS = ("SEC-registered CMBS only: excludes private 144A, bank balance-sheet and agency multifamily loans. "
          "Borrower names are not disclosed.")


class NotFound(Exception):
    pass


class BadParam(ValueError):
    pass


@dataclass(slots=True)
class Location:
    name: str = ""
    city: str = ""
    state: str = ""
    county: str = ""
    metro: str = ""
    properties: int = 0  # physical properties behind the loan
    lat: float = 0.0
    lon: float = 0.0


@dataclass(slots=True)
class Row:
    """One scored note plus what the api adds."""

    s: engine.Score
    trust_name: str = ""
    prev_class: str = ""
    changes: list[str] = field(default_factory=list)
    group_notes: int = 1
    group_sec_balance: float | None = None
    loc: Location = field(default_factory=Location)

    @property
    def id(self) -> str:
        return f"{self.s.trust_cik}/{self.s.asset_number}"


@dataclass(slots=True)
class Snapshot:
    run_id: int
    finished_at: datetime | None
    assumptions: Assumptions
    data_as_of: date | None = None
    rows: list[Row] = field(default_factory=list)
    by_id: dict[str, Row] = field(default_factory=dict)
    locs: dict[str, Location] = field(default_factory=dict)
    trust_names: dict[str, str] = field(default_factory=dict)


# ---- loading ------------------------------------------------------------------

_SCORE_COLS = """trust_cik, asset_number, period_end, coalesce(property_type, ''), class, flags, reasons,
    balance, whole_loan_factor, whole_balance, current_rate, refi_date, coalesce(refi_date_source, ''),
    months_to_refi, prepay_open_date, cash_flow, coalesce(cash_flow_basis, ''), coalesce(cash_flow_source, ''),
    financials_end, debt_service_annual, dscr, dscr_at_sec, debt_yield, occupancy, occupancy_at_sec,
    market_rate, max_loan_debt_yield, max_loan_dscr, max_new_loan, refi_gap_whole, refi_gap, refi_gap_pct,
    coalesce(prev_class, ''), changes, coalesce(whole_loan_key, ''), group_primary, coalesce(group_notes, 1),
    group_sec_balance"""


def check_schemas(pool: ConnectionPool) -> None:
    with pool.connection() as c:
        for name, q, want in [("ingest (public.schema_meta)", "SELECT version FROM public.schema_meta", INGEST_SCHEMA_VERSION),
                              ("scoring (scoring.schema_meta)", "SELECT version FROM scoring.schema_meta", SCORING_SCHEMA_VERSION)]:
            try:
                (v,) = c.execute(q).fetchone()
            except Exception as e:
                raise RuntimeError(f"{name}: {e} (has the service run?)") from e
            if v != want:
                raise RuntimeError(f"{name} is v{v}, api expects v{want}: update api")


def migrate(pool: ConnectionPool) -> None:
    """Create or rebuild the api schema (briefs are regenerable)."""
    with pool.connection() as c, c.transaction():
        c.execute("CREATE SCHEMA IF NOT EXISTS api")
        c.execute("CREATE TABLE IF NOT EXISTS api.schema_meta (version int NOT NULL)")
        row = c.execute("SELECT version FROM api.schema_meta").fetchone()
        if row is None or row[0] != API_SCHEMA_VERSION:
            c.execute("DROP TABLE IF EXISTS api.briefs")
            c.execute("DELETE FROM api.schema_meta")
            c.execute("INSERT INTO api.schema_meta VALUES (%s)", (API_SCHEMA_VERSION,))
        c.execute("""
            CREATE TABLE IF NOT EXISTS api.briefs (
                trust_cik      text        NOT NULL,
                asset_number   text        NOT NULL,
                run_id         bigint      NOT NULL,  -- scoring run the facts came from
                prompt_version text        NOT NULL,
                model          text        NOT NULL,
                brief          text        NOT NULL,
                facts          jsonb       NOT NULL,  -- exactly what the model was given
                created_at     timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (trust_cik, asset_number, run_id, prompt_version))""")


def latest_run_id(pool: ConnectionPool) -> int:
    with pool.connection() as c:
        (v,) = c.execute("SELECT max(run_id) FROM scoring.runs WHERE status = 'succeeded'").fetchone()
    return v or 0


def load_snapshot(pool: ConnectionPool) -> Snapshot:
    with pool.connection() as c:
        row = c.execute("SELECT run_id, finished_at, assumptions::text FROM scoring.runs "
                        "WHERE status = 'succeeded' ORDER BY run_id DESC LIMIT 1").fetchone()
        if row is None:
            raise RuntimeError("no successful scoring run yet: run scoring first")
        snap = Snapshot(run_id=row[0], finished_at=row[1], assumptions=load_assumptions(row[2]))
        _load_locations(c, snap)
        for cik, name in c.execute("""SELECT DISTINCT ON (trust_cik) trust_cik, trust_name FROM filings
                                      WHERE status = 'ingested' AND trust_cik <> '' ORDER BY trust_cik, filed_date DESC"""):
            snap.trust_names[cik] = name
        for r in c.execute(f"SELECT {_SCORE_COLS} FROM scoring.loan_scores WHERE run_id = %s", (snap.run_id,)):
            s = engine.Score(
                trust_cik=r[0], asset_number=r[1], period_end=r[2], property_type=r[3], cls=r[4], flags=list(r[5]),
                reasons=list(r[6]), balance=r[7], whole_loan_factor=r[8], whole_balance=r[9], current_rate=r[10],
                refi_date=r[11], refi_date_source=r[12], months_to_refi=r[13], prepay_open_date=r[14], cash_flow=r[15],
                cash_flow_basis=r[16], cash_flow_source=r[17], financials_end=r[18], debt_service_annual=r[19],
                dscr=r[20], dscr_at_sec=r[21], debt_yield=r[22], occupancy=r[23], occupancy_at_sec=r[24],
                market_rate=r[25], max_loan_debt_yield=r[26], max_loan_dscr=r[27], max_new_loan=r[28],
                refi_gap_whole=r[29], refi_gap=r[30], refi_gap_pct=r[31], whole_loan_key=r[34], group_primary=r[35])
            _add(snap, Row(s=s, prev_class=r[32], changes=list(r[33]), group_notes=r[36], group_sec_balance=r[37]))
    return snap


def _add(snap: Snapshot, row: Row) -> None:
    row.loc = snap.locs.get(row.id, Location())
    row.trust_name = snap.trust_names.get(row.s.trust_cik, "")
    if row.s.period_end and (snap.data_as_of is None or row.s.period_end > snap.data_as_of):
        snap.data_as_of = row.s.period_end
    snap.rows.append(row)
    snap.by_id[row.id] = row


def _load_locations(c, snap: Snapshot) -> None:
    """Each loan's first physical property with a state (else its portfolio
    rollup's name), with metro and map point."""
    for trust, asset, name, city, state, county, n, rollup in c.execute("""
        SELECT trust_cik, asset_number,
               (array_agg(coalesce(name, '') ORDER BY is_rollup, (state IS NULL), property_seq))[1],
               (array_agg(coalesce(city, '') ORDER BY is_rollup, (state IS NULL), property_seq))[1],
               (array_agg(coalesce(state, '') ORDER BY is_rollup, (state IS NULL), property_seq))[1],
               (array_agg(coalesce(county, '') ORDER BY is_rollup, (state IS NULL), property_seq))[1],
               count(*) FILTER (WHERE NOT is_rollup),
               (array_agg(name) FILTER (WHERE is_rollup))[1]
        FROM properties GROUP BY 1, 2"""):
        loc = Location(name=name, city=city, state=state, county=county, properties=n)
        if rollup and n > 1:
            loc.name = rollup  # portfolio: show its name
        loc.metro = geo.metro_for(state, county, city)
        pt = geo.point(loc.metro, state)
        if pt:
            loc.lat, loc.lon = pt
        snap.locs[f"{trust}/{asset}"] = loc


# ---- views --------------------------------------------------------------------


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def opportunity(r: Row) -> dict:
    s = r.s
    o = {
        "id": r.id, "name": r.loc.name, "city": r.loc.city, "state": r.loc.state, "lat": r.loc.lat, "lon": r.loc.lon,
        "properties": r.loc.properties, "property_type": s.property_type,
        "property_type_label": PROPERTY_TYPES.get(s.property_type, ""), "class": s.cls, "months_to_refi": s.months_to_refi,
        "balance": s.balance, "whole_balance": s.whole_balance, "max_new_loan": s.max_new_loan,
        "refi_gap_whole": s.refi_gap_whole, "refi_gap_pct": s.refi_gap_pct, "dscr": s.dscr, "debt_yield": s.debt_yield,
        "occupancy": s.occupancy, "flags": s.flags or [], "notes": max(r.group_notes or 1, 1),
    }
    # Omitted when empty.
    if r.loc.metro:
        o["metro"] = r.loc.metro
    if TEAMS.get(s.cls):
        o["team"] = TEAMS[s.cls]
    if s.refi_date:
        o["refi_date"] = s.refi_date.isoformat()
    if s.max_loan_debt_yield is not None and s.max_loan_dscr is not None:
        o["binding_constraint"] = "debt_yield" if s.max_loan_debt_yield <= s.max_loan_dscr else "dscr"
    if r.prev_class:
        o["prev_class"] = r.prev_class
    if r.changes:
        o["changes"] = r.changes
    return o


@dataclass(slots=True)
class Filter:
    classes: list[str] = field(default_factory=list)
    types: list[str] = field(default_factory=list)
    metro: str = ""
    state: str = ""
    min_months: int | None = None
    max_months: int | None = None
    min_gap_pct: float | None = None
    flags: list[str] = field(default_factory=list)  # all must be present
    query: str = ""  # substring of name, city or trust
    sort: str = "gap"  # gap | gap_pct | maturity | balance
    limit: int = 200

    @classmethod
    def parse(cls, q: dict[str, str]) -> Filter:
        def split(v: str) -> list[str]:
            return [p.strip() for p in v.split(",") if p.strip()]

        f = cls(classes=split(q.get("class", "")), types=split(q.get("type", "").upper()), metro=q.get("metro", ""),
                state=q.get("state", "").upper(), flags=split(q.get("flag", "")), query=q.get("q", "").strip().lower(),
                sort=q.get("sort", "") or "gap")
        for key in ("min_months", "max_months"):
            if v := q.get(key):
                try:
                    setattr(f, key, int(v))
                except ValueError:
                    raise BadParam(f"bad {key}: {v}") from None
        if v := q.get("min_gap_pct"):
            try:
                f.min_gap_pct = float(v)
            except ValueError:
                raise BadParam(f"bad min_gap_pct: {v}") from None
        if v := q.get("limit"):
            try:
                f.limit = int(v)
            except ValueError:
                raise BadParam(f"bad limit: {v}") from None
            if not 1 <= f.limit <= 5000:
                raise BadParam(f"bad limit: {v}")
        return f

    def match(self, r: Row) -> bool:
        """Only group primaries are listed: a split loan appears once."""
        s = r.s
        if not s.group_primary:
            return False
        if self.classes and s.cls not in self.classes:
            return False
        if self.types and s.property_type not in self.types:
            return False
        if self.metro and r.loc.metro != self.metro:
            return False
        if self.state and r.loc.state != self.state:
            return False
        if self.min_months is not None and (s.months_to_refi is None or s.months_to_refi < self.min_months):
            return False
        if self.max_months is not None and (s.months_to_refi is None or s.months_to_refi > self.max_months):
            return False
        if self.min_gap_pct is not None and (s.refi_gap_pct is None or s.refi_gap_pct < self.min_gap_pct):
            return False
        if any(fl not in s.flags for fl in self.flags):
            return False
        if self.query and self.query not in f"{r.loc.name} {r.loc.city} {r.trust_name}".lower():
            return False
        return True

    def apply(self, rows: list[Row]) -> list[Row]:
        out = [r for r in rows if self.match(r)]
        keys = {
            "gap": lambda r: -(r.s.refi_gap_whole or 0.0),
            "gap_pct": lambda r: -(r.s.refi_gap_pct or 0.0),
            "balance": lambda r: -(r.s.whole_balance or 0.0),
            "maturity": lambda r: r.s.refi_date.toordinal() if r.s.refi_date else 10**9,
        }
        out.sort(key=keys.get(self.sort, keys["gap"]))  # stable: ties keep snapshot order
        return out


def summarize(rows: list[Row], as_of: date | None) -> dict:
    """Totals by class and the maturity wall: whole-loan balance by refi
    quarter for the next 12 quarters (earlier refi dates count in the first)."""
    as_of = as_of or date.today()
    q0 = date(as_of.year, (as_of.month - 1) // 3 * 3 + 1, 1)
    wall = []
    for i in range(12):
        q = engine.add_months(q0, 3 * i)
        wall.append({"quarter": f"{q.year}Q{(q.month - 1) // 3 + 1}", "by_class": {}})
    by_class: dict[str, dict] = {}
    total = 0.0
    for r in rows:
        c, wb = r.s.cls, r.s.whole_balance or 0.0
        t = by_class.setdefault(c, {"loans": 0, "whole_balance": 0.0, "refi_gap_whole": 0.0})
        t["loans"] += 1
        t["whole_balance"] += wb
        if (g := r.s.refi_gap_whole or 0.0) > 0:
            t["refi_gap_whole"] += g
        if TEAMS.get(c):
            t["team"] = TEAMS[c]
        total += wb
        if r.s.refi_date:
            months = (r.s.refi_date.year - q0.year) * 12 + r.s.refi_date.month - q0.month
            i = max(int(months / 3), 0)  # truncates toward zero
            if i < len(wall):
                wall[i]["by_class"][c] = wall[i]["by_class"].get(c, 0.0) + wb
    return {"loans": len(rows), "whole_balance": total, "by_class": by_class, "maturity_wall": wall}


def map_points(rows: list[Row]) -> list[dict]:
    """Filtered loans aggregated by metro, else by state."""
    by: dict[str, dict] = {}
    for r in rows:
        loc = r.loc
        if loc.lat == 0 and loc.lon == 0:
            continue  # no location reported
        if loc.metro in geo.BY_ID:
            key, label = loc.metro, geo.BY_ID[loc.metro].name
        else:
            key, label = f"state:{loc.state}", f"{loc.state} (outside major metros)"
        p = by.setdefault(key, {"key": key, "label": label, "lat": loc.lat, "lon": loc.lon, "loans": 0,
                                "whole_balance": 0.0, "by_class": {}, **({"metro": loc.metro} if loc.metro else {})})
        p["loans"] += 1
        p["whole_balance"] += r.s.whole_balance or 0.0
        p["by_class"][r.s.cls] = p["by_class"].get(r.s.cls, 0.0) + (r.s.whole_balance or 0.0)
    return sorted(by.values(), key=lambda p: -p["whole_balance"])


# ---- the service --------------------------------------------------------------


class Service:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool
        self.snap: Snapshot | None = None
        self._scen: dict[tuple[int, float], dict[str, Row]] = {}
        self._scen_lock = threading.Lock()

    def refresh(self) -> None:
        """Load the latest scoring run if it changed."""
        run = latest_run_id(self.pool)
        if self.snap is not None and self.snap.run_id == run:
            return
        snap = load_snapshot(self.pool)
        self.snap = snap  # atomic swap; readers keep their reference
        with self._scen_lock:
            self._scen.clear()  # scenarios are per run
        log.info("loaded scoring run run_id=%d notes=%d assumptions=%s", snap.run_id, len(snap.rows), snap.assumptions.version)
        self._warm()

    # Scenarios the demo uses, precomputed so the first click is instant
    # (each re-scores the whole market: ~10s).
    WARM_SCENARIOS = (0.0, -50.0)

    def _warm(self) -> None:
        def run() -> None:
            for bps in self.WARM_SCENARIOS:
                try:
                    self.scored(bps)
                except Exception:
                    log.exception("warming scenario rate_shift_bps=%s", bps)
        threading.Thread(target=run, daemon=True, name="scenario-warmup").start()

    def watch(self, every: float = 60.0) -> None:
        """Refresh in a background thread so new runs show up without a restart."""
        def loop() -> None:
            while True:
                time.sleep(every)
                try:
                    self.refresh()
                except Exception:
                    log.exception("refreshing scoring run")
        threading.Thread(target=loop, daemon=True, name="snapshot-refresh").start()

    # -- endpoints --

    def meta(self) -> dict:
        snap = self.snap
        a = snap.assumptions
        types = {code: {"label": label, "debt_yield": a.sizing_for(code).debt_yield, "dscr": a.sizing_for(code).dscr,
                        "rate": a.rate(code), "amort_years": a.sizing_for(code).amort_years}
                 for code, label in PROPERTY_TYPES.items()}
        return {"run_id": snap.run_id, "scored_at": snap.finished_at, "data_as_of": _iso(snap.data_as_of),
                "assumptions": {"version": a.version, "base_rate": a.base_rate, "horizon_months": a.horizon_months,
                                "gap_tolerance": a.gap_tolerance, "distress_gap": a.distress_gap},
                "property_types": types, "metros": [m.to_dict() for m in geo.METROS], "teams": TEAMS, "limits": LIMITS}

    def detail(self, trust: str, asset: str) -> dict:
        """Everything about one opportunity. Also exactly the FACTS the brief
        is written from, so the brief can't cite anything else."""
        snap = self.snap
        r = snap.by_id.get(f"{trust}/{asset}")
        if r is None:
            raise NotFound("no such loan in the current scoring run")
        s, a = r.s, snap.assumptions
        z = a.sizing_for(s.property_type)
        sizing = {
            "assumptions_version": a.version, "market_rate": s.market_rate, "target_debt_yield": z.debt_yield,
            "target_dscr": z.dscr, "amort_years": z.amort_years, "current_rate": s.current_rate,
            "annual_cash_flow": s.cash_flow, "cash_flow_basis": s.cash_flow_basis, "cash_flow_source": s.cash_flow_source,
            "financials_end": _iso(s.financials_end), "annual_debt_service_whole_loan": s.debt_service_annual,
            "dscr_at_securitization": s.dscr_at_sec, "occupancy_at_securitization": s.occupancy_at_sec,
            "whole_loan_factor": s.whole_loan_factor, "whole_loan_is_estimate": s.whole_loan_factor > 1,
            "max_loan_by_debt_yield": s.max_loan_debt_yield, "max_loan_by_dscr": s.max_loan_dscr,
            "refi_gap_this_trust_share": s.refi_gap, "refi_date_source": s.refi_date_source,
            "prepayment_open_date": _iso(s.prepay_open_date),
        }
        if r.group_sec_balance is not None:
            sizing["sec_notes_combined_balance"] = r.group_sec_balance
        d = {**opportunity(r), "trust_cik": trust, "asset_number": asset, "trust_name": r.trust_name,
             "as_of_report": _iso(s.period_end), "reasons": s.reasons or [], "sizing": sizing,
             "data_limits": "SEC-registered CMBS only; borrower names are not disclosed. "
                            "Split-loan whole balances are estimated from reported debt service."}
        if s.whole_loan_key:
            others = [{"trust_cik": o.s.trust_cik, "trust_name": o.trust_name, "asset_number": o.s.asset_number,
                       "balance": o.s.balance} for o in snap.rows if o.s.whole_loan_key == s.whole_loan_key and o is not r]
            if others:
                d["other_notes"] = others
        with self.pool.connection() as c:
            d["properties"] = _properties(c, trust, asset)
            d["history"] = _history(c, trust, asset)
        return d

    def scored(self, bps: float) -> dict[str, Row]:
        """Every note scored with the run's assumptions shifted by bps, cached
        per run. Both sides of a scenario come from the same data, so
        differences are the rate move alone."""
        snap = self.snap
        key = (snap.run_id, bps)
        with self._scen_lock:
            if key in self._scen:
                return self._scen[key]
            a = snap.assumptions.with_rate_shift(bps) if bps else snap.assumptions
            start = time.monotonic()
            with self.pool.connection() as c:
                res = score_universe(Loader(c), a)
            m: dict[str, Row] = {}
            for x in res:
                row = Row(s=x.score, changes=x.changes, prev_class=x.prev_period.cls if x.prev_period else "",
                          group_notes=x.group.notes if x.group else 1)
                row.loc = snap.locs.get(row.id, Location())
                row.trust_name = snap.trust_names.get(row.s.trust_cik, "")
                m[row.id] = row
            self._scen[key] = m
            log.info("scenario scored rate_shift_bps=%s notes=%d took=%.1fs", bps, len(m), time.monotonic() - start)
            return m

    def scenario(self, bps: float, f: Filter) -> dict:
        snap = self.snap
        base, shifted = self.scored(0), self.scored(bps)
        selected = f.apply(list(base.values()))  # filters (incl. class) refer to the base case
        trans: dict[tuple[str, str], dict] = {}
        scen_rows, moved = [], []
        for b in selected:
            sr = shifted.get(b.id)
            if sr is None:
                continue
            scen_rows.append(sr)
            k = (b.s.cls, sr.s.cls)
            t = trans.setdefault(k, {"from": k[0], "to": k[1], "loans": 0, "whole_balance": 0.0})
            t["loans"] += 1
            t["whole_balance"] += b.s.whole_balance or 0.0
            if k[0] != k[1]:
                moved.append({**opportunity(sr), "base_class": k[0], "base_refi_gap_pct": b.s.refi_gap_pct,
                              "base_refi_gap_whole": b.s.refi_gap_whole})
        ts = sorted((t for t in trans.values() if t["from"] != t["to"]), key=lambda t: -t["loans"])
        a = snap.assumptions.with_rate_shift(bps)
        return {"rate_shift_bps": bps, "assumptions_version": a.version, "base_rate": a.base_rate,
                "base": summarize(selected, snap.data_as_of)["by_class"],
                "scenario": summarize(scen_rows, snap.data_as_of)["by_class"],
                "transitions": ts, "moved_total": len(moved), "moved": moved[:f.limit]}

    def backtest(self) -> dict:
        with self.pool.connection() as c:
            row = c.execute("""SELECT backtest_id, created_at, data_end, report, config, rates->>'version'
                               FROM scoring.backtest_runs ORDER BY backtest_id DESC LIMIT 1""").fetchone()
        if row is None:
            return {"backtest_id": None}
        out = {"backtest_id": row[0], "created_at": row[1], "report": row[3], "config": row[4], "rates_version": row[5] or ""}
        if row[2]:
            out["data_end"] = row[2].isoformat()
        return out

    # -- briefs --

    def cached_brief(self, trust: str, asset: str) -> dict | None:
        run = self.snap.run_id
        with self.pool.connection() as c:
            row = c.execute("""SELECT prompt_version, model, brief, created_at FROM api.briefs
                               WHERE trust_cik = %s AND asset_number = %s AND run_id = %s AND prompt_version = %s""",
                            (trust, asset, run, PROMPT_VERSION)).fetchone()
        if row is None:
            return None
        return {"trust_cik": trust, "asset_number": asset, "run_id": run, "prompt_version": row[0], "model": row[1],
                "brief": row[2], "created_at": row[3], "cached": True}

    def save_brief(self, b: dict, facts: dict) -> None:
        with self.pool.connection() as c:
            c.execute("""INSERT INTO api.briefs (trust_cik, asset_number, run_id, prompt_version, model, brief, facts)
                         VALUES (%s, %s, %s, %s, %s, %s, %s)
                         ON CONFLICT (trust_cik, asset_number, run_id, prompt_version)
                         DO UPDATE SET model = EXCLUDED.model, brief = EXCLUDED.brief, facts = EXCLUDED.facts, created_at = now()""",
                      (b["trust_cik"], b["asset_number"], b["run_id"], b["prompt_version"], b["model"], b["brief"],
                       json.dumps(facts, default=str)))


def _norm_occ(v: float | None) -> float | None:
    return v / 100 if v is not None and v > 1.5 else v


def _properties(c, trust: str, asset: str) -> list[dict]:
    out = []
    for r in c.execute("""
        SELECT p.property_seq, p.is_rollup, coalesce(p.name, ''), coalesce(p.city, ''), coalesce(p.state, ''),
               coalesce(p.property_type, ''), p.year_built, coalesce(p.net_rentable_sqft, p.sqft_at_securitization),
               p.units, p.valuation_at_securitization, o.occupancy, o.valuation_amount,
               coalesce(o.tenant1_name, ''), o.tenant1_lease_exp
        FROM properties p
        LEFT JOIN LATERAL (
            SELECT * FROM property_observations po
            WHERE po.trust_cik = p.trust_cik AND po.asset_number = p.asset_number AND po.property_seq = p.property_seq
            ORDER BY period_end DESC LIMIT 1) o ON true
        WHERE p.trust_cik = %s AND p.asset_number = %s
        ORDER BY p.property_seq LIMIT 60""", (trust, asset)):
        p = {"seq": r[0], "name": r[2]}
        optional = {"portfolio_totals": r[1] or None, "city": r[3], "state": r[4], "property_type": r[5], "year_built": r[6],
                    "net_rentable_sqft": r[7], "units": r[8], "occupancy": _norm_occ(r[10]),
                    "valuation_at_securitization": r[9], "most_recent_valuation": r[11], "largest_tenant": r[12],
                    "largest_tenant_lease_expires": _iso(r[13])}
        p.update({k: v for k, v in optional.items() if v not in (None, "")})  # omit empty fields
        out.append(p)
    return out


def _history(c, trust: str, asset: str) -> list[dict]:
    """The loan's monthly reports with loan-level property figures (portfolio
    totals row, else first property)."""
    out = []
    for period, bal, status, dscr, occ in c.execute("""
        SELECT lo.period_end, lo.current_balance, coalesce(lo.payment_status, ''), po.dscr, po.occupancy
        FROM loan_observations lo
        LEFT JOIN LATERAL (
            SELECT po.dscr, po.occupancy FROM property_observations po JOIN properties p USING (trust_cik, asset_number, property_seq)
            WHERE po.trust_cik = lo.trust_cik AND po.asset_number = lo.asset_number AND po.period_end = lo.period_end
            ORDER BY p.is_rollup DESC, p.property_seq LIMIT 1) po ON true
        WHERE lo.trust_cik = %s AND lo.asset_number = %s ORDER BY lo.period_end""", (trust, asset)):
        h = {"period": period.isoformat(), "balance": bal}
        if status:
            h["payment_status"] = status
        if dscr is not None:
            h["reported_dscr"] = dscr
        if (o := _norm_occ(occ)) is not None:
            h["occupancy"] = o
        out.append(h)
    return out
