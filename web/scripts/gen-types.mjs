// Generate src/types/caseview.ts from the CaseView JSON Schema (written by scripts/export_caseview_schema.py).
// With --check, exit 1 if the checked-in file is stale instead of writing it.
import { readFileSync, writeFileSync } from "node:fs";
import { compile } from "json-schema-to-typescript";

const SCHEMA = new URL("../src/types/caseview.schema.json", import.meta.url);
const OUT = new URL("../src/types/caseview.ts", import.meta.url);
const BANNER = "/* Generated from src/types/caseview.schema.json by `npm run gen:types`. Do not edit. */";

const schema = JSON.parse(readFileSync(SCHEMA, "utf8"));
const ts = await compile(schema, "CaseView", { bannerComment: BANNER, additionalProperties: false, unreachableDefinitions: true });

if (process.argv.includes("--check")) {
  let current = "";
  try { current = readFileSync(OUT, "utf8"); } catch { /* missing file is stale */ }
  if (current !== ts) {
    console.error("src/types/caseview.ts is stale: run `npm run gen:types`");
    process.exit(1);
  }
  console.log("caseview.ts is current");
} else {
  writeFileSync(OUT, ts);
  console.log("wrote src/types/caseview.ts");
}
