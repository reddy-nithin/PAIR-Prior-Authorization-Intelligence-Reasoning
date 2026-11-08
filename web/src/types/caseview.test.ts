import { execFileSync } from "node:child_process";
import { describe, expect, it } from "vitest";

describe("caseview.ts", () => {
  it("matches the checked-in schema (run `npm run gen:types` if this fails)", () => {
    expect(() => execFileSync("node", ["scripts/gen-types.mjs", "--check"], { stdio: "pipe" })).not.toThrow();
  });
});
