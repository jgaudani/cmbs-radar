import type { Backtest, Brief, Detail, Filters, MapPoint, Meta, OpportunityList, Scenario, Summary } from "./types";

async function get<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((body as { error?: string }).error ?? `HTTP ${r.status}`);
  return body as T;
}

/** Query string for the api's filters; withClass adds the class filter. */
export function filterQuery(f: Filters, withClass: boolean, extra: Record<string, string> = {}): string {
  const p = new URLSearchParams();
  if (f.metro) p.set("metro", f.metro);
  if (f.type) p.set("type", f.type);
  if (f.months) {
    p.set("max_months", f.months);
    p.set("min_months", "-120"); // past-maturity loans count as in the window
  }
  if (f.q.trim()) p.set("q", f.q.trim());
  p.set("sort", f.sort);
  if (withClass && f.classes.length) p.set("class", f.classes.join(","));
  for (const [k, v] of Object.entries(extra)) p.set(k, v);
  return p.toString();
}

const loanPath = (id: string) => id.split("/").map(encodeURIComponent).join("/");

export const api = {
  meta: () => get<Meta>("/api/meta"),
  summary: (f: Filters) => get<Summary>(`/api/summary?${filterQuery(f, false)}`),
  opportunities: (f: Filters) => get<OpportunityList>(`/api/opportunities?${filterQuery(f, true, { limit: "300" })}`),
  map: (f: Filters) => get<MapPoint[]>(`/api/map?${filterQuery(f, true)}`),
  detail: (id: string) => get<Detail>(`/api/opportunities/${loanPath(id)}`),
  brief: (id: string, refresh: boolean) =>
    get<Brief>(`/api/opportunities/${loanPath(id)}/brief${refresh ? "?refresh=1" : ""}`, { method: "POST" }),
  scenario: (bps: number, f: Filters) =>
    get<Scenario>(`/api/scenario?${filterQuery(f, true, { rate_shift_bps: String(bps), limit: "1000" })}`),
  backtest: () => get<Backtest>("/api/backtest"),
};
