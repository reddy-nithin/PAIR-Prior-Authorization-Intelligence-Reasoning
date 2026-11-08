"use client";

import { useEffect, useState } from "react";
import type { GapGroup } from "@/types/caseview";
import { StatusBadge } from "@/components/StatusBadge";
import { PersonIcon } from "@/components/Icons";
import { copy, fill } from "@/lib/copy";

const KEY = "pair-gap-ticks";

/** Ticks are a per-device convenience: they hold criterion ids only, never case text. */
function readTicks(caseId: string): Record<string, boolean> {
  try {
    return (JSON.parse(localStorage.getItem(KEY) ?? "{}") as Record<string, Record<string, boolean>>)[caseId] ?? {};
  } catch {
    return {};
  }
}
function writeTicks(caseId: string, ticks: Record<string, boolean>): void {
  try {
    const all = JSON.parse(localStorage.getItem(KEY) ?? "{}") as Record<string, Record<string, boolean>>;
    localStorage.setItem(KEY, JSON.stringify({ ...all, [caseId]: ticks }));
  } catch {
    /* storage blocked: ticks last for this visit only */
  }
}

/** What's missing, grouped by who can provide it, with a tick box per item. */
export function GapChecklist({ caseId, groups, persist }: { caseId: string; groups: GapGroup[]; persist: boolean }) {
  const [ticks, setTicks] = useState<Record<string, boolean>>({});
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- localStorage is only readable after mount
    if (persist) setTicks(readTicks(caseId));
  }, [caseId, persist]);
  const toggle = (id: string, on: boolean) => {
    const next = { ...ticks, [id]: on };
    setTicks(next);
    if (persist) writeTicks(caseId, next);
  };
  return (
    <>
      {groups.map((group) => (
        <section className="card who" key={group.who}>
          <h2 className="who-h">
            <span className="icon-dot"><PersonIcon /></span>
            {fill(copy.missing.askWho, { who: group.who })}
          </h2>
          {group.items.map((item) => {
            const id = `todo-${item.criterion_id}`;
            return (
              <div className={`todo${ticks[item.criterion_id] ? " checked" : ""}`} key={item.criterion_id}>
                <input type="checkbox" id={id} checked={!!ticks[item.criterion_id]} onChange={(e) => toggle(item.criterion_id, e.target.checked)} />
                <label htmlFor={id}>
                  <b className="h">{item.heading}</b>
                  <span>{item.message}</span>
                  <StatusBadge status={item.status} />
                </label>
              </div>
            );
          })}
        </section>
      ))}
    </>
  );
}
