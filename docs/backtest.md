# Backtest: did the score see it coming?

`cmbs-backtest` scores every loan (including paid-off ones) as it looked
12-24 months before its refi date and compares with what happened. Results
go to `scoring.backtest_runs` / `backtest_loans`; the api shows the latest.
Run on demand after backfills or assumption changes.

## Method (each rule has a test)
- **Scoring point**: the report closest to 18 months before the refi date
  (12-24), scored with `score_at`, which only sees data reported by then.
  The refi date is the one reported at that time (the static loans table
  holds the latest maturity and is not used).
- **Rates**: the base rate is the 10-year Treasury for the scoring quarter
  (`scoring/rates.json`). `--rates-at refi` uses the rate at the refi date
  instead (a hindsight diagnostic; results are nearly identical because most
  loans are sized by debt yield, which ignores rates).
  TODO: the table is approximate (typed from memory); replace it with FRED
  DGS10 quarterly averages before quoting results.
- **Outcome** through refi date + 6 months. Question: did the loan pay off
  (codes 2/5/8/9) without a loss? Trouble = loss (codes 3/6/7 or a realized
  loss) or not paid off in the window: still in special servicing, maturity
  default (status 3/5/6), extended (maturity moved > 30 days or a new
  modification code), or outstanding. A payoff after a special-servicing
  transfer or missed balloon is `refinanced_late` (success): several
  servicers transfer a loan days after a missed balloon and it pays off
  weeks later. Loans that vanish without a code are unresolved (excluded).
- Split loans are counted once. "Performing" = not in special servicing or
  60+ delinquent when scored.
- Known leak: cross-trust split evidence is computed on today's data.

## Findings (2026-09-27; data 2021-05 to 2026-09; 297 loans)
- Didn't pay off in time: clean 37%, gap 40%, distressed 65%. By predicted
  gap: surplus 37-39%, gap 10-25% 53%, gap 25%+ 63%. By refi year: 2022 23%,
  2023 45%, 2024 52%.
- AUC (0.5 = chance): refi gap 0.62 (0.59 on performing loans), debt yield
  0.60, DSCR 0.54, DSCR at securitization 0.36 (inverted). The score ranks
  risk better than DSCR, mostly through large gaps; clean vs small gap
  barely separates.
- Office predicted clean still failed ~90% of the time: in 2023-24 lender
  appetite for office, not sizing math, decided outcomes. A property-type or
  market-appetite overlay (e.g. from a debt desk) is the next lever; test it
  on a holdout.
- Open artifact: loans with no property type fail far less often (~20%)
  than typed ones (~75%). Not explained by defeasance or filing era; likely
  deal mix. Check before quoting results by property type.
- Bugs the backtest found and fixed: payoff after a transfer counted as
  trouble (overstated trouble by ~14 points); defeasance signalled by
  property name; split loans with no reported debt service.
- Sample is small because most EX-102 loans are 10-year loans maturing from
  2027; it grows as they mature.
