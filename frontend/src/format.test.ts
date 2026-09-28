import { money, months, pct, place, ratio } from "./format";

test("money", () => {
  expect(money(1_080_000_000)).toBe("$1.08B");
  expect(money(-190.8e6)).toBe("−$190.8M");
  expect(money(45_000)).toBe("$45K");
  expect(money(null)).toBe("—");
});

test("percent, ratio, months, place", () => {
  expect(pct(0.415)).toBe("42%");
  expect(pct(0.0425, 2)).toBe("4.25%");
  expect(ratio(1.7712)).toBe("1.77x");
  expect(months(-20)).toBe("20 mo past");
  expect(months(8)).toBe("8 mo");
  expect(place("New York", "NY")).toBe("New York, NY");
  expect(place("", "NY")).toBe("NY");
});
