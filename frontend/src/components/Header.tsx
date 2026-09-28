import { pct } from "../format";
import type { Meta } from "../types";

export function Header({ meta, onPreset }: { meta: Meta | null; onPreset: () => void }) {
  return (
    <header className="top">
      <div className="brand">
        <span className="logo" aria-hidden="true" />
        <div>
          <h1>CMBS Radar</h1>
          <p className="sub">Refinance opportunities in public CMBS loan data, routed to the team that can act</p>
        </div>
      </div>
      {meta && (
        <div className="meta">
          Data through <b>{meta.data_as_of}</b> · scoring run {meta.run_id} · assumptions {meta.assumptions.version}, base
          rate {pct(meta.assumptions.base_rate, 2)}
        </div>
      )}
      <button className="preset" onClick={onPreset} title="Office loans in the NYC metro maturing within 18 months with a refi gap">
        Demo: NYC office, 18 mo, gap
      </button>
    </header>
  );
}
