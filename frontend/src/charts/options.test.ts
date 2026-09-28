import { addMonths, quarterMonths } from "../format";
import type { Scenario } from "../types";
import { maturityWallOption, sankeyLinks } from "./options";

test("sankey keeps loans that stay in their class and adds the moves", () => {
  const s = {
    base: { gap_refi: { loans: 100, whole_balance: 0, refi_gap_whole: 0 }, distressed: { loans: 40, whole_balance: 0, refi_gap_whole: 0 },
      clean_refi: { loans: 10, whole_balance: 0, refi_gap_whole: 0 } },
    transitions: [{ from: "gap_refi", to: "clean_refi", loans: 81, whole_balance: 0 }, { from: "distressed", to: "gap_refi", loans: 40, whole_balance: 0 }],
  } as unknown as Scenario;
  expect(sankeyLinks(s)).toEqual([
    { source: "gap_refi:base", target: "gap_refi:scen", value: 19 },
    { source: "clean_refi:base", target: "clean_refi:scen", value: 10 }, // every distressed loan moved: no stay link
    { source: "gap_refi:base", target: "clean_refi:scen", value: 81 },
    { source: "distressed:base", target: "gap_refi:scen", value: 40 },
  ]);
});

test("maturity wall bars carry their quarter and class for drill-down", () => {
  const o = maturityWallOption([{ quarter: "2026Q3", by_class: { gap_refi: 5e8 } }]) as { series: { id: string; data: { value: number; quarter: string }[] }[] };
  const gap = o.series.find((x) => x.id === "gap_refi")!;
  expect(gap.data[0]).toEqual({ value: 5e8, quarter: "2026Q3" });
});

test("month and quarter helpers", () => {
  expect(addMonths("2026-09-11", 18)).toBe("2028-03");
  expect(addMonths("2026-01", -1)).toBe("2025-12");
  expect(quarterMonths("2027Q1")).toEqual(["2027-01", "2027-03"]);
  expect(quarterMonths("2026Q4")).toEqual(["2026-10", "2026-12"]);
});
