import type { CaseView } from "@/types/caseview";
import { copy } from "@/lib/copy";
import { longDate } from "@/lib/format";

/** The denial at a glance, like the reference block on a notice. */
export function CaseStrip({ view }: { view: CaseView }) {
  const d = view.denial;
  return (
    <div className="strip-ref" aria-label="Your denial">
      {d ? (
        <>
          <span>{copy.common.service} <b>{d.service}</b></span>
          <span>{copy.common.code} <b className="code">{d.codes.join(", ") || copy.common.notNamed}</b></span>
          <span>{copy.common.denied} <b>{longDate(d.date)}</b></span>
          <span>{copy.common.rule} <b className="code">{d.cited_rule?.label ?? copy.common.notNamed}</b></span>
        </>
      ) : null}
      <span className="chip">{view.mode === "live" ? copy.common.liveChip : copy.common.demoChip}</span>
    </div>
  );
}
