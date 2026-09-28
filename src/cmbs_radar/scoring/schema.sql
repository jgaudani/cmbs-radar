-- scoring schema, owned by the scoring job. Read by api.
-- Everything here is derived from ingest's public.* tables and the
-- assumptions recorded on each run, so an old schema is dropped and rebuilt.

CREATE TABLE IF NOT EXISTS scoring.runs (
    run_id                bigserial PRIMARY KEY,
    started_at            timestamptz NOT NULL DEFAULT now(),
    finished_at           timestamptz,
    status                text        NOT NULL,  -- running | succeeded | failed
    assumptions_version   text        NOT NULL,
    assumptions           jsonb       NOT NULL,  -- full set, for reproducibility
    ingest_schema_version int         NOT NULL,
    loans_scored          int,
    error                 text
);

-- One row per live loan per run: the score as of the loan's latest
-- remittance report, plus what changed since the previous report.
CREATE TABLE IF NOT EXISTS scoring.loan_scores (
    run_id              bigint  NOT NULL REFERENCES scoring.runs ON DELETE CASCADE,
    trust_cik           text    NOT NULL,
    asset_number        text    NOT NULL,
    period_end          date    NOT NULL,
    property_type       text,
    class               text    NOT NULL,  -- clean_refi | gap_refi | distressed | watch | none | excluded | insufficient_data
    flags               text[]  NOT NULL,
    reasons             text[]  NOT NULL,  -- plain language, most important first
    balance             numeric,           -- this trust's note
    whole_loan_factor   numeric NOT NULL,  -- whole loan / note (1 unless split pari passu)
    whole_balance       numeric,
    current_rate        numeric,
    refi_date           date,              -- ARD if present, else maturity
    refi_date_source    text,
    months_to_refi      int,
    prepay_open_date    date,
    cash_flow           numeric,           -- annual, whole property
    cash_flow_basis     text,              -- NCF | NOI
    cash_flow_source    text,              -- t12 | ytd_annualized | underwriting
    financials_end      date,
    debt_service_annual numeric,           -- whole loan
    dscr                numeric,           -- computed: cash_flow / debt_service_annual
    dscr_at_sec         numeric,
    debt_yield          numeric,
    occupancy           numeric,           -- fraction
    occupancy_at_sec    numeric,
    market_rate         numeric,
    max_loan_debt_yield numeric,           -- whole loan
    max_loan_dscr       numeric,
    max_new_loan        numeric,
    refi_gap_whole      numeric,           -- negative = surplus
    refi_gap            numeric,           -- this trust's pro rata share
    refi_gap_pct        numeric,
    prev_period_end     date,
    prev_class          text,
    changes             text[]  NOT NULL,  -- vs the previous report, same assumptions
    -- A split loan appears once per trust holding a note. Rows with the same
    -- whole_loan_key are one loan; list only group_primary rows.
    whole_loan_key      text,              -- null unless split across trusts
    group_primary       boolean NOT NULL,  -- false for secondary notes, companions, excluded
    group_notes         int,               -- notes of this loan in SEC trusts
    group_sec_balance   numeric,           -- their combined balance: floor for the whole loan
    PRIMARY KEY (run_id, trust_cik, asset_number)
);
CREATE INDEX IF NOT EXISTS loan_scores_class_idx ON scoring.loan_scores (run_id, class, months_to_refi) WHERE group_primary;
CREATE INDEX IF NOT EXISTS loan_scores_group_idx ON scoring.loan_scores (run_id, whole_loan_key);

-- What the api reads: the latest successful run.
CREATE OR REPLACE VIEW scoring.current_scores AS
SELECT s.*
FROM scoring.loan_scores s
WHERE s.run_id = (SELECT max(run_id) FROM scoring.runs WHERE status = 'succeeded');

-- Backtests: loans scored as they looked 12-24 months before their refi
-- date (point-in-time rates, no look-ahead) and what happened afterwards.
CREATE TABLE IF NOT EXISTS scoring.backtest_runs (
    backtest_id bigserial   PRIMARY KEY,
    created_at  timestamptz NOT NULL DEFAULT now(),
    assumptions jsonb       NOT NULL,
    rates       jsonb       NOT NULL,  -- base rate by quarter used for scoring dates
    config      jsonb       NOT NULL,  -- scoring window and grace period
    data_end    date,                  -- latest report in the data
    report      jsonb       NOT NULL   -- backtest.Report
);

CREATE TABLE IF NOT EXISTS scoring.backtest_loans (
    backtest_id    bigint  NOT NULL REFERENCES scoring.backtest_runs ON DELETE CASCADE,
    trust_cik      text    NOT NULL,
    asset_number   text    NOT NULL,
    scored_as_of   date    NOT NULL,
    base_rate      numeric NOT NULL,
    refi_date      date    NOT NULL,
    property_type  text,
    class          text    NOT NULL,
    performing     boolean NOT NULL,
    refi_gap_pct   numeric,
    dscr           numeric,
    debt_yield     numeric,
    whole_balance  numeric,
    outcome        text    NOT NULL,
    outcome_date   date,
    trouble        boolean NOT NULL,
    PRIMARY KEY (backtest_id, trust_cik, asset_number)
);
