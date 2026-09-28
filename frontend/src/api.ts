import type { Backtest, Brief, Detail, MapPoint, Meta, OpportunityList, Scenario, Summary } from "./types";

async function get<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((body as { error?: string }).error ?? `HTTP ${r.status}`);
  return body as T;
}

const loanPath = (id: string) => id.split("/").map(encodeURIComponent).join("/");
const withQuery = (path: string, qs: string) => (qs ? `${path}?${qs}` : path);

// Each call takes the api filter query string (see query.ts apiQuery).
export const api = {
  meta: () => get<Meta>("/api/meta"),
  summary: (qs: string) => get<Summary>(withQuery("/api/summary", qs)),
  opportunities: (qs: string) => get<OpportunityList>(withQuery("/api/opportunities", qs)),
  map: (qs: string) => get<MapPoint[]>(withQuery("/api/map", qs)),
  detail: (id: string) => get<Detail>(`/api/opportunities/${loanPath(id)}`),
  brief: (id: string, refresh: boolean) =>
    get<Brief>(`/api/opportunities/${loanPath(id)}/brief${refresh ? "?refresh=1" : ""}`, { method: "POST" }),
  scenario: (bps: number, qs: string) =>
    get<Scenario>(`/api/scenario?${[`rate_shift_bps=${bps}`, "limit=2000", qs].filter(Boolean).join("&")}`),
  backtest: () => get<Backtest>("/api/backtest"),
  csvUrl: (qs: string) => withQuery("/api/opportunities.csv", qs),
};

/** Links inside the app: a loan's page. */
export const loanHref = (id: string) => `/loans/${loanPath(id)}`;
