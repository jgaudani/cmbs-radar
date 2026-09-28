import { LABEL, money } from "../format";
import type { LoanClass, Summary } from "../types";

const STACK: LoanClass[] = ["clean_refi", "gap_refi", "distressed", "watch"];

/** Whole-loan balance by refi quarter, stacked by class. */
export function MaturityWall({ wall }: { wall: Summary["maturity_wall"] }) {
  const W = 560, H = 150, pad = 18;
  const bw = (W - 10) / Math.max(wall.length, 1);
  const totals = wall.map((q) => STACK.reduce((a, c) => a + (q.by_class[c] ?? 0), 0));
  const max = Math.max(1, ...totals);
  return (
    <figure className="wall">
      <figcaption>Maturity wall: whole-loan balance by refi quarter</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-label="Maturity wall">
        {wall.map((q, i) => {
          let y = H - pad;
          const x = 5 + i * bw;
          return (
            <g key={q.quarter}>
              {STACK.map((c) => {
                const v = q.by_class[c] ?? 0;
                const h = (v / max) * (H - pad - 12);
                if (h <= 0) return null;
                y -= h;
                return (
                  <rect key={c} x={x + 3} y={y} width={bw - 6} height={h} fill={`var(--${c})`}>
                    <title>{`${q.quarter} ${LABEL[c]}: ${money(v)}`}</title>
                  </rect>
                );
              })}
              <text x={x + bw / 2} y={H - 4} textAnchor="middle">{q.quarter.replace("20", "'")}</text>
              {totals[i] > 0 && (
                <text x={x + bw / 2} y={Math.max(10, y - 3)} textAnchor="middle">{money(totals[i]).replace(".00", "")}</text>
              )}
            </g>
          );
        })}
      </svg>
    </figure>
  );
}
