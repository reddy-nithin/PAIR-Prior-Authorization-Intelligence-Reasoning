"use client";

import { GetAHumanCard } from "@/components/GetAHumanCard";
import { StepNav } from "@/components/Stepper";
import { StrengthCard } from "@/components/StrengthCard";
import { useCase } from "@/lib/case-context";
import { copy } from "@/lib/copy";

export default function ChancesPage() {
  const view = useCase();
  const s = view.strength;
  return (
    <>
      <div className="stack">
        <h1>{copy.chances.title}</h1>
      </div>
      {s == null ? (
        <section className="panel"><p>{copy.chances.notAvailable}</p></section>
      ) : s.abstain ? (
        <GetAHumanCard strength={s} links={view.help_links} />
      ) : (
        <StrengthCard strength={s} />
      )}
      <StepNav caseId={view.case_id} current="chances" />
    </>
  );
}
