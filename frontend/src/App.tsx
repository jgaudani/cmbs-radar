import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { BacktestPanel } from "./components/BacktestPanel";
import { ClassCards } from "./components/ClassCards";
import { DetailDrawer } from "./components/DetailDrawer";
import { FilterBar } from "./components/FilterBar";
import { Header } from "./components/Header";
import { MaturityWall } from "./components/MaturityWall";
import { OpportunityMap } from "./components/OpportunityMap";
import { OpportunityTable } from "./components/OpportunityTable";
import { ScenarioBar } from "./components/ScenarioBar";
import { LABEL } from "./format";
import type { Filters, LoanClass, MapPoint, Meta, Moved, OpportunityList, Scenario, Summary, Transition } from "./types";

export const DEFAULT_FILTERS: Filters = {
  metro: "", type: "", months: "", q: "", sort: "gap", classes: ["distressed", "gap_refi", "clean_refi"],
};

// Demo step 2: office loans in the NYC metro maturing within 18 months with a gap.
const PRESET: Filters = { ...DEFAULT_FILTERS, metro: "nyc", type: "OF", months: "18", classes: ["distressed", "gap_refi"] };

export function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [list, setList] = useState<OpportunityList | null>(null);
  const [points, setPoints] = useState<MapPoint[]>([]);
  const [loadError, setLoadError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);

  const [bps, setBps] = useState(-50);
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [scenarioLoading, setScenarioLoading] = useState(false);
  const [scenarioError, setScenarioError] = useState("");
  const [shown, setShown] = useState<{ t: Transition; rows: Moved[] } | null>(null); // a transition's loans

  useEffect(() => { api.meta().then(setMeta).catch((e: Error) => setLoadError(e.message)); }, []);

  // Search is debounced; everything else reloads immediately.
  const [q, setQ] = useState(filters.q);
  useEffect(() => {
    const t = setTimeout(() => setQ(filters.q), 250);
    return () => clearTimeout(t);
  }, [filters.q]);
  const effective = useMemo(() => ({ ...filters, q }), [filters, q]);

  useEffect(() => {
    let live = true;
    Promise.all([api.summary(effective), api.opportunities(effective), api.map(effective)])
      .then(([s, l, p]) => {
        if (!live) return;
        setSummary(s); setList(l); setPoints(p); setLoadError(""); setShown(null);
      })
      .catch((e: Error) => live && setLoadError(e.message));
    return () => { live = false; };
  }, [effective]);

  const runScenario = useCallback(() => {
    setScenarioLoading(true);
    setScenarioError("");
    setShown(null);
    api.scenario(bps, effective)
      .then(setScenario)
      .catch((e: Error) => setScenarioError(e.message))
      .finally(() => setScenarioLoading(false));
  }, [bps, effective]);

  // Keep an open scenario in step with the filters.
  useEffect(() => { if (scenario) runScenario(); }, [effective]); // eslint-disable-line react-hooks/exhaustive-deps

  const patch = (p: Partial<Filters>) => setFilters((f) => ({ ...f, ...p }));
  const toggleClass = (c: LoanClass) =>
    patch({ classes: filters.classes.includes(c) ? filters.classes.filter((x) => x !== c) : [...filters.classes, c] });

  const moved = useMemo(() => (scenario ? new Map(scenario.moved.map((m) => [m.id, m])) : null), [scenario]);
  const rows = shown ? shown.rows : list?.opportunities ?? [];
  const caption = shown
    ? `${shown.rows.length} loans move ${LABEL[shown.t.from]} → ${LABEL[shown.t.to]} at ${bps > 0 ? "+" : ""}${bps}bp · largest gap first`
    : list
      ? `${list.total.toLocaleString()} loans${list.total > list.opportunities.length ? ` (top ${list.opportunities.length} shown)` : ""} · one row per whole loan`
      : "Loading…";
  const debtYieldBound = (list?.opportunities ?? []).filter((o) => o.binding_constraint === "debt_yield").length;

  return (
    <>
      <Header meta={meta} onPreset={() => setFilters(PRESET)} />
      {loadError && <p className="err" style={{ padding: "8px 24px" }}>Couldn't load data: {loadError}</p>}
      <section className="strip">
        <ClassCards summary={summary} selected={filters.classes} teams={meta?.teams ?? {}} onToggle={toggleClass} />
        <MaturityWall wall={summary?.maturity_wall ?? []} />
      </section>
      <FilterBar filters={filters} meta={meta} onChange={patch} onReset={() => setFilters(DEFAULT_FILTERS)} />
      <ScenarioBar
        bps={bps}
        onBps={setBps}
        scenario={scenario}
        loading={scenarioLoading}
        error={scenarioError}
        debtYieldBound={debtYieldBound}
        onRun={runScenario}
        onClear={() => { setScenario(null); setShown(null); }}
        onShow={(t) => setShown({ t, rows: scenario?.moved.filter((m) => m.base_class === t.from && m.class === t.to) ?? [] })}
      />
      <main className="work">
        <OpportunityMap
          points={points}
          metro={meta?.metros.find((m) => m.id === filters.metro)}
          onPickMetro={(metro) => patch({ metro })}
        />
        <OpportunityTable caption={caption} rows={rows} moved={moved} selected={selected} onSelect={setSelected} />
      </main>
      <BacktestPanel />
      {selected && <DetailDrawer id={selected} onClose={() => setSelected(null)} />}
      <footer className="foot">
        {meta?.limits} Whole-loan balances for loans split across trusts are estimates. Map points are metro or state centers.
      </footer>
    </>
  );
}
