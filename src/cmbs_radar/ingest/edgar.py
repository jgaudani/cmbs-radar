"""SEC EDGAR: quarterly filing indexes, filing headers and full submissions.

Enforces the SEC fair-access policy (declared User-Agent, <=10 requests per
second) on every request, including retries. When EDGAR throttles (403, 429,
or a 503 "File Unavailable" page, which looks permanent but isn't) every
thread pauses together: requests sent during a block only extend it.
"""

from __future__ import annotations

import logging
import posixpath
import random
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Iterator

import httpx
from lxml import etree

log = logging.getLogger("edgar")

DEFAULT_BASE_URL = "https://www.sec.gov/Archives/"
MAX_ASSET_DATA_BYTES = 256 << 20  # CMBS EX-102s are small; anything this big is not what we want


class EdgarError(Exception):
    pass


class HTTPError(EdgarError):
    def __init__(self, url: str, status: int, unavailable: bool = False):
        self.url, self.status, self.unavailable = url, status, unavailable
        extra = ' (SEC "File Unavailable", i.e. throttled)' if unavailable else ""
        super().__init__(f"GET {url}: HTTP {status}{extra}")


class NotCMBS(EdgarError):
    """The EX-102 belongs to another asset class (auto, RMBS...)."""


class NoEX102(EdgarError):
    """The submission has no EX-102 asset data exhibit."""


class TooLarge(EdgarError):
    pass


class NoIssuer(EdgarError):
    """The header doesn't identify the issuing entity."""


# ---- index --------------------------------------------------------------------


@dataclass(slots=True)
class IndexEntry:
    """One row of an EDGAR master.idx file."""

    cik: str
    company_name: str
    form_type: str
    date_filed: date
    filename: str  # e.g. edgar/data/1234567/0001234567-26-000123.txt
    depositor_cik: str = ""  # not in master.idx; filled from the header before storing

    @property
    def accession_no(self) -> str:
        return posixpath.basename(self.filename).removesuffix(".txt")

    @property
    def header_path(self) -> str:
        """e.g. edgar/data/1005007/000153949726002126/0001539497-26-002126.hdr.sgml"""
        acc = self.accession_no
        return posixpath.join(posixpath.dirname(self.filename), acc.replace("-", ""), acc + ".hdr.sgml")


def is_abs_ee(form_type: str) -> bool:
    return form_type in ("ABS-EE", "ABS-EE/A")


def parse_master_index(lines: Iterator[str], keep=is_abs_ee) -> list[IndexEntry]:
    """The pipe-delimited master.idx: free-text header, a dashed line, then
    CIK|Company Name|Form Type|Date Filed|Filename."""
    out: list[IndexEntry] = []
    in_body = False
    for line in lines:
        line = line.rstrip("\r\n")
        if not in_body:
            in_body = line.startswith("-----")
            continue
        parts = line.split("|")
        if len(parts) != 5 or not keep(parts[2].strip()):
            continue
        try:
            filed = datetime.strptime(parts[3].strip(), "%Y-%m-%d").date()
        except ValueError as e:
            raise EdgarError(f"master.idx: bad date in {line!r}") from e
        out.append(IndexEntry(parts[0].strip(), parts[1].strip(), parts[2].strip(), filed, parts[4].strip()))
    return out


# ---- header -------------------------------------------------------------------


@dataclass(slots=True)
class Filer:
    cik: str  # no leading zeros, matching master.idx
    name: str = ""


@dataclass(slots=True)
class Header:
    """A filing's SGML header from its ~2 KB .hdr.sgml file: classifies the
    filing without downloading the full submission (hundreds of MB for auto
    loans). An ABS-EE usually has two filers, the depositor and the issuing
    trust; only the trust identifies the loans (a depositor files for dozens
    of trusts, all numbering loans 1..N)."""

    period_of_report: date | None = None
    asset_class: str = ""  # e.g. "Commercial mortgages"; empty on some older filings
    filers: list[Filer] = field(default_factory=list)
    depositor_cik: str = ""
    sponsor_cik: str = ""

    def issuing_entity(self) -> Filer:
        """The filer that is neither the depositor nor the sponsor. A single
        filer with no depositor tag is the trust filing alone."""
        candidates = [f for f in self.filers if f.cik not in (self.depositor_cik, self.sponsor_cik)]
        if len(candidates) == 1:
            return candidates[0]
        raise NoIssuer(f"cannot identify issuing entity in filing header: filers {self.filers}, depositor {self.depositor_cik!r}")

    def is_cmbs(self) -> bool | None:
        """Whether the asset class is commercial mortgages; None when unknown."""
        if not self.asset_class:
            return None
        return "commercial mortgage" in self.asset_class.lower()


def _norm_cik(s: str) -> str:
    return s.strip().lstrip("0") or "0"


def parse_header(text: str) -> Header:
    """The tagged .hdr.sgml format: one <TAG>value per line, FILER blocks."""
    h = Header()
    in_filer = in_company = False
    for line in text.splitlines():
        tag, _, val = line.strip().partition(">")
        val = val.strip()
        if tag == "<PERIOD":
            try:
                h.period_of_report = datetime.strptime(val, "%Y%m%d").date()
            except ValueError:
                pass
        elif tag == "<ABS-ASSET-CLASS":
            h.asset_class = val
        elif tag == "<DEPOSITOR-CIK":
            h.depositor_cik = _norm_cik(val)
        elif tag == "<SPONSOR-CIK":
            h.sponsor_cik = _norm_cik(val)
        elif tag == "<FILER":
            h.filers.append(Filer(""))
            in_filer = True
        elif tag == "</FILER":
            in_filer = False
        elif tag == "<COMPANY-DATA":
            in_company = in_filer
        elif tag == "</COMPANY-DATA":
            in_company = False
        elif tag == "<CONFORMED-NAME" and in_company:
            h.filers[-1].name = val
        elif tag == "<CIK" and in_company:
            h.filers[-1].cik = _norm_cik(val)
    if not h.filers:
        raise EdgarError("filing header has no FILER")
    return h


# ---- client -------------------------------------------------------------------


class Client:
    """Thread-safe: all threads share one rate limiter and one throttling
    pause (10s doubling to 10 min, SEC documents a 10-minute block; reset
    on success)."""

    def __init__(self, user_agent: str, requests_per_second: int, base_url: str = DEFAULT_BASE_URL, max_retries: int = 8,
                 pause_base: float = 10.0, pause_max: float = 600.0, body_retry_delay: float = 5.0):
        if "@" not in user_agent:
            raise ValueError('SEC fair-access policy requires a User-Agent with contact info, e.g. "Jay Doe jay@example.com"')
        if not 1 <= requests_per_second <= 10:
            raise ValueError(f"requests_per_second must be 1..10 (SEC limit is 10), got {requests_per_second}")
        self.base_url = base_url if base_url.endswith("/") else base_url + "/"
        self.max_retries = max_retries
        self.pause_base, self.pause_max, self.body_retry_delay = pause_base, pause_max, body_retry_delay
        # Large EX-102 files can take a while; the timeout covers the body read.
        self.http = httpx.Client(headers={"User-Agent": user_agent}, timeout=httpx.Timeout(600.0, connect=30.0),
                                 follow_redirects=True)
        self._interval = 1.0 / requests_per_second
        self._lock = threading.Lock()
        self._next_slot = 0.0
        self._paused_until = 0.0
        self._pause = 0.0

    # -- pacing --

    def _wait(self) -> None:
        """Wait out the shared throttling pause, then take a rate-limiter slot."""
        while True:
            with self._lock:  # reserve under the lock, sleep outside it
                now = time.monotonic()
                paused = now < self._paused_until
                if paused:
                    delay = self._paused_until - now
                else:
                    slot = max(self._next_slot, now)
                    self._next_slot = slot + self._interval
                    delay = slot - now
            if delay > 0:
                time.sleep(delay)
            if not paused:
                return

    def _throttled(self, url: str, retry_after: float) -> None:
        with self._lock:
            now = time.monotonic()
            if now < self._paused_until:
                return  # sent before the current pause began
            self._pause = self.pause_base if self._pause == 0 else min(2 * self._pause, self.pause_max)
            d = max(self._pause, retry_after)
            self._paused_until = now + d
        log.warning("EDGAR is throttling; pausing all requests for=%.0fs url=%s", d, url)

    def _succeeded(self) -> None:
        with self._lock:
            self._pause = 0.0

    # -- requests --

    def open(self, rel_path: str) -> httpx.Response:
        """GET a path under the archive root as an open streaming response
        (caller closes it). Throttling pauses every thread; network errors
        and other 5xx back off per request."""
        url = self.base_url + rel_path.lstrip("/")
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            if attempt > 0 and not (isinstance(last, HTTPError) and last.status in (403, 429, 503)):
                backoff = float(1 << (attempt - 1))
                time.sleep(backoff + random.uniform(0, backoff / 2))
            self._wait()
            try:
                resp = self.http.send(self.http.build_request("GET", url), stream=True)
            except httpx.HTTPError as e:
                last = e
                continue
            code = resp.status_code
            if code == 200:
                self._succeeded()
                return resp
            if code in (403, 429, 503):
                body = resp.read()[: 32 << 10] if code == 503 else b""
                resp.close()
                last = HTTPError(url, code, unavailable=b"File Unavailable" in body)
                self._throttled(url, _retry_after(resp.headers.get("Retry-After")))
            elif code >= 500:
                resp.close()
                last = HTTPError(url, code)
            else:
                resp.close()
                raise HTTPError(url, code)
        raise EdgarError(f"giving up after {self.max_retries + 1} attempts: {last}")

    def get(self, rel_path: str) -> bytes:
        """GET a small file whole."""
        resp = self.open(rel_path)
        try:
            return resp.read()
        finally:
            resp.close()

    def quarter_index(self, year: int, quarter: int) -> list[IndexEntry]:
        """ABS-EE / ABS-EE/A filings in one quarter. The current quarter's
        index is rebuilt nightly, so a daily run picks up new filings."""
        text = self.get(f"edgar/full-index/{year}/QTR{quarter}/master.idx").decode("latin-1")
        return parse_master_index(iter(text.splitlines()))

    def fetch_header(self, e: IndexEntry) -> Header:
        return parse_header(self.get(e.header_path).decode("latin-1"))

    def fetch_cmbs_asset_data(self, e: IndexEntry) -> bytes:
        """The full submission's EX-102, only if it is a CMBS file. Other asset
        classes raise NotCMBS after the root element, so large files are never
        fully downloaded. A body that breaks mid-download is retried."""
        body_retries = 2
        for attempt in range(body_retries + 1):
            resp = self.open(e.filename)
            try:
                return extract_cmbs_asset_data(resp.iter_bytes())
            except (NotCMBS, NoEX102, TooLarge):
                raise
            except (httpx.HTTPError, EdgarError) as err:
                if attempt == body_retries:
                    raise EdgarError(f"reading submission: {err}") from err
            finally:
                resp.close()
            time.sleep((attempt + 1) * self.body_retry_delay)
        raise AssertionError("unreachable")


def _retry_after(v: str | None) -> float:
    if not v:
        return 0.0
    try:
        return float(int(v.strip()))
    except ValueError:
        return 0.0


# ---- submission ---------------------------------------------------------------


def is_cmbs_namespace(ns: str) -> bool:
    """http://www.sec.gov/edgar/document/absee/cmbs/assetdata"""
    return "/absee/cmbs/" in ns.lower()


def _lines(chunks: Iterator[bytes]) -> Iterator[bytes]:
    buf = b""
    for c in chunks:
        buf += c
        *lines, buf = buf.split(b"\n")
        for ln in lines:
            yield ln + b"\n"
    if buf:
        yield buf


def extract_cmbs_asset_data(chunks: Iterator[bytes]) -> bytes:
    """Scan an EDGAR SGML full submission for its EX-102 <TEXT> body, dropping
    the <XML>/</XML> wrapper lines. Rejects non-CMBS as soon as the root
    element's namespace is known."""
    lines = _lines(chunks)
    in_doc, doc_type = False, ""
    for raw in lines:
        t = raw.strip()
        if t == b"<DOCUMENT>":
            in_doc, doc_type = True, ""
        elif t == b"</DOCUMENT>":
            in_doc = False
        elif in_doc and t.startswith(b"<TYPE>"):
            doc_type = t[len(b"<TYPE>"):].strip().decode("latin-1")
        elif in_doc and t == b"<TEXT>" and doc_type == "EX-102":
            return _read_cmbs_document(lines)
    raise NoEX102("no EX-102 document in submission")


def _read_cmbs_document(lines: Iterator[bytes]) -> bytes:
    parser = etree.XMLPullParser(events=("start",))
    out: list[bytes] = []
    size, checked = 0, False
    for raw in lines:
        t = raw.strip()
        if t == b"</TEXT>":
            break
        if t in (b"<XML>", b"</XML>"):
            continue
        out.append(raw)
        size += len(raw)
        if size > MAX_ASSET_DATA_BYTES:
            raise TooLarge("EX-102 exceeds size limit")
        if not checked:
            try:
                parser.feed(raw)
                for _, el in parser.read_events():
                    ns = etree.QName(el).namespace or ""
                    if not is_cmbs_namespace(ns):
                        raise NotCMBS(f"EX-102 is not a CMBS asset data file (root <{etree.QName(el).localname}> xmlns={ns!r})")
                    checked = True
                    break
            except etree.XMLSyntaxError as e:
                raise EdgarError(f"reading EX-102 root element: {e}") from e
    if not checked:
        raise EdgarError("reading EX-102 root element: no root element")
    return b"".join(out)
