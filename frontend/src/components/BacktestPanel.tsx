import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { api } from "../api";
import { LABEL, pct } from "../format";
import type { Backtest, BacktestGroup, LoanClass } from "../types";

const METRICS: Record<string, string> = {
  refi_gap_pct: "Refi gap % (our score)",
  dscr_now: "DSCR today",
  debt_yield_now: "Debt yield today",
  dscr_at_securitized: "DSCR at securitization",
};

function Bars({ groups, color }: { groups: BacktestGroup[]; color: (g: BacktestGroup) => string }) {
  return (
    <>
      {groups.map((g) => (
        <div key={g.label} className="bar" style={{ "--c": color(g) } as CSSProperties}>
          <span>{LABEL[g.label as LoanClass] ?? g.label}</span>
          <div className="track"><div className="fill" style={{ width: `${(g.trouble_rate * 100).toFixed(1)}%` }} /></div>
          <span className="pct">{pct(g.trouble_rate)} of {g.loans}</span>
        </div>
      ))}
    </>
  );
}

const bucketColor = (g: BacktestGroup) =>
  g.label.startsWith("surplus") ? "var(--clean_refi)" : g.label === "gap 25%+" ? "var(--distressed)" : "var(--gap_refi)";

/** Demo step 4: how loans scored 12-24 months before their refi date turned out. */
export function BacktestPanel() {
  const [b, setB] = useState<Backtest | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.backtest().then(setB).catch((e: Error) => setError(e.message)); }, []);

  let body: ReactNode = <span className="muted">Loading…</span>;
  if (error) body = <span className="err">{error}</span>;
  else if (b && (!b.backtest_id || !b.report || !b.config)) body = <span className="muted">No backtest yet: run `uv run cmbs-backtest`.</span>;
  else if (b?.report && b.config) {
    const r = b.report, c = b.config;
    const standard = c.MinMonths === 12 && c.MaxMonths === 24;
    body = (
      <>
        <p>
          {r.samples.toLocaleString()} loans, each scored {c.MinMonths}–{c.MaxMonths} months before its refi date using only data
          reported by then and that quarter's rates. <b>{pct(r.trouble_rate)}</b> did not pay off by refi date + {c.GraceMonths}{" "}
          months (still in special servicing or default, extended, still outstanding) or took a loss.{" "}
          {r.by_outcome.refinanced_late ? `${r.by_outcome.refinanced_late} paid off late (after a special-servicing transfer or missed balloon) and count as refinanced.` : ""}
          {!standard && <span className="warn"> Short smoke-test window: not the standard 12–24 month backtest.</span>}
        </p>
        <div className="bt-grid">
          <div>
            <h4>Didn't pay off in time, by predicted class</h4>
            <Bars groups={r.by_class} color={(g) => `var(--${g.label})`} />
            <h4 style={{ marginTop: 12 }}>Loans performing when scored</h4>
            <Bars groups={r.by_class_performing} color={(g) => `var(--${g.label})`} />
          </div>
          <div>
            <h4>Ranking power (AUC; 0.5 = chance)</h4>
            <table className="auc">
              <tbody>
                <tr><td /><td className="num muted">all</td><td className="num muted">performing</td></tr>
                {Object.keys(METRICS).filter((k) => k in r.auc).map((k) => (
                  <tr key={k}>
                    <td>{METRICS[k]}</td>
                    <td className="num">{r.auc[k].toFixed(2)}</td>
                    <td className="num">{r.auc_performing[k]?.toFixed(2) ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h4 style={{ marginTop: 12 }}>By predicted gap</h4>
            <Bars groups={r.gap_buckets} color={bucketColor} />
          </div>
          <div>
            <h4>By refi year</h4>
            <Bars groups={r.by_refi_year} color={() => "var(--accent)"} />
            <p className="muted" style={{ fontSize: 12 }}>
              Backtest {b.backtest_id}, data through {b.data_end ?? "?"}, rates {b.rates_version} (approximate 10-year Treasury by
              quarter). Split loans counted once.
            </p>
          </div>
        </div>
      </>
    );
  }
  return (
    <section className="bt" aria-label="Backtest">
      <h2>Backtest: did the score see it coming?</h2>
      {body}
    </section>
  );
}
