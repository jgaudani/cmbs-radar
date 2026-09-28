# api

FastAPI app over `public.*` and `scoring.*`, with the demo UI (`api/web/`:
plain HTML/CSS/JS, Leaflet from cdnjs, OpenStreetMap tiles, inline SVG
charts). Owns `api.*` (brief cache).

## Design (keep these)
- Reads, never writes, other packages' tables; checks `public.schema_meta`
  (4) and `scoring.schema_meta` (3) at startup.
- The latest successful scoring run is held in memory (~17k notes) and
  reloaded within a minute of a new run. Filtering happens in Python so the
  base case and scenarios share one filter.
- Lists show `group_primary` rows only: one row per whole loan.
- **Scenarios** re-score the whole universe in memory (`scoring.universe`)
  with the run's own assumptions (bps 0) and shifted, cached per (run,
  bps), ~10s each the first time. Both sides use the same data, so
  differences are the rate move alone. Class filters refer to the base.
- Office loans are mostly sized by the debt-yield test, which ignores
  rates: NYC office moves 0 loans at -50bp. The UI says so
  (`binding_constraint`).
- **Briefs**: the facts sent to Claude are exactly the loan detail JSON
  (numbers from scoring); the prompt forbids new numbers, guessing
  borrowers or changing the class. Official `anthropic` SDK, `claude-opus-5`,
  effort medium, server-side refusal fallback. Cached in `api.briefs` per
  (loan, scoring run, prompt version) with the facts stored for audit. Bump
  `brief.PROMPT_VERSION` when the prompt changes.
- Metros are defined by county (EX-102 has no coordinates); map points are
  metro or state centers.
- JSON field names are the UI's contract (`web/app.js`).

## Endpoints
| Method | Path | |
|---|---|---|
| GET | /api/meta | run, data as-of, assumptions, metros, types, teams |
| GET | /api/summary?filters | totals by class, maturity wall (12 quarters) |
| GET | /api/opportunities?filters | ranked whole loans (sort=gap, gap_pct, maturity, balance) |
| GET | /api/map?filters | totals by metro / state |
| GET | /api/opportunities/{trust}/{asset} | detail: sizing, reasons, collateral, history, other notes |
| POST | /api/opportunities/{trust}/{asset}/brief[?refresh=1] | Claude brief (cached) |
| GET | /api/scenario?rate_shift_bps=-50&filters | class transitions and moved loans |
| GET | /api/backtest | latest backtest report |
| GET | /api/docs | OpenAPI UI |

Filters: class, type, metro, state, min_months, max_months, min_gap_pct,
flag, q, limit.
