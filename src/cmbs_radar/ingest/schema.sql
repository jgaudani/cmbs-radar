-- CMBS radar schema (version is tracked in schema_meta; see store.Migrate).
--
-- Design notes
--   * trust_cik is always the issuing trust from the filing header, never the
--     depositor that co-files for many trusts (their loan numbers collide).
--   * Static facts (loans, properties) are separate from monthly observations
--     (loan_observations, property_observations). Trends are the product.
--   * Every observation row remembers the filing it came from and its filed
--     date. Upserts only overwrite when the incoming filing is at least as
--     new, so ABS-EE/A amendments supersede originals and backfilling old
--     quarters never clobbers newer data.
--   * Percentages are stored as reported; scoring normalizes them.

CREATE TABLE IF NOT EXISTS filings (
    accession_no     text PRIMARY KEY,
    trust_cik        text        NOT NULL,  -- issuing trust; '' if the header didn't identify it
    trust_name       text        NOT NULL,
    depositor_cik    text,                  -- from the header; non-CMBS depositors are skipped
    form_type        text        NOT NULL,
    filed_date       date        NOT NULL,
    period_of_report date,
    status           text        NOT NULL,  -- ingested | skipped_not_cmbs | no_ex102 | failed
    loan_count       int,
    error            text,
    ingested_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS filings_trust_status_idx ON filings (trust_cik, status);
CREATE INDEX IF NOT EXISTS filings_depositor_status_idx ON filings (depositor_cik, status);

CREATE TABLE IF NOT EXISTS loans (
    trust_cik                      text NOT NULL,
    asset_number                   text NOT NULL,
    originator                     text,
    origination_date               date,
    original_amount                numeric,
    balance_at_securitization      numeric,
    original_term_months           int,
    original_amortization_months   int,
    original_io_term_months        int,
    original_rate                  numeric,
    rate_at_securitization         numeric,
    debt_service_at_securitization numeric,
    interest_only                  boolean,
    balloon                        boolean,
    payment_type                   text,
    loan_structure                 text,
    lien_position                  text,
    properties_at_securitization   int,
    -- refinance timing
    maturity_date                  date,    -- latest known (moves on modification)
    ard_date                       date,    -- anticipated repayment date, if ARD
    prepayment_lockout_end         date,
    yield_maintenance_end          date,
    prepayment_premium_end         date,
    first_seen_accession           text NOT NULL,
    last_seen_accession            text NOT NULL,
    last_filed_date                date NOT NULL,
    PRIMARY KEY (trust_cik, asset_number)
);
CREATE INDEX IF NOT EXISTS loans_maturity_idx ON loans (maturity_date);

CREATE TABLE IF NOT EXISTS loan_observations (
    trust_cik                      text NOT NULL,
    asset_number                   text NOT NULL,
    period_end                     date NOT NULL,
    accession_no                   text NOT NULL,
    filed_date                     date NOT NULL,
    maturity_date                  date,
    current_balance                numeric,
    scheduled_balance              numeric,
    current_rate                   numeric,
    paid_through_date              date,
    payment_status                 text,
    modified                       boolean,
    modified_this_period           boolean,
    workout_strategy               text,
    special_servicer_transfer_date date,
    non_recoverable                boolean,
    pi_advances_outstanding        numeric,
    realized_loss                  numeric,
    number_of_properties           int,
    primary_servicer               text,
    -- outcomes (backtest)
    liquidation_code               text,    -- liquidationPrepaymentCode, as reported
    liquidation_date               date,
    modification_code              text,
    last_modification_date         date,
    post_mod_maturity_date         date,
    post_mod_rate                  numeric,
    master_servicer_return_date    date,    -- returned from special servicing
    PRIMARY KEY (trust_cik, asset_number, period_end),
    FOREIGN KEY (trust_cik, asset_number) REFERENCES loans
);

CREATE TABLE IF NOT EXISTS properties (
    trust_cik                          text NOT NULL,
    asset_number                       text NOT NULL,
    property_seq                       int  NOT NULL,  -- 0 = portfolio rollup; members use their suffix (1.01 -> 1)
    is_rollup                          boolean NOT NULL DEFAULT false,  -- portfolio totals, not a building
    source_asset_number                text,  -- EX-102 <assets> block it came from, e.g. 1.01
    name                               text,
    address                            text,
    city                               text,
    state                              text,
    zip                                text,
    county                             text,
    property_type                      text,
    year_built                         int,
    year_renovated                     int,
    net_rentable_sqft                  numeric,
    units                              numeric,
    sqft_at_securitization             numeric,
    units_at_securitization            numeric,
    valuation_at_securitization        numeric,
    valuation_date_at_securitization   date,
    valuation_source_at_securitization text,
    financials_date_at_securitization  date,
    revenue_at_securitization          numeric,
    opex_at_securitization             numeric,
    noi_at_securitization              numeric,
    ncf_at_securitization              numeric,
    dscr_at_securitization             numeric,
    dscr_ncf_at_securitization         numeric,
    dscr_code_at_securitization        text,
    noi_ncf_code_at_securitization     text,
    occupancy_at_securitization        numeric,
    defeasance_option_start            date,
    last_filed_date                    date NOT NULL,
    PRIMARY KEY (trust_cik, asset_number, property_seq),
    FOREIGN KEY (trust_cik, asset_number) REFERENCES loans
);
CREATE INDEX IF NOT EXISTS properties_geo_idx ON properties (state, city, property_type);

CREATE TABLE IF NOT EXISTS property_observations (
    trust_cik             text NOT NULL,
    asset_number          text NOT NULL,
    property_seq          int  NOT NULL,
    period_end            date NOT NULL,
    accession_no          text NOT NULL,
    filed_date            date NOT NULL,
    status                text,
    defeased_status       text,
    valuation_amount      numeric,   -- most recent appraisal, when one was done
    valuation_date        date,
    valuation_source      text,
    occupancy             numeric,
    financials_start_date date,
    financials_end_date   date,
    revenue               numeric,
    opex                  numeric,
    noi                   numeric,
    ncf                   numeric,
    debt_service          numeric,
    dscr                  numeric,   -- NOI basis, as reported
    dscr_ncf              numeric,   -- NCF basis, as reported
    dscr_code             text,
    noi_ncf_code          text,
    tenant1_name          text,
    tenant1_sqft          numeric,
    tenant1_lease_exp     date,
    tenant2_name          text,
    tenant2_sqft          numeric,
    tenant2_lease_exp     date,
    tenant3_name          text,
    tenant3_sqft          numeric,
    tenant3_lease_exp     date,
    PRIMARY KEY (trust_cik, asset_number, property_seq, period_end),
    FOREIGN KEY (trust_cik, asset_number, property_seq) REFERENCES properties
);
