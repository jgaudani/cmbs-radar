import type { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";
import { useSearchParams } from "react-router";
import { api } from "../api";
import { Chart } from "../charts/Chart";
import { sankeyOption } from "../charts/options";
import { Transition } from "../components/Badge";
import { PageHeader } from "../components/Layout";
import { LoanGrid } from "../components/LoanGrid";
import { ShareButton } from "../components/ShareButton";
import { LABEL, money, pct } from "../format";
import { useLoad } from "../hooks";
import { useMeta } from "../meta";
import type { Moved } from "../types";

const SHIFTS = [-100, -75, -50, -25, 25, 50, 100];
const bp = (b: number) => `${b > 0 ? "+" : "−"}${Math.abs(b)}bp`;

const EXTRA: ColumnDef<Moved, never>[] = [
  {
    id: "move", header: "Class change", enableSorting: false,
    cell: ({ row: { original: m } }) => <Transition from={m.base_class} to={m.class} />,
  },
  {
    id: "gap_move", header: "Gap % before → after", enableSorting: false, meta: { num: true },
    cell: ({ row: { original: m } }) => <>{pct(m.base_refi_gap_pct)} → {pct(m.refi_gap_pct)}</>,
  },
];

/** Demo step 3: re-score every loan with the market rate shifted. The URL holds the shift and filters. */
export function ScenariosPage() {
  const { meta } = useMeta();
  const [search, setSearch] = useSearchParams();
  const bps = Number(search.get("bps")) || -50;
  const type = search.get("type") ?? "";
  const metro = search.get("metro") ?? "";
  const [only, setOnly] = useState<string | null>(null); // "from>to" transition shown in the grid

  // Loans refinancing inside the horizon: the ones whose sizing, and so class, depends on rates.
  const filters = new URLSearchParams({ class: "distressed,gap_refi,clean_refi", ...(type && { type }), ...(metro && { metro }) }).toString();
  const s = useLoad(`${bps}|${filters}`, () => api.scenario(bps, filters));
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(search);
    if (v) next.set(k, v);
    else next.delete(k);
    setSearch(next, { replace: true });
    setOnly(null);
  };

  const sc = s.data && !s.loading ? s.data : null;
  const rows = (sc?.moved ?? []).filter((m) => !only || `${m.base_class}>${m.class}` === only);
  const types = Object.entries(meta?.property_types ?? {}).sort((a, b) => a[1].label.localeCompare(b[1].label));

  return (
    <>
      <PageHeader title="Rate scenarios" sub="Re-score every loan with the market rate shifted: which loans change class?">
        <ShareButton />
      </PageHeader>
      <section className="card controls">
        <label>
          Rates move
          <select value={bps} onChange={(e) => set("bps", e.target.value === "-50" ? "" : e.target.value)}>
            {SHIFTS.map((b) => <option key={b} value={b}>{bp(b)}</option>)}
          </select>
        </label>
        <label>
          Property
          <select value={type} onChange={(e) => set("type", e.target.value)}>
            <option value="">All</option>
            {types.map(([code, t]) => <option key={code} value={code}>{t.label}</option>)}
          </select>
        </label>
        <label>
          Metro
          <select value={metro} onChange={(e) => set("metro", e.target.value)}>
            <option value="">All</option>
            {meta?.metros.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
        </label>
        <span className="muted">
          {s.loading ? `Re-scoring every loan at ${bp(bps)}… (−50bp is precomputed; others take a few seconds)`
            : sc ? `Base rate ${pct(sc.base_rate, 2)} · assumptions ${sc.assumptions_version}. Debt-yield-sized loans don't move: that test ignores rates.` : ""}
        </span>
      </section>
      {s.error && <p className="err">{s.error}</p>}

      {sc && (
        <div className="two wide-left">
          <section className="card">
            <h3>Today → at {bp(bps)} <span className="muted">loans refinancing within the horizon, by class</span></h3>
            <Chart option={sankeyOption(sc)} height={300} label="Class flows under the rate scenario" />
          </section>
          <section className="card">
            <h3>{sc.moved_total.toLocaleString()} loans change class</h3>
            <div className="transitions">
              {sc.transitions.map((t) => {
                const k = `${t.from}>${t.to}`;
                return (
                  <button key={k} className={`tr ${only === k ? "on" : ""}`} aria-pressed={only === k} onClick={() => setOnly(only === k ? null : k)}>
                    <Transition from={t.from} to={t.to} /> <b>{t.loans}</b> · {money(t.whole_balance)}
                  </button>
                );
              })}
              {sc.transitions.length === 0 && <p className="muted">No class changes for these loans.</p>}
            </div>
            <p className="muted">Click a move to list only those loans.</p>
          </section>
        </div>
      )}
      {sc && sc.moved.length > 0 && (
        <LoanGrid<Moved>
          rows={rows}
          extra={EXTRA}
          storageKey="cmbs-radar.columns.scenario"
          visible={{ class: false }}
          empty="No loans."
          toolbar={<span className="muted">{only ? `${LABEL[only.split(">")[0] as Moved["class"]]} → ${LABEL[only.split(">")[1] as Moved["class"]]}: ` : ""}{rows.length.toLocaleString()} loans{sc.moved_total > sc.moved.length ? ` (first ${sc.moved.length} shown)` : ""}</span>}
        />
      )}
    </>
  );
}
