import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { App } from "./App";

// Leaflet needs a real browser layout; the map has no logic worth testing here.
vi.mock("./components/OpportunityMap", () => ({ OpportunityMap: () => <div data-testid="map" /> }));

const opp = (id: string, name: string, cls: string, gap: number) => ({
  id, name, city: "New York", state: "NY", metro: "nyc", lat: 40.7, lon: -74, properties: 1, property_type: "OF",
  property_type_label: "Office", class: cls, team: "Investment Sales / Note Sales / Advisory", refi_date: "2027-06-01",
  months_to_refi: 8, balance: 80e6, whole_balance: 1.08e9, max_new_loan: 6.4e8, binding_constraint: "debt_yield",
  refi_gap_whole: gap, refi_gap_pct: 0.41, dscr: 1.77, debt_yield: 0.066, occupancy: 0.9, flags: ["split_loan"], notes: 13,
});

const responses: Record<string, unknown> = {
  "/api/meta": {
    run_id: 6, data_as_of: "2026-09-11", limits: "SEC-registered CMBS only.",
    assumptions: { version: "v1", base_rate: 0.0425, horizon_months: 24, gap_tolerance: 0.02, distress_gap: 0.25 },
    property_types: { OF: { label: "Office", debt_yield: 0.11, dscr: 1.4, rate: 0.07, amort_years: 30 } },
    metros: [{ id: "nyc", name: "New York", lat: 40.7, lon: -74 }],
    teams: { distressed: "Investment Sales / Note Sales / Advisory", gap_refi: "Structured Finance", clean_refi: "Debt & Structured Finance", watch: "Early relationship outreach" },
  },
  "/api/summary": {
    loans: 2, whole_balance: 2e9,
    by_class: { distressed: { loans: 1, whole_balance: 1.08e9, refi_gap_whole: 4.43e8 }, gap_refi: { loans: 1, whole_balance: 9e8, refi_gap_whole: 1e8 } },
    maturity_wall: [{ quarter: "2026Q3", by_class: { distressed: 1.08e9 } }, { quarter: "2026Q4", by_class: {} }],
  },
  "/api/opportunities": { total: 2, run_id: 6, opportunities: [opp("1708131/2", "245 PARK AVENUE", "distressed", 4.43e8), opp("1/1", "9 WEST 57TH", "gap_refi", 1e8)] },
  "/api/map": [],
  "/api/backtest": { backtest_id: null },
  "/api/opportunities/1708131/2": {
    ...opp("1708131/2", "245 PARK AVENUE", "distressed", 4.43e8), trust_cik: "1708131", asset_number: "2", trust_name: "CSAIL 2017-C8",
    as_of_report: "2026-09-11", reasons: ["Refi gap is 41% of the loan, at or above the 25% distress threshold."], data_limits: "limits",
    properties: [{ seq: 1, name: "245 PARK AVENUE", city: "New York", state: "NY" }], history: [],
    sizing: { assumptions_version: "v1", market_rate: 0.07, target_debt_yield: 0.11, target_dscr: 1.4, amort_years: 30, current_rate: 0.037,
      annual_cash_flow: 7.1e7, cash_flow_basis: "NCF", cash_flow_source: "t12", financials_end: "2025-12-31", annual_debt_service_whole_loan: 4e7,
      dscr_at_securitization: 2.73, occupancy_at_securitization: 0.98, whole_loan_factor: 13.5, whole_loan_is_estimate: true,
      max_loan_by_debt_yield: 6.47e8, max_loan_by_dscr: 6.37e8, refi_gap_this_trust_share: 3.3e7, refi_date_source: "maturity", prepayment_open_date: null },
  },
  "/api/scenario": {
    rate_shift_bps: -50, assumptions_version: "v1-50bp", base_rate: 0.0375, moved_total: 1,
    transitions: [{ from: "gap_refi", to: "clean_refi", loans: 1, whole_balance: 9e8 }],
    moved: [{ ...opp("1/1", "9 WEST 57TH", "clean_refi", -1e7), base_class: "gap_refi", base_refi_gap_pct: 0.1, base_refi_gap_whole: 1e8 }],
  },
};

const calls: string[] = [];
beforeEach(() => {
  calls.length = 0;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    calls.push(url);
    const path = url.split("?")[0];
    return new Response(JSON.stringify(responses[path] ?? { error: "no fixture" }), { status: path in responses ? 200 : 404 });
  }));
});

test("lists opportunities routed to teams and opens the detail", async () => {
  render(<App />);
  expect(await screen.findByText("245 PARK AVENUE")).toBeInTheDocument();
  expect(screen.getByText("$1.08B", { selector: ".kpi .v" })).toBeInTheDocument();
  expect(screen.getByText(/2 loans · one row per whole loan/)).toBeInTheDocument();
  expect(screen.getByText(/Data through/)).toHaveTextContent("scoring run 6");

  // Class cards filter the list.
  fireEvent.click(screen.getByRole("button", { name: /Clean refi/ }));
  await waitFor(() => expect(calls.some((u) => u.startsWith("/api/opportunities?") && !u.includes("clean_refi"))).toBe(true));

  // A row opens the drawer with the sizing and reasons.
  fireEvent.click(screen.getByText("245 PARK AVENUE"));
  const drawer = await screen.findByRole("complementary", { name: "Opportunity detail" });
  expect(await within(drawer).findByText(/41% of the loan/)).toBeInTheDocument();
  expect(within(drawer).getByText("$1.08B (est.)")).toBeInTheDocument();
});

test("rate scenario shows transitions and filters to moved loans", async () => {
  render(<App />);
  await screen.findByText("9 WEST 57TH");
  fireEvent.click(screen.getByRole("button", { name: "Re-score" }));
  const chip = await screen.findByTitle("Show these loans");
  expect(screen.getByText(/loans change class/)).toBeInTheDocument();
  fireEvent.click(chip);
  expect(await screen.findByText(/1 loans move Gap refi → Clean refi at −?-50bp/)).toBeInTheDocument();
  expect(screen.queryByText("245 PARK AVENUE")).not.toBeInTheDocument();
});
