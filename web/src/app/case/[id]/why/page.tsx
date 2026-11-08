"use client";

import { StatusBadge } from "@/components/StatusBadge";
import { StepNav } from "@/components/Stepper";
import { useCase } from "@/lib/case-context";
import { copy } from "@/lib/copy";
import { longDate } from "@/lib/format";

export default function WhyPage() {
  const view = useCase();
  const d = view.denial;
  return (
    <>
      <div className="stack">
        <p className="eyebrow">{copy.common.steps.why}</p>
        <h1>{copy.why.title}</h1>
      </div>
      {!view.supported ? <p className="error" role="alert">{view.unsupported_reason ?? copy.why.notSupported}</p> : null}
      {d ? (
        <>
          <section className="panel">
            <h2>{copy.why.theirWords}</h2>
            <blockquote className="quote">“{d.reason_text}”</blockquote>
            <h3>{copy.why.plainWords}</h3>
            <p>{d.reason_plain}</p>
          </section>
          <section className="panel">
            <h2>{copy.why.ruleCited}</h2>
            <dl className="kv">
              <dt>{copy.common.service}</dt>
              <dd>{d.service} {d.codes.length ? <span className="code">({d.codes.join(", ")})</span> : null}</dd>
              <dt>{copy.common.denied}</dt>
              <dd>{longDate(d.date)}</dd>
              <dt>{copy.common.rule}</dt>
              <dd>
                {d.cited_rule ? (
                  <a href={d.cited_rule.url} target="_blank" rel="noopener noreferrer">{`${d.cited_rule.label}: ${d.cited_rule.title}`}</a>
                ) : (
                  copy.common.notNamed
                )}
              </dd>
              {view.overall ? (<><dt>{copy.common.steps.stand}</dt><dd><StatusBadge status={view.overall} /></dd></>) : null}
            </dl>
          </section>
        </>
      ) : null}
      <StepNav caseId={view.case_id} current="why" />
    </>
  );
}
