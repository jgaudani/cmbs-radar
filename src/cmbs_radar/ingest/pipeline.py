"""Wires EDGAR discovery, EX-102 parsing and storage into an idempotent
pipeline meant to run on a schedule."""

from __future__ import annotations

import gzip
import io
import logging
import os
import queue
import re
import threading
from dataclasses import dataclass, field
from datetime import date

from . import edgar
from .cmbs import Coverage, parse_filing
from .store import HANDLED, INGESTED, NO_EX102, NON_CMBS_ISSUER, NOT_CMBS, FAILED

log = logging.getLogger("ingest")


@dataclass(frozen=True, order=True)
class Quarter:
    year: int
    q: int

    def __str__(self) -> str:
        return f"{self.year}Q{self.q}"

    def next(self) -> Quarter:
        return Quarter(self.year + 1, 1) if self.q == 4 else Quarter(self.year, self.q + 1)


def parse_quarter(s: str) -> Quarter:
    """"2026Q3", case-insensitive. EX-102 data starts 2016Q4."""
    m = re.fullmatch(r"(\d{4})Q([1-4])", s.strip().upper())
    if not m or (int(m.group(1)), int(m.group(2))) < (2016, 4):
        raise ValueError(f"quarter {s!r}: want e.g. 2026Q3 (EX-102 data starts 2016Q4)")
    return Quarter(int(m.group(1)), int(m.group(2)))


def current_quarter(d: date) -> Quarter:
    return Quarter(d.year, (d.month - 1) // 3 + 1)


def quarter_range(a: Quarter, b: Quarter) -> list[Quarter]:
    if b < a:
        raise ValueError(f"range {a}..{b} is backwards")
    out, q = [a], a
    while q != b:
        q = q.next()
        out.append(q)
    return out


@dataclass
class Config:
    quarters: list[Quarter]
    workers: int = 4
    name_filter: re.Pattern | None = None  # optional pre-filter on filer names
    limit: int = 0  # stop after ~N CMBS filings ingested; in-flight ones finish, so it can overshoot by workers
    raw_dir: str = ""  # optional archive of raw EX-102 XML (gzipped)
    progress_every: float = 30.0


@dataclass
class Stats:
    discovered: int = 0
    skipped: int = 0
    ingested: int = 0
    not_cmbs: int = 0
    no_ex102: int = 0
    failed: int = 0
    loans: int = 0
    _mu: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, name: str, n: int = 1) -> None:
        with self._mu:
            setattr(self, name, getattr(self, name) + n)

    def __str__(self) -> str:
        return (f"discovered={self.discovered} skipped={self.skipped} ingested={self.ingested} not_cmbs={self.not_cmbs} "
                f"no_ex102={self.no_ex102} failed={self.failed} loans={self.loans}")


def group_by_accession(entries: list[edgar.IndexEntry]) -> list[list[edgar.IndexEntry]]:
    """An ABS-EE appears once per filer (depositor and trust) in master.idx."""
    by: dict[str, list[edgar.IndexEntry]] = {}
    for e in entries:
        by.setdefault(e.accession_no, []).append(e)
    return list(by.values())


class Pipeline:
    def __init__(self, src, sink, cfg: Config, cov: Coverage | None = None):
        self.src, self.sink, self.cfg, self.cov = src, sink, cfg, cov
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> Stats:
        """Per-filing failures are recorded and counted, not fatal; the next
        run retries them. Only discovery errors abort the run."""
        stats = Stats()
        jobs: queue.Queue = queue.Queue()
        # Dispatch takes a free worker before deciding whether the next filing
        # needs work, so the skip check sees every filing handled so far (a
        # depositor classified non-CMBS a moment ago skips its next trust).
        self._free = threading.Semaphore(max(self.cfg.workers, 1))
        workers = [threading.Thread(target=self._worker, args=(jobs, stats), daemon=True) for _ in range(max(self.cfg.workers, 1))]
        for w in workers:
            w.start()
        # Most filings are non-CMBS and logged at debug only; report progress.
        done = threading.Event()

        def progress() -> None:
            while not done.wait(self.cfg.progress_every):
                log.info("progress %s", stats)
        threading.Thread(target=progress, daemon=True).start()
        try:
            self._dispatch(jobs, stats)
        finally:
            for _ in workers:
                jobs.put(None)
            for w in workers:
                w.join()
            done.set()
        return stats

    def _worker(self, jobs: queue.Queue, stats: Stats) -> None:
        while (e := jobs.get()) is not None:
            try:
                if not self._stop.is_set():
                    self._process(e, stats)
            finally:
                self._free.release()

    def _dispatch(self, jobs: queue.Queue, stats: Stats) -> None:
        for q in self.cfg.quarters:
            filings = group_by_accession(self.src.quarter_index(q.year, q.q))
            log.info("quarter index quarter=%s abs_ee_filings=%d", q, len(filings))
            for rows in filings:
                if self._stop.is_set():
                    return
                # Match any filer, so a filter written for trust names still
                # finds filings whose first index row is the depositor.
                if self.cfg.name_filter and not any(self.cfg.name_filter.search(r.company_name) for r in rows):
                    continue
                e = rows[0]
                stats.add("discovered")
                self._free.acquire()
                skip = self.sink.should_skip(e.accession_no, [r.cik for r in rows])
                if skip == NON_CMBS_ISSUER:
                    # Record it, so the filings table is complete and a filing
                    # that failed before its issuer was known isn't left "failed".
                    rec = edgar.IndexEntry("", e.company_name, e.form_type, e.date_filed, e.filename)
                    self._record(rec, None, NOT_CMBS)
                if skip:
                    stats.add("skipped")
                    self._free.release()
                    continue
                # Limit counts CMBS filings ingested, not filings dispatched.
                if self.cfg.limit and stats.ingested >= self.cfg.limit:
                    log.info("limit reached limit=%d", self.cfg.limit)
                    self._free.release()
                    return
                jobs.put(e)

    def _process(self, e: edgar.IndexEntry, stats: Stats) -> None:
        acc = e.accession_no
        try:
            hdr = self.src.fetch_header(e)
        except Exception as err:
            return self._fail(e, None, stats, f"header: {err}")
        period = hdr.period_of_report
        e.depositor_cik = hdr.depositor_cik
        # Key everything by the issuing trust, never the depositor.
        issuer_err = None
        try:
            iss = hdr.issuing_entity()
            e.cik, e.company_name = iss.cik, iss.name
        except edgar.NoIssuer as err:
            issuer_err = err

        def not_cmbs(reason: str) -> None:
            stats.add("not_cmbs")
            if issuer_err:
                e.cik = ""  # unknown trust: not under an index CIK that may be a CMBS depositor
            self._record(e, period, NOT_CMBS)
            log.debug("not CMBS accession=%s by=%s", acc, reason)

        if hdr.is_cmbs() is False:
            return not_cmbs("asset class " + hdr.asset_class)
        if issuer_err:
            return self._fail(e, period, stats, str(issuer_err))
        try:
            xml = self.src.fetch_cmbs_asset_data(e)
        except edgar.NotCMBS:
            return not_cmbs("EX-102 namespace")
        except edgar.NoEX102:
            stats.add("no_ex102")
            return self._record(e, period, NO_EX102)
        except Exception as err:
            return self._fail(e, period, stats, f"fetch: {err}")
        if self.cfg.raw_dir:
            try:
                d = os.path.join(self.cfg.raw_dir, e.cik)
                os.makedirs(d, exist_ok=True)
                with gzip.open(os.path.join(d, acc + ".xml.gz"), "wb") as f:
                    f.write(xml)
            except OSError as err:
                log.warning("raw archive write failed accession=%s err=%s", acc, err)  # non-fatal
        try:
            loans, orphans = parse_filing(io.BytesIO(xml), self.cov)
        except Exception as err:
            return self._fail(e, period, stats, f"parse: {err}")
        if orphans:
            log.warning("portfolio member blocks without a parent loan, stored as loans accession=%s assets=%s", acc, orphans)
        try:
            self.sink.save_filing(e, period, loans)
        except Exception as err:
            return self._fail(e, period, stats, f"save: {err}")
        stats.add("ingested")
        stats.add("loans", len(loans))
        log.info("ingested accession=%s trust_cik=%s trust=%r loans=%d bytes=%d", acc, e.cik, e.company_name, len(loans), len(xml))

    def _fail(self, e: edgar.IndexEntry, period: date | None, stats: Stats, msg: str) -> None:
        if self._stop.is_set():
            return  # shutting down; don't mark filings failed
        stats.add("failed")
        log.error("filing failed accession=%s err=%s", e.accession_no, msg)
        self._record(e, period, FAILED, msg)

    def _record(self, e: edgar.IndexEntry, period: date | None, status: str, msg: str = "") -> None:
        try:
            self.sink.record_filing(e, period, status, msg)
        except Exception as err:
            log.error("recording filing status accession=%s status=%s err=%s", e.accession_no, status, err)
