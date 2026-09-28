import { useEffect, useState, type RefObject } from "react";

/** Closes a popover on an outside click or Escape. */
export function useOutside(ref: RefObject<HTMLElement | null>, active: boolean, close: () => void) {
  useEffect(() => {
    if (!active) return;
    const onDown = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && close();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [ref, active, close]);
}

/** Loads data for a key (e.g. a query string); stale responses are dropped. */
export function useLoad<T>(key: string | null, load: () => Promise<T>, delay = 0): { data: T | null; error: string; loading: boolean } {
  const [state, setState] = useState<{ key: string | null; data: T | null; error: string }>({ key: null, data: null, error: "" });
  useEffect(() => {
    if (key == null) return;
    let live = true;
    const t = setTimeout(() => {
      load()
        .then((data) => live && setState({ key, data, error: "" }))
        .catch((e: Error) => live && setState((s) => ({ key, data: s.data, error: e.message })));
    }, delay);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps -- key identifies the request
  return { data: state.data, error: state.error, loading: key != null && state.key !== key };
}
