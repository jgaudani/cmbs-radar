import { useWatchlist } from "../watchlist";

/** Star toggle; `compact` for grid rows. */
export function WatchButton({ loan, compact }: { loan: { id: string; name: string }; compact?: boolean }) {
  const { has, toggle } = useWatchlist();
  const on = has(loan.id);
  const label = on ? "Remove from watchlist" : "Add to watchlist";
  return (
    <button
      className={`watch ${on ? "on" : ""} ${compact ? "compact" : ""}`}
      aria-pressed={on}
      aria-label={compact ? `${label}: ${loan.name}` : undefined}
      title={label}
      onClick={(e) => {
        e.stopPropagation();
        toggle(loan);
      }}
    >
      <span aria-hidden="true">{on ? "★" : "☆"}</span>
      {!compact && (on ? " Watching" : " Watch")}
    </button>
  );
}
