import type { CSSProperties } from "react";
import { LABEL } from "../format";
import type { LoanClass } from "../types";

export function Badge({ cls }: { cls: LoanClass }) {
  return (
    <span className="badge" style={{ "--c": `var(--${cls})` } as CSSProperties}>
      {LABEL[cls] ?? cls}
    </span>
  );
}

export function Transition({ from, to }: { from: LoanClass; to: LoanClass }) {
  return (
    <>
      <Badge cls={from} />
      <span className="arrow">→</span>
      <Badge cls={to} />
    </>
  );
}
