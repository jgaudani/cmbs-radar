import type { SortingState } from "@tanstack/react-table";
import { useSearchParams } from "react-router";
import { api } from "../api";
import { FilterPanel } from "../components/FilterPanel";
import { PageHeader } from "../components/Layout";
import { DESC_FIRST, LoanGrid } from "../components/LoanGrid";
import { ShareButton } from "../components/ShareButton";
import { money } from "../format";
import { useLoad } from "../hooks";
import { useMeta } from "../meta";
import { PAGE_SIZES, apiQuery, paging } from "../query";

/** Every scored whole loan, filtered, sorted and paged by the api; the URL holds the view. */
export function LoansPage() {
  const { meta } = useMeta();
  const [search, setSearch] = useSearchParams();
  const { page, size, offset } = paging(search);
  const filters = apiQuery(search);
  const list = useLoad(`${filters}|${offset}|${size}`, () => api.opportunities(apiQuery(search, { limit: String(size), offset: String(offset) })), 100);
  const totals = useLoad(filters, () => api.summary(filters), 100);

  const patch = (p: Record<string, string | null>, replace = false) => {
    const next = new URLSearchParams(search);
    for (const [k, v] of Object.entries(p)) {
      if (v == null || v === "") next.delete(k);
      else next.set(k, v);
    }
    if (!("page" in p)) next.delete("page"); // a new filter or sort starts at page 1
    setSearch(next, { replace });
  };

  const sortKey = search.get("sort") || "gap";
  const desc = search.get("dir") ? search.get("dir") === "desc" : DESC_FIRST.has(sortKey);
  const sorting: SortingState = [{ id: sortKey, desc }];
  const onSort = (s: SortingState) => {
    const { id, desc: d } = s[0];
    patch({ sort: id === "gap" ? null : id, dir: d === DESC_FIRST.has(id) ? null : d ? "desc" : "asc" });
  };

  const total = list.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / size));
  const t = totals.data;
  const gap = t ? Object.values(t.by_class).reduce((a, c) => a + (c?.refi_gap_whole ?? 0), 0) : 0;

  return (
    <>
      <PageHeader
        title="Loans"
        sub={t ? <>{t.loans.toLocaleString()} whole loans · {money(t.whole_balance)} · refi gaps {money(gap)}</> : "Loading…"}
      >
        <ShareButton />
        <a className="button" href={api.csvUrl(filters)} download>Export CSV</a>
      </PageHeader>
      <FilterPanel search={search} meta={meta} onChange={patch} onReset={() => setSearch(new URLSearchParams())} />
      {list.error && <p className="err">Couldn't load loans: {list.error}</p>}
      <LoanGrid
        rows={list.data?.opportunities ?? []}
        sorting={sorting}
        onSortingChange={onSort}
        storageKey="cmbs-radar.columns.loans"
        empty={list.loading && !list.data ? "Loading…" : "No loans match these filters."}
        toolbar={
          <span className={`muted ${list.loading ? "loading" : ""}`}>
            {total > 0 ? `${(offset + 1).toLocaleString()}–${Math.min(offset + size, total).toLocaleString()} of ${total.toLocaleString()}` : ""}
            {" · one row per whole loan; split loans show their combined balance"}
          </span>
        }
      />
      <nav className="pager" aria-label="Pages">
        <button disabled={page <= 1} onClick={() => patch({ page: String(page - 1) })}>Previous</button>
        <span>Page {page} of {pages}</span>
        <button disabled={page >= pages} onClick={() => patch({ page: String(page + 1) })}>Next</button>
        <label>
          Rows
          <select value={size} onChange={(e) => patch({ size: e.target.value === "50" ? null : e.target.value })}>
            {PAGE_SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
      </nav>
    </>
  );
}
