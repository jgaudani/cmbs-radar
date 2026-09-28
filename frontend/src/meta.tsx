import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "./api";
import type { Meta } from "./types";

interface MetaState { meta: Meta | null; error: string }

const Ctx = createContext<MetaState>({ meta: null, error: "" });

/** Run metadata (as-of date, assumptions, metros, flags), loaded once for every page. */
export function MetaProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<MetaState>({ meta: null, error: "" });
  useEffect(() => {
    api.meta().then((meta) => setState({ meta, error: "" })).catch((e: Error) => setState({ meta: null, error: e.message }));
  }, []);
  return <Ctx.Provider value={state}>{children}</Ctx.Provider>;
}

export const useMeta = () => useContext(Ctx);
