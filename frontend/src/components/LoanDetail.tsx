import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import { Chart } from "../charts/Chart";
import { historyOption } from "../charts/options";
import { LABEL, money, pct, place, ratio } from "../format";
import { Markdown } from "../markdown";
import type { Brief, Detail, LoanClass } from "../types";
import { Badge } from "./Badge";

const SOURCE: Record<string, string> = {
  t12: "full-year statement",
  ytd_annualized: "partial-year statement, annualized",
  underwriting: "underwriting at securitization",
};

/** Everything about one loan: sizing, brief, reasons, history, collateral. */
export function LoanDetail({ d }: { d: Detail }) {
  const z = d.sizing;
  const props = d.properties.filter((p) => !p.portfolio_totals);
  const grid: [string, ReactNode][] = [
    ["Whole loan", `${money(d.whole_balance)}${z.whole_loan_is_estimate ? " (est.)" : ""}`],
    ["Max new loan", money(d.max_new_loan)],
    ["Refi gap", `${money(d.refi_gap_whole)} · ${pct(d.refi_gap_pct)}`],
    ["Refi date", `${d.refi_date ?? "—"} (${z.refi_date_source === "ard" ? "ARD" : "maturity"})`],
    ["DSCR", <>{ratio(d.dscr)} <span className="muted">vs {ratio(z.dscr_at_securitization)} at sec.</span></>],
    ["Debt yield", pct(d.debt_yield, 1)],
    ["Occupancy", <>{pct(d.occupancy)} <span className="muted">vs {pct(z.occupancy_at_securitization)}</span></>],
    ["This trust's note", money(d.balance)],
    ["Current rate", pct(z.current_rate, 2)],
  ];
  return (
    <>
      <div className="team">
        <Badge cls={d.class} /> {d.team && <>routed to <b>{d.team}</b></>}
        {d.prev_class && d.prev_class !== d.class && <span className="muted"> · was {LABEL[d.prev_class as LoanClass] ?? d.prev_class} last report</span>}
      </div>
      <div className="facts">
        {grid.map(([k, v]) => (
          <div key={k}><div className="k">{k}</div><div className="v">{v}</div></div>
        ))}
      </div>

      <div className="two">
        <section className="card">
          <h3>Brief</h3>
          <BriefPanel id={d.id} />
        </section>
        <section className="card">
          <h3>Why this class</h3>
          <ul className="reasons">{d.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
          {d.changes && d.changes.length > 0 && (
            <>
              <h3>Changed since last report</h3>
              <ul className="reasons">{d.changes.map((c) => <li key={c}>{c.replace(/_/g, " ")}</li>)}</ul>
            </>
          )}
        </section>
      </div>

      <section className="card">
        <h3>Balance, DSCR and occupancy by report</h3>
        {d.history.length < 2 ? <p className="muted">Not enough history.</p> : <Chart option={historyOption(d.history)} height={240} label="Loan history" />}
      </section>

      <div className="two">
        <section className="card">
          <h3>Sizing inputs</h3>
          <table className="kv">
            <tbody>
              <tr>
                <td>Annual cash flow ({z.cash_flow_basis})</td>
                <td>{money(z.annual_cash_flow)} · {SOURCE[z.cash_flow_source] ?? "—"}{z.financials_end && ` ending ${z.financials_end.slice(0, 10)}`}</td>
              </tr>
              <tr>
                <td>Market rate / target DSCR / debt yield</td>
                <td>{pct(z.market_rate, 2)} · {z.target_dscr.toFixed(2)}x · {pct(z.target_debt_yield, 1)} · {z.amort_years ? `${z.amort_years}-yr amort.` : "IO"}</td>
              </tr>
              <tr><td>Max loan by debt yield / by DSCR</td><td>{money(z.max_loan_by_debt_yield)} / {money(z.max_loan_by_dscr)}</td></tr>
              <tr><td>Whole-loan debt service</td><td>{money(z.annual_debt_service_whole_loan)}</td></tr>
              {z.whole_loan_factor > 1 && (
                <tr>
                  <td>Split loan</td>
                  <td>note ≈ 1/{z.whole_loan_factor.toFixed(1)} of whole; this trust's gap share {money(z.refi_gap_this_trust_share)}</td>
                </tr>
              )}
              {z.prepayment_open_date && <tr><td>Prepayment open</td><td>{z.prepayment_open_date.slice(0, 10)}</td></tr>}
            </tbody>
          </table>
          {d.other_notes && d.other_notes.length > 0 && (
            <>
              <h3>Other notes of this loan ({d.other_notes.length})</h3>
              <table className="kv">
                <tbody>
                  {d.other_notes.map((n) => (
                    <tr key={`${n.trust_cik}/${n.asset_number}`}><td>{n.trust_name}</td><td>{money(n.balance)}</td></tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </section>
        <section className="card">
          <h3>Collateral ({props.length})</h3>
          <table className="kv">
            <tbody>
              {props.slice(0, 12).map((p) => (
                <tr key={p.seq}>
                  <td>
                    {p.name}
                    <div className="ploc">{place(p.city, p.state)}{p.year_built ? ` · built ${p.year_built}` : ""}</div>
                  </td>
                  <td>
                    {p.net_rentable_sqft ? `${Math.round(p.net_rentable_sqft).toLocaleString()} sf` : p.units ? `${p.units} units` : ""}
                    {p.occupancy != null && ` · ${pct(p.occupancy)} occ.`}
                    {p.largest_tenant && (
                      <div className="ploc">
                        Largest tenant {p.largest_tenant}
                        {p.largest_tenant_lease_expires && `, lease to ${p.largest_tenant_lease_expires.slice(0, 10)}`}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
              {props.length > 12 && <tr><td className="muted">…and {props.length - 12} more</td><td /></tr>}
            </tbody>
          </table>
        </section>
      </div>
      <p className="muted">{d.data_limits}</p>
    </>
  );
}

function BriefPanel({ id }: { id: string }) {
  const [brief, setBrief] = useState<Brief | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");
  const [error, setError] = useState("");
  useEffect(() => { setBrief(null); setState("idle"); }, [id]);

  const load = (refresh: boolean) => {
    setState("loading");
    api.brief(id, refresh)
      .then((b) => { setBrief(b); setState("idle"); })
      .catch((e: Error) => { setError(e.message); setState("error"); });
  };

  return (
    <div className="brief">
      {state === "loading" && <p className="muted">Writing brief…</p>}
      {state === "error" && (
        <>
          <p className="err">{error}</p>
          <button onClick={() => load(false)}>Try again</button>
        </>
      )}
      {state === "idle" && !brief && (
        <>
          <button onClick={() => load(false)}>Write brief</button>{" "}
          <span className="muted">Claude writes it from the facts below; numbers come from scoring.</span>
        </>
      )}
      {state === "idle" && brief && (
        <>
          <Markdown text={brief.brief} />
          <div className="src">
            {brief.model} · {brief.cached ? "cached" : "new"} for scoring run {brief.run_id} · {brief.prompt_version}{" "}
            <button className="link" onClick={() => load(true)}>Regenerate</button>
          </div>
        </>
      )}
    </div>
  );
}
