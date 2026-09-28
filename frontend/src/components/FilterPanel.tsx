import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { CLASSES, LABEL, addMonths } from "../format";
import { useOutside } from "../hooks";
import { FILTERS, describe, isActive, paramsOf, toApi, toUi, type FilterDef } from "../query";
import type { Meta } from "../types";

interface Props {
  search: URLSearchParams;
  meta: Meta | null;
  /** Applies changed params (null removes one) and resets paging. */
  onChange: (patch: Record<string, string | null>, replace?: boolean) => void;
  onReset: () => void;
}

/** Search, class pills, and the other filters as removable chips added from a menu. */
export function FilterPanel({ search, meta, onChange, onReset }: Props) {
  const [editing, setEditing] = useState<string | null>(null); // filter key, or "+" for the add menu
  const [q, setQ] = useState(search.get("q") ?? "");

  // Search goes to the URL as you type (debounced, replacing history).
  useEffect(() => setQ(search.get("q") ?? ""), [search]);
  useEffect(() => {
    if (q === (search.get("q") ?? "")) return;
    const t = setTimeout(() => onChange({ q: q || null }, true), 250);
    return () => clearTimeout(t);
  }, [q]); // eslint-disable-line react-hooks/exhaustive-deps

  const classes = (search.get("class") ?? "").split(",").filter(Boolean);
  const toggleClass = (c: string) => {
    const next = classes.includes(c) ? classes.filter((x) => x !== c) : [...classes, c];
    onChange({ class: next.join(",") || null });
  };
  const chips = FILTERS.filter((f) => f.key !== "class" && isActive(f, search));
  const available = FILTERS.filter((f) => f.key !== "class" && !isActive(f, search));
  const otherClasses = classes.filter((c) => !(CLASSES as string[]).includes(c));

  return (
    <section className="filter-panel" aria-label="Filters">
      <div className="filter-row">
        <input className="search" type="search" placeholder="Search property, city or trust" aria-label="Search" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="pills" role="group" aria-label="Class">
          {CLASSES.map((c) => (
            <button key={c} className={`pill ${classes.includes(c) ? "on" : ""}`} style={{ "--c": `var(--${c})` } as CSSProperties}
              aria-pressed={classes.includes(c)} onClick={() => toggleClass(c)}>
              {LABEL[c]}
            </button>
          ))}
          {otherClasses.length > 0 && (
            <button className="pill on" style={{ "--c": "var(--none)" } as CSSProperties} aria-pressed onClick={() => onChange({ class: classes.filter((c) => (CLASSES as string[]).includes(c)).join(",") || null })}>
              {otherClasses.map((c) => LABEL[c as keyof typeof LABEL] ?? c).join(", ")} ✕
            </button>
          )}
        </div>
      </div>
      <div className="filter-row chips">
        {chips.map((f) => (
          <Popover key={f.key} open={editing === f.key} onClose={() => setEditing(null)}
            trigger={
              <span className="chip">
                <button className="chip-label" onClick={() => setEditing(editing === f.key ? null : f.key)}>{describe(f, search, meta)}</button>
                <button className="chip-x" aria-label={`Remove ${f.label} filter`} onClick={() => onChange(Object.fromEntries(paramsOf(f).map((p) => [p, null])))}>✕</button>
              </span>
            }>
            <Editor def={f} search={search} meta={meta} onApply={(p) => { onChange(p); setEditing(null); }} />
          </Popover>
        ))}
        <Popover open={editing === "+"} onClose={() => setEditing(null)}
          trigger={<button className="add-filter" aria-expanded={editing === "+"} onClick={() => setEditing(editing === "+" ? null : "+")}>+ Add filter</button>}>
          <AddMenu defs={available} meta={meta} search={search} onApply={(p) => { onChange(p); setEditing(null); }} />
        </Popover>
        {(chips.length > 0 || classes.length > 0 || q) && <button className="link" onClick={onReset}>Clear all</button>}
      </div>
    </section>
  );
}

function Popover({ open, onClose, trigger, children }: { open: boolean; onClose: () => void; trigger: ReactNode; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useOutside(ref, open, onClose);
  return (
    <div className="menu-anchor" ref={ref}>
      {trigger}
      {open && <div className="popover" role="dialog">{children}</div>}
    </div>
  );
}

/** The add menu: pick a filter, then edit it in place. */
function AddMenu({ defs, meta, search, onApply }: { defs: FilterDef[]; meta: Meta | null; search: URLSearchParams; onApply: (p: Record<string, string | null>) => void }) {
  const [picked, setPicked] = useState<FilterDef | null>(null);
  if (picked) return <Editor def={picked} search={search} meta={meta} onApply={onApply} />;
  return (
    <ul className="menu" aria-label="Add filter">
      {defs.map((f) => <li key={f.key}><button onClick={() => setPicked(f)}>{f.label}</button></li>)}
    </ul>
  );
}

type Apply = (p: Record<string, string | null>) => void;

function Editor({ def, search, meta, onApply }: { def: FilterDef; search: URLSearchParams; meta: Meta | null; onApply: Apply }) {
  return (
    <div className="editor">
      <div className="editor-title">{def.label}</div>
      {def.kind === "range" && <RangeEditor def={def} search={search} onApply={onApply} />}
      {def.kind === "multi" && <MultiEditor def={def} search={search} meta={meta} onApply={onApply} />}
      {def.kind === "date" && <DateEditor search={search} asOf={meta?.data_as_of} onApply={onApply} />}
      {def.kind === "changed" && <ChangedEditor search={search} onApply={onApply} />}
    </div>
  );
}

function RangeEditor({ def, search, onApply }: { def: Extract<FilterDef, { kind: "range" }>; search: URLSearchParams; onApply: Apply }) {
  const [lo, setLo] = useState(toUi(def.unit, search.get(`min_${def.param}`)));
  const [hi, setHi] = useState(toUi(def.unit, search.get(`max_${def.param}`)));
  const bad = [lo, hi].some((x) => x.trim() !== "" && isNaN(Number(x)));
  const apply = () => onApply({ [`min_${def.param}`]: toApi(def.unit, lo) || null, [`max_${def.param}`]: toApi(def.unit, hi) || null });
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (!bad) apply(); }}>
      <div className="range">
        <label>Min<input inputMode="decimal" value={lo} onChange={(e) => setLo(e.target.value)} autoFocus aria-label={`${def.label} min`} /></label>
        <span>–</span>
        <label>Max<input inputMode="decimal" value={hi} onChange={(e) => setHi(e.target.value)} aria-label={`${def.label} max`} /></label>
      </div>
      <p className="hint">{def.hint}</p>
      <button type="submit" className="primary" disabled={bad}>Apply</button>
    </form>
  );
}

function MultiEditor({ def, search, meta, onApply }: { def: Extract<FilterDef, { kind: "multi" }>; search: URLSearchParams; meta: Meta | null; onApply: Apply }) {
  const [sel, setSel] = useState<string[]>((search.get(def.param) ?? "").split(",").filter(Boolean));
  const [find, setFind] = useState("");
  const opts = def.options(meta).filter(([, label]) => label.toLowerCase().includes(find.toLowerCase()));
  const toggle = (v: string) => setSel((s) => (s.includes(v) ? s.filter((x) => x !== v) : [...s, v]));
  return (
    <form onSubmit={(e) => { e.preventDefault(); onApply({ [def.param]: sel.join(",") || null }); }}>
      {def.options(meta).length > 10 && <input className="find" placeholder="Find…" value={find} onChange={(e) => setFind(e.target.value)} autoFocus />}
      <div className="checks">
        {opts.map(([v, label]) => (
          <label key={v}><input type="checkbox" checked={sel.includes(v)} onChange={() => toggle(v)} /> {label}</label>
        ))}
      </div>
      {def.all && <p className="hint">Loans must have every selected flag.</p>}
      <button type="submit" className="primary">Apply</button>
    </form>
  );
}

function DateEditor({ search, asOf, onApply }: { search: URLSearchParams; asOf?: string; onApply: Apply }) {
  const [from, setFrom] = useState((search.get("refi_from") ?? "").slice(0, 7));
  const [to, setTo] = useState((search.get("refi_to") ?? "").slice(0, 7));
  const quick = (n: number) => asOf && onApply({ refi_from: null, refi_to: addMonths(asOf, n) });
  return (
    <form onSubmit={(e) => { e.preventDefault(); onApply({ refi_from: from || null, refi_to: to || null }); }}>
      <div className="quick">
        {[6, 12, 18, 24, 36].map((n) => <button type="button" key={n} onClick={() => quick(n)} disabled={!asOf}>Next {n} mo</button>)}
        <button type="button" onClick={() => asOf && onApply({ refi_from: null, refi_to: addMonths(asOf, -1) })} disabled={!asOf}>Past maturity</button>
      </div>
      <p className="hint">Quick picks include loans already past their refi date. Effective refi date is the ARD if any, else maturity.</p>
      <div className="range">
        <label>From<input type="month" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="Refi from" /></label>
        <span>–</span>
        <label>To<input type="month" value={to} onChange={(e) => setTo(e.target.value)} aria-label="Refi to" /></label>
      </div>
      <button type="submit" className="primary">Apply</button>
    </form>
  );
}

function ChangedEditor({ search, onApply }: { search: URLSearchParams; onApply: Apply }) {
  const [v, setV] = useState(search.get("changed") || "class");
  return (
    <form onSubmit={(e) => { e.preventDefault(); onApply({ changed: v }); }}>
      <div className="checks">
        <label><input type="radio" name="changed" checked={v === "class"} onChange={() => setV("class")} /> Class changed</label>
        <label><input type="radio" name="changed" checked={v === "any"} onChange={() => setV("any")} /> Anything changed (class, new flag, threshold crossed)</label>
      </div>
      <button type="submit" className="primary">Apply</button>
    </form>
  );
}
