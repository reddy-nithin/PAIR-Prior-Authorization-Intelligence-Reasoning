"""Draw the README pipeline diagram as plain SVG, in a light and a dark version.

Run: ``python scripts/readme_diagram.py``. Writes ``docs/img/pipeline.svg`` and ``pipeline-dark.svg``.
Two lanes show the core rule: the language model reads and words things; code decides and checks.
"""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs" / "img"

THEMES = {
    "": {"bg": "#ffffff", "ink": "#2a2522", "muted": "#655c54", "line": "#d8d0c6", "llm": "#fbebc8", "llm_ink": "#7a4f00",
         "code": "#e1f0e6", "code_ink": "#1f5c45", "out": "#2f6f62", "out_ink": "#ffffff", "lane": "#faf7f3"},
    "-dark": {"bg": "#0d1117", "ink": "#e6edf3", "muted": "#9aa4ae", "line": "#3a414a", "llm": "#3a2e14", "llm_ink": "#f1c76a",
              "code": "#1d3528", "code_ink": "#8fd3ad", "out": "#1f9e7e", "out_ink": "#0d1117", "lane": "#161b22"},
}  # fmt: skip

# (step, lane, title, detail). Lane "llm" = language model, "code" = deterministic code or a checking model.
STEPS = [
    (1, "llm", "Read the denial", "service, codes, reason"),
    (2, "code", "Pick the checklist", "NCD / LCD as YAML rules"),
    (3, "llm", "Find evidence", "quotes with exact offsets"),
    (4, "code", "Rule engine", "met / not met / not sure"),
    (5, "llm", "Draft the letter", "one claim per sentence"),
    (6, "code", "Verify every sentence", "span → MiniCheck → conformal"),
    (7, "code", "Strength or get a human", "IMR model, or abstains"),
]

W, H = 1160, 380
COL0, COLW, BOXW, BOXH = 150, 118, 108, 96
LANE_Y = {"llm": 70, "code": 214}
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"


def esc(text: str) -> str:
    """Escape text for SVG."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def wrap(text: str, limit: int = 15) -> list[str]:
    """Split a label into short lines at word breaks."""
    lines: list[str] = []
    for word in text.split():
        if lines and len(lines[-1]) + len(word) + 1 <= limit:
            lines[-1] += f" {word}"
        else:
            lines.append(word)
    return lines


def box(step: int, lane: str, head: str, detail: str, c: dict[str, str]) -> str:
    """One rounded step box with a number badge, title and detail."""
    x = COL0 + (step - 1) * COLW
    y = LANE_Y[lane]
    fill, ink = (c["llm"], c["llm_ink"]) if lane == "llm" else (c["code"], c["code_ink"])
    parts = [
        f'<rect x="{x}" y="{y}" width="{BOXW}" height="{BOXH}" rx="14" fill="{fill}"/>',
        f'<circle cx="{x + 16}" cy="{y + 16}" r="10" fill="{ink}"/>',
        f'<text x="{x + 16}" y="{y + 20}" font-size="11" font-weight="700" fill="{c["bg"]}" text-anchor="middle">{step}</text>',
    ]
    for i, line in enumerate(wrap(head, 14)):
        parts.append(f'<text x="{x + 10}" y="{y + 44 + i * 15}" font-size="12.5" font-weight="700" fill="{c["ink"]}">{esc(line)}</text>')
    offset = 44 + len(wrap(head, 14)) * 15 + 2
    for i, line in enumerate(wrap(detail, 17)):
        parts.append(f'<text x="{x + 10}" y="{y + offset + i * 13}" font-size="10.5" fill="{c["muted"]}">{esc(line)}</text>')
    return "".join(parts)


def arrow(a: int, b: int, c: dict[str, str]) -> str:
    """A connector from the right of step a to the left of step b, across lanes when needed."""
    la, lb = STEPS[a - 1][1], STEPS[b - 1][1]
    x1, y1 = COL0 + (a - 1) * COLW + BOXW, LANE_Y[la] + BOXH / 2
    x2, y2 = COL0 + (b - 1) * COLW, LANE_Y[lb] + BOXH / 2
    mid = (x1 + x2) / 2
    path = f"M{x1},{y1} C{mid},{y1} {mid},{y2} {x2 - 4},{y2}"
    return f'<path d="{path}" fill="none" stroke="{c["line"]}" stroke-width="2" marker-end="url(#ah)"/>'


def svg(c: dict[str, str]) -> str:
    """The whole diagram for one theme."""
    lanes = "".join(
        f'<rect x="16" y="{LANE_Y[k] - 18}" width="{W - 32}" height="{BOXH + 36}" rx="18" fill="{c["lane"]}"/>'
        f'<text x="32" y="{LANE_Y[k] + 30}" font-size="12" font-weight="700" fill="{fg}">{esc(t1)}</text>'
        f'<text x="32" y="{LANE_Y[k] + 47}" font-size="11" fill="{c["muted"]}">{esc(t2)}</text>'
        for k, fg, t1, t2 in (
            ("llm", c["llm_ink"], "Language model", "reads and words"),
            ("code", c["code_ink"], "Code and checks", "decide and verify"),
        )
    )
    inputs = (
        f'<text x="32" y="40" font-size="12" fill="{c["muted"]}">In: denial letter + medical records (PDF, photo or text)</text>'
    )
    out_x = COL0 + 7 * COLW
    output = (
        f'<rect x="{out_x}" y="{LANE_Y["llm"]}" width="{W - out_x - 32}" height="{LANE_Y["code"] + BOXH - LANE_Y["llm"]}" rx="16" fill="{c["out"]}"/>'
        + "".join(
            f'<text x="{out_x + 14}" y="{LANE_Y["llm"] + 30 + i * 19}" font-size="{13 if i == 0 else 11.5}" font-weight="{700 if i == 0 else 400}" fill="{c["out_ink"]}">{esc(t)}</text>'
            for i, t in enumerate(["8  For the patient", "Why they said no", "Where you stand", "What's missing", "Cited letter", "Your chances", "Word + PDF"])
        )
    )
    arrows = "".join(arrow(i, i + 1, c) for i in range(1, 7))
    last = STEPS[6]
    x7, y7 = COL0 + 6 * COLW + BOXW, LANE_Y[last[1]] + BOXH / 2
    arrows += f'<path d="M{x7},{y7} L{out_x - 4},{y7}" stroke="{c["line"]}" stroke-width="2" marker-end="url(#ah)"/>'
    foot = (
        f'<text x="32" y="{H - 22}" font-size="11.5" fill="{c["muted"]}">'
        "The model never decides coverage. Every letter sentence must quote a record span and a policy clause, "
        "or it is kept out.</text>"
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="{FONT}" role="img" '
        f'aria-label="PAIR pipeline: a language model reads the denial, finds evidence and drafts the letter; code picks the checklist, '
        f'decides each requirement, verifies every sentence and scores strength or says get a human.">'
        f'<defs><marker id="ah" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M0,0 L10,5 L0,10 z" fill="{c["line"]}"/></marker></defs>'
        f'<rect width="{W}" height="{H}" rx="20" fill="{c["bg"]}"/>{inputs}{lanes}{arrows}'
        + "".join(box(s, lane, h, d, c) for s, lane, h, d in STEPS)
        + f"{output}{foot}</svg>"
    )


def main() -> None:
    """Write both themes."""
    OUT.mkdir(parents=True, exist_ok=True)
    for suffix, colours in THEMES.items():
        (OUT / f"pipeline{suffix}.svg").write_text(svg(colours), encoding="utf-8")
    print(f"wrote pipeline diagrams to {OUT}")


if __name__ == "__main__":
    main()
