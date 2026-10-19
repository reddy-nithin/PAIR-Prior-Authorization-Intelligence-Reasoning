"""`pair run` and `pair eval-core` with injected fakes (T11)."""

import json
import shutil
from pathlib import Path

import pytest

from pair import cli
from tests.conftest import REPO_ROOT
from tests.fakes import FakeLLM
from tests.test_pipeline import CASE, denial_reply, gold_extract

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "cases" / "pap-osa-fixture.json"


def test_run_prints_denial_verdict_and_gaps(capsys: pytest.CaptureFixture[str]) -> None:
    """`pair run <case>` prints the parsed denial, the verdict table with traces and the gaps."""
    code = cli.main(["run", str(FIXTURE)], client=FakeLLM([denial_reply()]), extract_fn=gold_extract)
    out = capsys.readouterr().out
    assert code == 0
    assert "Denial:" in out and "E0601" in out
    assert "Policy: pap-osa" in out
    assert f"Overall: {CASE.gold_overall.value.upper()}" in out
    for criterion_id, status in CASE.gold_statuses.items():
        assert f"{criterion_id}" in out and status.value in out
    assert "rule:" in out
    assert "Gaps" in out
    assert "Grounding:" in out


def test_run_context_override(capsys: pytest.CaptureFixture[str]) -> None:
    """`--context initial=true` changes the overall outcome logic input."""
    code = cli.main(
        ["run", str(FIXTURE), "--context", "initial=true"], client=FakeLLM([denial_reply()]), extract_fn=gold_extract
    )
    assert code == 0
    assert "context: initial=True" in capsys.readouterr().out


@pytest.mark.parametrize("bad", ["initial", "initial=perhaps"])
def test_run_rejects_bad_context(bad: str) -> None:
    """Malformed --context values exit with a usage error."""
    with pytest.raises(SystemExit):
        cli.main(["run", str(FIXTURE), "--context", bad], client=FakeLLM([]), extract_fn=gold_extract)


def test_run_unsupported_denial(capsys: pytest.CaptureFixture[str]) -> None:
    """An unsupported denial prints the reason and exits 3."""
    reply = {**denial_reply(), "codes": ["L1832"], "policy_ref": None}
    code = cli.main(["run", str(FIXTURE)], client=FakeLLM([reply]), extract_fn=gold_extract)
    assert code == 3
    assert "unsupported" in capsys.readouterr().out


def test_run_missing_case_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A missing case file exits 1 with a message."""
    assert cli.main(["run", str(tmp_path / "x.json")], client=FakeLLM([]), extract_fn=gold_extract) == 1
    assert "no case file" in capsys.readouterr().err


def test_run_denial_parse_failure(capsys: pytest.CaptureFixture[str]) -> None:
    """If the denial can't be parsed, exit 2 with the error."""
    assert cli.main(["run", str(FIXTURE)], client=FakeLLM(["no", "no"]), extract_fn=gold_extract) == 2
    assert "denial parse failed" in capsys.readouterr().err


def test_eval_core_writes_log_and_results(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`pair eval-core` scores every case, writes a JSONL log with a config hash and RESULTS.md."""
    cases = tmp_path / "cases" / "pap-osa"
    cases.mkdir(parents=True)
    shutil.copy(FIXTURE, cases / "a.json")
    shutil.copy(FIXTURE, cases / "b.json")
    results = tmp_path / "RESULTS.md"
    runs = tmp_path / "runs"
    code = cli.main(
        ["eval-core", "--cases", str(tmp_path / "cases"), "--results", str(results), "--runs", str(runs)],
        client=FakeLLM([denial_reply(), denial_reply()]),
        extract_fn=gold_extract,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "macro-F1" in out
    logs = list(runs.glob("eval-core-*.jsonl"))
    assert len(logs) == 1
    lines = [json.loads(line) for line in logs[0].read_text().splitlines()]
    assert lines[0]["kind"] == "meta" and lines[0]["config_hash"]
    assert len(lines) == 3
    assert "Checklist macro-F1" in results.read_text()
    assert "1.00" in results.read_text()


def test_eval_core_with_no_cases(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """No cases exits 1."""
    code = cli.main(["eval-core", "--cases", str(tmp_path)], client=FakeLLM([]), extract_fn=gold_extract)
    assert code == 1
    assert "no cases" in capsys.readouterr().err


def test_eval_core_records_per_case_errors(tmp_path: Path) -> None:
    """An LLM failure on one case is logged as an error row, not a crash."""
    from pair.llm import LLMError

    cases = tmp_path / "cases" / "pap-osa"
    cases.mkdir(parents=True)
    shutil.copy(FIXTURE, cases / "a.json")

    def broken(**_kwargs: object) -> object:
        raise LLMError("tunnel down")

    code = cli.main(
        ["eval-core", "--cases", str(tmp_path / "cases"), "--results", str(tmp_path / "R.md"),
         "--runs", str(tmp_path / "runs")],
        client=FakeLLM([denial_reply()]), extract_fn=broken,
    )  # fmt: skip
    assert code == 0
    row = json.loads(next((tmp_path / "runs").glob("*.jsonl")).read_text().splitlines()[1])
    assert "tunnel down" in row["error"]


def test_bad_backend_config_exits_1(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """An invalid LLM setting is reported, not raised."""
    monkeypatch.setenv("PAIR_LLM_NUM_CTX", "lots")
    assert cli.main(["run", str(FIXTURE)], client=FakeLLM([]), extract_fn=gold_extract) == 1
    assert "PAIR_LLM_NUM_CTX" in capsys.readouterr().err


def test_run_llm_failure_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    """A transport failure during `pair run` exits 1 with the message."""
    from pair.llm import LLMError

    assert cli.main(["run", str(FIXTURE)], client=FakeLLM([LLMError("tunnel down")]), extract_fn=gold_extract) == 1
    assert "tunnel down" in capsys.readouterr().err


def test_entry_exits_with_main_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """The console script exits with main's return code."""
    monkeypatch.setattr(cli, "main", lambda: 3)
    with pytest.raises(SystemExit) as raised:
        cli.entry()
    assert raised.value.code == 3


def test_run_warns_about_unreadable_documents(capsys: pytest.CaptureFixture[str]) -> None:
    """If the extractor can't parse a document, `pair run` says so instead of hiding it."""
    from langextract.resolver import ResolverParsingError

    def unparseable(**_kwargs: object) -> object:
        raise ResolverParsingError("bad output")

    assert cli.main(["run", str(FIXTURE)], client=FakeLLM([denial_reply()]), extract_fn=unparseable) == 0
    assert "2 document(s) could not be read" in capsys.readouterr().out
