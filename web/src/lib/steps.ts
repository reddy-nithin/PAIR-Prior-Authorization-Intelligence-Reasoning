import { copy } from "@/lib/copy";

export const STEP_IDS = ["why", "stand", "missing", "letter", "chances", "download"] as const;
export type StepId = (typeof STEP_IDS)[number];

/** All 7 steps in order; step 1 is the start page, the rest live under /case/{id}/. */
export const STEPS: { id: "start" | StepId; name: string }[] = [
  { id: "start", name: copy.common.steps.start },
  ...STEP_IDS.map((id) => ({ id, name: copy.common.steps[id] })),
];

/** The URL of a step for a case. */
export function stepHref(caseId: string, id: "start" | StepId): string {
  return id === "start" ? "/" : `/case/${encodeURIComponent(caseId)}/${id}`;
}
