// The Loans page keeps its whole state in the URL: the query string is the
// api's filter query plus two UI-only params (page, size). Sharing a view is
// sharing its URL.
import { CLASSES, LABEL, addMonths, flagLabel, money, pct, ratio } from "./format";
import type { LoanClass, Meta } from "./types";

export type Unit = "money" | "pct" | "ratio";

export type FilterDef =
  | { key: string; label: string; kind: "multi"; param: string; options: (m: Meta | null) => [string, string][]; all?: boolean }
  | { key: string; label: string; kind: "range"; param: string; unit: Unit; hint: string }
  | { key: "refi"; label: string; kind: "date" }
  | { key: "changed"; label: string; kind: "changed" };

const OTHER_CLASSES: LoanClass[] = ["none", "insufficient_data", "excluded"];

/** Every filter the Loans page offers, in menu order. */
export const FILTERS: FilterDef[] = [
  { key: "class", label: "Class", kind: "multi", param: "class", options: () => [...CLASSES, ...OTHER_CLASSES].map((c) => [c, LABEL[c]]) },
  { key: "refi", label: "Refi date", kind: "date" },
  { key: "gap_pct", label: "Refi gap %", kind: "range", param: "gap_pct", unit: "pct", hint: "of the whole loan; negative = surplus" },
  { key: "gap", label: "Refi gap $", kind: "range", param: "gap", unit: "money", hint: "$M, whole loan" },
  { key: "dscr", label: "DSCR", kind: "range", param: "dscr", unit: "ratio", hint: "x, from cash flow and debt service" },
  { key: "dy", label: "Debt yield", kind: "range", param: "dy", unit: "pct", hint: "cash flow ÷ whole loan, %" },
  { key: "balance", label: "Loan amount", kind: "range", param: "balance", unit: "money", hint: "$M, whole loan" },
  { key: "occupancy", label: "Occupancy", kind: "range", param: "occupancy", unit: "pct", hint: "%" },
  {
    key: "type", label: "Property type", kind: "multi", param: "type",
    options: (m) => Object.entries(m?.property_types ?? {}).map(([k, t]) => [k, t.label] as [string, string]).sort((a, b) => a[1].localeCompare(b[1])),
  },
  { key: "metro", label: "Metro", kind: "multi", param: "metro", options: (m) => (m?.metros ?? []).map((x) => [x.id, x.name]) },
  { key: "flag", label: "Risk flags", kind: "multi", param: "flag", all: true, options: (m) => (m?.flags ?? []).map((f) => [f, flagLabel(f)]) },
  { key: "changed", label: "Changed since last report", kind: "changed" },
];

const RANGE_KEYS = ["months", "gap", "gap_pct", "dscr", "dy", "balance", "occupancy"];
const API_PARAMS = new Set([
  "class", "type", "metro", "state", "ids", "flag", "changed", "q", "sort", "dir", "refi_from", "refi_to",
  ...RANGE_KEYS.flatMap((k) => [`min_${k}`, `max_${k}`]),
]);

export const PAGE_SIZES = [25, 50, 100, 200];
export const DEFAULT_SIZE = 50;

/** The api query for a page URL: known filter params only, plus paging. */
export function apiQuery(search: URLSearchParams, extra: Record<string, string> = {}): string {
  const out = new URLSearchParams();
  for (const [k, v] of search) if (API_PARAMS.has(k) && v !== "") out.set(k, v);
  for (const [k, v] of Object.entries(extra)) out.set(k, v);
  return out.toString();
}

/** limit/offset for the page and size in a page URL. */
export function paging(search: URLSearchParams): { page: number; size: number; offset: number } {
  const size = PAGE_SIZES.includes(Number(search.get("size"))) ? Number(search.get("size")) : DEFAULT_SIZE;
  const page = Math.max(1, Math.floor(Number(search.get("page")) || 1));
  return { page, size, offset: (page - 1) * size };
}

// Ranges are shown in friendly units and stored as the api's: $M and % in the UI, dollars and fractions in the URL.
const SCALE: Record<Unit, number> = { money: 1e6, pct: 0.01, ratio: 1 };
const clean = (v: number) => String(Number(v.toPrecision(10)));
export const toApi = (unit: Unit, ui: string) => (ui.trim() === "" || isNaN(Number(ui)) ? "" : clean(Number(ui) * SCALE[unit]));
export const toUi = (unit: Unit, api: string | null) => (api == null || api === "" ? "" : clean(Number(api) / SCALE[unit]));

const show = (unit: Unit, v: string) => {
  const n = Number(v);
  return unit === "money" ? money(n) : unit === "pct" ? pct(n, Math.abs(n) < 0.1 && n !== 0 ? 1 : 0) : ratio(n);
};

export function isActive(def: FilterDef, s: URLSearchParams): boolean {
  switch (def.kind) {
    case "multi": return !!s.get(def.param);
    case "range": return !!(s.get(`min_${def.param}`) || s.get(`max_${def.param}`));
    case "date": return !!(s.get("refi_from") || s.get("refi_to"));
    case "changed": return !!s.get("changed");
  }
}

/** The params a filter owns, to clear it. */
export function paramsOf(def: FilterDef): string[] {
  switch (def.kind) {
    case "multi": return [def.param];
    case "range": return [`min_${def.param}`, `max_${def.param}`];
    case "date": return ["refi_from", "refi_to", "min_months", "max_months"];
    case "changed": return ["changed"];
  }
}

/** Chip text for an active filter, e.g. "DSCR ≤ 1.25x". */
export function describe(def: FilterDef, s: URLSearchParams, meta: Meta | null): string {
  switch (def.kind) {
    case "multi": {
      const names = new Map(def.options(meta));
      const vals = (s.get(def.param) ?? "").split(",").filter(Boolean).map((v) => names.get(v) ?? v);
      const list = vals.length > 2 ? `${vals.slice(0, 2).join(", ")} +${vals.length - 2}` : vals.join(", ");
      return `${def.label}: ${list}`;
    }
    case "range": {
      const lo = s.get(`min_${def.param}`), hi = s.get(`max_${def.param}`);
      if (lo && hi) return `${def.label} ${show(def.unit, lo)} – ${show(def.unit, hi)}`;
      return lo ? `${def.label} ≥ ${show(def.unit, lo)}` : `${def.label} ≤ ${show(def.unit, hi!)}`;
    }
    case "date": {
      const from = s.get("refi_from"), to = s.get("refi_to");
      if (from && to) return `Refi ${from} – ${to}`;
      return from ? `Refi from ${from}` : `Refi by ${to}`;
    }
    case "changed":
      return s.get("changed") === "class" ? "Class changed since last report" : "Anything changed since last report";
  }
}

/** Demo step 2: office loans in the NYC metro with a refi gap, refinancing within 18 months (past maturity included). */
export function demoQuery(dataAsOf: string): string {
  return new URLSearchParams({ metro: "nyc", type: "OF", class: "distressed,gap_refi", refi_to: addMonths(dataAsOf, 18) }).toString();
}
