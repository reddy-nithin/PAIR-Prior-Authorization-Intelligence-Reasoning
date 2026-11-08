"""Patient copy: plain UI headings and the grade-8 reading level check (Phase 4 T3).

Rule (plan §Phase 4, spec §10): patient text targets grade 8. Flesch-Kincaid on a
three-word label is noise, so each copy group is scored as a whole (≤ 8) and each
item of 6+ words on its own (≤ 10). Required terms with no plain synonym (named
in ``REQUIRED_TERMS``) become a one-syllable placeholder before scoring; every
other word counts.
"""

import json
import re
from pathlib import Path

import pytest
import textstat
import yaml

from pair.contracts import Checklist
from pair.pipeline import Resources
from pair.score.strength import IMR_NOTE, load_ship_links
from pair.ui.copy import UiCopyError, load_ui_headings, mid_sentence
from pair.ui.view import DECISION_LABEL, REASON_PLAIN, STATUS_DISPLAY, UNMET_WHO
from tests.conftest import REPO_ROOT

GROUP_MAX, ITEM_MAX, ITEM_MIN_WORDS = 8.0, 10.0, 6
REQUIRED_TERMS = (
    "42 CFR 422.101(b)", "CMS-4201-F", "Medicare Advantage", "national coverage determinations",
    "local coverage determinations", "State Health Insurance Assistance Program", "radiculopathy",
    "neurogenic claudication", "physical therapy", "diagnostic", "Medicare", "AHI", "RDI", "PO2", "PAP", "RFA",
)  # fmt: skip
WEB_COPY = REPO_ROOT / "web" / "src" / "copy" / "en.json"


def scorable(text: str) -> str:
    """Text with placeholders and required terms swapped for a short word, ending in a period."""
    text = re.sub(r"\{[a-z_]+\}|\[[A-Za-z ]+\]", "it", text)
    for term in REQUIRED_TERMS:
        text = text.replace(term, "term")
    text = text.strip()
    return text if text.endswith((".", "?", "!", ":")) else text + "."


def grade(texts: list[str]) -> float:
    """Flesch-Kincaid grade of the texts read one after another."""
    return float(textstat.flesch_kincaid_grade(" ".join(scorable(t) for t in texts)))


def web_strings() -> list[str]:
    """Every string in the web app's copy file."""
    def walk(node: object) -> list[str]:
        if isinstance(node, dict):
            return [s for value in node.values() for s in walk(value)]
        if isinstance(node, list):
            return [s for value in node for s in walk(value)]
        return [node] if isinstance(node, str) else []
    return walk(json.loads(WEB_COPY.read_text()))


def groups(resources: Resources) -> dict[str, list[str]]:
    """Every patient-facing text, by group."""
    letter = yaml.safe_load((REPO_ROOT / "policies" / "_letter.yaml").read_text())
    ui = load_ui_headings(REPO_ROOT / "policies" / "_ui.yaml", resources.checklists)
    return {
        "view labels": [*(s.label for s in STATUS_DISPLAY.values()), *REASON_PLAIN.values(),
                        *DECISION_LABEL.values(), UNMET_WHO, IMR_NOTE],
        "gap messages": list(resources.gaps.all_messages()),
        "help links": [link.note for link in load_ship_links(REPO_ROOT / "policies" / "_ship.yaml")],
        "ui headings": list(ui.values()),
        "letter": [letter[k] for k in ("opening", "ma_argument", "policy_intro", "conclusion", "closing", "notice")]
        + list(letter["headings"].values()),
        "web copy": web_strings(),
    }  # fmt: skip


def test_every_group_reads_at_grade_8(resources: Resources) -> None:
    """Each copy group as a whole is grade 8 or lower."""
    scores = {name: grade(texts) for name, texts in groups(resources).items()}
    assert all(score <= GROUP_MAX for score in scores.values()), scores


def test_no_long_item_is_far_above_grade_8(resources: Resources) -> None:
    """No single item of 6+ words is above grade 10."""
    hard = [
        (round(grade([text]), 1), name, text)
        for name, texts in groups(resources).items()
        for text in texts
        if len(text.split()) >= ITEM_MIN_WORDS and grade([text]) > ITEM_MAX
    ]
    assert not hard, hard


def test_ui_headings_cover_every_criterion_in_plain_words(resources: Resources) -> None:
    """One UI heading per criterion, addressed to the patient, without internal tags."""
    ui = load_ui_headings(REPO_ROOT / "policies" / "_ui.yaml", resources.checklists)
    keys = {f"{c.id}/{criterion.id}" for c in resources.checklists.values() for criterion in c.criteria}
    assert set(ui) == keys
    assert all("ADR" not in text and "practitioner" not in text for text in ui.values())


def test_web_copy_exists_for_every_screen() -> None:
    """The web app's chrome strings have a section per screen."""
    copy = json.loads(WEB_COPY.read_text())
    assert {"start", "why", "stand", "missing", "letter", "chances", "download", "common"} <= set(copy)


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("headings: {}\n", "missing"),
        ("headings: {'pap-osa/f2f_visit': ok, 'pap-osa/nope': x}\n", "unknown"),
        ("headings: {'pap-osa/f2f_visit': ''}\n", "empty"),
        ("headings: {'pap-osa/f2f_visit': 'A — visit'}\n", "dash"),
        ("headings: {'pap-osa/f2f_visit': 'Visit (ADR-0015)'}\n", "ADR"),
        ("headings: [1]\n", "mapping"),
        ("headings: {'pap-osa/f2f_visit': ok\n", "YAML"),
    ],
)
def test_bad_ui_heading_files_fail_loudly(tmp_path: Path, pap_only: dict[str, Checklist], text: str, match: str) -> None:
    """Missing, extra, empty, dashed or tagged headings raise ``UiCopyError``."""
    path = tmp_path / "_ui.yaml"
    path.write_text(text)
    with pytest.raises(UiCopyError, match=match):
        load_ui_headings(path, pap_only)


@pytest.fixture
def pap_only(resources: Resources) -> dict[str, Checklist]:
    """A one-criterion PAP checklist for loader structure tests."""
    pap = resources.checklists["pap-osa"]
    return {"pap-osa": pap.model_copy(update={"criteria": pap.criteria[:1], "logic": "f2f_visit"})}


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        ("An in-person visit with your doctor", "an in-person visit with your doctor"),
        ("Group II: PO2 56 to 59", "Group II: PO2 56 to 59"),
        ("PAP use for 30 days", "PAP use for 30 days"),
        ("No other cause was found", "no other cause was found"),
    ],
)
def test_mid_sentence_lowercases_only_ordinary_first_words(heading: str, expected: str) -> None:
    """A heading placed after "…no record yet:" starts lowercase unless it starts with a name or acronym."""
    assert mid_sentence(heading) == expected
