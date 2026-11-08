"use client";

import { createContext, useContext } from "react";
import type { CaseView } from "@/types/caseview";

export const CaseContext = createContext<CaseView | null>(null);

/** The case the current /case/{id}/ page shows. */
export function useCase(): CaseView {
  const view = useContext(CaseContext);
  if (!view) throw new Error("useCase needs the case layout");
  return view;
}
