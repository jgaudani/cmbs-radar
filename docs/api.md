# api

FastAPI app over `public.*` and `scoring.*`. Owns `api.*` (brief cache).
Serves the React UI built from `frontend/`.

## UI (`frontend/`)
React 19 + TypeScript, built with Vite into `src/cmbs_radar/api/web/`
(gitignored; the Docker image builds it in a Node stage). `src/types.ts`
mirrors the api's JSON.

Pages (React Router, left menu):

| Path | Page |
|---|---|
| `/` | Home: class cards (routed teams), maturity wall, map, largest gaps, class changes since last report |
| `/loans` | Loans grid: search, class pills, "+ Add filter" chips (refi date, gap $ and %, DSCR, debt yield, amount, occupancy, type, metro, flags, changed), server-side sort and paging, column chooser, Share, Export CSV |
| `/loans/:trust/:asset` | One loan: sizing, brief, reasons, history chart, collateral, other notes; Watch, Share |
| `/watchlist` | Starred loans with what changed; Share watchlist, Export CSV. `?ids=` opens a shared list with "Add to my watchlist" |
| `/scenarios` | Rate shift, class-flow Sankey, the loans that move. Shift and filters in the URL |
| `/backtest` | Backtest charts: trouble rate by class, gap and refi year; AUC by metric |
| `/data` | Method, sizing assumptions by type, flags, data limits |

- **The URL is the state.** The Loans page's query string is the api's filter
  query (plus `page`, `size`), so Share copies the address bar and a link
  reproduces the view. Ranges are shown in $M and % and stored in the api's
  units (dollars, fractions): `query.ts`.
- **Watchlist** is per browser (localStorage, synced across tabs). Sharing
  sends the loan ids in the link; there are no accounts yet. Loans that leave
  the data (paid off, defeased) are listed separately.
- **Charts** use Apache ECharts (`charts/Chart.tsx` registers only the chart
  types used); options are pure functions in `charts/options.ts`, tested
  without a canvas. The map stays on Leaflet (real basemap). Chart and map
  pages are lazy-loaded, so the first download skips ECharts.
- The api serves `index.html` for unknown page paths, so deep links work.
- Briefs render Markdown as React elements: model output is text, never
  HTML (tested with script/img injection).
- `index.html` is served `no-cache` and the hashed assets `immutable`, so a
  deploy is picked up at once.
- If the UI isn't built, `/` explains how to build it; the API still works.

```bash
cd frontend && npm install
npm run dev        # http://localhost:5173, proxies /api to cmbs-api on :8080
npm test           # vitest: formatting, query model, chart data, Markdown safety, page flows with a mocked api
npm run build      # into src/cmbs_radar/api/web
```

## Design (keep these)
- Reads, never writes, other packages' tables; checks `public.schema_meta`
  (4) and `scoring.schema_meta` (3) at startup.
- The latest successful scoring run is held in memory (~17k notes) and
  reloaded within a minute of a new run. Filtering happens in Python so the
  base case and scenarios share one filter.
- Lists show `group_primary` rows only: one row per whole loan.
- **Scenarios** re-score the whole universe in memory (`scoring.universe`)
  with the run's own assumptions (bps 0) and shifted, cached per (run,
  bps), ~12s each. The base case and -50bp are precomputed in the
  background whenever a scoring run loads, so the demo click is instant.
  Both sides use the same data, so differences are the rate move alone.
  Class filters refer to the base.
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
- JSON field names are the UI's contract (`frontend/src/types.ts`).

## Endpoints
| Method | Path | |
|---|---|---|
| GET | /api/meta | run, data as-of, assumptions, metros, types, teams, flags in use |
| GET | /api/summary?filters | totals by class, maturity wall (12 quarters) |
| GET | /api/opportunities?filters | ranked whole loans, paged (offset, limit ≤ 5000) |
| GET | /api/opportunities.csv?filters | every matching loan as CSV |
| GET | /api/map?filters | totals by metro / state |
| GET | /api/opportunities/{trust}/{asset} | detail: sizing, reasons, collateral, history, other notes |
| POST | /api/opportunities/{trust}/{asset}/brief[?refresh=1] | Claude brief (cached) |
| GET | /api/scenario?rate_shift_bps=-50&filters | class transitions and moved loans |
| GET | /api/backtest | latest backtest report |
| GET | /api/docs | OpenAPI UI |

Filters (all optional, combined with AND):

| Param | Meaning |
|---|---|
| class, type, metro, state | comma-separated lists (any of) |
| ids | comma-separated `trust/asset` ids, e.g. a watchlist |
| min_X / max_X | ranges; X is months (to refi), gap ($), gap_pct, dscr, dy (debt yield), balance (whole loan), occupancy. Ratios are fractions (dy 0.08 = 8%) |
| refi_from, refi_to | refi date range, `YYYY-MM-DD` or `YYYY-MM` (to = end of month) |
| flag | comma-separated flags, all required (list in /api/meta) |
| changed | `class`: class changed since the loan's previous report; `any`: any class change, new flag or threshold crossing |
| q | substring of property name, city or trust |
| sort, dir | gap, gap_pct, balance, maturity, dscr, dy, occupancy, name, class; dir asc/desc (default per key). Missing values sort last |

A loan missing a value is excluded once a range on that value is set.
