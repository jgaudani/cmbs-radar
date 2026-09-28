"""api: metros, filters, summaries, map, and the brief request (against a
fake Messages API: no key, no spend)."""

import json
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer

import anthropic
import pytest

from cmbs_radar.api import geo
from cmbs_radar.api.brief import DEFAULT_MODEL, Generator, RefusedError
from cmbs_radar.api.service import BadParam, Filter, Location, Row, map_points, opportunity, summarize
from cmbs_radar.scoring import engine as e


@pytest.mark.parametrize("state,county,city,want", [
    ("NY", "New York", "New York", "nyc"), ("NY", "NEW YORK", "NEW YORK", "nyc"), ("NY", "Kings County", "Brooklyn", "nyc"),
    ("NJ", "Hudson", "Jersey City", "nyc"), ("NY", "", "Brooklyn", "nyc"), ("NY", "Albany", "Albany", ""),
    ("PA", "Montgomery", "King of Prussia", "philadelphia"), ("MD", "Montgomery", "Bethesda", "dc"),
    ("TX", "Montgomery", "Conroe", "houston"), ("FL", "Orange", "Orlando", "orlando"), ("CA", "Orange", "Irvine", "la"),
    ("", "", "", "")])
def test_metro_for(state, county, city, want):
    assert geo.metro_for(state, county, city) == want


def row(asset, cls, typ, metro, months, whole, gap, primary=True):
    refi = e.add_months(date(2026, 9, 11), months)
    s = e.Score("1", asset, cls=cls, property_type=typ, group_primary=primary, months_to_refi=months, refi_date=refi,
                whole_balance=whole, refi_gap_whole=gap, refi_gap_pct=gap / whole, flags=["split_loan"])
    return Row(s=s, loc=Location(name=f"{asset} Tower", city="New York", state="NY", metro=metro, lat=40.7, lon=-74))


def test_filter_and_sort():
    rows = [row("a", e.DISTRESSED, "OF", "nyc", 12, 900e6, 450e6), row("b", e.GAP_REFI, "OF", "nyc", 17, 100e6, 20e6),
            row("b2", e.GAP_REFI, "OF", "nyc", 17, 100e6, 20e6, primary=False),  # secondary note of a split loan
            row("c", e.CLEAN_REFI, "OF", "nyc", 6, 50e6, -10e6), row("d", e.DISTRESSED, "RT", "nyc", 12, 80e6, 40e6),
            row("e", e.GAP_REFI, "OF", "la", 12, 70e6, 10e6), row("f", e.GAP_REFI, "OF", "nyc", 30, 70e6, 10e6)]
    f = Filter.parse({"metro": "nyc", "type": "of", "max_months": "18", "class": "gap_refi,distressed"})
    assert [r.s.asset_number for r in f.apply(rows)] == ["a", "b"]  # the demo query
    f = Filter.parse({"metro": "nyc", "type": "of", "max_months": "18", "class": "gap_refi,distressed", "sort": "maturity"})
    assert f.apply(rows)[0].s.asset_number == "a"
    assert [r.s.asset_number for r in Filter.parse({"q": "c tower"}).apply(rows)] == ["c"]
    for bad in [{"max_months": "x"}, {"min_gap_pct": "big"}, {"limit": "0"}, {"limit": "99999"}, {"sort": "color"},
                {"dir": "up"}, {"refi_to": "soon"}, {"offset": "-1"}]:
        with pytest.raises(BadParam):
            Filter.parse(bad)


def test_filter_ranges_dates_ids_and_paging():
    rows = [row("a", e.DISTRESSED, "OF", "nyc", 12, 900e6, 450e6), row("b", e.GAP_REFI, "RT", "la", 3, 100e6, 20e6),
            row("c", e.CLEAN_REFI, "OF", "nyc", 20, 50e6, -10e6), row("n", e.GAP_REFI, "OF", "nyc", 5, 60e6, 6e6)]
    for r, dscr, dy in zip(rows, [1.1, 1.6, 2.0, None], [0.06, 0.09, 0.12, None]):
        r.s.dscr, r.s.debt_yield = dscr, dy
    ids = lambda q: [r.s.asset_number for r in Filter.parse(q).apply(rows)]
    assert ids({"max_dscr": "1.5"}) == ["a"]  # "n" has no DSCR: excluded once a DSCR bound is set
    assert ids({"min_dy": "0.08", "max_dy": "0.1"}) == ["b"]
    assert ids({"min_balance": "60e6", "max_gap": "30e6"}) == ["b", "n"]
    assert ids({"metro": "nyc,la", "type": "OF,RT", "min_gap_pct": "0.1"}) == ["a", "b", "n"]
    # Refi dates are 2026-09-11 + months; a YYYY-MM upper bound covers the whole month.
    assert ids({"refi_from": "2026-12", "refi_to": "2027-02"}) == ["b", "n"]
    assert ids({"refi_to": "2026-12-10"}) == []
    assert ids({"ids": "1/c,1/b,9/zz"}) == ["b", "c"]
    # Sorting: natural direction per key, dir overrides, missing values last.
    assert ids({"sort": "dscr"}) == ["a", "b", "c", "n"]
    assert ids({"sort": "dscr", "dir": "desc"}) == ["c", "b", "a", "n"]
    assert ids({"sort": "class"}) == ["a", "b", "n", "c"]
    assert ids({"sort": "maturity"}) == ["b", "n", "a", "c"]
    f = Filter.parse({"sort": "maturity", "offset": "1", "limit": "2"})
    assert [r.s.asset_number for r in f.page(f.apply(rows))] == ["n", "a"]


def test_http_csv_and_ui_routes(tmp_path):
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from cmbs_radar.api.app import _UIFiles, create_app

    rows = [row("a", e.DISTRESSED, "OF", "nyc", 12, 900e6, 450e6), row("b", e.GAP_REFI, "OF", "nyc", 3, 100e6, 20e6)]
    rows[0].loc.name = 'The "A", Tower'
    client = TestClient(create_app(SimpleNamespace(snap=SimpleNamespace(rows=rows, run_id=6)), None))
    page = client.get("/api/opportunities?sort=maturity&limit=1&offset=1").json()
    assert (page["total"], page["offset"], [o["id"] for o in page["opportunities"]]) == (2, 1, ["1/a"])
    resp = client.get("/api/opportunities.csv?class=distressed")
    assert resp.headers["content-type"].startswith("text/csv") and "run6" in resp.headers["content-disposition"]
    lines = resp.text.splitlines()
    assert lines[0].startswith("id,name,city") and len(lines) == 2
    assert lines[1].startswith('1/a,"The ""A"", Tower",New York') and lines[1].endswith(",split_loan")
    assert client.get("/api/opportunities?sort=nope").status_code == 400

    # The UI routes in the browser: page paths get index.html; files and api paths still 404.
    (tmp_path / "index.html").write_text("<div id=root></div>")
    ui = FastAPI()
    ui.mount("/", _UIFiles(directory=str(tmp_path), html=True))
    c = TestClient(ui)
    for path in ["/", "/loans", "/loans/1708131/2", "/watchlist"]:
        r = c.get(path)
        assert r.status_code == 200 and "root" in r.text and r.headers["cache-control"] == "no-cache", path
    for path in ["/assets/app.js", "/favicon.ico", "/api/nope"]:
        assert c.get(path).status_code == 404, path


def test_summarize_wall():
    rows = [row("p", e.DISTRESSED, "OF", "nyc", -20, 100e6, 50e6),  # past maturity counts in the first quarter
            row("a", e.GAP_REFI, "OF", "nyc", 5, 200e6, 20e6), row("far", e.WATCH, "OF", "nyc", 60, 1e9, 0)]
    s = summarize(rows, date(2026, 9, 11))
    assert s["loans"] == 3 and s["by_class"]["distressed"]["refi_gap_whole"] == 50e6 and s["by_class"]["gap_refi"]["team"]
    assert s["maturity_wall"][0] == {"quarter": "2026Q3", "by_class": {"distressed": 100e6}}
    assert s["maturity_wall"][2]["by_class"] == {"gap_refi": 200e6}  # Feb 2027 -> 2027Q1
    assert sum(v for q in s["maturity_wall"] for v in q["by_class"].values()) == 300e6


def test_opportunity_and_map():
    r = row("a", e.GAP_REFI, "OF", "nyc", 12, 100e6, 10e6)
    r.s.max_loan_debt_yield, r.s.max_loan_dscr = 90e6, 95e6
    o = opportunity(r)
    assert (o["binding_constraint"], o["property_type_label"], o["id"], o["notes"]) == ("debt_yield", "Office", "1/a", 1)
    pts = map_points([r, row("b", e.DISTRESSED, "OF", "nyc", 3, 300e6, 90e6)])
    assert len(pts) == 1 and pts[0]["loans"] == 2 and pts[0]["label"] == "New York" and pts[0]["by_class"]["distressed"] == 300e6


class FakeClaude(BaseHTTPRequestHandler):
    stop = "end_turn"
    last: dict = {}

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeClaude.last = {"body": body, "beta": self.headers.get("anthropic-beta", "")}
        out = json.dumps({"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5",
                          "content": [{"type": "text", "text": "**Worldwide Plaza, New York, NY**\n\n**Situation** ..."}],
                          "stop_reason": FakeClaude.stop, "usage": {"input_tokens": 10, "output_tokens": 20}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *_):
        pass


@pytest.fixture
def claude():
    srv = HTTPServer(("127.0.0.1", 0), FakeClaude)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_brief_request_is_grounded(claude):
    FakeClaude.stop = "end_turn"
    g = Generator(client=anthropic.Anthropic(base_url=claude, api_key="test", max_retries=0))
    text, model = g.write({"name": "WORLDWIDE PLAZA", "refi_gap_whole": 488.4e6})
    assert text.startswith("**Worldwide Plaza") and model == "claude-opus-5"
    body = FakeClaude.last["body"]
    assert body["model"] == DEFAULT_MODEL and body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in FakeClaude.last["beta"]
    assert "Never calculate" in json.dumps(body["system"])
    assert "WORLDWIDE PLAZA" in json.dumps(body["messages"]) and "488400000" in json.dumps(body["messages"])


def test_brief_refusal(claude):
    FakeClaude.stop = "refusal"
    g = Generator(client=anthropic.Anthropic(base_url=claude, api_key="test", max_retries=0))
    with pytest.raises(RefusedError):
        g.write({})
