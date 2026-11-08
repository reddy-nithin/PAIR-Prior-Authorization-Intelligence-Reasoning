import en from "@/copy/en.json";

export const copy = en;

/** Fill `{name}` placeholders in a copy string. */
export function fill(text: string, vars: Record<string, string | number>): string {
  return text.replace(/\{(\w+)\}/g, (_, key: string) => String(vars[key] ?? `{${key}}`));
}
