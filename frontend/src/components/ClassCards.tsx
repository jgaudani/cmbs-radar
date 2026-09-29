import type { CSSProperties } from "react";
import { CLASSES, LABEL, money } from "../format";
import type { LoanClass, Summary } from "../types";

interface Props {
  summary: Summary | null;
  teams: Partial<Record<LoanClass, string>>;
  onPick: (c: LoanClass) => void;
}

/** One card per class with the Newmark team it routes to; a card opens its loans. */
export function ClassCards({ summary, teams, onPick }: Props) {
  return (
    <div className="kpis">
      {CLASSES.map((c) => {
        const t = summary?.by_class[c] ?? { loans: 0, whole_balance: 0, refi_gap_whole: 0 };
        return (
          <button key={c} className="kpi" style={{ "--c": `var(--${c})` } as CSSProperties} onClick={() => onPick(c)}>
            <div className="l">{LABEL[c]}</div>
            <div className="v">{summary ? money(t.whole_balance) : "—"}</div>
            <div className="n">
              {summary ? <>{t.loans.toLocaleString()} loans{t.refi_gap_whole ? ` · gap ${money(t.refi_gap_whole)}` : ""}</> : "Loading…"}
            </div>
            <div className="t">{teams[c] ?? ""}</div>
          </button>
        );
      })}
    </div>
  );
}
