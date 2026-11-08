import type { LinkView, StrengthView } from "@/types/caseview";
import { ExternalIcon, PersonIcon, QuestionIcon } from "@/components/Icons";
import { StepsList } from "@/components/StrengthCard";
import { copy } from "@/lib/copy";

/** "Talk to a person first": the reason, free help, and what would help. Never shows a number. */
export function GetAHumanCard({ strength, links }: { strength: StrengthView; links: LinkView[] }) {
  return (
    <>
      <section className="card" aria-labelledby="h-human">
        <div className="human-h">
          <span className="icon-dot"><PersonIcon /></span>
          <h2 id="h-human">{copy.chances.getHuman}</h2>
        </div>
        <p>{copy.chances.getHumanIntro}</p>
        <p className="banner"><QuestionIcon />{strength.reason}</p>
        <p className="note">{copy.chances.noNumber}</p>
        <h3 className="label">{copy.chances.freeHelp}</h3>
        <ul className="links">
          {links.map((link) => (
            <li key={link.url}>
              <a className="helplink" href={link.url} target="_blank" rel="noopener noreferrer">
                <b>{link.name}</b>
                <span>{link.note}</span>
                <span className="url">{link.url}</span>
                <ExternalIcon />
              </a>
            </li>
          ))}
        </ul>
      </section>
      {strength.improve.length ? (
        <section className="card soft">
          <h2>{copy.chances.whatHelps}</h2>
          {strength.improve.map((m) => (
            <p key={m.criterion_id}><b>{m.heading}.</b> {m.action}</p>
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
