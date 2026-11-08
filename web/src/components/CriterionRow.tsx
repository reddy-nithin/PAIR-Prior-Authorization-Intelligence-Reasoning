"use client";

import * as Collapsible from "@radix-ui/react-collapsible";
import type { CriterionView } from "@/types/caseview";
import { StatusBadge } from "@/components/StatusBadge";
import { ChevronIcon } from "@/components/Icons";
import { copy } from "@/lib/copy";

/** One requirement: heading and status; opens to the record lines, the rule text and how it was decided. */
export function CriterionRow({ criterion, titles }: { criterion: CriterionView; titles: Record<string, string> }) {
  return (
    <Collapsible.Root asChild>
      <li>
        <Collapsible.Trigger className="row">
          <b>{criterion.heading}</b>
          <span className="tags">
            {criterion.critical ? <span className="tag must">{copy.stand.required}</span> : null}
            <StatusBadge status={criterion.status} />
            <ChevronIcon />
          </span>
        </Collapsible.Trigger>
        <Collapsible.Content className="detail">
          <div>
            <p className="eyebrow">{copy.stand.recordSays}</p>
            {criterion.quotes.length ? (
              <ul className="evid">
                {criterion.quotes.map((q) => (
                  <li key={`${q.doc_id}-${q.char_start}`}>
                    <mark>{q.quote}</mark>
                    <span className="note">{titles[q.doc_id] ?? q.doc_id}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="note">{copy.stand.noRecord}</p>
            )}
          </div>
          <div>
            <p className="eyebrow">{`${copy.stand.ruleSays} (${criterion.policy.source.label})`}</p>
            <p className="clause">“{criterion.policy.clause}”</p>
          </div>
          <details className="trace">
            <summary>{copy.stand.howDecided}</summary>
            <pre>{criterion.trace}</pre>
          </details>
        </Collapsible.Content>
      </li>
    </Collapsible.Root>
  );
}
