# CMBS Radar

Roughly $2T of U.S. commercial mortgages mature in 2026-2028
([MBA via Newmark's 10-Q](#research-and-context)), and brokers find
refinancing opportunities by hand. CMBS loan-level data is public on SEC
EDGAR. CMBS Radar ingests it monthly, estimates each loan's refinance gap
with plain-language reasons, routes each opportunity to the team that can act
on it, and backtests the score against what actually happened.

## Research and context

Why this problem, and why it matters to Newmark. Figures are as stated in
each source (checked 2026-09-28).

**The maturity wall**
- Mortgage Bankers Association, [17 Percent of Commercial and Multifamily
  Mortgage Balances to Mature in 2026](https://www.mba.org/news-and-research/newsroom/news/2026/02/09/17-percent-of-commercial-and-multifamily-mortgage-balances-to-mature-in-2026)
  (Feb 9, 2026): $875B of $5.0T outstanding matures in 2026 and $652B in
  2027; $200B of the 2026 maturities sit in CMBS, CLOs and other ABS; 17% of
  office loans and 30% of hotel loans come due in 2026.
- Reed Smith, [The Debt Maturity Wall and 2026 Wave: Challenges and
  Opportunities](https://www.reedsmith.com/our-insights/blogs/real-estate-legal-update/102mijo/the-debt-maturity-wall-and-2026-wave-challenges-and-opportunities/)
  (Feb 17, 2026): refinancing is harder at today's rates and underwriting;
  owners turn to recapitalizations, partnerships and alternative lenders,
  which is the gap-refi and structured-finance opportunity.

**CMBS loans failing to pay off at maturity**
- Multi-Housing News (Trepp data), [2026 CMBS Delinquency
  Rates](https://www.multihousingnews.com/cmbs-delinquency-rates/) (Sep 2026):
  CMBS delinquency at 7.85% in August 2026; non-performing matured balloon
  loans were 81% of newly delinquent balances, led by office towers.
- DBRS Morningstar, [CMBS Monthly Highlights, November
  remittance](https://dbrs.morningstar.com/research/425526/dbrs-morningstar-cmbs-monthly-highlightsnovember-remittance-cmbs-delinquency-and-special-servicing-rates-rise-maturity-payoff-rate-declines-amid-uncertainty)
  (Dec 2023): only 52% of maturing CMBS loans paid off that month; special
  servicing at 7.26%. The period the backtest covers.

**Newmark's view of the opportunity**
- Newmark Group, [Form 10-Q for Q2
  2026](https://www.sec.gov/Archives/edgar/data/1690680/000162828026054877/nmrk-20260630.htm):
  "the MBA expects approximately $2.1 trillion of U.S. commercial and
  multifamily mortgage maturities between 2026 and 2028 alone", expected to
  lift debt volumes and investment sales.
- Newmark, [Q4 2025 earnings call
  transcript](https://www.fool.com/earnings/call-transcripts/2026/02/25/newmark-nmrk-q4-2025-earnings-call-transcript/)
  (Feb 2026): CEO Barry Gosin on "$2.0 trillion of debt coming due over the
  next three years"; the CFO expected debt volumes to grow 20%+ in 2026.
- Newmark, [Loan Sale Advisory & Asset
  Resolutions](https://www.nmrk.com/services/investor-solutions/capital-markets/loan-sale-advisory):
  the note-sale practice the "distressed" class routes to.

**Data and AI in commercial real estate**
- McKinsey, [The real estate industry can solve problems with data, if it asks
  the right questions](https://www.mckinsey.com/industries/real-estate/our-insights/the-real-estate-industry-can-solve-problems-with-data-if-it-asks-the-right-questions)
  (Jan 2025): start from the business question, then gather and structure
  the data.
- Deloitte, [RE-generative AI: How technology can transform commercial real
  estate](https://www.deloitte.com/us/en/insights/industry/financial-services/generative-ai-in-real-estate-benefits.html).

**Primary data**
- SEC, [Accessing EDGAR data](https://www.sec.gov/os/accessing-edgar-data)
  (fair-access rules) and [Regulation AB, Schedule AL](https://www.ecfr.gov/current/title-17/chapter-II/part-229/subpart-229.1100/section-229.1125)
  (EX-102 field definitions). Example filing: [GS Mortgage Securities Trust
  2018-GS9](https://www.sec.gov/Archives/edgar/data/1731056/000188852426016948/0001888524-26-016948-index.htm).


## Product Modules

- **ingest**: ingest service will pull data from SEC EDGAR from available ABS-EE
    filings, format the data and store it in our persistence layer, PostgreSQL.
  - header-first EDGAR discovery (SEC fair-access limits, shared
  throttling pause), streaming EX-102 parser, newest-filing-wins upserts.
- **scoring**: scoring service will score each loan based on available data and 
    different metrics and financials pulled during ingest stage.
  - whole-loan sizing for loans split across trusts, annualized
  financials, max new loan = lower of debt-yield and DSCR sizing, flags,
  classes, month-over-month changes.
- **backtest**: backtest replays the scoring on loans that have already
    matured, as they looked about 18 months earlier, and checks whether the
    predicted class matched what actually happened. It is the evidence that
    the score is worth acting on.
  - each loan scored 12-24 months before its refi date with that
  quarter's rates and only the data reported by then; outcomes from
  liquidation codes, special servicing, extensions; trouble rate by class
  and AUC against DSCR and debt yield.
- **api**: api service serves the scored loans to the UI, lets users filter
    and search them, re-runs scoring for rate what-ifs, and asks Claude to
    write a short brief for a loan from the numbers scoring computed.
  - filters (ranges, dates, ids), sorting and paging, CSV export, maturity
  wall, map, loan detail, rate scenarios (re-scores the market in memory,
  common ones precomputed), Claude-written briefs grounded in the computed
  numbers and cached with the facts sent.
- **frontend**: frontend is the web app brokers use: a dashboard of the
    opportunities, a searchable loan list, a page per loan, a personal
    watchlist, rate scenarios and the backtest results.
  - React + TypeScript (Vite), served by the api; left-menu pages, filterable
  loans grid (TanStack Table) with watchlist and shareable links (page state
  in the URL), charts in Apache ECharts, map in Leaflet.

## Prerequisites

| Tool | Version | Why |
|---|---|---|
| Git | any recent | clone the repo |
| Docker Desktop (or Rancher Desktop / Podman) | any recent | runs Postgres 16 via `docker compose` |
| [uv](https://docs.astral.sh/uv/) | 0.12+ | installs Python 3.12+ and the locked dependencies; no separate Python install needed |
| Node.js | 22.12+ | builds the React UI |
| Anthropic API key | optional | only for Claude-written briefs |

Ports 5432 (Postgres) and 8080 (the app) must be free. If you already run a
local Postgres, change the mapping in `docker-compose.yml` to `"5433:5432"`
and use port 5433 in `DATABASE_URL`.

**macOS** (with [Homebrew](https://brew.sh)):
```bash
brew install git uv node
```
```bash
brew install --cask docker
```
Open Docker Desktop once so its engine starts.

**Windows 10/11** (PowerShell): enable WSL 2 in an admin PowerShell and
reboot, which Docker Desktop requires:
```powershell
wsl --install
```
Then install the tools and open a new PowerShell window so they are on PATH:
```powershell
winget install --id Git.Git -e
```
```powershell
winget install --id Docker.DockerDesktop -e
```
```powershell
winget install --id astral-sh.uv -e
```
```powershell
winget install --id OpenJS.NodeJS.LTS -e
```
Start Docker Desktop once. It needs virtualization enabled in BIOS/UEFI.
Docker Desktop is free for personal use; larger companies need a license
(Rancher Desktop and Podman are free alternatives).

Check everything is installed (in PowerShell, separate them with `;`):
```bash
git --version && docker --version && uv --version && node --version
```

## Setup

Commands below are for macOS/Linux shells. On Windows PowerShell, set
variables with `$env:NAME = "value"` instead of `export NAME='value'`, and
build the UI with `cd frontend; npm install; npm run build; cd ..`.

```bash
docker compose up -d && uv sync
```
```bash
export DATABASE_URL='postgres://radar:radar@localhost:5432/radar?sslmode=disable'
```

### Option A: restore the database snapshot (about a minute)

The snapshot holds everything the demo shows: EDGAR data from 2021-05 to
2026-09 (833,516 monthly loan observations), scoring run 6 and the backtest.
Download `cmbs-radar.dump` (84 MB) from the repository's Releases page into
`data/`, then:
```bash
docker compose cp data/cmbs-radar.dump postgres:/tmp/cmbs-radar.dump
```
```bash
docker compose exec -T postgres pg_restore -U radar -d radar --no-owner --no-privileges --clean --if-exists /tmp/cmbs-radar.dump
```
Then build the UI and start the app (the last three steps of option B).

### Option B: build from EDGAR (hours for the full history)

```bash
uv run cmbs-ingest --ua "Your Name you@example.com" --from 2025Q4 --raw-dir data/raw   # EDGAR -> Postgres
```
```bash
uv run cmbs-score # scoring.*
```
```bash
uv run cmbs-backtest # scoring.backtest_*
```
The SEC requires a real name and email in `--ua`. One or two quarters are
enough to try the app; the backtest needs several years of history
(`--from 2021Q3`) to have outcomes to compare against.

### Build the UI and start the app

```bash
(cd frontend && npm install && npm run build) # React UI
```
```bash
export ANTHROPIC_API_KEY=...   # only needed for Claude briefs
```
```bash
uv run cmbs-api # http://localhost:8080
```

To make a new snapshot after re-running ingest or scoring (written inside
the container, then copied out, so it works the same in PowerShell):
```bash
docker compose exec -T postgres pg_dump -U radar -d radar -Fc -Z 9 --no-owner --no-privileges -n public -n scoring -n api -f /tmp/cmbs-radar.dump
```
```bash
docker compose cp postgres:/tmp/cmbs-radar.dump data/cmbs-radar.dump
```

## Notes

Docs: `docs/data.md`, `docs/scoring.md`, `docs/backtest.md`, `docs/api.md`.
Limits: SEC-registered CMBS only; borrower names are not disclosed.