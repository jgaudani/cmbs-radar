import { Link, useSearchParams } from "react-router";
import { api } from "../api";
import { PageHeader } from "../components/Layout";
import { LoanGrid } from "../components/LoanGrid";
import { ShareButton } from "../components/ShareButton";
import { money } from "../format";
import { useLoad } from "../hooks";
import { shareWatchlistUrl, useWatchlist } from "../watchlist";

/** The user's watchlist (this browser), or a shared one opened from a link (?ids=). */
export function WatchlistPage() {
  const [search] = useSearchParams();
  const { items, add, remove } = useWatchlist();
  const shared = search.get("ids")?.split(",").filter(Boolean) ?? null;
  const ids = shared ?? items.map((w) => w.id);
  const key = [...ids].sort().join(",");
  const qs = `ids=${key}&limit=5000&sort=gap`;
  const list = useLoad(ids.length ? key : null, () => api.opportunities(qs));
  const rows = ids.length ? list.data?.opportunities ?? [] : [];

  // Watched loans missing from the latest run have left the data: paid off, defeased or liquidated.
  const found = new Set(rows.map((o) => o.id));
  const gone = list.data && !list.loading ? items.filter((w) => !shared && !found.has(w.id)) : [];
  const changed = rows.filter((o) => o.changes?.length).length;
  const mine = new Set(items.map((w) => w.id));
  const newToMe = rows.filter((o) => !mine.has(o.id));

  return (
    <>
      <PageHeader
        title={shared ? "Shared watchlist" : "Watchlist"}
        sub={
          ids.length === 0 ? "Star loans on the Loans page to follow them here."
            : `${ids.length} loans · ${money(rows.reduce((a, o) => a + (o.whole_balance ?? 0), 0))}${changed ? ` · ${changed} changed since last report` : ""}`
        }
      >
        {ids.length > 0 && (
          <>
            {!shared && <ShareButton label="Share watchlist" url={shareWatchlistUrl(ids)} title="Copy a link that opens this watchlist" />}
            <a className="button" href={api.csvUrl(`ids=${key}&sort=gap`)} download>Export CSV</a>
          </>
        )}
      </PageHeader>

      {shared && (
        <div className="banner">
          Someone shared {shared.length} loans with you. Your own watchlist is kept in this browser.
          {newToMe.length > 0
            ? <button className="primary" onClick={() => add(newToMe.map((o) => ({ id: o.id, name: o.name })))}>Add {newToMe.length} to my watchlist</button>
            : rows.length > 0 && <span className="muted"> All are on your watchlist.</span>}
          <Link to="/watchlist">View my watchlist</Link>
        </div>
      )}

      {list.error && <p className="err">Couldn't load the watchlist: {list.error}</p>}
      {ids.length === 0 ? (
        <div className="card empty-state">
          <p>Nothing on your watchlist yet.</p>
          <p className="muted">Use ☆ on any loan to watch it. Each month the watchlist shows what changed: class moves, new risk flags, DSCR or gap thresholds crossed.</p>
          <Link className="button primary" to="/loans">Browse loans</Link>
        </div>
      ) : (
        <LoanGrid
          rows={rows}
          storageKey="cmbs-radar.columns.watchlist"
          visible={{ changes: true }}
          empty={list.loading ? "Loading…" : "None of these loans are in the latest scoring run."}
        />
      )}
      {gone.length > 0 && (
        <section className="card">
          <h3>No longer in the latest data ({gone.length})</h3>
          <p className="muted">These loans left the reporting trusts (paid off, defeased or liquidated) or their trust stopped filing.</p>
          <ul>
            {gone.map((w) => (
              <li key={w.id}>
                {w.name || w.id} <span className="muted">watched since {w.added}</span>{" "}
                <button className="link" onClick={() => remove(w.id)}>Remove</button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
