"use client";

import { FlagIcon } from "@/components/Icons";
import { LetterView } from "@/components/LetterView";
import { StatusBadge } from "@/components/StatusBadge";
import { StepNav } from "@/components/Stepper";
import { useCase } from "@/lib/case-context";
import { copy } from "@/lib/copy";

export default function LetterPage() {
  const view = useCase();
  const letter = view.letter;
  return (
    <>
      <div className="stack">
        <h1>{copy.letter.title}</h1>
        <p className="lede">{copy.letter.intro}</p>
        
      </div>
      {letter ? <p className="fillin">{copy.letter.fillIn}</p> : null}
      <LetterView view={view} />
      {letter?.unconfirmed.length ? (
        <section className="card tight" aria-labelledby="unconf-h">
          <h2 id="unconf-h">{copy.letter.unconfirmedTitle}</h2>
          <p>{copy.letter.unconfirmedIntro}</p>
          <ul className="links">
            {letter.unconfirmed.map((s) => (
              <li className="flagline" key={`${s.criterion_id}-${s.record.char_start}`}>
                <span className="tag unmet"><FlagIcon />{s.decision_label}</span>
                <span>{s.text}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {letter?.not_argued.length ? (
        <section className="card tight" aria-labelledby="na-h">
          <h2 id="na-h">{copy.letter.notArguedTitle}</h2>
          <ul className="links">
            {letter.not_argued.map((n) => (
              <li className="flagline" key={n.criterion_id}>
                <StatusBadge status={n.status} />
                <span><b>{n.heading}.</b> {n.message}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <StepNav caseId={view.case_id} current="letter" />
    </>
  );
}
