/** "2026-07-23" as "July 23, 2026"; anything else unchanged. */
export function longDate(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return iso;
  const date = new Date(Date.UTC(+match[1], +match[2] - 1, +match[3]));
  return date.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric", timeZone: "UTC" });
}

/** A probability (0..1) as a count out of 100. */
export function outOf100(p: number): number {
  return Math.round(p * 100);
}
