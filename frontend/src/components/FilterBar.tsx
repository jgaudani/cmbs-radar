import type { Filters, Meta } from "../types";

interface Props {
  filters: Filters;
  meta: Meta | null;
  onChange: (patch: Partial<Filters>) => void;
  onReset: () => void;
}

export function FilterBar({ filters, meta, onChange, onReset }: Props) {
  const types = Object.entries(meta?.property_types ?? {}).sort((a, b) => a[1].label.localeCompare(b[1].label));
  return (
    <section className="filters" aria-label="Filters">
      <label>
        Metro
        <select value={filters.metro} onChange={(e) => onChange({ metro: e.target.value })}>
          <option value="">All</option>
          {meta?.metros.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
        </select>
      </label>
      <label>
        Property
        <select value={filters.type} onChange={(e) => onChange({ type: e.target.value })}>
          <option value="">All</option>
          {types.map(([code, t]) => <option key={code} value={code}>{t.label}</option>)}
        </select>
      </label>
      <label>
        Refi within
        <select value={filters.months} onChange={(e) => onChange({ months: e.target.value })}>
          <option value="">Any time</option>
          {["6", "12", "18", "24", "36"].map((m) => <option key={m} value={m}>{m} months</option>)}
        </select>
      </label>
      <label className="grow">
        Search
        <input type="search" placeholder="Property, city or trust" value={filters.q} onChange={(e) => onChange({ q: e.target.value })} />
      </label>
      <label>
        Sort
        <select value={filters.sort} onChange={(e) => onChange({ sort: e.target.value as Filters["sort"] })}>
          <option value="gap">Largest gap ($)</option>
          <option value="gap_pct">Largest gap (%)</option>
          <option value="maturity">Soonest refi</option>
          <option value="balance">Largest loan</option>
        </select>
      </label>
      <button className="link" onClick={onReset}>Reset</button>
    </section>
  );
}
