import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { StrengthView } from "@/types/caseview";
import { GetAHumanCard } from "@/components/GetAHumanCard";
import { StrengthCard } from "@/components/StrengthCard";

const base = {
  reason: "A required item has no record yet.",
  n_similar: 118,
  steps: [{ criterion_id: "f2f", heading: "A visit in person", status: { status: "insufficient", icon: "question", label: "Not enough information" }, effect: "lowers" }],
  improve: [],
  data_note: "Based on public appeal decisions.",
} as const;

describe("GetAHumanCard", () => {
  it("never shows a number out of 100", () => {
    const strength = { ...base, abstain: true, p: 0.41, low: 0.3, high: 0.5, base_rate: 0.45 } as unknown as StrengthView;
    const { container } = render(<GetAHumanCard strength={strength} links={[{ name: "SHIP", note: "Free help", url: "https://www.shiphelp.org" }]} />);
    expect(screen.getByRole("heading", { name: /Talk to a person first/ })).toBeVisible();
    expect(container.textContent).not.toMatch(/\b(41|30|50|45)\b/);
    expect(container.textContent).not.toMatch(/out of 100/);
    expect(screen.getByText("https://www.shiphelp.org")).toBeVisible();
  });
});

describe("StrengthCard", () => {
  it("shows the range in words and as 100 dots", () => {
    const strength = { ...base, abstain: false, p: 0.41, low: 0.3, high: 0.5, base_rate: 0.45 } as unknown as StrengthView;
    render(<StrengthCard strength={strength} />);
    expect(screen.getByRole("img", { name: "About 30 to 50 out of 100 similar appeals won." })).toBeVisible();
    expect(screen.getByTestId("icon-array").children).toHaveLength(100);
  });
});
