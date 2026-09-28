// ECharts options, as pure functions of api data (tested without a canvas).
import { ACCENT, COLOR, LABEL, MUTED, money, pct } from "../format";
import type { BacktestGroup, Detail, LoanClass, Scenario, Summary } from "../types";
import type { ChartOption } from "./Chart";

const STACK: LoanClass[] = ["clean_refi", "gap_refi", "distressed", "watch"];
const AXIS = { axisLine: { lineStyle: { color: "#c9d0d8" } }, axisLabel: { color: MUTED, fontSize: 11 } };
const TOOLTIP = { confine: true, textStyle: { fontSize: 12 } };

/** Whole-loan balance by refi quarter, stacked by class. Click: quarter (name) and class (seriesId). */
export function maturityWallOption(wall: Summary["maturity_wall"]): ChartOption {
  return {
    grid: { left: 8, right: 8, top: 28, bottom: 4, containLabel: true },
    legend: { top: 0, left: 0, itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 11, color: MUTED } },
    tooltip: {
      ...TOOLTIP, trigger: "axis", axisPointer: { type: "shadow" },
      valueFormatter: (v: unknown) => money(Number(v)),
    },
    xAxis: { type: "category", data: wall.map((q) => q.quarter.replace("20", "'")), ...AXIS },
    yAxis: { type: "value", ...AXIS, splitLine: { lineStyle: { color: "#eef1f4" } }, axisLabel: { ...AXIS.axisLabel, formatter: (v: number) => money(v) } },
    series: STACK.map((c) => ({
      id: c, name: LABEL[c], type: "bar", stack: "wall", barMaxWidth: 36, itemStyle: { color: COLOR[c] },
      emphasis: { focus: "series" },
      data: wall.map((q) => ({ value: q.by_class[c] ?? 0, quarter: q.quarter })),
    })),
  };
}

/** Class flows from the base case to the rate scenario, by number of loans. */
export function sankeyLinks(s: Scenario): { source: string; target: string; value: number }[] {
  const out = new Map<LoanClass, number>();
  for (const t of s.transitions) out.set(t.from, (out.get(t.from) ?? 0) + t.loans);
  const stay = (Object.entries(s.base) as [LoanClass, { loans: number }][])
    .map(([c, t]) => ({ source: `${c}:base`, target: `${c}:scen`, value: t.loans - (out.get(c) ?? 0) }))
    .filter((l) => l.value > 0);
  const moved = s.transitions.map((t) => ({ source: `${t.from}:base`, target: `${t.to}:scen`, value: t.loans }));
  return [...stay, ...moved];
}

export function sankeyOption(s: Scenario): ChartOption {
  const links = sankeyLinks(s);
  const names = [...new Set(links.flatMap((l) => [l.source, l.target]))];
  const cls = (n: string) => n.split(":")[0] as LoanClass;
  return {
    tooltip: {
      ...TOOLTIP,
      formatter: (p: { dataType: string; data: { source?: string; target?: string; value?: number }; name: string }) =>
        p.dataType === "edge"
          ? `${LABEL[cls(p.data.source!)]} → ${LABEL[cls(p.data.target!)]}: ${p.data.value!.toLocaleString()} loans`
          : LABEL[cls(p.name)],
    },
    series: [{
      type: "sankey", left: 8, right: 110, top: 8, bottom: 8, nodeWidth: 14, nodeGap: 10, draggable: false,
      emphasis: { focus: "adjacency" },
      data: names.map((n) => ({
        name: n, itemStyle: { color: COLOR[cls(n)] ?? MUTED },
        label: { formatter: () => LABEL[cls(n)] ?? cls(n), color: "#14181f", fontSize: 12 },
      })),
      links: links.map((l) => ({ ...l, lineStyle: { color: l.source.split(":")[0] === l.target.split(":")[0] ? "#dfe4ea" : COLOR[cls(l.target)], opacity: 0.55 } })),
    }],
  };
}

/** Share of loans that didn't pay off in time, per group; one bar series per list. */
export function troubleOption(series: { name: string; groups: BacktestGroup[]; color?: (g: BacktestGroup) => string }[]): ChartOption {
  const labels = series[0]?.groups.map((g) => g.label) ?? [];
  return {
    grid: { left: 8, right: 48, top: series.length > 1 ? 26 : 6, bottom: 4, containLabel: true },
    legend: series.length > 1 ? { top: 0, left: 0, itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 11, color: MUTED } } : undefined,
    tooltip: {
      ...TOOLTIP, trigger: "axis", axisPointer: { type: "shadow" },
      formatter: (ps: { seriesName: string; dataIndex: number; seriesIndex: number }[]) =>
        ps.map((p) => {
          const g = series[p.seriesIndex].groups[p.dataIndex];
          return g ? `${p.seriesName}: <b>${pct(g.trouble_rate)}</b> of ${g.loans.toLocaleString()} loans (${money(g.whole_balance)})` : "";
        }).join("<br/>"),
    },
    xAxis: { type: "value", max: 1, ...AXIS, splitLine: { lineStyle: { color: "#eef1f4" } }, axisLabel: { ...AXIS.axisLabel, formatter: (v: number) => pct(v) } },
    yAxis: { type: "category", inverse: true, data: labels.map((l) => LABEL[l as LoanClass] ?? l), ...AXIS },
    series: series.map((s, i) => ({
      name: s.name, type: "bar", barMaxWidth: 16, barGap: "20%",
      itemStyle: { color: i === 0 ? ACCENT : "#9fb4d3" },
      label: { show: true, position: "right", fontSize: 11, color: MUTED, formatter: (p: { value: number }) => pct(p.value) },
      data: s.groups.map((g) => ({ value: g.trouble_rate, itemStyle: s.color ? { color: s.color(g), opacity: i === 0 ? 1 : 0.5 } : undefined })),
    })),
  };
}

/** Ranking power of each metric; 0.5 is chance. */
export function aucOption(metrics: Record<string, string>, all: Record<string, number>, performing: Record<string, number>): ChartOption {
  const keys = Object.keys(metrics).filter((k) => k in all);
  const lo = Math.min(0.4, ...keys.flatMap((k) => [all[k], performing[k] ?? 1]));
  return {
    grid: { left: 8, right: 40, top: 26, bottom: 4, containLabel: true },
    legend: { top: 0, left: 0, itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 11, color: MUTED } },
    tooltip: { ...TOOLTIP, trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v: unknown) => Number(v).toFixed(2) },
    xAxis: { type: "value", min: Math.floor(lo * 10) / 10, max: 0.8, ...AXIS, splitLine: { lineStyle: { color: "#eef1f4" } } },
    yAxis: { type: "category", inverse: true, data: keys.map((k) => metrics[k]), ...AXIS },
    series: [
      {
        name: "All loans", type: "bar", barMaxWidth: 14, itemStyle: { color: ACCENT },
        label: { show: true, position: "right", fontSize: 11, color: MUTED, formatter: (p: { value: number }) => p.value.toFixed(2) },
        data: keys.map((k) => all[k]),
        markLine: { symbol: "none", silent: true, lineStyle: { color: MUTED, type: "dashed" }, label: { formatter: "chance", color: MUTED, fontSize: 10 }, data: [{ xAxis: 0.5 }] },
      },
      { name: "Performing when scored", type: "bar", barMaxWidth: 14, itemStyle: { color: "#9fb4d3" }, data: keys.map((k) => performing[k] ?? null) },
    ],
  };
}

/** A loan's balance (left axis) and reported DSCR and occupancy (right axes) by report. */
export function historyOption(history: Detail["history"]): ChartOption {
  const h = history.filter((x) => x.balance != null || x.reported_dscr != null);
  return {
    grid: { left: 8, right: 8, top: 28, bottom: 4, containLabel: true },
    legend: { top: 0, left: 0, itemWidth: 12, itemHeight: 8, textStyle: { fontSize: 11, color: MUTED } },
    tooltip: {
      ...TOOLTIP, trigger: "axis",
      formatter: (ps: { dataIndex: number }[]) => {
        const x = h[ps[0]?.dataIndex ?? 0];
        if (!x) return "";
        return [`<b>${x.period}</b>`, `Balance ${money(x.balance)}`, x.reported_dscr != null ? `Reported DSCR ${x.reported_dscr.toFixed(2)}x` : "",
          x.occupancy != null ? `Occupancy ${pct(x.occupancy)}` : "", x.payment_status ? `Payment status ${x.payment_status}` : ""].filter(Boolean).join("<br/>");
      },
    },
    xAxis: { type: "category", data: h.map((x) => x.period.slice(0, 7)), ...AXIS },
    yAxis: [
      { type: "value", scale: true, ...AXIS, splitLine: { lineStyle: { color: "#eef1f4" } }, axisLabel: { ...AXIS.axisLabel, formatter: (v: number) => money(v) } },
      { type: "value", scale: true, ...AXIS, splitLine: { show: false }, axisLabel: { ...AXIS.axisLabel, formatter: (v: number) => `${v.toFixed(1)}x` } },
      { type: "value", min: 0, max: 1, show: false },
    ],
    series: [
      { name: "Balance", type: "line", yAxisIndex: 0, showSymbol: false, step: "end", lineStyle: { width: 2 }, itemStyle: { color: ACCENT }, data: h.map((x) => x.balance) },
      { name: "Reported DSCR", type: "line", yAxisIndex: 1, showSymbol: false, connectNulls: true, itemStyle: { color: COLOR.gap_refi }, data: h.map((x) => x.reported_dscr ?? null) },
      { name: "Occupancy", type: "line", yAxisIndex: 2, showSymbol: false, connectNulls: true, lineStyle: { type: "dashed" }, itemStyle: { color: COLOR.clean_refi }, data: h.map((x) => x.occupancy ?? null) },
    ],
  };
}
