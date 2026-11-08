import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { CaseView, SentenceView } from "@/types/caseview";
import { LetterView, letterParts } from "@/components/LetterView";

const RECORD = "Sleep study: AHI 22 events per hour. Patient tired.";
const LETTER = "Dear plan. My AHI was 22. Please approve.";

function sentence(over: Partial<SentenceView> = {}): SentenceView {
  return {
    criterion_id: "ahi",
    decision: "kept",
    decision_label: "Checked against your records",
    letter_start: 11,
    letter_end: 25,
    policy: { clause: "AHI of 15 or more", source: { label: "NCD 240.4", title: "CPAP", url: "https://example.org" } },
    record: { doc_id: "doc-1", char_start: 13, char_end: 35, quote: "AHI 22 events per hour" },
    score: 0.9,
    text: "My AHI was 22.",
    ...over,
  } as SentenceView;
}

function view(sentences: SentenceView[]): CaseView {
  return {
    case_id: "c1",
    mode: "cached",
    documents: [{ doc_id: "doc-1", title: "Sleep study", text: RECORD }],
    letter: { text: LETTER, sentences, unconfirmed: [], not_argued: [] },
  } as unknown as CaseView;
}

describe("letterParts", () => {
  it("cuts the letter at the sentence offsets and keeps every character", () => {
    const parts = letterParts(LETTER, [sentence()]);
    expect(parts.map((p) => p.text).join("")).toBe(LETTER);
    expect(parts.filter((p) => p.kind === "sentence").map((p) => p.text)).toEqual(["My AHI was 22."]);
  });

  it("skips sentences without offsets", () => {
    const parts = letterParts(LETTER, [sentence({ letter_start: null, letter_end: null })]);
    expect(parts).toEqual([{ kind: "text", text: LETTER }]);
  });
});

describe("LetterView", () => {
  it("marks exactly the record span of the chosen sentence and announces it", async () => {
    render(<LetterView view={view([sentence()])} />);
    expect(screen.queryByTestId("source-mark")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /My AHI was 22/ }));
    expect(screen.getByTestId("source-mark")).toHaveTextContent(/^AHI 22 events per hour$/);
    expect(screen.getByRole("button", { name: /My AHI was 22/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/Sleep study\. AHI 22 events per hour/)).toBeInTheDocument();
  });

  it("works from the keyboard", async () => {
    render(<LetterView view={view([sentence()])} />);
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    expect(screen.getByTestId("source-mark")).toHaveTextContent("AHI 22 events per hour");
  });
});
