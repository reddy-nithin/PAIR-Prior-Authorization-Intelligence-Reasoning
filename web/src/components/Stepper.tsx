"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { copy, fill } from "@/lib/copy";
import { STEPS, stepHref, type StepId } from "@/lib/steps";

/** The 7 steps: a rail on wide screens, a "Step n of 7" picker on phones. */
export function Stepper({ caseId, current }: { caseId: string; current: StepId }) {
  const router = useRouter();
  const index = STEPS.findIndex((s) => s.id === current);
  return (
    <>
      <nav className="rail" aria-label="Steps">
        <ol>
          {STEPS.map((step, i) => (
            <li key={step.id}>
              <Link href={stepHref(caseId, step.id)} aria-current={i === index ? "step" : undefined} className={i < index ? "done" : undefined}>
                <span className="n" aria-hidden="true">{i + 1}</span>
                <span>{step.name}</span>
              </Link>
            </li>
          ))}
        </ol>
      </nav>
      <div className="mobile-step">
        <span>{fill(copy.common.stepOf, { step: index + 1, total: STEPS.length })}</span>
        <label className="sr" htmlFor="jump">{copy.common.goToStep}</label>
        <select id="jump" value={current} onChange={(e) => router.push(stepHref(caseId, e.target.value as StepId))}>
          {STEPS.map((step, i) => (
            <option key={step.id} value={step.id}>{`${i + 1}. ${step.name}`}</option>
          ))}
        </select>
      </div>
    </>
  );
}

/** Back / Next links at the bottom of a step. */
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
