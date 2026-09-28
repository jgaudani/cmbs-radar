import { Suspense, useEffect, type ReactNode } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import { pct } from "../format";
import { useMeta } from "../meta";
import { useWatchlist } from "../watchlist";

// 20px line icons.
const ICON: Record<string, string> = {
  home: "M3 10.5 10 4l7 6.5M5 9v7h4v-4h2v4h4V9",
  loans: "M3 5h14M3 10h14M3 15h14M6 3v14",
  watch: "M10 3.5l2 4.2 4.6.6-3.3 3.2.8 4.5L10 13.8 5.9 16l.8-4.5-3.3-3.2 4.6-.6z",
  scenario: "M3 15l4-5 3 3 6-8M13 5h3v3",
  backtest: "M4 16V9M8 16V5M12 16v-4M16 16V7M3 16.5h14",
  data: "M10 4c3.9 0 7 1.1 7 2.5S13.9 9 10 9 3 7.9 3 6.5 6.1 4 10 4zM3 6.5v7C3 14.9 6.1 16 10 16s7-1.1 7-2.5v-7M3 10c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5",
};

function Icon({ name }: { name: string }) {
  return (
    <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round">
      <path d={ICON[name]} />
    </svg>
  );
}

const NAV = [
  { to: "/", label: "Home", icon: "home", end: true },
  { to: "/loans", label: "Loans", icon: "loans" },
  { to: "/watchlist", label: "Watchlist", icon: "watch" },
  { to: "/scenarios", label: "Rate scenarios", icon: "scenario" },
  { to: "/backtest", label: "Backtest", icon: "backtest" },
  { to: "/data", label: "Method & data", icon: "data" },
];

export function Layout() {
  const { meta, error } = useMeta();
  const { items } = useWatchlist();
  const { pathname } = useLocation();
  useEffect(() => window.scrollTo(0, 0), [pathname]); // a new page starts at the top; filter changes keep the scroll
  return (
    <div className="shell">
      <nav className="side" aria-label="Main">
        <div className="brand">
          <span className="logo" aria-hidden="true" />
          <div>
            <div className="brand-name">CMBS Radar</div>
            <div className="brand-sub">Refinance opportunities</div>
          </div>
        </div>
        <ul>
          {NAV.map((n) => (
            <li key={n.to}>
              <NavLink to={n.to} end={n.end}>
                <Icon name={n.icon} />
                <span>{n.label}</span>
                {n.icon === "watch" && items.length > 0 && <span className="count">{items.length}</span>}
              </NavLink>
            </li>
          ))}
        </ul>
        <div className="side-foot">
          {meta && (
            <>
              Data through <b>{meta.data_as_of}</b>
              <br />
              Scoring run {meta.run_id} · {meta.assumptions.version} · base rate {pct(meta.assumptions.base_rate, 2)}
            </>
          )}
          {error && <span className="err">API unavailable: {error}</span>}
        </div>
      </nav>
      <main className="page">
        <Suspense fallback={<p className="muted">Loading…</p>}>
          <Outlet />
        </Suspense>
      </main>
    </div>
  );
}

/** Page title row with actions on the right. */
export function PageHeader({ title, sub, children }: { title: string; sub?: ReactNode; children?: ReactNode }) {
  return (
    <header className="page-head">
      <div>
        <h1>{title}</h1>
        {sub && <p className="sub">{sub}</p>}
      </div>
      <div className="actions">{children}</div>
    </header>
  );
}
