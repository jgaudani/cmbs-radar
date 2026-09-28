import { money, pct } from "../format";
import type { Scenario, Transition as T } from "../types";
import { Transition } from "./Badge";

interface Props {
  bps: number;
  onBps: (bps: number) => void;
  scenario: Scenario | null;
  loading: boolean;
  error: string;
  debtYieldBound: number; // listed loans sized by the rate-insensitive debt-yield test
  onRun: () => void;
  onClear: () => void;
  onShow: (t: T) => void;
}

export function ScenarioBar({ bps, onBps, scenario, loading, error, debtYieldBound, onRun, onClear, onShow }: Props) {
  return (
    <section className="scenario" aria-label="Rate scenario">
      <span>What if rates move</span>
      <select value={bps} onChange={(e) => onBps(Number(e.target.value))}>
        {[-100, -50, -25, 25, 50, 100].map((b) => <option key={b} value={b}>{b > 0 ? `+${b}` : `−${-b}`}bp</option>)}
      </select>
      <button onClick={onRun} disabled={loading}>Re-score</button>
      {scenario && <button className="link" onClick={onClear}>Clear scenario</button>}
      <div className="s-out">
        {loading && <span className="muted">Re-scoring every loan at {bps > 0 ? "+" : ""}{bps}bp…</span>}
        {error && <span className="err">{error}</span>}
        {scenario && !loading && (
          <>
            <b>{scenario.moved_total}</b> loans change class.
            <div className="trans">
              {scenario.transitions.map((t) => (
                <button key={`${t.from}-${t.to}`} className="tr" title="Show these loans" onClick={() => onShow(t)}>
                  <Transition from={t.from} to={t.to} /> <b>{t.loans}</b> loans · {money(t.whole_balance)}
                </button>
              ))}
            </div>
            <div className="note">
              {scenario.moved_total === 0 && debtYieldBound > 0
                ? `No class changes: ${debtYieldBound} of the listed loans are sized by the debt-yield test, which doesn't depend on rates.`
                : `Base rate ${pct(scenario.base_rate, 2)} (${scenario.assumptions_version}). Moved loans show old → new class in the table.`}
            </div>
          </>
        )}
      </div>
    </section>
  );
}
