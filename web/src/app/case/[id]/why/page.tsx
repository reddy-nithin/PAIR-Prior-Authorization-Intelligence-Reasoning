"use client";

import { MessageIcon, ScaleIcon } from "@/components/Icons";
import { StatusBadge } from "@/components/StatusBadge";
import { StepNav } from "@/components/Stepper";
import { useCase } from "@/lib/case-context";
import { copy, fill } from "@/lib/copy";
import { longDate } from "@/lib/format";

export default function WhyPage() {
  const view = useCase();
  const d = view.denial;
  return (
    <>
      <h1>{copy.why.title}</h1>
      {!view.supported ? <p className="error" role="alert">{view.unsupported_reason ?? copy.why.notSupported}</p> : null}
      {d ? (
        <>
          <section className="card" aria-labelledby="their-h">
            <h2 id="their-h" className="label"><MessageIcon />{copy.why.theirWords}</h2>
            <blockquote className="quote">“{d.reason_text}”</blockquote>
            <p className="note">{fill(copy.why.fromNotice, { date: longDate(d.date) })}</p>
          </section>
          <section className="card soft" aria-labelledby="plain-h">
            <h2 id="plain-h" className="label">{copy.why.plainWords}</h2>
            <p>{d.reason_plain}</p>
          </section>
          <p className="rulechip">
            <ScaleIcon />
            {copy.why.ruleCited}:
            {d.cited_rule ? (
              <a href={d.cited_rule.url} target="_blank" rel="noopener noreferrer">{`${d.cited_rule.label}: ${d.cited_rule.title}`}</a>
            ) : (
              <span className="code">{copy.common.notNamed}</span>
            )}
          </p>
          {view.overall ? (
            <p className="tags"><span className="note">{copy.common.steps.stand}:</span> <StatusBadge status={view.overall} /></p>
          ) : null}
        </>
      ) : null}
      <StepNav caseId={view.case_id} current="why" />
    </>
  );
}
