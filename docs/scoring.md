# Scoring

Pure engine (`scoring/engine.py`: no database, no clock) scoring one
`LoanHistory`. The job (`cmbs-score`), the api's scenarios and the backtest
all call it. Each run records its full assumptions, so results are
reproducible (`scripts/check_scoring.py`).

## How a loan is scored
1. **Refi date**: ARD if present, else maturity as reported that month.
   Prepayment opens when lockout and yield maintenance end.
2. **Cash flow**: the most recent full-year statement ending within 15
   months, else the latest year-to-date statement annualized
   (`annualized_ytd`), else underwriting at securitization
   (`stale_financials`). NCF when reported, else NOI.
3. **Whole loan**: whole-loan factor = annual debt service / this trust's
   note debt service (payment at securitization, floored at balance x rate
   because some filers report ~0). Split at >= 1.5x, or >= 1.1x when another
   trust reports the same property (1.1-1.5x alone is more likely an IO
   period ending). With no debt service in the statement, underwritten
   coverage (NOI / DSCR at securitization) is used. Gap is computed on the
   whole loan and prorated to the note.
4. **Max new loan** = lower of cash flow / target debt yield and the loan
   the cash flow carries at the target DSCR and market rate (base rate +
   spread by property type, amortizing). **Refi gap** = balance - max loan.
5. **Flags**: special servicing, 60+ delinquent, past maturity, paid-through
   lag, P&I advances, interest-only, modified, DSCR below floor or declined,
   occupancy / valuation declined, near-term tenant rollover, stale or
   annualized financials, split loan.
6. **Class** (first match): distressed (special servicing, delinquent, or
   gap >= 25% in window) > gap refi (in window, gap > 2%) > clean refi (in
   window) > watch (outside window with a deterioration flag) > none. Plus
   excluded and insufficient_data. Window = 24 months (past maturity counts).
7. **Changes**: the loan is also scored as of its previous report with the
   same assumptions; class moves and threshold crossings are stored.

Assumptions: `scoring/assumptions/v1.json` (base rate, debt yield / DSCR /
spread / amortization by property type, thresholds). The base rate is a
placeholder: set it from the market before a demo.

## Rules from the data (each has a test)
- Special servicing = transfer date with no later return date. Delinquent =
  payment status 2, 3, 5, 6. Left pool = liquidation code AND no balance.
- Fully defeased = status "F" or every financial property named
  "Defeased..." / typed SE: excluded (repaid from Treasuries).
- Companion notes (1, 1A, 1B in one trust) are scored as one loan; the
  companions are excluded, pointing at it.
- Occupancy values > 1.5 are divided by 100.
- Tenant rollover counts only leases ending within the horizon and before
  refi date + 12 months.
- Split loans appear once per trust holding a note. Notes are grouped by
  property name + city + state + refi month (`whole_loan_key`); the note
  with the median whole-balance estimate is `group_primary` (ties broken by
  trust and asset, so reruns agree). Estimates vary with note coupons (245
  Park Ave: $0.96B-2.1B, median $1.08B; the loan is ~$1.2B).
- Co-op loans (CH) show huge debt yields (market-rent underwriting).
- Known gap: grouping matches normalized names, so filer variants ("50
  VARICK STREET" vs "50 Varick") stay separate.

## Contract with the api
- Read `scoring.current_scores` (latest successful run); check
  `scoring.schema_meta` = 3.
- Lists and counts use `WHERE group_primary` (one row per whole loan);
  `whole_loan_key` finds the other notes.
- `class` and `flags` values are stable strings (constants in the engine).
- `reasons` are plain language grounded in the numbers; briefs may quote
  them but never compute new numbers.
