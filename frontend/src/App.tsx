import { lazy } from "react";
import { Link, Route, Routes } from "react-router";
import { Layout, PageHeader } from "./components/Layout";
import { MetaProvider } from "./meta";
import { DataPage } from "./pages/DataPage";
import { LoansPage } from "./pages/LoansPage";
import { WatchlistPage } from "./pages/WatchlistPage";

// Pages with charts or the map load on demand: ECharts and Leaflet stay out of the first download.
const HomePage = lazy(() => import("./pages/HomePage").then((m) => ({ default: m.HomePage })));
const LoanPage = lazy(() => import("./pages/LoanPage").then((m) => ({ default: m.LoanPage })));
const ScenariosPage = lazy(() => import("./pages/ScenariosPage").then((m) => ({ default: m.ScenariosPage })));
const BacktestPage = lazy(() => import("./pages/BacktestPage").then((m) => ({ default: m.BacktestPage })));

/** Routes; the router itself is supplied by main.tsx (browser) or tests (memory). */
export function App() {
  return (
    <MetaProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<HomePage />} />
          <Route path="loans" element={<LoansPage />} />
          <Route path="loans/:trust/:asset" element={<LoanPage />} />
          <Route path="watchlist" element={<WatchlistPage />} />
          <Route path="scenarios" element={<ScenariosPage />} />
          <Route path="backtest" element={<BacktestPage />} />
          <Route path="data" element={<DataPage />} />
          <Route path="*" element={<PageHeader title="Page not found" sub={<Link to="/">Go to the home page</Link>} />} />
        </Route>
      </Routes>
    </MetaProvider>
  );
}
