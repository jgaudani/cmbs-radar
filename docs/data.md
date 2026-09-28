# Data: EDGAR, EX-102 and ingest

## Source
Form ABS-EE, exhibit EX-102 (Regulation AB II, Schedule AL Item 2), from
Nov 2016. One filing per trust per month: loans (`<assets>`) with nested
collateral (`<property>`). Only SEC-registered CMBS file it.

## Ingest design (keep these)
- **SEC fair access**: User-Agent with a contact email; <= 10 req/s (default
  3), shared across workers and retries.
- **Throttling**: EDGAR throttles with 403, 429, or a 503 "File Unavailable"
  page that looks permanent but isn't (the same files load minutes later).
  The client pauses every worker together (10s doubling to 10 min, reset on
  success); requests sent while blocked only extend the block. We were
  throttled at 5 req/s, hence the default of 3.
- **Header first**: each filing's ~2 KB `.hdr.sgml` gives the asset class,
  depositor and issuing trust. Non-CMBS filings stop there; their full
  submissions (hundreds of MB for auto loans) are never downloaded. The
  EX-102 root namespace (`/absee/cmbs/`) is the backstop.
- **Skip by trust or depositor**: auto issuers create a new trust per deal
  but reuse the depositor (a depositor's shelf covers one asset class), so
  one classified filing skips the rest. Skipped filings are recorded
  `skipped_not_cmbs` so a filing that failed before that was known doesn't
  stay `failed`.
- **Trust identity**: `trust_cik` is the issuing trust from the header, never
  the depositor co-filer (a depositor files for dozens of trusts that all
  number loans 1..N). master.idx lists a filing under each filer, so
  accessions are deduped; the name filter matches any filer. An
  unidentifiable issuer fails the filing rather than guessing.
- **Idempotent**: the filings table tracks status; failed filings retry.
- **One transaction per filing**; loans written in asset-number order and
  deadlocks retried (two monthly filings of one trust saved concurrently
  deadlocked in the first backfill).
- **Newest filing wins**: observation upserts only overwrite from filings at
  least as new, so ABS-EE/A amendments supersede originals and backfills
  never clobber newer data. Static tables COALESCE so omitted fields keep
  prior values.
- **Static facts vs monthly observations** are separate tables; maturity is
  tracked per observation because modifications move it.
- **Adding a field**: one line in the mapping in `ingest/cmbs.py`
  (`LOAN_STATIC`, `LOAN_OBS`, `PROP_STATIC`, `PROP_OBS`) and a column in
  `ingest/schema.sql`. Bump `SCHEMA_VERSION` for incompatible changes: the
  old schema is dropped and rebuilt (data is re-derivable from `data/raw`).
- **Raw archive**: `--raw-dir` keeps each EX-102 gzipped so the parser can
  evolve and re-run without re-downloading. `scripts/check_parser.py`
  re-parses archived files and compares with stored rows.

## EX-102 quirks (match exactly; each has a test)
- `DefeasedStatusCode`: capital D, property level.
- `mostRecentDebtServiceCoverageNetCashFlowpercentage`: lowercase p.
- `netCashFlowFlowSecuritizationAmount`: doubled "Flow".
- `mostRecentFinancialsStartDate` / `EndDate` (not `...EndPeriodDate`).
- `mostRecentValuationAmount` exists (property level, ~33%, after appraisals).
- `mostRecentSpecialServicerTransferDate` is only reported for transferred loans.
- **Portfolio loans**: some filers report each property of a portfolio loan
  as its own `<assets>` block numbered after the parent (`1.01`, `3-001`)
  with only identity fields, and a rollup `<property>` (totals, no
  location) on the parent. These are folded into the parent in any order:
  rollup = `property_seq` 0 / `is_rollup`, members = their suffix.
- **Companion notes**: a trust can hold one loan as notes `1`, `1A`, `1B`
  with financials on one note (scoring groups them).
- Deliberately ignored fields: `INTENTIONALLY_UNMAPPED` in `ingest/cmbs.py`.

## Validation (2026Q3 sample, then the 2021Q3-2026Q3 backfill)
- **Percentages are fractions**: rates (0.0466), occupancy (0.91), DSCR (1.61
  despite the `Percentage` name). Exception: CSMC 2016-NXSR reports
  occupancy at securitization on 0-100; scoring normalizes values > 1.5.
- **Most statements are year-to-date** (3/6/9 months); about a third are
  full-year. Reported DSCR = NOI / debt service for the same period.
- **Split (pari passu) loans are common**: property NOI and debt service
  cover the whole loan while the balance is one trust's note (over half the
  loans; 245 Park Avenue has notes in 13 trusts).
- **Left the pool**: ~21% of loans carry a liquidation code; code 1 with a
  balance is a partial payoff.
- **Defeasance** is often signalled by renaming the property "Defeased" (or
  typing it SE) while the status field says "N" (1,430 loans).
- **Recent financials** exist for ~61% of active loans maturing 2026-27; new
  deals report none until their first annual statement.
- Dates are MM-DD-YYYY; no unparseable values across the backfill.
- Backfill 2021Q3-2026Q3: 16,845 filings, 0 failures, 19,965 loans from 375
  trusts, 833,516 monthly observations.

## Tables (public.*)
| Table | Grain |
|---|---|
| `filings` | one ABS-EE filing: trust, depositor, status |
| `loans` | one loan (trust CIK + asset number): origination terms, latest maturity |
| `loan_observations` | loan x period: balance, rate, status, maturity, servicing, outcomes |
| `properties` | collateral: location, type, size, underwriting baseline, rollup flag |
| `property_observations` | property x period: occupancy, NOI/NCF, debt service, DSCR, valuation, tenants |
