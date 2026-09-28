"""EDGAR: index, headers, issuer, EX-102 extraction, client pacing."""

import threading
import time

import pytest

from cmbs_radar.ingest import edgar
from conftest import fixture


def test_parse_master_index():
    entries = edgar.parse_master_index(iter(fixture("master.idx").decode().splitlines()))
    # One row per filer: filings are listed under depositor and trust.
    assert len(entries) == 10
    e = entries[0]
    assert (e.cik, e.form_type, e.accession_no, e.date_filed.isoformat()) == ("1000009", "ABS-EE", "0001000001-26-000010", "2026-08-14")
    assert entries[9].form_type == "ABS-EE/A" and entries[9].accession_no == entries[8].accession_no


def test_header_path():
    e = edgar.IndexEntry("1005007", "x", "ABS-EE", None, "edgar/data/1005007/0001539497-26-002126.txt")
    assert e.header_path == "edgar/data/1005007/000153949726002126/0001539497-26-002126.hdr.sgml"


def test_parse_header():
    h = edgar.parse_header(fixture("cmbs_header.sgml").decode())
    assert h.period_of_report.isoformat() == "2026-07-31"
    assert (len(h.filers), h.depositor_cik, h.sponsor_cik) == (2, "1000009", "1000007")
    assert h.filers[0] == edgar.Filer("1000009", "Example Commercial Mortgage Securities Inc.")
    assert h.issuing_entity() == edgar.Filer("1000001", "EXAMPLE COMMERCIAL MORTGAGE TRUST 2017-C1")  # not the depositor
    assert h.is_cmbs() is True
    assert edgar.parse_header(fixture("auto_header.sgml").decode()).is_cmbs() is False
    assert edgar.Header(filers=[edgar.Filer("1")]).is_cmbs() is None  # missing asset class: unknown, not non-CMBS
    with pytest.raises(edgar.EdgarError):
        edgar.parse_header("<SEC-HEADER>\n</SEC-HEADER>\n")


@pytest.mark.parametrize("filers,dep,sponsor,want", [
    (["9", "1"], "9", "", "1"), (["1"], "", "", "1"), (["9", "5", "1"], "9", "5", "1"),
    (["9"], "9", "", None), (["9", "1", "2"], "9", "", None), (["9", "1"], "", "", None)])
def test_issuing_entity(filers, dep, sponsor, want):
    h = edgar.Header(filers=[edgar.Filer(c) for c in filers], depositor_cik=dep, sponsor_cik=sponsor)
    if want is None:
        with pytest.raises(edgar.NoIssuer):
            h.issuing_entity()
    else:
        assert h.issuing_entity().cik == want


def test_extract_cmbs():
    x = edgar.extract_cmbs_asset_data(iter([fixture("cmbs_submission.txt")]))
    assert x.startswith(b"<?xml") and b"<XML>" not in x and b"</TEXT>" not in x
    assert b"Warehouse B" in x and b"assetRelatedDocument" not in x


def test_extract_non_cmbs_aborts_early():
    auto = fixture("auto_submission.txt")
    pad = b"<assets><assetNumber>X</assetNumber></assets>\n" * 450000  # ~20 MB of auto loans
    big = auto.replace(b"<assets>", pad + b"<assets>", 1)
    read = 0

    def chunks():
        nonlocal read
        for i in range(0, len(big), 64 << 10):
            read += 64 << 10
            yield big[i:i + (64 << 10)]

    with pytest.raises(edgar.NotCMBS):
        edgar.extract_cmbs_asset_data(chunks())
    assert read < 1 << 20, "should abort after the root element"


def test_extract_no_ex102():
    with pytest.raises(edgar.NoEX102):
        edgar.extract_cmbs_asset_data(iter([b"<SEC-DOCUMENT>\n<DOCUMENT>\n<TYPE>ABS-EE\n<TEXT>\nx\n</TEXT>\n</DOCUMENT>\n"]))


def test_client_requires_contact_ua():
    with pytest.raises(ValueError):
        edgar.Client("my-bot", 5)
    with pytest.raises(ValueError):
        edgar.Client("a b@c.com", 11)


def test_client_retries_and_user_agent(http_server):
    hits = []

    def route(req):
        hits.append(req.headers.get("User-Agent"))
        return (429, b"", None) if len(hits) == 1 else (200, b"ok", None)

    c = edgar.Client("Test tester@example.com", 10, base_url=http_server(route), pause_base=0.001, pause_max=1)
    assert c.get("x") == b"ok"
    assert len(hits) == 2 and all("@" in h for h in hits)


def test_client_no_retry_on_404(http_server):
    hits = []
    c = edgar.Client("Test tester@example.com", 10, base_url=http_server(lambda r: (hits.append(1), (404, b"", None))[1]))
    with pytest.raises(edgar.HTTPError) as e:
        c.open("missing")
    assert e.value.status == 404 and len(hits) == 1


def test_client_shared_throttle_pause(http_server):
    """EDGAR throttles with a 503 "File Unavailable" page: retried, and every
    request waits out one shared, doubling pause."""
    hits = []

    def route(req):
        hits.append(req.path)
        if len(hits) <= 3:
            return 503, b"<html><title>SEC.gov | File Unavailable</title></html>", None
        return 200, b"ok", None

    base = 0.04
    c = edgar.Client("Test tester@example.com", 10, base_url=http_server(route), pause_base=base, pause_max=1)
    start = time.monotonic()
    c.open("a.txt").close()
    assert time.monotonic() - start >= 7 * base and len(hits) == 4  # base, 2*base, 4*base
    assert c._pause == 0  # reset after success

    c._throttled("x", 0)  # a pause blocks every request, not just the throttled one
    start = time.monotonic()
    c.open("b.txt").close()
    assert time.monotonic() - start >= base * 0.9

    hits.clear()
    c2 = edgar.Client("Test tester@example.com", 10, base_url=http_server(route), pause_base=0.001, pause_max=0.001, max_retries=0)
    with pytest.raises(edgar.EdgarError, match="File Unavailable"):
        c2.open("c.txt")


def test_fetch_retries_broken_body(http_server):
    """EDGAR sometimes resets a stream mid-body; the download is retried."""
    full = fixture("cmbs_submission.txt")
    hits = []

    def route(req):
        hits.append(1)
        if len(hits) == 1:  # promise the full length, send half, close: a broken stream
            return 200, full[: len(full) // 2], {"Content-Length": str(len(full))}
        return 200, full, None

    c = edgar.Client("Test tester@example.com", 10, base_url=http_server(route), body_retry_delay=0.001)
    e = edgar.IndexEntry("1", "x", "ABS-EE", None, "edgar/data/1/0000000001-26-000001.txt")
    x = c.fetch_cmbs_asset_data(e)
    assert b"Warehouse B" in x and len(hits) == 2
