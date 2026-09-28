// Response shapes of the api (src/cmbs_radar/api/service.py).

export type LoanClass = "distressed" | "gap_refi" | "clean_refi" | "watch" | "none" | "insufficient_data" | "excluded";

export interface Metro { id: string; name: string; lat: number; lon: number }

export interface Meta {
  run_id: number;
  data_as_of: string;
  assumptions: { version: string; base_rate: number; horizon_months: number; gap_tolerance: number; distress_gap: number };
  property_types: Record<string, { label: string; debt_yield: number; dscr: number; rate: number; amort_years: number }>;
  metros: Metro[];
  teams: Partial<Record<LoanClass, string>>;
  limits: string;
  flags: string[]; // risk flags present in this run
}

export interface ClassTotal { loans: number; whole_balance: number; refi_gap_whole: number; team?: string }

export interface Summary {
  loans: number;
  whole_balance: number;
  by_class: Partial<Record<LoanClass, ClassTotal>>;
  maturity_wall: { quarter: string; by_class: Partial<Record<LoanClass, number>> }[];
}

export interface Opportunity {
  id: string;
  name: string;
  city: string;
  state: string;
  metro?: string;
  lat: number;
  lon: number;
  properties: number;
  property_type: string;
  property_type_label: string;
  class: LoanClass;
  team?: string;
  refi_date?: string;
  months_to_refi: number | null;
  balance: number | null;
  whole_balance: number | null;
  max_new_loan: number | null;
  binding_constraint?: "debt_yield" | "dscr";
  refi_gap_whole: number | null;
  refi_gap_pct: number | null;
  dscr: number | null;
  debt_yield: number | null;
  occupancy: number | null;
  flags: string[];
  notes: number;
  prev_class?: string;
  changes?: string[];
}

export interface OpportunityList { total: number; offset: number; run_id: number; opportunities: Opportunity[] }

export interface MapPoint {
  key: string;
  label: string;
  metro?: string;
  lat: number;
  lon: number;
  loans: number;
  whole_balance: number;
  by_class: Partial<Record<LoanClass, number>>;
}

// The detail replaces the list row's property count with the collateral list.
export interface Detail extends Omit<Opportunity, "properties"> {
  trust_cik: string;
  asset_number: string;
  trust_name: string;
  as_of_report: string;
  reasons: string[];
  sizing: {
    assumptions_version: string;
    market_rate: number;
    target_debt_yield: number;
    target_dscr: number;
    amort_years: number;
    current_rate: number | null;
    annual_cash_flow: number | null;
    cash_flow_basis: string;
    cash_flow_source: string;
    financials_end: string | null;
    annual_debt_service_whole_loan: number | null;
    dscr_at_securitization: number | null;
    occupancy_at_securitization: number | null;
    whole_loan_factor: number;
    whole_loan_is_estimate: boolean;
    sec_notes_combined_balance?: number;
    max_loan_by_debt_yield: number | null;
    max_loan_by_dscr: number | null;
    refi_gap_this_trust_share: number | null;
    refi_date_source: string;
    prepayment_open_date: string | null;
  };
  properties: {
    seq: number;
    portfolio_totals?: boolean;
    name: string;
    city?: string;
    state?: string;
    year_built?: number;
    net_rentable_sqft?: number;
    units?: number;
    occupancy?: number;
    largest_tenant?: string;
    largest_tenant_lease_expires?: string;
  }[];
  history: { period: string; balance: number | null; payment_status?: string; reported_dscr?: number; occupancy?: number }[];
  other_notes?: { trust_cik: string; trust_name: string; asset_number: string; balance: number | null }[];
  data_limits: string;
}

export interface Brief {
  run_id: number;
  prompt_version: string;
  model: string;
  brief: string;
  cached: boolean;
}

export interface Transition { from: LoanClass; to: LoanClass; loans: number; whole_balance: number }

export interface Moved extends Opportunity {
  base_class: LoanClass;
  base_refi_gap_pct: number | null;
  base_refi_gap_whole: number | null;
}

export interface Scenario {
  rate_shift_bps: number;
  assumptions_version: string;
  base_rate: number;
  base: Partial<Record<LoanClass, ClassTotal>>; // the selected loans by class, before and after the shift
  scenario: Partial<Record<LoanClass, ClassTotal>>;
  transitions: Transition[];
  moved_total: number;
  moved: Moved[];
}

export interface BacktestGroup { label: string; loans: number; trouble: number; trouble_rate: number; whole_balance: number }

export interface Backtest {
  backtest_id: number | null;
  data_end?: string;
  rates_version?: string;
  config?: { MinMonths: number; MaxMonths: number; TargetMonths: number; GraceMonths: number; RatesAt?: string };
  report?: {
    samples: number;
    unresolved: number;
    trouble_rate: number;
    by_outcome: Record<string, number>;
    by_class: BacktestGroup[];
    by_class_performing: BacktestGroup[];
    gap_buckets: BacktestGroup[];
    by_refi_year: BacktestGroup[];
    auc: Record<string, number>;
    auc_performing: Record<string, number>;
  };
}
