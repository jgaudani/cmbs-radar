import type { LoanClass } from "./types";

export const CLASSES: LoanClass[] = ["distressed", "gap_refi", "clean_refi", "watch"];

export const LABEL: Record<LoanClass, string> = {
  distressed: "Distressed",
  gap_refi: "Gap refi",
  clean_refi: "Clean refi",
  watch: "Watch",
  none: "No action",
  insufficient_data: "Insufficient data",
  excluded: "Excluded",
};

// Canvas charts and Leaflet can't read CSS variables: the class palette, mirrored from styles.css.
export const COLOR: Record<LoanClass, string> = {
  distressed: "#c0392b", gap_refi: "#d68910", clean_refi: "#1e8449", watch: "#2e6fb7", none: "#9aa4b1",
  insufficient_data: "#c3c9d1", excluded: "#c3c9d1",
};
export const ACCENT = "#1f4e8c";
export const MUTED = "#5b6573";

export function money(v: number | null | undefined): string {
  if (v == null) return "—";
  const a = Math.abs(v);
  const s = v < 0 ? "−" : "";
  if (a >= 1e9) return `${s}$${(a / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `${s}$${(a / 1e3).toFixed(0)}K`;
  return `${s}$${a.toFixed(0)}`;
}

export const pct = (v: number | null | undefined, digits = 0) => (v == null ? "—" : `${(v * 100).toFixed(digits)}%`);
export const ratio = (v: number | null | undefined) => (v == null ? "—" : `${v.toFixed(2)}x`);
export const months = (m: number | null) => (m == null ? "" : m < 0 ? `${-m} mo past` : `${m} mo`);
export const place = (city?: string, state?: string) => [city, state].filter(Boolean).join(", ");
export const flagLabel = (f: string) => f.replace(/_/g, " ");

/** "YYYY-MM" n months after an ISO date (or "YYYY-MM"). */
export function addMonths(iso: string, n: number): string {
  const [y, m] = iso.split("-").map(Number);
  const t = y * 12 + (m - 1) + n;
  return `${Math.floor(t / 12)}-${String((t % 12) + 1).padStart(2, "0")}`;
}

/** First and last month of a "2027Q1" quarter, as "YYYY-MM". */
export function quarterMonths(q: string): [string, string] {
  const y = q.slice(0, 4), n = Number(q.slice(5));
  const first = `${y}-${String(3 * n - 2).padStart(2, "0")}`;
  return [first, addMonths(first, 2)];
}
