// The watchlist lives in this browser (localStorage). Sharing one is a link
// carrying the loan ids; the receiver can add them to their own.
import { useCallback, useSyncExternalStore } from "react";

export interface Watched { id: string; name: string; added: string }

const KEY = "cmbs-radar.watchlist";
const listeners = new Set<() => void>();
let cache: { raw: string | null; items: Watched[] } = { raw: null, items: [] };

function read(): Watched[] {
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(KEY);
  } catch {
    return cache.items; // storage blocked: keep what this tab has
  }
  if (raw !== cache.raw) {
    let items: Watched[] = [];
    try {
      const v = JSON.parse(raw ?? "[]");
      if (Array.isArray(v)) items = v.filter((x) => x && typeof x.id === "string");
    } catch { /* corrupt: start over */ }
    cache = { raw, items };
  }
  return cache.items;
}

function write(items: Watched[]) {
  const raw = JSON.stringify(items);
  cache = { raw, items };
  try {
    localStorage.setItem(KEY, raw);
  } catch { /* storage blocked: this tab still works */ }
  listeners.forEach((l) => l());
}

function subscribe(l: () => void) {
  listeners.add(l);
  const onStorage = (e: StorageEvent) => e.key === KEY && l(); // other tabs
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(l);
    window.removeEventListener("storage", onStorage);
  };
}

export function useWatchlist() {
  const items = useSyncExternalStore(subscribe, read, read);
  const has = useCallback((id: string) => items.some((w) => w.id === id), [items]);
  const add = useCallback((loans: { id: string; name: string }[]) => {
    const cur = read();
    const seen = new Set(cur.map((w) => w.id));
    const today = new Date().toISOString().slice(0, 10);
    write([...cur, ...loans.filter((l) => !seen.has(l.id)).map((l) => ({ id: l.id, name: l.name, added: today }))]);
  }, []);
  const remove = useCallback((id: string) => write(read().filter((w) => w.id !== id)), []);
  const toggle = useCallback((loan: { id: string; name: string }) => {
    if (read().some((w) => w.id === loan.id)) remove(loan.id);
    else add([loan]);
  }, [add, remove]);
  return { items, has, add, remove, toggle };
}

/** A link that opens these loans as a shared watchlist. */
export const shareWatchlistUrl = (ids: string[]) =>
  `${window.location.origin}/watchlist?${new URLSearchParams({ ids: ids.join(",") })}`;
