import { FILTERS, apiQuery, demoQuery, describe as chip, isActive, paging, paramsOf, toApi, toUi } from "./query";
import type { Meta } from "./types";

const meta = {
  data_as_of: "2026-09-11", metros: [{ id: "nyc", name: "New York", lat: 0, lon: 0 }],
  property_types: { OF: { label: "Office" }, RT: { label: "Retail" }, MF: { label: "Multifamily" } },
  flags: ["special_servicing"],
} as unknown as Meta;
const def = (key: string) => FILTERS.find((f) => f.key === key)!;

test("the api query keeps filter params only and adds paging", () => {
  const s = new URLSearchParams("class=gap_refi&max_dscr=1.25&page=3&size=25&cols=x&q=&refi_to=2028-03");
  expect(apiQuery(s, { limit: "25" })).toBe("class=gap_refi&max_dscr=1.25&refi_to=2028-03&limit=25");
  expect(paging(s)).toEqual({ page: 3, size: 25, offset: 50 });
  expect(paging(new URLSearchParams("page=-2&size=7"))).toEqual({ page: 1, size: 50, offset: 0 });
});

test("ranges show friendly units and store the api's", () => {
  expect(toApi("money", "12.5")).toBe("12500000");
  expect(toApi("pct", "7")).toBe("0.07");
  expect(toApi("ratio", "abc")).toBe("");
  expect(toUi("pct", "0.07")).toBe("7"); // not 7.000000000000001
  expect(toUi("money", "12500000")).toBe("12.5");
  expect(toUi("ratio", null)).toBe("");
});

test("chips describe active filters", () => {
  const s = new URLSearchParams("max_dscr=1.25&min_dy=0.08&max_dy=0.1&type=OF,RT,MF&refi_to=2028-03&changed=class&min_balance=5e7");
  expect(chip(def("dscr"), s, meta)).toBe("DSCR ≤ 1.25x");
  expect(chip(def("dy"), s, meta)).toBe("Debt yield 8.0% – 10%");
  expect(chip(def("balance"), s, meta)).toBe("Loan amount ≥ $50.0M");
  expect(chip(def("type"), s, meta)).toBe("Property type: Office, Retail +1");
  expect(chip(def("refi"), s, meta)).toBe("Refi by 2028-03");
  expect(chip(def("changed"), s, meta)).toBe("Class changed since last report");
  expect(isActive(def("gap"), s)).toBe(false);
  expect(paramsOf(def("refi"))).toContain("refi_from");
});

test("the demo preset is NYC office with a gap, refinancing within 18 months", () => {
  expect(demoQuery("2026-09-11")).toBe("metro=nyc&type=OF&class=distressed%2Cgap_refi&refi_to=2028-03");
});
