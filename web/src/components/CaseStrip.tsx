import type { CaseView } from "@/types/caseview";
import { FileIcon } from "@/components/Icons";
import { copy } from "@/lib/copy";
import { longDate } from "@/lib/format";

/** The denial at a glance, as one chip above the page title. */
export function CaseStrip({ view }: { view: CaseView }) {
  const d = view.denial;
  if (!d) return null;
  const parts = [
    d.service,
    d.codes.join(", ") || null,
    `${copy.common.denied.toLowerCase()} ${longDate(d.date)}`,
    `${copy.common.rule.toLowerCase()} ${d.cited_rule?.label ?? copy.common.notNamed.toLowerCase()}`,
  ].filter(Boolean);
  return (
    <p className="casechip" aria-label="Your denial">
      <FileIcon />
      <span>{parts.join(" · ")}</span>
    </p>
  );
}

/** The tag in the top bar: demo or live. */
export function ModeTag({ view }: { view: CaseView }) {
  return <span className="tag insufficient">{view.mode === "live" ? copy.common.liveChip : copy.common.demoTag}</span>;
}
