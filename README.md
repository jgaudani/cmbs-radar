# CMBS Radar

Roughly $2T of U.S. commercial mortgages mature in 2026-2028, and brokers
find refinancing opportunities by hand. CMBS loan-level data is public on SEC
EDGAR. CMBS Radar ingests it monthly, estimates each loan's refinance gap
with plain-language reasons, routes each opportunity to the team that can act
on it, and backtests the score against what actually happened.

```bash
docker compose up -d && uv sync
export DATABASE_URL='postgres://radar:radar@localhost:5432/radar?sslmode=disable'
uv run cmbs-ingest --ua "Your Name you@example.com" --from 2025Q4 --raw-dir data/raw   # EDGAR -> Postgres
uv run cmbs-score                                                                      # scoring.*
uv run cmbs-backtest                                                                   # scoring.backtest_*
(cd frontend && npm install && npm run build)                                          # React UI
ANTHROPIC_API_KEY=... uv run cmbs-api                                                  # http://localhost:8080
```

- **ingest**: header-first EDGAR discovery (SEC fair-access limits, shared
  throttling pause), streaming EX-102 parser, newest-filing-wins upserts.
- **scoring**: whole-loan sizing for loans split across trusts, annualized
  financials, max new loan = lower of debt-yield and DSCR sizing, flags,
  classes, month-over-month changes.
- **backtest**: each loan scored 12-24 months before its refi date with that
  quarter's rates and only the data reported by then; outcomes from
  liquidation codes, special servicing, extensions.
- **api**: filters, maturity wall, map, loan detail, rate scenarios
  (re-scores the market in memory), Claude-written briefs grounded in the
  computed numbers.
- **frontend**: React + TypeScript UI (Vite) served by the api.

Docs: `docs/data.md`, `docs/scoring.md`, `docs/backtest.md`, `docs/api.md`.
Limits: SEC-registered CMBS only; borrower names are not disclosed.
