import type { LinkView, StrengthView } from "@/types/caseview";
import { PersonIcon } from "@/components/Icons";
import { StepsList } from "@/components/StrengthCard";
import { copy } from "@/lib/copy";

/** "Talk to a person first": the reason, free help, and what would help. Never shows a number. */
export function GetAHumanCard({ strength, links }: { strength: StrengthView; links: LinkView[] }) {
  return (
    <>
      <section className="verdict" aria-labelledby="h-human">
        <h2 id="h-human"><PersonIcon />{copy.chances.getHuman}</h2>
        <p>{strength.reason}</p>
        <p>{copy.chances.noNumber}</p>
        <p>{copy.chances.getHumanIntro}</p>
      </section>
      <section className="panel">
        <h2>{copy.chances.freeHelp}</h2>
        <ul className="links">
          {links.map((link) => (
            <li key={link.url}>
              <a href={link.url} target="_blank" rel="noopener noreferrer">{link.name}</a>
              <br />
              <span>{link.note}</span>
              <br />
              <span className="url">{link.url}</span>
            </li>
          ))}
        </ul>
      </section>
      {strength.improve.length ? (
        <section className="panel">
          <h2>{copy.chances.whatHelps}</h2>
          {strength.improve.map((m) => (
            <p key={m.criterion_id}><b>{m.heading}.</b> {m.action}</p>
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
