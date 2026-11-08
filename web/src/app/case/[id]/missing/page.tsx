"use client";

import { GapChecklist } from "@/components/GapChecklist";
import { StepNav } from "@/components/Stepper";
import { useCase } from "@/lib/case-context";
import { copy } from "@/lib/copy";

export default function MissingPage() {
  const view = useCase();
  const empty = view.gap_groups.length === 0;
  return (
    <>
      <div className="stack">
        <p className="eyebrow">{copy.common.steps.missing}</p>
        <h1>{copy.missing.title}</h1>
        <p className="lede">{empty ? copy.missing.nothingMissing : copy.missing.intro}</p>
      </div>
      {empty ? null : <GapChecklist caseId={view.case_id} groups={view.gap_groups} persist={view.mode === "cached"} />}
      {empty ? null : <p className="note">{copy.missing.tickNote}</p>}
      <StepNav caseId={view.case_id} current="missing" />
    </>
  );
}
