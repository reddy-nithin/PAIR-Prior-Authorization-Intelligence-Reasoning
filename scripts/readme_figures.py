"""Draw the README charts from the numbers in RESULTS.md, in a light and a dark version.

Run: ``uv run --with matplotlib python scripts/readme_figures.py``. Writes SVGs to ``docs/img/``.
The numbers below are copied from RESULTS.md (Phase 2 run 3 and dev, Phase 3 trust run, IMR 2024+);
update both together.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parents[1] / "docs" / "img"


@dataclass(frozen=True)
class Theme:
    """Colours for one mode. Series hues were checked with a colour-blind palette validator."""

    name: str
    surface: str
    ink: str
    muted: str
    grid: str
    a: str  # series 1 (teal)
    b: str  # series 2 (amber)
    neutral: str


LIGHT = Theme("light", "#ffffff", "#2a2522", "#655c54", "#ece6de", "#008a6e", "#c4841d", "#b9b0a6")
DARK = Theme("dark", "#0d1117", "#e6edf3", "#9aa4ae", "#262c33", "#1f9e7e", "#b8801f", "#4a525b")

# RESULTS.md, Phase 2 (F1 per status) on the 30 test cases and the 30 held-out dev cases.
F1 = {"Met": (0.96, 0.98), "Not met": (0.88, 0.93), "Not enough info": (0.86, 0.92), "Macro-F1": (0.90, 0.94)}
# RESULTS.md, Phase 3 claim funnel.
SUPPORT = [("Drafted sentences, before the verifier", 245, 292), ("Sentences kept in the letter", 153, 154)]
# RESULTS.md, Phase 3 conformal leak rate (kept among unsupported), alpha 0.1.
LEAK = {"point": 1 / 47, "low": 0.0, "high": 0.081, "max_point": 0.15, "max_upper": 0.30}
# RESULTS.md, IMR 2024+ reliability table: (mean predicted, observed overturn rate, n).
RELIABILITY = [
    (0.064, 0.444, 9), (0.170, 0.198, 91), (0.265, 0.314, 220), (0.357, 0.359, 306), (0.475, 0.566, 961),
    (0.551, 0.611, 1106), (0.649, 0.629, 278), (0.766, 0.803, 1448), (0.864, 0.869, 1441), (0.945, 0.931, 131),
]  # fmt: skip


def style(ax: plt.Axes, t: Theme, *, xgrid: bool = False) -> None:
    """Recessive axes: no top/right spines, thin grid, muted tick labels."""
    ax.set_facecolor(t.surface)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(t.grid)
    ax.tick_params(colors=t.muted, labelsize=10, length=0)
    ax.grid(axis="x" if xgrid else "y", color=t.grid, linewidth=0.8)
    ax.set_axisbelow(True)


def save(fig: plt.Figure, stem: str, t: Theme) -> None:
    """Write one SVG per theme; the dark file gets a -dark suffix."""
    OUT.mkdir(parents=True, exist_ok=True)
    suffix = "" if t.name == "light" else "-dark"
    fig.savefig(OUT / f"{stem}{suffix}.svg", facecolor=t.surface, bbox_inches="tight", pad_inches=0.25)
    plt.close(fig)


def title(fig: plt.Figure, t: Theme, head: str, sub: str) -> None:
    """Left-aligned title and subtitle in text colours, never series colours."""
    ax = fig.axes[0]
    common = {"xy": (0, 1), "xycoords": "axes fraction", "textcoords": "offset points", "ha": "left", "va": "bottom"}
    ax.annotate(head, xytext=(0, 30), color=t.ink, fontsize=14, fontweight="bold", **common)
    ax.annotate(sub, xytext=(0, 14), color=t.muted, fontsize=10, **common)


def f1_chart(t: Theme) -> None:
    """Grouped bars: F1 per status, test vs held-out dev."""
    fig, ax = plt.subplots(figsize=(7.2, 3.6), facecolor=t.surface)
    style(ax, t)
    labels = list(F1)
    w = 0.36
    for k, (name, colour) in enumerate((("Test (30 cases)", t.a), ("Held-out dev (30 cases)", t.b))):
        xs = [i + (k - 0.5) * (w + 0.03) for i in range(len(labels))]
        vals = [F1[lab][k] for lab in labels]
        ax.bar(xs, vals, width=w, color=colour, label=name, edgecolor=t.surface, linewidth=2)
        for x, v in zip(xs, vals, strict=True):
            ax.text(x, v + 0.012, f"{v:.2f}", ha="center", va="bottom", fontsize=9.5, color=t.ink)
    ax.axhline(0.85, color=t.muted, linewidth=1, linestyle=(0, (4, 3)))
    ax.text(len(labels) - 0.5, 0.855, "target 0.85", color=t.muted, fontsize=9, ha="right", va="bottom")
    ax.set_xticks(range(len(labels)), labels, color=t.ink, fontsize=10.5)
    ax.set_ylim(0.5, 1.04)
    ax.legend(frameon=False, loc="upper center", fontsize=9.5, labelcolor=t.ink, ncols=2, bbox_to_anchor=(0.5, -0.1))
    title(fig, t, "Checklist accuracy (F1) per requirement status", "Rule engine verdicts vs gold labels, synthetic cases")
    save(fig, "f1", t)


def support_chart(t: Theme) -> None:
    """Two horizontal bars: share of supported sentences before and after the verifier."""
    fig, ax = plt.subplots(figsize=(7.2, 2.3), facecolor=t.surface)
    style(ax, t, xgrid=True)
    for i, (label, k, n) in enumerate(SUPPORT):
        share = k / n
        ax.barh(i, 1.0, color=t.grid, height=0.5)
        ax.barh(i, share, color=t.neutral if i == 0 else t.a, height=0.5)
        ax.text(share - 0.01, i, f"{share:.1%}", ha="right", va="center", color="#ffffff", fontsize=11, fontweight="bold")
        ax.text(1.01, i, f"{k} of {n}", ha="left", va="center", color=t.muted, fontsize=10)
    ax.set_yticks(range(len(SUPPORT)), [s[0] for s in SUPPORT], color=t.ink, fontsize=10.5)
    ax.invert_yaxis()
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    title(fig, t, "Sentences fully supported by their sources", "Strict support (critic labels), before and after the verifier and conformal filter")
    save(fig, "verifier", t)


def leak_chart(t: Theme) -> None:
    """One estimate with its bootstrap interval against the pre-registered limits."""
    fig, ax = plt.subplots(figsize=(7.2, 1.9), facecolor=t.surface)
    style(ax, t, xgrid=True)
    ax.axvspan(0, LEAK["max_point"], color=t.a, alpha=0.08, linewidth=0)
    ax.hlines(0, LEAK["low"], LEAK["high"], color=t.a, linewidth=3)
    ax.plot([LEAK["point"]], [0], "o", color=t.a, markersize=11, markeredgecolor=t.surface, markeredgewidth=2)
    for x, label in ((LEAK["max_point"], "limit for the estimate (0.15)"), (LEAK["max_upper"], "limit for the upper bound (0.30)")):
        ax.axvline(x, color=t.muted, linewidth=1, linestyle=(0, (4, 3)))
        ax.text(x + 0.004, 0.32, label, color=t.muted, fontsize=9, va="center")
    ax.text(LEAK["point"], -0.36, "0.021  (1 of 47), 95% CI 0.000 to 0.081", color=t.ink, fontsize=10, va="center")
    ax.set_yticks([])
    ax.set_ylim(-0.6, 0.55)
    ax.set_xlim(0, 0.34)
    ax.spines["left"].set_visible(False)
    title(fig, t, "Unsupported sentences that got past the filter", "Leak rate on held-out test patients, patient-level bootstrap interval (ADR-0020)")
    save(fig, "leak", t)


def reliability_chart(t: Theme) -> None:
    """Reliability diagram: predicted vs observed overturn rate, dot area by number of reviews."""
    fig, ax = plt.subplots(figsize=(5.2, 4.6), facecolor=t.surface)
    style(ax, t)
    ax.grid(axis="x", color=t.grid, linewidth=0.8)
    ax.plot([0, 1], [0, 1], color=t.muted, linewidth=1, linestyle=(0, (4, 3)))
    ax.text(0.84, 0.76, "perfect calibration", color=t.muted, fontsize=9, ha="center", va="top", rotation=41)
    xs, ys, ns = zip(*RELIABILITY, strict=True)
    ax.plot(xs, ys, color=t.a, linewidth=2)
    ax.scatter(xs, ys, s=[max(30, n / 6) for n in ns], color=t.a, edgecolor=t.surface, linewidth=2, zorder=3)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Predicted chance the denial is overturned", color=t.ink, fontsize=10)
    ax.set_ylabel("Observed overturn rate", color=t.ink, fontsize=10)
    ax.text(0.03, 0.97, "n = 5,991 reviews, 2024 and later\nAUROC 0.722 · Brier 0.186\ndot area = reviews in the bin", color=t.muted, fontsize=9, va="top")
    title(fig, t, "Strength score calibration", "California IMR outcomes, scored once on unseen years")
    save(fig, "calibration", t)


def main() -> None:
    """Draw every chart in both themes."""
    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"], "svg.fonttype": "none"})
    for t in (LIGHT, DARK):
        f1_chart(t)
        support_chart(t)
        leak_chart(t)
        reliability_chart(t)
    print(f"wrote {len(list(OUT.glob('*.svg')))} SVGs to {OUT}")


if __name__ == "__main__":
    main()
