"use client";

import { CriterionRow } from "@/components/CriterionRow";
import { PersonIcon } from "@/components/Icons";
import { StatusBadge } from "@/components/StatusBadge";
import { StepNav } from "@/components/Stepper";
import { useCase } from "@/lib/case-context";
import { copy, fill } from "@/lib/copy";

const TALLY = [
  { status: "met", icon: "check", label: copy.stand.counts.met },
  { status: "unmet", icon: "cross", label: copy.stand.counts.unmet },
  { status: "insufficient", icon: "question", label: copy.stand.counts.unknown },
] as const;

export default function StandPage() {
  const view = useCase();
  const titles = Object.fromEntries(view.documents.map((d) => [d.doc_id, d.title]));
  const count = (s: string) => view.criteria.filter((c) => c.status.status === s).length;
  const missingRequired = view.criteria.some((c) => c.critical && c.status.status === "insufficient");
  const who = view.gap_groups[0]?.who;
  return (
    <>
      <div className="stack">
        <h1>{copy.stand.title}</h1>
        <p className="lede">{copy.stand.intro}</p>
      </div>
      <section className="card tally" aria-label={fill(copy.stand.summary, { met: count("met"), unmet: count("unmet"), unknown: count("insufficient") })}>
        {TALLY.map((t) => (
          <div key={t.status} aria-hidden="true">
            <b>{count(t.status)}</b>
            <StatusBadge status={t} />
          </div>
        ))}
      </section>
      {missingRequired && who ? (
        <p className="banner"><PersonIcon />{fill(copy.stand.missingBanner, { who })}</p>
      ) : null}
      <p className="note">{copy.stand.open}</p>
      <ul className="ledger">
        {view.criteria.map((c) => <CriterionRow key={c.id} criterion={c} titles={titles} />)}
      </ul>
      <StepNav caseId={view.case_id} current="stand" />
    </>
  );
}
