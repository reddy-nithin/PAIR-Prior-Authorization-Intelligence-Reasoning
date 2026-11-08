"use client";

import { CriterionRow } from "@/components/CriterionRow";
import { StepNav } from "@/components/Stepper";
import { useCase } from "@/lib/case-context";
import { copy, fill } from "@/lib/copy";

export default function StandPage() {
  const view = useCase();
  const titles = Object.fromEntries(view.documents.map((d) => [d.doc_id, d.title]));
  const count = (s: string) => view.criteria.filter((c) => c.status.status === s).length;
  return (
    <>
      <div className="stack">
        <p className="eyebrow">{copy.common.steps.stand}</p>
        <h1>{copy.stand.title}</h1>
        <p className="lede">{copy.stand.intro}</p>
        <p>
          <b>{fill(copy.stand.summary, { met: count("met"), unmet: count("unmet"), unknown: count("insufficient") })}.</b> {copy.stand.open}
        </p>
      </div>
      <ul className="ledger">
        {view.criteria.map((c) => <CriterionRow key={c.id} criterion={c} titles={titles} />)}
      </ul>
      <StepNav caseId={view.case_id} current="stand" />
    </>
  );
}
