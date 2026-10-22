"""Critic output validation, seeded-fault scoring and the audit CLI (ADR-0013)."""

import json
from pathlib import Path
from typing import Any

import pytest

from pair.cli import main
from pair.eval.audit import PrecheckFinding, Severity
from pair.eval.cases import save_case
from pair.eval.critic import (
    CriticOutputError,
    ValidatedOutput,
    Verdict,
    case_documents,
    policy_text,
    score_seeded,
    validate_output,
)
from pair.policies.mcd import MCDExport
from tests.eval.test_audit import CHECKLISTS, make
from tests.eval.test_faults import suite_cases

FIXTURE_MCD = Path(__file__).parents[1] / "fixtures" / "mcd"


def write_jsonl(path: Path, rows: list[Any]) -> Path:
    """Write rows (dicts or raw strings) as JSONL."""
    path.write_text("\n".join(r if isinstance(r, str) else json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def row(check: str = "L1", verdict: str = "fail", severity: str = "blocker", quotes: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """One verdict row."""
    return {"case_id": "c", "check_id": check, "target": "t", "verdict": verdict, "severity": severity,
            "quotes": quotes or [], "source_urls": [], "reasoning": "r"}  # fmt: skip


DOCS = {"clinic": "Sleep medicine visit 04/30/2026.\nAHI 22.4   events/hour", "denial": "We denied it."}


def test_verbatim_quotes_are_kept_whitespace_insensitive(tmp_path: Path) -> None:
    """A quote that matches up to whitespace is valid."""
    path = write_jsonl(tmp_path / "c.jsonl", [row(quotes=[{"doc_id": "clinic", "text": "AHI 22.4 events/hour"}])])
    out = validate_output(path, DOCS)
    assert out.rejected == [] and out.verdicts[0].quotes[0]["doc_id"] == "clinic"


@pytest.mark.parametrize(
    ("bad", "reason"),
    [
        (row(quotes=[{"doc_id": "clinic", "text": "AHI 25 events/hour"}]), "not verbatim"),
        (row(quotes=[{"doc_id": "lab", "text": "AHI"}]), "unknown doc"),
        (row(verdict="maybe"), "bad verdict"),
        (row(severity="huge"), "bad verdict"),
        ("not json", "not JSON"),
        ("[1, 2]", "not an object"),
    ],
)
def test_bad_lines_are_rejected(tmp_path: Path, bad: Any, reason: str) -> None:
    """Invented quotes, unknown docs and malformed rows never count."""
    out = validate_output(write_jsonl(tmp_path / "c.jsonl", [bad]), DOCS)
    assert out.verdicts == [] and reason in out.rejected[0]


def test_quoteless_pass_becomes_a_fail(tmp_path: Path) -> None:
    """Rubric: a pass needs a quote."""
    out = validate_output(write_jsonl(tmp_path / "c.jsonl", [row(verdict="pass"), row("SUMMARY", "pass")]), DOCS)
    assert [(v.verdict, v.coerced) for v in out.verdicts] == [("fail", True), ("pass", False)]


def test_missing_output_is_an_error(tmp_path: Path) -> None:
    """A critic run that wrote nothing is reported, not silently scored as clean."""
    with pytest.raises(CriticOutputError):
        validate_output(tmp_path / "none.jsonl", DOCS)


def test_case_documents_cover_the_doc_ids() -> None:
    """Notes, the denial, the LCD text and each clause are quotable."""
    case = make()
    docs = case_documents(case, CHECKLISTS["pap-osa"], "LCD TEXT")
    assert {"clinic", "report", "denial", "lcd", "policy:ahi_threshold"} <= docs.keys()


def test_policy_text_dumps_sources() -> None:
    """The fixture LCD's sections come out as plain text with a header."""
    checklist = CHECKLISTS["pap-osa"].model_copy(
        update={"sources": [CHECKLISTS["pap-osa"].sources[0].model_copy(update={"type": "LCD", "id": "L99001"})]}
    )
    text = policy_text(checklist, MCDExport(FIXTURE_MCD))
    assert text.startswith("=== LCD L99001") and "--- " in text


def verdict(check: str, value: str = "fail", severity: str = "blocker", coerced: bool = False) -> Verdict:
    """A validated verdict."""
    return Verdict("x", check, "t", value, severity, "r", coerced=coerced)


KEY = [
    {"seed_id": "s1", "fault": {"kind": "paraphrase_leak", "expected": ["K1", "L1"], "severity": "blocker", "target": "a"}},
    {"seed_id": "s2", "fault": {"kind": "label_flip", "expected": ["L1"], "severity": "blocker", "target": "b"}},
    {"seed_id": "s3", "fault": {"kind": "age_mismatch", "expected": ["R1"], "severity": "major", "target": "p"}},
    {"seed_id": "s4", "fault": None},
    {"seed_id": "s5", "fault": None},
]  # fmt: skip


def test_score_counts_catches_misses_and_false_alarms() -> None:
    """Critic fails and precheck findings both catch; uncertain and coerced don't; clean blockers are false alarms."""
    outputs = {
        "s1": ValidatedOutput([verdict("K1")]),
        "s3": ValidatedOutput([verdict("R1", "uncertain", "major")]),
        "s4": ValidatedOutput([verdict("R2", "fail", "major"), verdict("L1", coerced=True)]),
        "s5": ValidatedOutput([verdict("D1")]),
    }
    precheck = [PrecheckFinding("s2", "L1", "b", Severity.BLOCKER, "flip")]
    score = score_seeded(KEY, outputs, precheck)
    assert (score.caught, score.n_faults, score.blocker_caught, score.n_blocker_faults) == (2, 3, 2, 2)
    assert score.blocker_catch_rate == 1.0
    assert score.misses == ["s3 age_mismatch (p)"]
    assert (score.clean_false_blockers, score.false_alarms) == (1, ["s5"])
    assert score.by_kind == {"age_mismatch": (0, 1), "label_flip": (1, 1), "paraphrase_leak": (1, 1)}
    assert score.coerced == 1


def test_audit_seed_and_score_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``pair audit seed`` writes cases + a separate key; ``score`` with no critic output reports it missing."""
    cases_dir = tmp_path / "cases"
    for case in suite_cases():
        save_case(case, cases_dir / case.policy_id / f"{case.id}.json")
    seeded, key = tmp_path / "seeded", tmp_path / "seed-key" / "key.json"
    args = ["audit", "seed", "--cases", str(cases_dir), "--out", str(seeded), "--key", str(key), "--seed", "5"]
    assert main(args) == 0
    data = json.loads(key.read_text(encoding="utf-8"))
    assert len(data["key"]) == 30 and len(list(seeded.glob("*/*.json"))) == 30
    lcd = tmp_path / "lcd"
    lcd.mkdir()
    for policy_id in CHECKLISTS:
        (lcd / f"{policy_id}.txt").write_text("LCD", encoding="utf-8")
    results = tmp_path / "RESULTS.md"
    critic = tmp_path / "critic"
    critic.mkdir()
    score_args = ["audit", "score", "--seeded", str(seeded), "--critic", str(critic), "--key", str(key),
                  "--lcd", str(lcd), "--results", str(results)]  # fmt: skip
    assert main(score_args) == 1
    assert "outputs missing: 30" in capsys.readouterr().out
    assert "<!-- audit-critic:start -->" in results.read_text(encoding="utf-8")
