import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { App } from "./App";

// Canvas charts and Leaflet need a real browser layout; their data is tested in charts/options.test.ts.
vi.mock("./charts/Chart", () => ({ Chart: ({ label }: { label: string }) => <div role="img" aria-label={label} /> }));
vi.mock("./components/OpportunityMap", () => ({ OpportunityMap: () => <div data-testid="map" /> }));

const opp = (id: string, name: string, cls: string, gap: number, extra: object = {}) => ({
  id, name, city: "New York", state: "NY", metro: "nyc", lat: 40.7, lon: -74, properties: 1, property_type: "OF",
  property_type_label: "Office", class: cls, team: "Investment Sales / Note Sales / Advisory", refi_date: "2027-06-01",
  months_to_refi: 8, balance: 80e6, whole_balance: 1.08e9, max_new_loan: 6.4e8, binding_constraint: "debt_yield",
  refi_gap_whole: gap, refi_gap_pct: 0.41, dscr: 1.77, debt_yield: 0.066, occupancy: 0.9, flags: ["split_loan"], notes: 13, ...extra,
});

const PARK = opp("1708131/2", "245 PARK AVENUE", "distressed", 4.43e8, { prev_class: "gap_refi", changes: ["class gap_refi -> distressed"] });
const W57 = opp("1/1", "9 WEST 57TH", "gap_refi", 1e8);

const responses: Record<string, unknown> = {
  "/api/meta": {
    run_id: 6, data_as_of: "2026-09-11", limits: "SEC-registered CMBS only.", flags: ["special_servicing", "split_loan"],
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
  "/api/opportunities": { total: 2, offset: 0, run_id: 6, opportunities: [PARK, W57] },
  "/api/map": [],
  "/api/backtest": { backtest_id: null },
  "/api/opportunities/1708131/2": {
    ...PARK, trust_cik: "1708131", asset_number: "2", trust_name: "CSAIL 2017-C8",
    as_of_report: "2026-09-11", reasons: ["Refi gap is 41% of the loan, at or above the 25% distress threshold."], data_limits: "limits",
    properties: [{ seq: 1, name: "245 PARK AVENUE", city: "New York", state: "NY" }], history: [],
    sizing: { assumptions_version: "v1", market_rate: 0.07, target_debt_yield: 0.11, target_dscr: 1.4, amort_years: 30, current_rate: 0.037,
      annual_cash_flow: 7.1e7, cash_flow_basis: "NCF", cash_flow_source: "t12", financials_end: "2025-12-31", annual_debt_service_whole_loan: 4e7,
      dscr_at_securitization: 2.73, occupancy_at_securitization: 0.98, whole_loan_factor: 13.5, whole_loan_is_estimate: true,
      max_loan_by_debt_yield: 6.47e8, max_loan_by_dscr: 6.37e8, refi_gap_this_trust_share: 3.3e7, refi_date_source: "maturity", prepayment_open_date: null },
  },
  "/api/scenario": {
    rate_shift_bps: -50, assumptions_version: "v1-50bp", base_rate: 0.0375, moved_total: 2,
    base: { gap_refi: { loans: 5, whole_balance: 0, refi_gap_whole: 0 }, distressed: { loans: 1, whole_balance: 0, refi_gap_whole: 0 } },
    scenario: {},
    transitions: [{ from: "gap_refi", to: "clean_refi", loans: 1, whole_balance: 9e8 }, { from: "distressed", to: "gap_refi", loans: 1, whole_balance: 1e9 }],
    moved: [
      { ...opp("1/1", "9 WEST 57TH", "clean_refi", -1e7), base_class: "gap_refi", base_refi_gap_pct: 0.1, base_refi_gap_whole: 1e8 },
      { ...opp("2/2", "ONE MOVER PLAZA", "gap_refi", 5e7), base_class: "distressed", base_refi_gap_pct: 0.3, base_refi_gap_whole: 3e8 },
    ],
  },
};

const calls: string[] = [];
const called = (path: string) => calls.filter((u) => u.startsWith(`${path}?`) || u === path);
const params = (url: string) => new URLSearchParams(url.split("?")[1] ?? "");

beforeEach(() => {
  calls.length = 0;
  localStorage.clear();
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    calls.push(url);
    const path = url.split("?")[0];
    return new Response(JSON.stringify(responses[path] ?? { error: "no fixture" }), { status: path in responses ? 200 : 404 });
  }));
});

const at = (url: string) => render(<MemoryRouter initialEntries={[url]}><App /></MemoryRouter>);

test("home shows totals by team, top gaps and class changes; a card opens its loans", async () => {
  at("/");
  expect(await screen.findByText("$1.08B", { selector: ".kpi .v" })).toBeInTheDocument();
  expect(screen.getByText("Investment Sales / Note Sales / Advisory", { selector: ".kpi .t" })).toBeInTheDocument();
  expect(await screen.findByRole("img", { name: "Maturity wall" })).toBeInTheDocument();
  expect(called("/api/opportunities").some((u) => params(u).get("changed") === "class")).toBe(true);
  const moved = screen.getByText("Changed class since last report").closest("section")!;
  expect(within(moved).getAllByText("245 PARK AVENUE")[0]).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Demo: NYC office/ })).toHaveAttribute("href", "/loans?metro=nyc&type=OF&class=distressed%2Cgap_refi&refi_to=2028-03");

  fireEvent.click(screen.getByRole("button", { name: /Distressed/ }));
  expect(await screen.findByRole("heading", { name: "Loans" })).toBeInTheDocument();
  await waitFor(() => expect(called("/api/opportunities").some((u) => params(u).get("class") === "distressed" && params(u).get("limit") === "50")).toBe(true));
});

test("the loans grid takes its filters from the URL; chips and sorting update it", async () => {
  at("/loans?class=gap_refi&max_dscr=1.25&metro=nyc");
  expect(await screen.findByText("9 WEST 57TH")).toBeInTheDocument();
  const first = called("/api/opportunities").at(-1)!;
  expect(Object.fromEntries(params(first))).toEqual({ class: "gap_refi", max_dscr: "1.25", metro: "nyc", limit: "50", offset: "0" });
  expect(screen.getByText("Metro: New York")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Gap refi" })).toHaveAttribute("aria-pressed", "true");

  // Remove the DSCR chip.
  fireEvent.click(screen.getByRole("button", { name: "Remove DSCR filter" }));
  await waitFor(() => expect(params(called("/api/opportunities").at(-1)!).has("max_dscr")).toBe(false));

  // Add a debt-yield filter from the menu: 8% in the UI, 0.08 in the query.
  fireEvent.click(screen.getByRole("button", { name: "+ Add filter" }));
  fireEvent.click(within(screen.getByRole("list", { name: "Add filter" })).getByRole("button", { name: "Debt yield" }));
  fireEvent.change(screen.getByLabelText("Debt yield min"), { target: { value: "8" } });
  fireEvent.click(screen.getByRole("button", { name: "Apply" }));
  expect(await screen.findByText("Debt yield ≥ 8.0%")).toBeInTheDocument();
  await waitFor(() => expect(params(called("/api/opportunities").at(-1)!).get("min_dy")).toBe("0.08"));

  // Sort by DSCR (ascending first), then flip.
  fireEvent.click(screen.getByRole("button", { name: /^DSCR/ }));
  await waitFor(() => expect(params(called("/api/opportunities").at(-1)!).get("sort")).toBe("dscr"));
  fireEvent.click(screen.getByRole("button", { name: /^DSCR/ }));
  await waitFor(() => expect(params(called("/api/opportunities").at(-1)!).get("dir")).toBe("desc"));

  // Export uses the same filters.
  expect(screen.getByRole("link", { name: "Export CSV" }).getAttribute("href")).toMatch(/^\/api\/opportunities\.csv\?.*min_dy=0\.08/);
});

test("stars build a watchlist that can be shared and imported", async () => {
  const writeText = vi.fn(async () => undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  const { unmount } = at("/loans");
  fireEvent.click(await screen.findByRole("button", { name: "Add to watchlist: 245 PARK AVENUE" }));
  expect(screen.getByRole("button", { name: "Remove from watchlist: 245 PARK AVENUE" })).toHaveAttribute("aria-pressed", "true");
  expect(JSON.parse(localStorage.getItem("cmbs-radar.watchlist")!)[0]).toMatchObject({ id: "1708131/2", name: "245 PARK AVENUE" });
  expect(screen.getByRole("link", { name: /Watchlist/ })).toHaveTextContent("1");

  fireEvent.click(screen.getByRole("link", { name: /Watchlist/ }));
  expect(await screen.findByText(/1 loans · .* 1 changed since last report/)).toBeInTheDocument();
  await waitFor(() => expect(called("/api/opportunities").some((u) => params(u).get("ids") === "1708131/2")).toBe(true));
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Share watchlist" })));
  expect(writeText).toHaveBeenCalledWith(expect.stringMatching(/\/watchlist\?ids=1708131%2F2$/));
  unmount();

  // Someone opens a shared link with one loan they don't have yet.
  at("/watchlist?ids=1708131/2,1/1");
  expect(await screen.findByText(/Someone shared 2 loans/)).toBeInTheDocument();
  fireEvent.click(await screen.findByRole("button", { name: "Add 1 to my watchlist" }));
  expect(JSON.parse(localStorage.getItem("cmbs-radar.watchlist")!).map((w: { id: string }) => w.id)).toEqual(["1708131/2", "1/1"]);
});

test("a loan has its own page with sizing, reasons and watch", async () => {
  at("/loans/1708131/2");
  expect(await screen.findByRole("heading", { name: "245 PARK AVENUE" })).toBeInTheDocument();
  expect(await screen.findByText(/41% of the loan/)).toBeInTheDocument();
  expect(screen.getByText("$1.08B (est.)")).toBeInTheDocument();
  expect(screen.getByText(/was Gap refi last report/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Watch/ }));
  expect(screen.getByRole("button", { name: /Watching/ })).toBeInTheDocument();
});

test("rate scenario shows class flows and lists the loans of one move", async () => {
  at("/scenarios");
  expect(await screen.findByText("2 loans change class")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /Class flows/ })).toBeInTheDocument();
  expect(params(called("/api/scenario")[0]).get("rate_shift_bps")).toBe("-50");
  expect(screen.getByText("ONE MOVER PLAZA")).toBeInTheDocument();

  fireEvent.click(screen.getAllByRole("button", { pressed: false }).find((b) => b.classList.contains("tr") && b.textContent?.includes("Clean refi"))!);
  await waitFor(() => expect(screen.queryByText("ONE MOVER PLAZA")).not.toBeInTheDocument());
  expect(screen.getByText("9 WEST 57TH")).toBeInTheDocument();
});

test("unknown pages say so", async () => {
  at("/nope");
  expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
});
