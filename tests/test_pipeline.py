"""Pipeline against a fake EDGAR serving the fixtures. CMBS filings are
indexed under depositor 1000009 and trust 1000001, auto filings under
depositor 1000008 and trusts 1000002 and 1000003. Nothing is served for
trust 1000003: it must be skipped via its depositor."""

import re
import threading

import pytest

from cmbs_radar.ingest import edgar
from cmbs_radar.ingest.pipeline import Config, Pipeline, Quarter, parse_quarter, quarter_range
from cmbs_radar.ingest.store import FAILED, NOT_CMBS, MemSink
from conftest import fixture


@pytest.fixture
def fake_edgar(http_server):
    idx = fixture("master.idx")
    cmbs_hdr, cmbs_sub = fixture("cmbs_header.sgml"), fixture("cmbs_submission.txt")
    auto_hdr, auto_sub = fixture("auto_header.sgml"), fixture("auto_submission.txt")
    hits = {"headers": 0, "submissions": 0, "paths": []}
    mu = threading.Lock()

    def route(req):
        p = req.path.lstrip("/")
        with mu:
            hits["paths"].append(p)
        is_hdr = p.endswith(".hdr.sgml")
        cmbs = p.startswith(("edgar/data/1000001/", "edgar/data/1000009/"))
        auto = p.startswith(("edgar/data/1000002/", "edgar/data/1000008/"))
        if p == "edgar/full-index/2026/QTR3/master.idx":
            return 200, idx, None
        if is_hdr and (cmbs or auto):
            with mu:
                hits["headers"] += 1
            return 200, cmbs_hdr if cmbs else auto_hdr, None
        if cmbs or auto:
            with mu:
                hits["submissions"] += 1
            return 200, cmbs_sub if cmbs else auto_sub, None
        return 404, b"", None

    base = http_server(route)
    return edgar.Client("Test tester@example.com", 10, base_url=base), hits


def run(client, sink, **cfg):
    return Pipeline(client, sink, Config([Quarter(2026, 3)], progress_every=60, **cfg)).run()


def test_dry_run_is_idempotent(fake_edgar, tmp_path):
    client, hits = fake_edgar
    sink = MemSink()
    stats = run(client, sink, workers=2, raw_dir=str(tmp_path))
    # Each CMBS filing is indexed twice (depositor, trust): fetched once, stored under the trust.
    assert (stats.discovered, stats.ingested, stats.loans, stats.failed) == (5, 2, 4, 0)
    assert set(sink.trusts.values()) == {"1000001"}
    assert hits["submissions"] == 2  # auto filings classified from the header alone
    assert stats.not_cmbs + stats.skipped == 3
    assert (tmp_path / "1000001" / "0001000001-26-000010.xml.gz").exists()

    before = hits["headers"] + hits["submissions"]
    stats = run(client, sink, workers=2)
    assert hits["headers"] + hits["submissions"] == before and stats.skipped == 5


def test_limit_counts_only_cmbs(fake_edgar):
    client, _ = fake_edgar
    assert run(client, MemSink(), workers=1, limit=1).ingested == 1


def test_name_filter_matches_any_filer(fake_edgar):
    client, hits = fake_edgar
    stats = run(client, MemSink(), workers=1, name_filter=re.compile("MORTGAGE TRUST"))  # first index row is the depositor
    assert (stats.discovered, stats.ingested, hits["submissions"]) == (2, 2, 2)


def test_skips_known_non_cmbs_depositor(fake_edgar):
    client, hits = fake_edgar
    stats = run(client, MemSink(), workers=1, name_filter=re.compile("AUTO"))
    assert not any("0001000003-26-000030" in p for p in hits["paths"])  # new trust, known depositor: no request
    # One header request classifies the depositor; its other two filings are
    # skipped (by trust, and by depositor for the new trust).
    assert (stats.not_cmbs, stats.skipped, stats.failed, hits["headers"], hits["submissions"]) == (1, 2, 0, 1, 0)


def test_skipped_non_cmbs_filing_is_recorded(fake_edgar):
    """A filing that failed before its depositor was known to be non-CMBS is
    recorded as non-CMBS, not left "failed"."""
    client, _ = fake_edgar
    sink = MemSink()
    sink.statuses["0001000003-26-000030"] = FAILED
    run(client, sink, workers=1, name_filter=re.compile("AUTO"))
    assert sink.statuses["0001000003-26-000030"] == NOT_CMBS


def test_quarters():
    a, b = parse_quarter("2025q4"), parse_quarter("2026Q2")
    assert quarter_range(a, b) == [Quarter(2025, 4), Quarter(2026, 1), Quarter(2026, 2)]
    for bad in ("2015Q1", "2016Q3", "2026Q5", "x"):
        with pytest.raises(ValueError):
            parse_quarter(bad)
    assert parse_quarter("2016Q4") == Quarter(2016, 4)  # first EX-102 quarter
    with pytest.raises(ValueError):
        quarter_range(b, a)
