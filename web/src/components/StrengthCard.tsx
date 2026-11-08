import type { StepView, StrengthView } from "@/types/caseview";
import { CheckIcon, FlagIcon } from "@/components/Icons";
import { copy, fill } from "@/lib/copy";
import { outOf100 } from "@/lib/format";

const EFFECT: Record<StepView["effect"], { label: string; cls: string; Icon: (() => React.JSX.Element) | null }> = {
  raises: { label: copy.chances.helps, cls: "met", Icon: CheckIcon },
  lowers: { label: copy.chances.hurts, cls: "unmet", Icon: FlagIcon },
  "no change": { label: copy.chances.noEffect, cls: "must", Icon: null },
};

/** How each requirement moved the estimate: an effect tag (icon + word) beside the requirement. */
export function StepsList({ steps }: { steps: StepView[] }) {
  return (
    <ul className="steps">
      {steps.map((s) => {
        const e = EFFECT[s.effect];
        return (
          <li key={s.criterion_id}>
            <span className={`tag ${e.cls}`}>{e.Icon ? <e.Icon /> : null}{e.label}</span>
            <span>{s.heading} <span className="sr">({s.status.label})</span></span>
          </li>
        );
      })}
    </ul>
  );
}

/** The range in words first, then as 100 dots (won / not sure / did not win). */
export function StrengthCard({ strength }: { strength: StrengthView }) {
  if (strength.low == null || strength.high == null || strength.p == null) return null;
  const lo = outOf100(strength.low);
  const hi = outOf100(strength.high);
  const sentence = fill(copy.chances.range, { low: lo, high: hi });
  return (
    <>
      <section className="card verdict" aria-labelledby="h-score">
        <h2 id="h-score">{sentence}</h2>
        <p className="note">{fill(copy.chances.bestGuess, { p: outOf100(strength.p) })}</p>
        <div className="icons" role="img" aria-label={sentence} data-testid="icon-array">
          {Array.from({ length: 100 }, (_, i) => (
            <i key={i} className={i < lo ? "yes" : i < hi ? "maybe" : undefined} />
          ))}
        </div>
        <div className="legend" aria-hidden="true">
          <span><i className="yes" />{copy.chances.won}</span>
          <span><i className="maybe" />{copy.chances.unsure}</span>
          <span><i />{copy.chances.lost}</span>
        </div>
        {strength.base_rate != null ? <p className="pill-note">{fill(copy.chances.before, { p: outOf100(strength.base_rate) })}</p> : null}
      </section>
      {strength.improve.length ? (
        <section className="card soft">
          <h2>{copy.chances.whatHelps}</h2>
          {strength.improve.map((m) => (
            <p key={m.criterion_id}>
              <b>{m.heading}.</b> {m.action}
              {m.p_if_fixed != null ? ` ${fill(copy.chances.ifFixed, { p: outOf100(m.p_if_fixed) })}` : null}
            </p>
          ))}
        </section>
      ) : null}
      <section className="card">
        <h2>{copy.chances.eachPart}</h2>
        <StepsList steps={strength.steps} />
      </section>
      <p className="note">{strength.data_note}</p>
    </>
  );
}
