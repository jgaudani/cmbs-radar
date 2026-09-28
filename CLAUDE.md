# CMBS Radar

Finds commercial real estate refinancing opportunities in public CMBS
loan-level data and routes each one to the team that can act on it.

## The problem
Roughly $2T of U.S. commercial and multifamily mortgages mature 2026-2028,
many originated at far lower rates. Brokers find refinancing opportunities by
hand. CMBS loan-level data is public on SEC EDGAR (Form ABS-EE, exhibit
EX-102, from Nov 2016). The radar ingests it monthly, estimates each loan's
refinance gap, and routes each opportunity to the Newmark business line that
monetizes it:

| Class | Situation | Newmark team |
|---|---|---|
| clean refi | matures soon, no equity gap | Debt & Structured Finance |
| gap refi | equity shortfall at refinance | structured finance (mezz, pref equity, recap) |
| distressed | large gap and/or special servicing | investment sales, note sales, advisory |
| watch | deteriorating, maturity further out | early relationship outreach |

## Design principles
The radar is one instance of a reusable pattern: turning fragmented data into
analysis embedded in a team's workflow. The same pipeline can ingest a firm's
own servicing portfolio and CRM data, where the proprietary advantage lives.
Keep designs consistent with that: pluggable sources, explainable scoring,
humans in the loop.

## Layout
One Python project (uv), one package per service. Postgres is the only
integration point; each service writes only its own tables.

| Package | Command | Owns | Role |
|---|---|---|---|
| `src/cmbs_radar/ingest/` | `cmbs-ingest` | `public.*` (schema v4) | EDGAR -> filings, loans, properties, monthly observations. Scheduled. |
| `src/cmbs_radar/scoring/` | `cmbs-score`, `cmbs-backtest` | `scoring.*` (schema v3) | Refi gap, flags, class, changes, whole-loan grouping, backtest. Scheduled after ingest. |
| `src/cmbs_radar/api/` | `cmbs-api` | `api.*` (schema v1) | HTTP API, rate scenarios, Claude briefs; serves the UI. |
| `frontend/` | `npm run build` | | React + TypeScript UI (Vite), built into `src/cmbs_radar/api/web/`. |

```
EDGAR -> ingest -> Postgres public.* -> scoring -> scoring.* -> api -> browser
                                                                 └-> Claude (briefs, cached in api.*)
```

Rules:
- Readers check the owner's schema version at startup and fail fast on a
  mismatch (`public.schema_meta`, `scoring.schema_meta`).
- Changing a table another package reads: bump the owner's version and
  update readers in the same change.
- The api imports `scoring.engine`, `scoring.load` and `scoring.universe`
  for scenarios (a library, not a service call): change them together.

## Docs (read before changing a package)
- `docs/data.md`: EX-102 quirks, validation findings, ingest design.
- `docs/scoring.md`: sizing, rules from the data, classes, contract with the api.
- `docs/backtest.md`: method, outcome rules, findings.
- `docs/api.md`: endpoints, scenarios, briefs, UI.

## Conventions
- Python >= 3.12, uv, few dependencies (psycopg, lxml, httpx, FastAPI,
  anthropic). Type hints and dataclasses; stdlib first.
- Frontend: React + TypeScript (strict), Vite, Vitest. `src/types.ts`
  mirrors the api's JSON; keep them in step.
- Tests for every data quirk and business rule (`tests/`, pytest).
  Postgres integration tests run when `TEST_DATABASE_URL` is set and must
  use their own database (`radar_test`): they drop tables.
- Logging via `logging`; jobs exit non-zero on partial failure so schedulers
  alert. Jobs are idempotent and safe to re-run; no state outside Postgres.
- Config via flags with env var fallbacks; secrets only from env.
- Money in dollars; percentages stored as reported (fractions) and
  normalized in scoring.
- The LLM only writes briefs grounded in computed facts passed in the
  prompt. It never computes numbers or decides classifications.
- Deploy: one image, a CronJob per job, a Deployment for the api (`deploy/`).
- Engine results are reproducible: `scripts/check_scoring.py` re-scores and
  diffs against the stored run. Run it after engine changes.

## Local development
```bash
docker compose up -d                  # Postgres on :5432 (+ radar_test for tests)
uv sync
export DATABASE_URL='postgres://radar:radar@localhost:5432/radar?sslmode=disable'
export EDGAR_USER_AGENT='Your Name you@example.com'     # ingest only
export ANTHROPIC_API_KEY=...                             # api briefs only
(cd frontend && npm install && npm run build)          # UI into the api package
uv run pytest -q && (cd frontend && npm test)
TEST_DATABASE_URL='postgres://radar:radar@localhost:5432/radar_test?sslmode=disable' uv run pytest -q
uv run cmbs-ingest --from 2021Q3 --to 2026Q3 --raw-dir data/raw
uv run cmbs-score && uv run cmbs-backtest && uv run cmbs-api
```
Run order: ingest -> scoring -> (backtest) -> api. `data/` (raw EX-102
archive, ~500 MB) is gitignored and re-derivable from EDGAR.

## Core workflows
Changes must keep these working end to end:
1. The maturity wall: how much debt refinances when, by class.
2. A targeted search, e.g. "office loans in the NYC metro maturing in 18
   months with a refi gap" -> ranked list -> open one -> brief.
3. Rate scenario: rates -50bp; loans move from gap refi to clean refi
   (office mostly doesn't: it is sized by debt yield).
4. Backtest: what the score predicted 12-24 months ahead vs what happened.
5. New sources: the same pipeline over a firm's own loan and CRM data.

## Known data limits
Only SEC-registered CMBS: excludes private 144A, bank balance-sheet and
agency multifamily loans. Borrower names are not disclosed. Whole-loan sizes
for split loans are estimates. Surface these limits in the UI and docs.

## History
First built as three Go services, then ported to Python and verified against
them on the full dataset (scoring: all 17,369 notes identical; backtest: all
319 samples; parser: 63,977 stored rows; api: 29 endpoints identical JSON).
The Go code was then retired.
