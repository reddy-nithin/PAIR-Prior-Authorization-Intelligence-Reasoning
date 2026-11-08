import type { StepView, StrengthView } from "@/types/caseview";
import { StatusBadge } from "@/components/StatusBadge";
import { copy, fill } from "@/lib/copy";
import { outOf100 } from "@/lib/format";

const EFFECT: Record<StepView["effect"], [string, string]> = {
  raises: [copy.chances.helps, "raises"],
  lowers: [copy.chances.hurts, "lowers"],
  "no change": [copy.chances.noEffect, "none"],
};

/** How each requirement moved the estimate. */
export function StepsList({ steps }: { steps: StepView[] }) {
  return (
    <ul className="steps">
      {steps.map((s) => (
        <li key={s.criterion_id}>
          <span className={`eff ${EFFECT[s.effect][1]}`}>{EFFECT[s.effect][0]}</span>
          <span>{s.heading} <StatusBadge status={s.status} /></span>
        </li>
      ))}
    </ul>
  );
}

/** The range as 100 dots (won / not sure / did not win) plus the same in words. */
export function StrengthCard({ strength }: { strength: StrengthView }) {
  if (strength.low == null || strength.high == null || strength.p == null) return null;
  const lo = outOf100(strength.low);
  const hi = outOf100(strength.high);
  const sentence = fill(copy.chances.range, { low: lo, high: hi });
  return (
    <>
      <section className="panel" aria-labelledby="h-score">
        <h2 id="h-score">{copy.chances.title}</h2>
        <div className="score">
          <div className="icons" role="img" aria-label={sentence} data-testid="icon-array">
            {Array.from({ length: 100 }, (_, i) => (
              <i key={i} className={i < lo ? "yes" : i < hi ? "maybe" : undefined} />
            ))}
          </div>
          <div className="stack">
            <p><span className="big">{`${lo} to ${hi}`}</span></p>
            <p>{sentence}</p>
            <p>{fill(copy.chances.bestGuess, { p: outOf100(strength.p) })}</p>
            <div className="legend" aria-hidden="true">
              <span><i className="yes" />{copy.chances.won}</span>
              <span><i className="maybe" />{copy.chances.unsure}</span>
              <span><i />{copy.chances.lost}</span>
            </div>
          </div>
        </div>
        {strength.base_rate != null ? <p className="note">{fill(copy.chances.before, { p: outOf100(strength.base_rate) })}</p> : null}
      </section>
      {strength.improve.length ? (
        <section className="panel">
          <h2>{copy.chances.whatHelps}</h2>
          {strength.improve.map((m) => (
            <p key={m.criterion_id}>
              <b>{m.heading}.</b> {m.action}
              {m.p_if_fixed != null ? ` ${fill(copy.chances.ifFixed, { p: outOf100(m.p_if_fixed) })}` : null}
            </p>
          ))}
        </section>
      ) : null}
      <section className="panel">
        <h2>{copy.chances.eachPart}</h2>
        <StepsList steps={strength.steps} />
        <p className="note">{strength.data_note}</p>
      </section>
    </>
  );
}
