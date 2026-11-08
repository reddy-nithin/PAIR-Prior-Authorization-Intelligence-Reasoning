"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import type { CaseView } from "@/types/caseview";

/**
 * Live results live only in this tab's memory (never localStorage or sessionStorage):
 * the patient's records must not be written to disk. A reload forgets them.
 */
interface LiveStore {
  get(caseId: string): CaseView | undefined;
  put(view: CaseView): void;
}

const LiveContext = createContext<LiveStore | null>(null);

export function LiveCaseProvider({ children }: { children: ReactNode }) {
  const [views, setViews] = useState<Record<string, CaseView>>({});
  const get = useCallback((caseId: string) => views[caseId], [views]);
  const put = useCallback((view: CaseView) => setViews((current) => ({ ...current, [view.case_id]: view })), []);
  const value = useMemo(() => ({ get, put }), [get, put]);
  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

export function useLiveStore(): LiveStore {
  const store = useContext(LiveContext);
  if (!store) throw new Error("useLiveStore needs <LiveCaseProvider>");
  return store;
}
