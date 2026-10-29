"""Phase 3 commands with injected fakes: draft-claims, fit-threshold, eval-trust, imr-fit, imr-test, run --trust."""

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from pair import cli
from pair.contracts import ClaimDecision
from pair.eval.claims import read_records, write_records
from pair.llm import LLMResponseError
from pair.verify.conformal import ThresholdBook
from tests.conftest import REPO_ROOT
from tests.eval.test_trust_metrics import rec
from tests.fakes import FakeLLM
from tests.score.test_base_model import synthetic
from tests.test_pipeline import denial_reply, gold_extract

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "cases" / "pap-osa-fixture.json"


class FakeVerifier:
    """Scores every claim the same."""

    def __init__(self, score: float = 0.9) -> None:
        self.value = score

    def score(self, claim: str, premise: str) -> float:
        """The fixed score."""
        return self.value

    def describe(self) -> dict[str, str]:
        """Run metadata for the Phase 3 pair."""
        return {"verifier_backend": "minicheck", "verifier_model": "bespoke-minicheck", "verifier_host": "fake"}


def wording_failures(n: int = 60) -> list[dict[str, object] | str | Exception]:
    """Replies that make every claim fall back to its verbatim quote."""
    return [LLMResponseError("offline")] * n


def cases_dir(tmp_path: Path) -> Path:
    """A cases folder holding the fixture case."""
    folder = tmp_path / "cases" / "pap-osa"
    folder.mkdir(parents=True)
    shutil.copy(FIXTURE, folder / "pap-osa-fixture.json")
    return tmp_path / "cases"


def test_draft_claims_writes_records_with_run_tags(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Predicted evidence in, one record per claim out; no threshold file means 'not evaluated'."""
    out = tmp_path / "claims.jsonl"
    code = cli.main(
        ["draft-claims", "--cases", str(cases_dir(tmp_path)), "--out", str(out),
         "--thresholds", str(tmp_path / "none.json")],
        client=FakeLLM([denial_reply(), *wording_failures()]), extract_fn=gold_extract, verifier=FakeVerifier(),
    )
    records = read_records(out)
    assert code == 0 and records
    assert {r.drafter for r in records} == {"gemma4:e4b"}
    assert {r.premise_rule for r in records} == {"adr-0022"}
    assert all(r.decision is None and r.score == 0.9 for r in records)
    assert json.loads(out.with_suffix(".meta.json").read_text())["threshold"] == "none"
    assert "claims" in capsys.readouterr().out


def labeled_dev(tmp_path: Path, n_unsupported: int) -> tuple[Path, Path]:
    """Dev records and labels with ``n_unsupported`` strict-unsupported claims plus 5 supported."""
    records = [rec(f"u{i}", f"c{i % 3}", "f2f_visit", None).model_copy(update={"score": i / 20})
               for i in range(n_unsupported)]
    records += [rec(f"s{i}", "c0", "f2f_visit", None) for i in range(5)]
    labels = {f"u{i}": "unsupported" for i in range(n_unsupported)} | {f"s{i}": "supported" for i in range(5)}
    claims, label_file = tmp_path / "dev.jsonl", tmp_path / "labels.json"
    write_records(records, claims)
    label_file.write_text(json.dumps(labels))
    return claims, label_file


def test_fit_threshold_writes_the_book(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Eleven strict-unsupported dev claims: q-hat is fit and saved for the pair."""
    claims, labels = labeled_dev(tmp_path, 11)
    book = tmp_path / "thresholds.json"
    code = cli.main(["fit-threshold", "--claims", str(claims), "--labels", str(labels), "--thresholds", str(book)],
                    client=FakeLLM([]))
    threshold = ThresholdBook.load(book).lookup("gemma4:e4b", "minicheck", "bespoke-minicheck")
    assert code == 0 and threshold is not None and threshold.n == 11 and threshold.premise_rule == "adr-0022"
    assert "P(leak > 0.2)" in capsys.readouterr().out


def test_fit_threshold_refuses_below_eleven(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Ten negatives: no threshold, the count is printed, exit 1."""
    claims, labels = labeled_dev(tmp_path, 10)
    code = cli.main(["fit-threshold", "--claims", str(claims), "--labels", str(labels),
                     "--thresholds", str(tmp_path / "t.json")], client=FakeLLM([]))
    assert code == 1 and not (tmp_path / "t.json").exists()
    assert "10 unsupported" in capsys.readouterr().err


def test_eval_trust_writes_results_and_log(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Funnel, rates and an 'inconclusive' verdict go to RESULTS.md and a JSONL log."""
    case_id = json.loads(FIXTURE.read_text())["id"]
    records = [rec(f"k{i}", case_id, "f2f_visit", ClaimDecision.KEEP) for i in range(3)]
    claims = tmp_path / "test.jsonl"
    write_records(records, claims)
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({"k0": "supported", "k1": "unsupported", "k2": "supported"}))
    imr = tmp_path / "imr.json"
    imr.write_text(json.dumps({"n": 10, "auroc": 0.7, "brier": 0.2,
                               "coverage": {"coverage": 0.9, "low": 0.8, "high": 0.95, "share_both": 0.5}}))
    results, runs = tmp_path / "RESULTS.md", tmp_path / "runs"
    code = cli.main(
        ["eval-trust", "--claims", str(claims), "--labels", str(labels), "--cases", str(cases_dir(tmp_path)),
         "--imr-report", str(imr), "--results", str(results), "--runs", str(runs),
         "--thresholds", str(tmp_path / "none.json")],
        client=FakeLLM([]),
    )
    out = capsys.readouterr().out
    assert code == 0 and "inconclusive" in out
    text = results.read_text()
    assert "<!-- phase3-trust:start -->" in text and "relative to critic labels" in text
    (log,) = runs.glob("eval-trust-*.jsonl")
    assert json.loads(log.read_text().splitlines()[0])["kind"] == "meta"


def test_eval_trust_adds_agreement_and_shift_when_given(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Spot-check kappas and the dev-vs-test exchangeability check go into the section; meta carries the config hash."""
    case_id = json.loads(FIXTURE.read_text())["id"]
    claims, calib = tmp_path / "test.jsonl", tmp_path / "dev.jsonl"
    write_records([rec(f"k{i}", case_id, "f2f_visit", ClaimDecision.KEEP) for i in range(3)], claims)
    write_records([rec(f"d{i}", "dev-1", "f2f_visit", ClaimDecision.FLAG) for i in range(3)], calib)
    claims.with_suffix(".meta.json").write_text(json.dumps({"config_hash": "abc123"}))
    labels, calib_labels = tmp_path / "labels.json", tmp_path / "dev-labels.json"
    labels.write_text(json.dumps({"k0": "supported", "k1": "unsupported", "k2": "partly"}))
    calib_labels.write_text(json.dumps({"d0": "unsupported", "d1": "partly", "d2": "supported"}))
    spot = tmp_path / "spot.json"
    spot.write_text(json.dumps({"n": 86, "kappa": 0.55, "kappa_low": 0.39, "kappa_high": 0.71, "ac1": 0.8,
                                "kappa_binary": 0.8, "kappa_binary_low": 0.63, "kappa_binary_high": 0.94,
                                "ac1_binary": 0.92}))
    results, runs = tmp_path / "RESULTS.md", tmp_path / "runs"
    code = cli.main(
        ["eval-trust", "--claims", str(claims), "--labels", str(labels), "--cases", str(cases_dir(tmp_path)),
         "--imr-report", str(tmp_path / "none-imr.json"), "--results", str(results), "--runs", str(runs),
         "--thresholds", str(tmp_path / "none.json"), "--calib-claims", str(calib), "--calib-labels", str(calib_labels),
         "--spot-check-result", str(spot)],
        client=FakeLLM([]),
    )
    capsys.readouterr()
    text = results.read_text()
    assert code == 0 and "binary kappa 0.80" in text and "Exchangeability check" in text
    assert "config_hash `abc123`" in text


def imr_csv(tmp_path: Path) -> Path:
    """A synthetic IMR CSV in the documented schema."""
    frame = synthetic(3000, seed=2)
    out = pd.DataFrame({
        "ReferenceID": [f"FAKE-{i}" for i in range(len(frame))],
        "ReportYear": frame["report_year"].astype(int),
        **{c: frame[c].astype(object) for c in ["DiagnosisCategory", "DiagnosisSubCategory", "TreatmentCategory",
                                                 "TreatmentSubCategory"]},
        "Determination": frame["label"].map({1: "Overturned Decision of Health Plan",
                                             0: "Upheld Decision of Health Plan"}),
        **{c: frame[c].astype(object) for c in ["Type", "AgeRange", "PatientGender", "IMRType"]},
        "DaysToReview": 10, "DaysToAdopt": 20, "Findings": "Fake findings.",
    })
    path = tmp_path / "imr.csv"
    out.to_csv(path, index=False)
    return path


def test_imr_fit_then_test(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """imr-fit saves the model and prints the 2023 width rule; imr-test scores 2024+ once."""
    csv, model, report = imr_csv(tmp_path), tmp_path / "m.pkl", tmp_path / "r.json"
    mapping = tmp_path / "map.yaml"
    mapping.write_text("pap-osa:\n  rationale: t\n  match_any:\n    - TreatmentSubCategory: [C-Pap Machine]\n")
    assert cli.main(["imr-fit", "--imr", str(csv), "--model", str(model), "--mapping", str(mapping)],
                    client=FakeLLM([])) == 0
    assert "width" in capsys.readouterr().out and model.exists()
    assert cli.main(["imr-test", "--imr", str(csv), "--model", str(model), "--out", str(report)],
                    client=FakeLLM([])) == 0
    assert json.loads(report.read_text())["auroc"] > 0.5
    assert "AUROC" in capsys.readouterr().out


def test_imr_test_without_model_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """No saved model: a clear error."""
    code = cli.main(["imr-test", "--imr", str(imr_csv(tmp_path)), "--model", str(tmp_path / "none.pkl"),
                     "--out", str(tmp_path / "r.json")], client=FakeLLM([]))
    assert code == 1 and "imr-fit" in capsys.readouterr().err


def test_run_with_trust_prints_letter_and_strength(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`pair run --trust` adds the letter (claims marked not evaluated) and the strength or 'get a human'."""
    csv, model = imr_csv(tmp_path), tmp_path / "m.pkl"
    cli.main(["imr-fit", "--imr", str(csv), "--model", str(model)], client=FakeLLM([]))
    capsys.readouterr()
    code = cli.main(
        ["run", str(FIXTURE), "--trust", "--imr-model", str(model), "--thresholds", str(tmp_path / "none.json")],
        client=FakeLLM([denial_reply(), *wording_failures()]), extract_fn=gold_extract, verifier=FakeVerifier(),
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "Requirement:" in out and "not evaluated" in out
    assert "Strength:" in out or "Get a human" in out
    assert "not a guarantee for Medicare Advantage" in out


def test_run_with_trust_and_no_model_still_prints_the_letter(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Missing IMR model: the letter prints and the strength line says why it's missing."""
    code = cli.main(
        ["run", str(FIXTURE), "--trust", "--imr-model", str(tmp_path / "none.pkl"),
         "--thresholds", str(tmp_path / "none.json")],
        client=FakeLLM([denial_reply(), *wording_failures()]), extract_fn=gold_extract, verifier=FakeVerifier(),
    )
    out = capsys.readouterr().out
    assert code == 0 and "Requirement:" in out and "imr-fit" in out


def test_gate_export_writes_blind_batches_key_and_human_set(tmp_path: Path) -> None:
    """Critic batches are blind, the key and gate records go to seed-key, Nithin's set has no scores or labels."""
    records = [rec(f"n{i:02d}", f"c{i % 5}", f"crit{i % 3}", ClaimDecision.FLAG).model_copy(
        update={"quote": f"AHI {20 + i}", "premise": f"Study: AHI {20 + i} events.", "score": (i % 10) / 10})
        for i in range(70)]
    claims = tmp_path / "dev.jsonl"
    write_records(records, claims)
    out, key_dir, batches = tmp_path / "gate", tmp_path / "seed-key", tmp_path / "batches"
    code = cli.main(["gate-export", "--claims", str(claims), "--out-dir", str(out), "--key-dir", str(key_dir),
                     "--batches", str(batches), "--batch-size", "20"], client=FakeLLM([]))
    assert code == 0
    inputs = sorted((out / "input").glob("batch-*.jsonl"))
    rows = [json.loads(line) for path in inputs for line in path.read_text().splitlines()]
    assert len(rows) == 80 and all(set(r) == {"claim_id", "claim", "premise"} for r in rows)
    specs = sorted(batches.glob("batch-*.md"))
    assert len(specs) == len(inputs) and "mode: claims" in specs[0].read_text()
    key = json.loads((key_dir / "key.json").read_text())
    assert set(key) == {r["claim_id"] for r in rows}
    assert len(read_records(key_dir / "gate.jsonl")) == 60
    human = [json.loads(line) for line in (out / "human" / "natural-20.jsonl").read_text().splitlines()]
    assert len(human) == 20 and all(h["label"] == "" and "score" not in h for h in human)
    assert {h["claim_id"] for h in human} <= set(key)


def test_gate_export_refuses_to_overwrite_open_batches(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """An unclaimed batch file already in the folder: stop rather than clobber it."""
    batches = tmp_path / "batches"
    batches.mkdir()
    (batches / "batch-01.md").write_text("old")
    claims = tmp_path / "dev.jsonl"
    write_records([rec("a", "c", "f2f_visit", None)], claims)
    code = cli.main(["gate-export", "--claims", str(claims), "--out-dir", str(tmp_path / "g"),
                     "--key-dir", str(tmp_path / "k"), "--batches", str(batches)], client=FakeLLM([]))
    assert code == 1 and "batch-01.md" in capsys.readouterr().err


def exported_gate(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    """Run gate-export on synthetic claims; return the out dir, key dir and blind-to-kind map."""
    records = [rec(f"n{i:02d}", f"c{i % 5}", f"crit{i % 3}", ClaimDecision.FLAG).model_copy(
        update={"quote": f"AHI {20 + i}", "premise": f"Study: AHI {20 + i} events.", "score": (i % 10) / 10})
        for i in range(70)]
    claims = tmp_path / "dev.jsonl"
    write_records(records, claims)
    out, key_dir = tmp_path / "gate", tmp_path / "seed-key"
    cli.main(["gate-export", "--claims", str(claims), "--out-dir", str(out), "--key-dir", str(key_dir),
              "--batches", str(tmp_path / "batches"), "--batch-size", "20"], client=FakeLLM([]))
    key = json.loads((key_dir / "key.json").read_text())
    kinds = {r.claim_id: r.kind for r in read_records(key_dir / "gate.jsonl")}
    return out, key_dir, {blind: kinds.get(real, "natural") for blind, real in key.items()}


def write_critic(out: Path, kinds: dict[str, str], skip_last_batch: bool = False) -> None:
    """A perfect critic: faults unsupported, clean twins and naturals supported, each with a verbatim quote."""
    inputs = sorted((out / "input").glob("batch-*.jsonl"))
    for path in inputs[:-1] if skip_last_batch else inputs:
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        lines = [json.dumps({"claim_id": r["claim_id"], "check_id": "S1",
                             "label": "unsupported" if kinds[r["claim_id"]] == "fault" else "supported",
                             "quotes": [{"doc_id": "premise", "text": r["premise"][:10]}], "reasoning": "x"})
                 for r in rows]
        (out / "critic" / path.name).write_text("\n".join(lines) + "\n")


def fill_human(out: Path, label: str) -> None:
    """Nithin's file with every label filled in."""
    path = out / "human" / "natural-20.jsonl"
    rows = [json.loads(line) | {"label": label} for line in path.read_text().splitlines()]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_gate_score_passes_a_perfect_critic(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """All faults caught, no clean twin flagged, full agreement with Nithin: PASS, and a JSON report."""
    out, key_dir, kinds = exported_gate(tmp_path)
    write_critic(out, kinds)
    fill_human(out, "supported")
    code = cli.main(["gate-score", "--out-dir", str(out), "--key-dir", str(key_dir)], client=FakeLLM([]))
    text = capsys.readouterr().out
    assert code == 0 and "PASS" in text and "30/30" in text
    report = json.loads((out / "gate-result.json").read_text())
    assert report["passed"] is True and report["by_fault"]["number_swap"]["caught"] == report["by_fault"]["number_swap"]["n"]


def test_gate_score_reports_missing_batches_and_blank_human_labels(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A batch not written yet and an unfilled human file: not passed, and both are named."""
    out, key_dir, kinds = exported_gate(tmp_path)
    write_critic(out, kinds, skip_last_batch=True)
    code = cli.main(["gate-score", "--out-dir", str(out), "--key-dir", str(key_dir)], client=FakeLLM([]))
    text = capsys.readouterr().out
    assert code == 0 and "NOT PASSED" in text
    assert "batch-04" in text and "20 blank" in text


def test_gate_score_rejects_a_bad_human_label(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A typo in Nithin's file is an error, not a silent skip."""
    out, key_dir, kinds = exported_gate(tmp_path)
    write_critic(out, kinds)
    fill_human(out, "suported")
    code = cli.main(["gate-score", "--out-dir", str(out), "--key-dir", str(key_dir)], client=FakeLLM([]))
    assert code == 1 and "suported" in capsys.readouterr().err


def test_label_export_then_import_writes_real_id_labels(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """All natural claims go out blind; verified verdicts come back keyed by real claim id; a gap is re-run once."""
    records = [rec(f"n{i:02d}", f"c{i % 5}", f"crit{i % 3}", ClaimDecision.FLAG).model_copy(
        update={"premise": f"Study: AHI {20 + i} events."}) for i in range(25)]
    claims = tmp_path / "dev.jsonl"
    write_records(records, claims)
    out, key_dir, batches = tmp_path / "s1", tmp_path / "key", tmp_path / "batches"
    assert cli.main(["label-export", "--claims", str(claims), "--out-dir", str(out), "--key-dir", str(key_dir),
                     "--batches", str(batches), "--batch-size", "10"], client=FakeLLM([])) == 0
    inputs = sorted((out / "input").glob("batch-*.jsonl"))
    assert [len(p.read_text().splitlines()) for p in inputs] == [10, 10, 5]
    for path in inputs:
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        lines = [json.dumps({"claim_id": r["claim_id"], "check_id": "S1", "label": "supported",
                             "quotes": [{"doc_id": "premise", "text": r["premise"][:6]}], "reasoning": "x"})
                 for r in rows if not (path == inputs[-1] and r is rows[-1])]
        (out / "critic" / path.name).write_text("\n".join(lines) + "\n")
    assert cli.main(["label-import", "--out-dir", str(out), "--key-dir", str(key_dir), "--batches", str(batches)],
                    client=FakeLLM([])) == 0
    text = capsys.readouterr().out
    assert "24 labeled" in text and "1 to re-run" in text
    labels = json.loads((out / "labels.json").read_text())
    assert len(labels) == 24 and set(labels) <= {r.claim_id for r in records}
    rerun_specs = sorted(batches.glob("batch-*.md"))
    assert "rerun" in rerun_specs[-1].read_text()


def test_label_export_skips_dropped_and_seeded_claims(tmp_path: Path) -> None:
    """Only natural claims that passed the citation checks get labels."""
    records = [rec("a", "c", "x", ClaimDecision.DROP), rec("b", "c", "x", None),
               rec("s", "c", "x", None, kind="fault")]
    claims = tmp_path / "dev.jsonl"
    write_records(records, claims)
    cli.main(["label-export", "--claims", str(claims), "--out-dir", str(tmp_path / "o"), "--key-dir",
              str(tmp_path / "k"), "--batches", str(tmp_path / "b")], client=FakeLLM([]))
    assert json.loads((tmp_path / "k" / "key.json").read_text()) == {"d-001": "b"}


def test_fit_threshold_refuses_records_without_a_premise_rule(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Untagged or mixed premise rules: no threshold."""
    claims, labels = labeled_dev(tmp_path, 11)
    records = read_records(claims)
    write_records([r.model_copy(update={"premise_rule": None if i == 0 else r.premise_rule})
                   for i, r in enumerate(records)], claims)
    code = cli.main(["fit-threshold", "--claims", str(claims), "--labels", str(labels),
                     "--thresholds", str(tmp_path / "t.json")], client=FakeLLM([]))
    assert code == 1 and "premise rule" in capsys.readouterr().err


def test_spot_check_export_then_score(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The sheet hides critic labels; scoring reports kappa and whether the labels count."""
    records = [rec(f"n{i:02d}", "pap-osa-fixture", "f2f_visit", None).model_copy(
        update={"premise": f"Study: AHI {20 + i} events."}) for i in range(40)]
    claims = tmp_path / "dev.jsonl"
    write_records(records, claims)
    out, key_dir = tmp_path / "s1", tmp_path / "key"
    key_dir.mkdir()
    (key_dir / "key.json").write_text(json.dumps({f"d-{i + 1:03d}": f"n{i:02d}" for i in range(40)}))
    out.mkdir()
    labels = {f"n{i:02d}": ("unsupported" if i % 2 else "supported") for i in range(40)}
    (out / "labels.json").write_text(json.dumps(labels))
    args = ["--claims", str(claims), "--out-dir", str(out), "--key-dir", str(key_dir), "--cases", str(cases_dir(tmp_path))]
    assert cli.main(["spot-check", "export", *args], client=FakeLLM([])) == 0
    sheet = [json.loads(line) for line in (out / "human" / "spot-check.jsonl").read_text().splitlines()]
    assert len(sheet) >= 20 and all(set(r) == {"claim_id", "claim", "premise", "label"} for r in sheet)
    assert f"Don't open {out / 'critic'}/ or labels.json" in (out / "human" / "spot-check-checklist.md").read_text()
    key = json.loads((key_dir / "key.json").read_text())
    (out / "human" / "spot-check.jsonl").write_text("".join(
        json.dumps(r | {"label": labels[key[r["claim_id"]]]}) + "\n" for r in sheet))
    assert cli.main(["spot-check", "score", *args], client=FakeLLM([])) == 0
    text = capsys.readouterr().out
    assert "binary kappa 1.00" in text and "3-class kappa 1.00" in text and "labels count" in text
    assert json.loads((out / "spot-check-result.json").read_text())["labels_count"] is True
