"use client";

import Link from "next/link";
import { copy, fill } from "@/lib/copy";
import { STEPS, stepHref, type StepId } from "@/lib/steps";

/** The 7 steps as a path of dots (Direction C): done steps filled, the current one large, each a link. */
export function Stepper({ caseId, current }: { caseId: string; current: StepId }) {
  const index = STEPS.findIndex((s) => s.id === current);
  return (
    <nav className="rail" aria-label="Steps">
      <ol>
        {STEPS.map((step, i) => (
          <li key={step.id} className={i < index ? "done" : undefined}>
            <Link
              href={stepHref(caseId, step.id)}
              aria-current={i === index ? "step" : undefined}
              aria-label={`${fill(copy.common.stepOf, { step: i + 1, total: STEPS.length })}: ${step.name}`}
            />
          </li>
        ))}
      </ol>
      <p aria-hidden="true">{`${fill(copy.common.stepOf, { step: index + 1, total: STEPS.length })} · ${STEPS[index].name}`}</p>
    </nav>
  );
}

/** Back / Next pills at the bottom of a step. */
export function StepNav({ caseId, current }: { caseId: string; current: StepId }) {
  const index = STEPS.findIndex((s) => s.id === current);
  const prev = STEPS[index - 1];
  const next = STEPS[index + 1];
  return (
    <div className="nav">
      {prev ? <Link className="btn secondary" href={stepHref(caseId, prev.id)}>{copy.common.back}</Link> : <span />}
      {next ? <Link className="btn" href={stepHref(caseId, next.id)}>{`${copy.common.next}: ${next.name}`}</Link> : null}
    </div>
  );
}
