"""Tests for the demo cache build, verify and publish commands (Phase 4 T5)."""

import dataclasses
import json
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from pair.llm import Backend, LLMResult, LLMUsage
from pair.ui import demo_build
from pair.ui.cache import load_view, read_manifest, verify_cache
from pair.verify.conformal import Threshold, ThresholdBook
from tests.conftest import REPO_ROOT
from tests.test_pipeline import CASE, denial_reply, gold_extract
from tests.ui.conftest import FirstLowVerifier


class DemoLLM:
    """Parses the denial with the gold reply and words every claim with an empty sentence (verbatim fallback)."""

    def generate_json(self, prompt: str, schema: Mapping[str, Any]) -> LLMResult:
        """Gold denial for the denial schema, an empty sentence otherwise."""
        data = {"sentence": ""} if "sentence" in schema.get("properties", {}) else denial_reply()
        usage = LLMUsage(prompt_tokens=1, output_tokens=1, thinking_tokens=None)
        return LLMResult(data=data, raw_text="{}", usage=usage, backend=Backend.OLLAMA, model="gemma4:e4b")


@pytest.fixture
def cases(tmp_path: Path) -> Path:
    """A cases folder holding the fixture case under its policy."""
    folder = tmp_path / "cases" / "pap-osa"
    folder.mkdir(parents=True)
    shutil.copy(REPO_ROOT / "tests" / "fixtures" / "cases" / "pap-osa-fixture.json", folder)
    return tmp_path / "cases"


@pytest.fixture
def thresholds(tmp_path: Path) -> Path:
    """A threshold file for the drafter and fake verifier pair."""
    path = tmp_path / "thresholds.json"
    ThresholdBook([Threshold(q_hat=0.5, n=54, k=1, alpha=0.1, drafter="gemma4:e4b", verifier_backend="minicheck",
                             verifier_model="bespoke-minicheck")]).save(path)  # fmt: skip
    return path


def build(cases: Path, thresholds: Path, out: Path, *extra: str) -> int:
    """Run the build command with fakes."""
    argv = ["--cases", str(cases), "--out", str(out), "--thresholds", str(thresholds),
            "--imr-model", str(out.parent / "no-model.pkl"), "--case", CASE.id, *extra]  # fmt: skip
    return demo_build.build_main(argv, client=DemoLLM(), extract_fn=gold_extract, verifier=FirstLowVerifier())


def test_build_writes_a_verified_cache_with_run_metadata(
    cases: Path, thresholds: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The build runs steps 1 to 7, writes a cache that verifies, and records models, threshold and commit."""
    out = tmp_path / "demo-cache"
    assert build(cases, thresholds, out) == demo_build.EXIT_OK
    assert verify_cache(out) == []
    view = load_view(out, CASE.id)
    assert view.mode == "cached" and view.policy_id == "pap-osa" and view.letter is not None
    run = read_manifest(out)["run"]
    assert run["drafter"] == "gemma4:e4b" and run["verifier_model"] == "bespoke-minicheck"
    assert run["threshold"] == "gemma4:e4b | minicheck | bespoke-minicheck (q_hat 0.5000, n 54)"
    assert run["premise_rule"] and run["git_commit"] and run["imr_model_sha256"] is None
    (item,) = read_manifest(out)["items"]
    assert len(item["input_sha256"]) == 64
    assert item["files"] == {"view": f"views/{CASE.id}.json", "docx": f"files/{CASE.id}.docx",
                             "pdf": f"files/{CASE.id}.pdf"}  # fmt: skip
    assert (out / item["files"]["pdf"]).read_bytes().startswith(b"%PDF")
    printed = capsys.readouterr().out
    assert CASE.id in printed and "1 case(s)" in printed
    assert "1 quoted, 0 kept out" in printed  # the fixture's first claim is flagged, then quoted (ADR-0024)


def test_build_without_a_threshold_says_claims_are_not_evaluated(
    cases: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """With no calibrated pair the build still runs, and the run metadata says so."""
    out = tmp_path / "demo-cache"
    assert build(cases, tmp_path / "none.json", out) == demo_build.EXIT_OK
    assert read_manifest(out)["run"]["threshold"] == "none"
    assert "not evaluated" in capsys.readouterr().err


def test_build_requiring_get_a_human_fails_when_no_case_abstains(
    cases: Path, thresholds: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--require-get-a-human`` fails the build (and writes no cache) if every case gets a number."""
    monkeypatch.setattr(demo_build, "_abstains", lambda entry: False)
    out = tmp_path / "demo-cache"
    assert build(cases, thresholds, out, "--require-get-a-human") == demo_build.EXIT_ERROR
    assert not out.exists() and "get-a-human" in capsys.readouterr().err


def test_unknown_case_id_is_an_error(cases: Path, thresholds: Path, tmp_path: Path) -> None:
    """Asking for a case that isn't in the folder fails before any model call."""
    argv = ["--cases", str(cases), "--out", str(tmp_path / "c"), "--thresholds", str(thresholds), "--case", "nope"]
    assert demo_build.build_main(argv, client=DemoLLM(), extract_fn=gold_extract,
                                 verifier=FirstLowVerifier()) == demo_build.EXIT_ERROR  # fmt: skip


def test_default_picks_take_the_first_wrongly_denied_case_per_policy_and_one_fixable_gap(tmp_path: Path) -> None:
    """With no ``--case``, the build takes one type A case per policy plus the first type B case."""
    for policy, kind in [("pap-osa", "A"), ("pap-osa", "B"), ("home-oxygen", "B"), ("home-oxygen", "A")]:
        folder = tmp_path / policy
        folder.mkdir(exist_ok=True)
        n = len(list(folder.glob("*.json"))) + 1
        (folder / f"{policy}-0{n}.json").write_text(json.dumps({"id": f"{policy}-0{n}", "case_type": kind}))
    picks = [p.stem for p in demo_build.default_picks(tmp_path)]
    assert picks == ["home-oxygen-02", "pap-osa-01", "home-oxygen-01"]


def test_verify_and_publish_commands(
    cases: Path, thresholds: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``verify`` reports OK or each problem; ``publish`` copies a verified cache and refuses a broken one."""
    out = tmp_path / "demo-cache"
    build(cases, thresholds, out)
    web = tmp_path / "web" / "demo"
    assert demo_build.verify_main(["--cache", str(out)]) == demo_build.EXIT_OK
    assert demo_build.publish_main(["--cache", str(out), "--dest", str(web)]) == demo_build.EXIT_OK
    assert (web / "index.json").is_file()
    (out / read_manifest(out)["items"][0]["files"]["view"]).write_text("{}")
    assert demo_build.verify_main(["--cache", str(out)]) == demo_build.EXIT_ERROR
    assert demo_build.publish_main(["--cache", str(out), "--dest", str(web)]) == demo_build.EXIT_ERROR
    assert demo_build.verify_main(["--cache", str(tmp_path / "missing")]) == demo_build.EXIT_ERROR
    err = capsys.readouterr().err
    assert "hash mismatch" in err and "no manifest" in err


def test_abstain_check_reads_the_view(view: Any) -> None:
    """The fixture view abstains (f2f is critical and insufficient), so it counts as a get-a-human case."""
    from pair.ui.cache import CacheEntry

    assert demo_build._abstains(CacheEntry(view=view, input_sha256="0" * 64))
    no_strength = view.model_copy(update={"strength": None})
    assert not demo_build._abstains(CacheEntry(view=no_strength, input_sha256="0" * 64))


def test_git_commit_outside_a_repo_is_unknown(tmp_path: Path) -> None:
    """A build outside git still writes a manifest, with ``unknown`` as the commit."""
    assert demo_build.git_commit(tmp_path) == "unknown"
    assert demo_build.git_commit(REPO_ROOT) not in ("", "unknown")


def test_case_without_a_verdict_fails_the_build(
    cases: Path, thresholds: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A case that gets no verdict can't be shown, so the build stops and writes nothing."""
    from pair.ui import runner

    real = runner.run_core
    monkeypatch.setattr(runner, "run_core", lambda *a, **k: dataclasses.replace(real(*a, **k), verdict=None))
    out = tmp_path / "demo-cache"
    assert build(cases, thresholds, out) == demo_build.EXIT_ERROR
    assert not out.exists() and "no verdict" in capsys.readouterr().err
