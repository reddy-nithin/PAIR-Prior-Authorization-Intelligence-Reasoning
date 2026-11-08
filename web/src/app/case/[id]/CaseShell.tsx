"use client";

import Link from "next/link";
import { useParams, useSelectedLayoutSegment } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import type { CaseView } from "@/types/caseview";
import { Footer, Header } from "@/app/Header";
import { CaseStrip, ModeTag } from "@/components/CaseStrip";
import { Stepper } from "@/components/Stepper";
import { CaseContext } from "@/lib/case-context";
import { DataError, LIVE_PREFIX, loadCachedView } from "@/lib/data";
import { useLiveStore } from "@/lib/live-store";
import { copy } from "@/lib/copy";
import { STEP_IDS, type StepId } from "@/lib/steps";

/** Loads the case once (cached JSON, or the live result from memory) and frames every step around it. */
export function CaseShell({ children }: { children: ReactNode }) {
  const { id } = useParams<{ id: string }>();
  const caseId = decodeURIComponent(id);
  const segment = useSelectedLayoutSegment();
  const current: StepId = STEP_IDS.includes(segment as StepId) ? (segment as StepId) : "why";
  const live = useLiveStore();
  const liveView = caseId.startsWith(LIVE_PREFIX) ? live.get(caseId) : undefined;
  const [cached, setCached] = useState<CaseView | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (caseId.startsWith(LIVE_PREFIX)) return;
    let gone = false;
    loadCachedView(caseId).then(
      (view) => !gone && setCached(view),
      (e: unknown) => !gone && setError(e instanceof DataError ? e.message : copy.common.caseMissing),
    );
    return () => {
      gone = true;
    };
  }, [caseId]);

  // After a step change, move focus to the new step so keyboard and screen reader users start at its top.
  const shown = useRef<StepId | null>(null);
  useEffect(() => {
    if (shown.current && shown.current !== current) document.getElementById("main")?.focus();
    shown.current = current;
  }, [current]);

  const view = liveView ?? cached;
  const problem = caseId.startsWith(LIVE_PREFIX) && !liveView ? copy.common.caseGone : error;

  if (!view) {
    return (
      <>
        <Header />
        <div className="col">
          <main id="main" tabIndex={-1}>
            {problem ? (
              <>
                <h1>{copy.common.caseMissing}</h1>
                <p role="alert">{problem}</p>
                <p><Link className="btn" href="/">{copy.common.home}</Link></p>
              </>
            ) : (
              <p className="lede" role="status">{copy.common.loading}</p>
            )}
          </main>
        </div>
      </>
    );
  }

  return (
    <CaseContext.Provider value={view}>
      <Header><ModeTag view={view} /></Header>
      <Stepper caseId={caseId} current={current} />
      <div className={`col on-case${current === "letter" ? " wide" : ""}`}>
        <main id="main" tabIndex={-1}>
          <CaseStrip view={view} />
          {children}
          <Footer />
        </main>
      </div>
    </CaseContext.Provider>
  );
}
