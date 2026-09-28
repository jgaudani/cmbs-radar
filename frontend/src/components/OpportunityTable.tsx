import { money, months, pct, place, ratio } from "../format";
import type { Moved, Opportunity } from "../types";
import { Badge, Transition } from "./Badge";

const SHOWN_FLAGS = ["special_servicing", "delinquent_60_plus", "tenant_rollover", "occupancy_declined", "split_loan", "annualized_ytd"];

interface Props {
  caption: string;
  rows: Opportunity[];
  moved: Map<string, Moved> | null; // scenario results by loan id
  selected: string | null;
  onSelect: (id: string) => void;
}

export function OpportunityTable({ caption, rows, moved, selected, onSelect }: Props) {
  return (
    <div className="table-wrap">
      <div className="table-head">{caption}</div>
      <table>
        <thead>
          <tr>
            <th>Property</th><th>Class</th><th className="num">Refi</th><th className="num">Whole loan</th>
            <th className="num">Gap</th><th className="num">DSCR</th><th className="num">DY</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={7} className="muted">No loans match these filters.</td></tr>
          )}
          {rows.map((o) => {
            const mv = moved?.get(o.id);
            const flags = o.flags.filter((f) => SHOWN_FLAGS.includes(f));
            return (
              <tr key={o.id} className={selected === o.id ? "sel" : ""} onClick={() => onSelect(o.id)}>
                <td>
                  <div className="pname">{o.name || "(unnamed)"}</div>
                  <div className="ploc">
                    {place(o.city, o.state)}
                    {o.property_type_label && ` · ${o.property_type_label}`}
                    {o.properties > 1 && ` · ${o.properties} properties`}
                    {o.notes > 1 && ` · ${o.notes} notes`}
                  </div>
                  {flags.length > 0 && (
                    <div className="flags">{flags.map((f) => <span key={f} className="flag">{f.replace(/_/g, " ")}</span>)}</div>
                  )}
                </td>
                <td>{mv ? <Transition from={mv.base_class} to={mv.class} /> : <Badge cls={o.class} />}</td>
                <td className="num">{o.refi_date ?? "—"}<div className="ploc">{months(o.months_to_refi)}</div></td>
                <td className="num">{money(o.whole_balance)}</td>
                <td className="num">
                  {money(mv ? mv.refi_gap_whole : o.refi_gap_whole)}
                  <div className="ploc">{pct(mv ? mv.refi_gap_pct : o.refi_gap_pct)}</div>
                </td>
                <td className="num">{ratio(o.dscr)}</td>
                <td className="num">{pct(o.debt_yield, 1)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
