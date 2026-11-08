import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusBadge } from "@/components/StatusBadge";

describe("StatusBadge", () => {
  it.each([
    ["met", "check", "Meets the rule"],
    ["unmet", "cross", "Does not meet the rule"],
    ["insufficient", "question", "Not enough information"],
  ] as const)("shows the words for %s, not only a colour", (status, icon, label) => {
    render(<StatusBadge status={{ status, icon, label }} />);
    expect(screen.getByText(label)).toBeVisible();
    expect(screen.getByText(label)).toHaveClass("tag", status);
  });

  it("still shows the words when the icon is unknown", () => {
    render(<StatusBadge status={{ status: "met", icon: "nope", label: "Meets the rule" }} />);
    expect(screen.getByText("Meets the rule")).toBeVisible();
  });
});
