"""Postgres integration (TEST_DATABASE_URL, its own database: these tests
drop tables)."""

import threading
from datetime import date

import psycopg
import pytest

from cmbs_radar.ingest.cmbs import LOAN_OBS, LOAN_STATIC, PROP_OBS, PROP_STATIC, Loan, Property
from cmbs_radar.ingest.edgar import IndexEntry
from cmbs_radar.ingest.store import FAILED, HANDLED, NON_CMBS_ISSUER, NOT_CMBS, SCHEMA_VERSION, Store


@pytest.fixture
def store(test_dsn):
    with psycopg.connect(test_dsn, autocommit=True) as c:
        c.execute("DROP TABLE IF EXISTS property_observations, properties, loan_observations, loans, filings, schema_meta CASCADE")
    s = Store(test_dsn)
    s.migrate()
    s.migrate()  # idempotent
    yield s
    s.close()


def entry(acc, filed, cik="1000001", name="EXAMPLE CMT 2017-C1", dep=""):
    return IndexEntry(cik, name, "ABS-EE", date.fromisoformat(filed), f"edgar/data/{cik}/{acc}.txt", depositor_cik=dep)


def loan(balance, maturity, asset="1"):
    l = Loan(asset_number=asset, period_end=date(2026, 7, 31),
             static={c: None for c, _, _ in LOAN_STATIC} | {"originator": "Example Bank", "maturity_date": date.fromisoformat(maturity),
                                                             "ard_date": date(2026, 12, 1)},
             obs={c: None for c, _, _ in LOAN_OBS} | {"current_balance": balance, "maturity_date": date.fromisoformat(maturity)})
    p = Property(seq=1, source_asset=asset, static={c: None for c, _, _ in PROP_STATIC} | {"name": "One Example Plaza", "state": "NY"},
                 obs={c: None for c, _, _ in PROP_OBS} | {"dscr": 1.3, "debt_service": 3e6, "tenant1_name": "Example Law LLP",
                                                          "tenant1_lease_exp": date(2027, 3, 31), "tenant2_name": "Example Capital LP"})
    l.properties.append(p)
    return l


def one(s, q, *a):
    return s.conn.execute(q, a).fetchone()


def test_amendments_and_backfill(store):
    store.save_filing(entry("acc-1", "2026-08-14"), date(2026, 7, 31), [loan(75e6, "2027-01-06")])
    store.save_filing(entry("acc-2", "2026-08-20"), date(2026, 7, 31), [loan(74e6, "2028-01-06")])  # amendment wins
    store.save_filing(entry("acc-1", "2026-08-14"), date(2026, 7, 31), [loan(75e6, "2027-01-06")])  # stale re-delivery must not
    assert one(store, "SELECT current_balance, accession_no FROM loan_observations") == (74e6, "acc-2")
    assert one(store, "SELECT maturity_date::text, last_seen_accession, first_seen_accession, ard_date::text FROM loans") == \
        ("2028-01-06", "acc-2", "acc-1", "2026-12-01")
    assert one(store, """SELECT count(*) FROM property_observations WHERE dscr = 1.3 AND debt_service = 3000000
                         AND tenant1_name = 'Example Law LLP' AND tenant1_lease_exp = '2027-03-31'
                         AND tenant2_name = 'Example Capital LP' AND tenant3_name IS NULL""")[0] == 1

    assert store.should_skip("acc-2", ["1000001"]) == HANDLED
    store.record_filing(entry("acc-9", "2026-08-01"), None, FAILED, "boom")
    assert store.should_skip("acc-9", ["1000001"]) is None  # failed filings retry
    store.record_filing(entry("auto-1", "2026-08-15", cik="2000002", name="AUTO TRUST", dep="2000009"), None, NOT_CMBS)
    assert store.should_skip("auto-2", ["2000009", "2000002"]) == NON_CMBS_ISSUER
    assert store.should_skip("auto-3-new-trust", ["2000009", "2000003"]) == NON_CMBS_ISSUER  # via the depositor
    assert store.should_skip("cmbs-never-seen", ["1000009", "1000001"]) is None


def test_save_filing_is_atomic(store):
    bad = Loan(asset_number="2", static={c: None for c, _, _ in LOAN_STATIC}, obs={c: None for c, _, _ in LOAN_OBS})
    with pytest.raises(ValueError):
        store.save_filing(entry("acc-3", "2026-08-14"), None, [loan(1, "2027-01-01"), bad])
    assert one(store, "SELECT count(*) FROM loans")[0] == 0


def test_migrate_rebuilds_old_schema(store):
    store.save_filing(entry("acc-1", "2026-08-14"), date(2026, 7, 31), [loan(1, "2027-01-01")])
    store.conn.execute("UPDATE schema_meta SET version = 1")
    store.migrate()
    assert one(store, "SELECT count(*) FROM filings")[0] == 0
    assert one(store, "SELECT version FROM schema_meta")[0] == SCHEMA_VERSION


def test_concurrent_saves_of_one_trust(store):
    """Seen in the 2025Q4-2026Q3 backfill: two monthly filings of one trust
    saved concurrently deadlocked. Loans in opposite order must not fail."""
    assets = [str(i) for i in range(1, 41)]
    for rnd in range(5):
        errs = []

        def save(i, order):
            try:
                pe = date(2026, rnd * 2 + i + 1, 28)
                store.save_filing(entry(f"acc-{rnd}-{i}", pe.isoformat()), pe, [loan(1e6, "2027-01-01", a) for a in order])
            except Exception as e:
                errs.append(e)

        ts = [threading.Thread(target=save, args=(i, o)) for i, o in enumerate([assets, assets[::-1]])]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert not errs, errs


def test_portfolio_columns(store):
    l = loan(150e6, "2027-06-01")
    l.obs |= {"liquidation_code": "2", "liquidation_date": date(2026, 7, 11), "post_mod_rate": 0.0525}
    l.properties = [
        Property(0, "1", True, {c: None for c, _, _ in PROP_STATIC} | {"name": "Storage Portfolio"},
                 {c: None for c, _, _ in PROP_OBS} | {"noi": 13.99e6, "valuation_amount": 180e6}),
        Property(1, "1.01", False, {c: None for c, _, _ in PROP_STATIC} | {"name": "Storage A", "state": "NV"}, {c: None for c, _, _ in PROP_OBS}),
        Property(2, "1.02", False, {c: None for c, _, _ in PROP_STATIC} | {"name": "Storage B", "state": "AZ"}, {c: None for c, _, _ in PROP_OBS}),
    ]
    store.save_filing(entry("acc-1", "2026-08-14"), date(2026, 7, 31), [l])
    assert one(store, """SELECT count(*) FILTER (WHERE NOT is_rollup AND state IS NOT NULL),
                                count(*) FILTER (WHERE is_rollup AND property_seq = 0 AND source_asset_number = '1') FROM properties""") == (2, 1)
    assert one(store, "SELECT valuation_amount FROM property_observations WHERE property_seq = 0")[0] == 180e6
    assert one(store, "SELECT liquidation_code FROM loan_observations")[0] == "2"
