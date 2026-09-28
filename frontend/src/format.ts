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
