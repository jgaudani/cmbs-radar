import {
  createColumnHelper, flexRender, getCoreRowModel, getSortedRowModel, useReactTable,
  type ColumnDef, type SortingState, type VisibilityState,
} from "@tanstack/react-table";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import { loanHref } from "../api";
import { flagLabel, money, months, pct, place, ratio } from "../format";
import { useOutside } from "../hooks";
import type { Opportunity } from "../types";
import { Badge } from "./Badge";
import { WatchButton } from "./WatchButton";

const SHOWN_FLAGS = ["special_servicing", "delinquent_60_plus", "tenant_rollover", "occupancy_declined", "split_loan", "past_maturity"];

// Sort keys whose natural order is largest first (as the api sorts them).
export const DESC_FIRST = new Set(["gap", "gap_pct", "balance"]);

// Missing values sort last (TanStack treats undefined, not null, as missing).
const v = (x: number | null | undefined) => x ?? undefined;

const col = createColumnHelper<Opportunity>();

/** Column ids double as the api's sort keys where sortable. */
export const COLUMNS: ColumnDef<Opportunity, never>[] = [
  col.display({
    id: "watch", header: () => <span className="sr-only">Watch</span>, enableHiding: false,
    cell: (c) => <WatchButton compact loan={{ id: c.row.original.id, name: c.row.original.name }} />,
  }),
  col.accessor((o) => o.name || undefined, {
    id: "name", header: "Property", enableHiding: false, sortUndefined: "last",
    cell: (c) => {
      const o = c.row.original;
      const flags = o.flags.filter((f) => SHOWN_FLAGS.includes(f));
      return (
        <>
          <Link className="pname" to={loanHref(o.id)} onClick={(e) => e.stopPropagation()}>{o.name || "(unnamed)"}</Link>
          <div className="ploc">
            {place(o.city, o.state)}
            {o.property_type_label && ` · ${o.property_type_label}`}
            {o.properties > 1 && ` · ${o.properties} properties`}
            {o.notes > 1 && ` · ${o.notes} notes`}
          </div>
          {flags.length > 0 && <div className="flags">{flags.map((f) => <span key={f} className="flag">{flagLabel(f)}</span>)}</div>}
        </>
      );
    },
  }),
  col.accessor("class", { id: "class", header: "Class", cell: (c) => <Badge cls={c.getValue()} /> }),
  col.accessor((o) => o.changes, {
    id: "changes", header: "Since last report", enableSorting: false,
    cell: (c) => {
      const ch = c.row.original.changes;
      return ch?.length ? <ul className="changes">{ch.map((x) => <li key={x}>{x.replace(/_/g, " ")}</li>)}</ul> : <span className="ploc">no change</span>;
    },
  }),
  col.accessor((o) => o.refi_date, {
    id: "maturity", header: "Refi date", sortUndefined: "last", meta: { num: true },
    cell: (c) => <>{c.row.original.refi_date ?? "—"}<div className="ploc">{months(c.row.original.months_to_refi)}</div></>,
  }),
  col.accessor((o) => v(o.whole_balance), { id: "balance", header: "Whole loan", sortUndefined: "last", meta: { num: true }, cell: (c) => money(c.getValue()) }),
  col.accessor((o) => v(o.max_new_loan), { id: "max_new_loan", header: "Max new loan", enableSorting: false, meta: { num: true }, cell: (c) => money(c.getValue()) }),
  col.accessor((o) => v(o.refi_gap_whole), { id: "gap", header: "Refi gap", sortUndefined: "last", meta: { num: true }, cell: (c) => money(c.getValue()) }),
  col.accessor((o) => v(o.refi_gap_pct), { id: "gap_pct", header: "Gap %", sortUndefined: "last", meta: { num: true }, cell: (c) => pct(c.getValue()) }),
  col.accessor((o) => v(o.dscr), { id: "dscr", header: "DSCR", sortUndefined: "last", meta: { num: true }, cell: (c) => ratio(c.getValue()) }),
  col.accessor((o) => v(o.debt_yield), { id: "dy", header: "Debt yield", sortUndefined: "last", meta: { num: true }, cell: (c) => pct(c.getValue(), 1) }),
  col.accessor((o) => v(o.occupancy), { id: "occupancy", header: "Occupancy", sortUndefined: "last", meta: { num: true }, cell: (c) => pct(c.getValue()) }),
  col.accessor("team", { id: "team", header: "Routed to", enableSorting: false, cell: (c) => <span className="ploc">{c.getValue() ?? "—"}</span> }),
] as ColumnDef<Opportunity, never>[];

const LABELS: Record<string, string> = Object.fromEntries(
  COLUMNS.map((c) => [c.id!, typeof c.header === "string" ? c.header : c.id!]),
);

const DEFAULT_HIDDEN: VisibilityState = { max_new_loan: false, team: false, changes: false };

function loadVisibility(key: string, forced: VisibilityState): VisibilityState {
  let saved: VisibilityState = {};
  try {
    saved = JSON.parse(localStorage.getItem(key) ?? "{}");
  } catch { /* none saved */ }
  return { ...DEFAULT_HIDDEN, ...saved, ...forced };
}

interface Props<T extends Opportunity> {
  rows: T[];
  /** Server mode: sorting is the api's; the page reports clicks through onSortingChange. Client mode (omitted): sorts in the browser. */
  sorting?: SortingState;
  onSortingChange?: (s: SortingState) => void;
  extra?: ColumnDef<T, never>[]; // inserted after Class
  visible?: VisibilityState; // forced on/off, e.g. the watchlist's change column
  storageKey: string; // remembers this grid's column choice
  empty: ReactNode;
  toolbar?: ReactNode;
}

export function LoanGrid<T extends Opportunity>({ rows, sorting, onSortingChange, extra = [], visible = {}, storageKey, empty, toolbar }: Props<T>) {
  const navigate = useNavigate();
  const server = onSortingChange != null;
  const [clientSort, setClientSort] = useState<SortingState>([]);
  const [visibility, setVisibility] = useState<VisibilityState>(() => loadVisibility(storageKey, visible));
  const [chooser, setChooser] = useState(false);

  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(visibility));
    } catch { /* not remembered */ }
  }, [storageKey, visibility]);

  const base = COLUMNS as unknown as ColumnDef<T, never>[];
  const i = base.findIndex((c) => c.id === "class") + 1;
  const columns = [...base.slice(0, i), ...extra, ...base.slice(i)];

  const table = useReactTable<T>({
    data: rows,
    columns,
    state: { sorting: server ? sorting : clientSort, columnVisibility: visibility },
    onColumnVisibilityChange: setVisibility,
    onSortingChange: (u) => {
      const cur = server ? sorting ?? [] : clientSort;
      const next = typeof u === "function" ? u(cur) : u;
      if (server) onSortingChange!(next);
      else setClientSort(next);
    },
    manualSorting: server,
    enableSortingRemoval: false,
    sortDescFirst: false,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: server ? undefined : getSortedRowModel(),
    getRowId: (o) => o.id,
  });

  const hideable = table.getAllLeafColumns().filter((c) => c.getCanHide());

  return (
    <div className="grid-wrap">
      <div className="grid-bar">
        <div className="grid-toolbar">{toolbar}</div>
        <ColumnChooser open={chooser} onOpen={setChooser}>
          {hideable.map((c) => (
            <label key={c.id}>
              <input type="checkbox" checked={c.getIsVisible()} onChange={c.getToggleVisibilityHandler()} /> {LABELS[c.id] ?? c.id}
            </label>
          ))}
        </ColumnChooser>
      </div>
      <div className="grid-scroll">
        <table className="grid">
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((h) => {
                  const num = (h.column.columnDef.meta as { num?: boolean } | undefined)?.num;
                  const s = h.column.getIsSorted();
                  const sortable = h.column.getCanSort();
                  return (
                    <th key={h.id} className={num ? "num" : ""} aria-sort={s ? (s === "desc" ? "descending" : "ascending") : undefined}>
                      {sortable ? (
                        <button
                          className="th-sort"
                          onClick={() => {
                            // First click uses the column's natural order; the next flips it.
                            const desc = s ? s === "asc" : DESC_FIRST.has(h.column.id);
                            table.setSorting([{ id: h.column.id, desc }]);
                          }}
                        >
                          {flexRender(h.column.columnDef.header, h.getContext())}
                          <span className="arrow" aria-hidden="true">{s === "asc" ? "▲" : s === "desc" ? "▼" : ""}</span>
                        </button>
                      ) : (
                        flexRender(h.column.columnDef.header, h.getContext())
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan={table.getVisibleLeafColumns().length} className="empty">{empty}</td></tr>
            )}
            {table.getRowModel().rows.map((r) => (
              <tr key={r.id} onClick={() => navigate(loanHref(r.original.id))}>
                {r.getVisibleCells().map((c) => {
                  const num = (c.column.columnDef.meta as { num?: boolean } | undefined)?.num;
                  return <td key={c.id} className={num ? "num" : ""}>{flexRender(c.column.columnDef.cell, c.getContext())}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ColumnChooser({ open, onOpen, children }: { open: boolean; onOpen: (v: boolean) => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useOutside(ref, open, () => onOpen(false));
  return (
    <div className="menu-anchor" ref={ref}>
      <button onClick={() => onOpen(!open)} aria-expanded={open}>Columns</button>
      {open && <div className="popover right columns" role="dialog" aria-label="Columns">{children}</div>}
    </div>
  );
}
