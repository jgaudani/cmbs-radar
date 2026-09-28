import { PageHeader } from "../components/Layout";
import { CLASSES, LABEL, flagLabel, pct } from "../format";
import { useMeta } from "../meta";

const CLASS_RULE: Record<string, string> = {
  distressed: "In special servicing or 60+ days delinquent, or refi within the horizon with a gap at or above the distress threshold",
  gap_refi: "Refi within the horizon with an equity shortfall above the tolerance",
  clean_refi: "Refi within the horizon; a new loan covers the balance",
  watch: "Refi beyond the horizon, with deteriorating DSCR, occupancy or other risk flags",
};

/** How scoring works and what the data can't tell you. */
export function DataPage() {
  const { meta } = useMeta();
  if (!meta) return <PageHeader title="Method & data" sub="Loading…" />;
  const a = meta.assumptions;
  const types = Object.entries(meta.property_types).sort((x, y) => x[1].label.localeCompare(y[1].label));
  return (
    <>
      <PageHeader title="Method & data" sub={`Scoring run ${meta.run_id} on data through ${meta.data_as_of}, assumptions ${a.version}`} />
      <div className="two">
        <section className="card">
          <h3>How a loan is scored</h3>
          <ol className="reasons">
            <li>Effective refi date: the ARD if there is one, else maturity.</li>
            <li>Max new loan = the lower of cash flow ÷ target debt yield and the loan a target DSCR supports at today's rate.</li>
            <li>Refi gap = whole-loan balance − max new loan. Split loans are sized as one whole loan across trusts.</li>
            <li>DSCR is recomputed from reported cash flow and debt service, not taken from the filing.</li>
            <li>Classes route each loan to the Newmark team that can act on it.</li>
          </ol>
          <table className="kv">
            <tbody>
              {CLASSES.map((c) => (
                <tr key={c}><td><b>{LABEL[c]}</b> → {meta.teams[c]}</td><td>{CLASS_RULE[c]}</td></tr>
              ))}
              <tr><td>Horizon / gap tolerance / distress gap</td><td>{a.horizon_months} months · {pct(a.gap_tolerance)} · {pct(a.distress_gap)}</td></tr>
            </tbody>
          </table>
        </section>
        <section className="card">
          <h3>Sizing assumptions by property type</h3>
          <table className="kv num-cols">
            <thead><tr><th>Type</th><th className="num">Debt yield</th><th className="num">DSCR</th><th className="num">Rate</th><th className="num">Amort.</th></tr></thead>
            <tbody>
              {types.map(([code, t]) => (
                <tr key={code}>
                  <td>{t.label}</td><td className="num">{pct(t.debt_yield, 1)}</td><td className="num">{t.dscr.toFixed(2)}x</td>
                  <td className="num">{pct(t.rate, 2)}</td><td className="num">{t.amort_years ? `${t.amort_years} yr` : "IO"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted">Base rate {pct(a.base_rate, 2)}; scenarios shift every property type's rate by the same amount.</p>
        </section>
      </div>
      <div className="two">
        <section className="card">
          <h3>Risk flags in this run</h3>
          <div className="flags">{meta.flags.map((f) => <span key={f} className="flag">{flagLabel(f)}</span>)}</div>
        </section>
        <section className="card">
          <h3>Data limits</h3>
          <p>{meta.limits}</p>
          <p className="muted">
            Source: SEC EDGAR Form ABS-EE, exhibit EX-102 (loan-level CMBS data, monthly since November 2016). The same pipeline can
            ingest a lender's own servicing portfolio and CRM data.
          </p>
        </section>
      </div>
    </>
  );
}
