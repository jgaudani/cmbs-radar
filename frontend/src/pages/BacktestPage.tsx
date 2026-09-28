import { api } from "../api";
import { Chart } from "../charts/Chart";
import { aucOption, troubleOption } from "../charts/options";
import { PageHeader } from "../components/Layout";
import { COLOR, pct } from "../format";
import { useLoad } from "../hooks";
import type { BacktestGroup, LoanClass } from "../types";

const METRICS: Record<string, string> = {
  refi_gap_pct: "Refi gap % (our score)",
  dscr_now: "DSCR today",
  debt_yield_now: "Debt yield today",
  dscr_at_securitized: "DSCR at securitization",
};

const OUTCOMES: Record<string, string> = {
  refinanced: "Paid off by refi date + grace",
  refinanced_late: "Paid off late (after special servicing or a missed balloon)",
  loss: "Liquidated with a loss",
  special_servicing: "Still in special servicing",
  maturity_default: "Matured and not paid off",
  extended: "Maturity extended or modified",
  past_maturity: "Still outstanding past maturity",
  unresolved: "Too recent to tell (excluded)",
};

const classColor = (g: BacktestGroup) => COLOR[g.label as LoanClass] ?? COLOR.none;
const bucketColor = (g: BacktestGroup) =>
  g.label.startsWith("surplus") ? COLOR.clean_refi : g.label === "gap 25%+" ? COLOR.distressed : COLOR.gap_refi;

/** Demo step 4: how loans scored 12-24 months before their refi date turned out. */
export function BacktestPage() {
  const { data: b, error } = useLoad("bt", () => api.backtest());
  const r = b?.report, c = b?.config;
  const h = (n: number) => 40 + 30 * n;

  return (
    <>
      <PageHeader title="Backtest" sub="Did the score see it coming? Loans scored 12–24 months before their refi date, using only what was known then." />
      {error && <p className="err">{error}</p>}
      {b && (!b.backtest_id || !r || !c) && <p className="muted">No backtest yet: run <code>uv run cmbs-backtest</code>.</p>}
      {r && c && (
        <>
          <section className="card">
            <p>
              <b>{r.samples.toLocaleString()}</b> loans, each scored {c.MinMonths}–{c.MaxMonths} months before its refi date with the
              data reported by then and that quarter's rates. <b>{pct(r.trouble_rate)}</b> did not pay off by refi date + {c.GraceMonths} months
              or took a loss.
              {!(c.MinMonths === 12 && c.MaxMonths === 24) && <span className="warn"> Short smoke-test window: not the standard 12–24 month backtest.</span>}
            </p>
          </section>
          <div className="two">
            <section className="card">
              <h3>Didn't pay off in time, by predicted class</h3>
              <Chart height={h(r.by_class.length) + 20} label="Trouble rate by predicted class"
                option={troubleOption([{ name: "All loans", groups: r.by_class, color: classColor }, { name: "Performing when scored", groups: r.by_class_performing, color: classColor }])} />
            </section>
            <section className="card">
              <h3>Ranking power <span className="muted">AUC; 0.5 = chance</span></h3>
              <Chart height={h(Object.keys(METRICS).length) + 20} label="AUC by metric" option={aucOption(METRICS, r.auc, r.auc_performing)} />
              <p className="muted">The refi gap ranks eventual trouble better than today's DSCR, the usual screen.</p>
            </section>
          </div>
          <div className="two">
            <section className="card">
              <h3>By predicted gap</h3>
              <Chart height={h(r.gap_buckets.length)} label="Trouble rate by predicted gap" option={troubleOption([{ name: "All loans", groups: r.gap_buckets, color: bucketColor }])} />
            </section>
            <section className="card">
              <h3>By refi year</h3>
              <Chart height={h(r.by_refi_year.length)} label="Trouble rate by refi year" option={troubleOption([{ name: "All loans", groups: r.by_refi_year }])} />
            </section>
          </div>
          <section className="card">
            <h3>Outcomes</h3>
            <table className="kv">
              <tbody>
                {Object.entries(r.by_outcome).sort((x, y) => y[1] - x[1]).map(([k, n]) => (
                  <tr key={k}><td>{OUTCOMES[k] ?? k}</td><td className="num">{n.toLocaleString()}</td></tr>
                ))}
              </tbody>
            </table>
            <p className="muted">
              Backtest {b!.backtest_id}, data through {b!.data_end ?? "?"}, rates {b!.rates_version} (approximate 10-year Treasury by quarter).
              Split loans counted once.
            </p>
          </section>
        </>
      )}
    </>
  );
}
