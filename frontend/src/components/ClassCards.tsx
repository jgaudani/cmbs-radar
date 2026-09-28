import type { CSSProperties } from "react";
import { CLASSES, LABEL, money } from "../format";
import type { LoanClass, Summary } from "../types";

interface Props {
  summary: Summary | null;
  selected: LoanClass[];
  teams: Partial<Record<LoanClass, string>>;
  onToggle: (c: LoanClass) => void;
}

/** One card per class with its routed Newmark team; clicking filters the list. */
export function ClassCards({ summary, selected, teams, onToggle }: Props) {
  return (
    <div className="kpis">
      {CLASSES.map((c) => {
        const t = summary?.by_class[c] ?? { loans: 0, whole_balance: 0, refi_gap_whole: 0 };
        const on = selected.includes(c);
        return (
          <div
            key={c}
            className={`kpi ${on ? "on" : ""}`}
            style={{ "--c": `var(--${c})` } as CSSProperties}
            role="button"
            tabIndex={0}
            aria-pressed={on}
            onClick={() => onToggle(c)}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onToggle(c))}
          >
            <div className="l">{LABEL[c]}</div>
            <div className="v">{money(t.whole_balance)}</div>
            <div className="n">
              {t.loans.toLocaleString()} loans{t.refi_gap_whole ? ` · gap ${money(t.refi_gap_whole)}` : ""}
            </div>
            <div className="t">{teams[c] ?? ""}</div>
          </div>
        );
      })}
    </div>
  );
}
