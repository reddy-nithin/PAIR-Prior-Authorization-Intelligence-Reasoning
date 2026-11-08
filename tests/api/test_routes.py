"""Tests for the demo API (Phase 4 T7): cached cases, live runs, export, errors, CORS, privacy."""

import base64
import builtins
import dataclasses
import io
import logging
import tempfile
from pathlib import Path
from typing import Any

import pytest
from docx import Document
from fastapi.testclient import TestClient

from pair.api.app import ApiConfigError, ApiSettings, create_app
from pair.ui.view import CaseView
from tests.api.conftest import FakeRunner
from tests.test_pipeline import CASE


def b64(text: str) -> str:
    """Base64 of UTF-8 text."""
    return base64.b64encode(text.encode()).decode()


def run_body() -> dict[str, Any]:
    """The fixture case as a live upload: denial and each record as a .txt file."""
    return {
        "denial": {"name": "denial.txt", "data": b64(CASE.denial_text)},
        "documents": [{"name": f"{note.title}.txt", "data": b64(note.text)} for note in CASE.notes],
        "context": CASE.context,
    }


def error_code(response: Any) -> str:
    """The error envelope's code."""
    body = response.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message"}
    return str(body["error"]["code"])


def test_health_reports_cache_and_live(client: TestClient) -> None:
    """Health says how many cached cases there are and whether live mode can run."""
    body = client.get("/health").json()
    assert body == {"status": "ok", "cache": {"ok": True, "cases": 1}, "live": {"enabled": True, "reachable": True}}


def test_health_without_live_or_cache(tmp_path: Path) -> None:
    """With no runner and no cache, health still answers and says so."""
    app = create_app(ApiSettings(cache_dir=tmp_path / "none", runner=None, redact_logs=False))
    body = TestClient(app).get("/health").json()
    assert body["cache"] == {"ok": False, "cases": 0} and body["live"] == {"enabled": False, "reachable": False}


def test_cases_lists_the_cache(client: TestClient, view: CaseView) -> None:
    """The case list has one row per cached case."""
    (row,) = client.get("/cases").json()["cases"]
    assert row["case_id"] == view.case_id and row["policy_id"] == "pap-osa"


def test_case_returns_the_cached_view(client: TestClient, view: CaseView) -> None:
    """A cached case comes back as the same CaseView."""
    response = client.get(f"/cases/{view.case_id}")
    assert response.status_code == 200
    assert CaseView.model_validate(response.json()) == view


def test_unknown_case_is_404(client: TestClient) -> None:
    """An unknown case id is a 404 in the error envelope."""
    response = client.get("/cases/no-such-case")
    assert response.status_code == 404 and error_code(response) == "not_found"


def test_missing_cache_is_503(tmp_path: Path, runner: FakeRunner) -> None:
    """No cache means cached mode is unavailable, with a hint to build it."""
    app = create_app(ApiSettings(cache_dir=tmp_path / "none", runner=runner, redact_logs=False))
    response = TestClient(app).get("/cases")
    assert response.status_code == 503 and error_code(response) == "cache_unavailable"
    assert "demo-cache" in response.json()["error"]["message"]


def test_cached_downloads(client: TestClient, view: CaseView) -> None:
    """Cached DOCX and PDF are served as attachments."""
    docx = client.get(f"/cases/{view.case_id}/files/docx")
    assert docx.status_code == 200 and "attachment" in docx.headers["content-disposition"]
    assert view.safety_notice in "\n".join(p.text for p in Document(io.BytesIO(docx.content)).paragraphs)
    pdf = client.get(f"/cases/{view.case_id}/files/pdf")
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    assert client.get(f"/cases/{view.case_id}/files/exe").status_code == 404


def test_live_run_returns_a_live_view(client: TestClient) -> None:
    """A live run parses the uploads in memory, runs steps 1 to 7 and returns a live CaseView."""
    response = client.post("/run", json=run_body())
    assert response.status_code == 200, response.text
    view = CaseView.model_validate(response.json())
    assert view.mode == "live" and view.supported and view.policy_id == "pap-osa"
    assert view.case_id.startswith("live-") and float(response.headers["x-run-seconds"]) >= 0
    assert [d.title for d in view.documents] == [note.title for note in CASE.notes]


def test_live_run_writes_nothing_and_logs_no_upload_text(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """During a live run nothing is opened for writing, no temp file is made, and no record text is logged."""
    real_open = builtins.open

    def read_only_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if any(flag in mode for flag in "wax+"):
            raise AssertionError(f"write to {file}")
        return real_open(file, mode, *args, **kwargs)

    def no_temp(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("temp file")

    monkeypatch.setattr(builtins, "open", read_only_open)
    for name in ("NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile", "mkstemp", "mkdtemp"):
        monkeypatch.setattr(tempfile, name, no_temp)
    with caplog.at_level(logging.DEBUG):
        assert client.post("/run", json=run_body()).status_code == 200
    logged = "\n".join(record.getMessage() for record in caplog.records)
    for note in CASE.notes:
        for line in (line.strip() for line in note.text.splitlines()):
            if len(line) > 25:
                assert line not in logged
    assert CASE.denial_text.strip()[:60] not in logged


def test_live_off_is_503(demo_cache: Path) -> None:
    """Without a runner, /run says live mode is off and points to the cached cases."""
    app = create_app(ApiSettings(cache_dir=demo_cache, runner=None, redact_logs=False))
    response = TestClient(app).post("/run", json=run_body())
    assert response.status_code == 503 and error_code(response) == "live_off"
    assert "cached" in response.json()["error"]["message"]


def test_unreachable_lab_is_503(client: TestClient, runner: FakeRunner) -> None:
    """If the lab tunnel is down, /run fails fast with a clear message."""
    runner.up = False
    response = client.post("/run", json=run_body())
    assert response.status_code == 503 and error_code(response) == "model_unavailable"


def test_model_failure_mid_run_is_502(client: TestClient, monkeypatch: pytest.MonkeyPatch, runner: FakeRunner) -> None:
    """A backend error during the run is a 502 that names no case content."""
    from pair.llm import LLMError

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise LLMError("ollama said: Mary Jones record text")

    monkeypatch.setattr(runner, "view", boom)
    response = client.post("/run", json=run_body())
    assert response.status_code == 502 and error_code(response) == "model_failed"
    assert "Mary" not in response.text


def test_body_over_the_cap_is_413(demo_cache: Path, runner: FakeRunner) -> None:
    """A body larger than the cap is refused before parsing."""
    app = create_app(ApiSettings(cache_dir=demo_cache, runner=runner, redact_logs=False, max_body_bytes=1000))
    response = TestClient(app).post("/run", json=run_body())
    assert response.status_code == 413 and error_code(response) == "too_large"


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (b"not json", "bad_request"),
        (b'{"documents": []}', "bad_request"),
        (b'{"denial": {"name": "d.txt", "data": "%%%"}, "documents": []}', "bad_request"),
        (b'{"denial": {"name": "d.exe", "data": "aGk="}, "documents": []}', "bad_upload"),
        (b'{"denial": {"name": "d.txt", "data": "aGk="}, "documents": [], "context": {"Bad Key!": true}}', "bad_request"),
    ],
)
def test_bad_run_bodies_are_400(client: TestClient, body: bytes, code: str) -> None:
    """Malformed JSON, missing fields, bad base64, unsupported files and bad context keys are 400s."""
    response = client.post("/run", content=body, headers={"content-type": "application/json"})
    assert response.status_code == 400 and error_code(response) == code


def test_bad_upload_message_names_the_file_not_its_contents(client: TestClient) -> None:
    """An upload error names the file only."""
    body = run_body()
    body["documents"][0] = {"name": "scan.exe", "data": b64("SECRET RECORD TEXT")}
    response = client.post("/run", json=body)
    assert response.status_code == 400 and "scan.exe" in response.text and "SECRET" not in response.text


def test_busy_runner_is_429(client: TestClient, settings: ApiSettings) -> None:
    """Only one live run at a time on the M2; a second one is told to wait."""
    app = client.app
    app.state.live_lock.acquire()  # type: ignore[attr-defined]
    try:
        response = client.post("/run", json=run_body())
    finally:
        app.state.live_lock.release()  # type: ignore[attr-defined]
    assert response.status_code == 429 and error_code(response) == "busy"


@pytest.mark.parametrize(("fmt", "magic"), [("docx", b"PK"), ("pdf", b"%PDF")])
def test_export_renders_a_posted_view(client: TestClient, view: CaseView, fmt: str, magic: bytes) -> None:
    """POST a CaseView, get the letter file back as an attachment."""
    response = client.post(f"/export/{fmt}", content=view.model_dump_json(), headers={"content-type": "application/json"})
    assert response.status_code == 200 and response.content.startswith(magic)
    assert f"appeal-letter-{view.case_id}.{fmt}" in response.headers["content-disposition"]


def test_export_errors(client: TestClient, view: CaseView) -> None:
    """Unknown format is 404, a non-CaseView is 400, a view with no letter is 422."""
    assert client.post("/export/exe", content=view.model_dump_json()).status_code == 404
    bad = client.post("/export/pdf", content=b'{"case_id": 1}')
    assert bad.status_code == 400 and error_code(bad) == "bad_request"
    empty = client.post("/export/pdf", content=view.model_copy(update={"letter": None}).model_dump_json())
    assert empty.status_code == 422 and error_code(empty) == "export_failed"


def test_cors_allows_only_the_local_web_app(client: TestClient) -> None:
    """The local Next.js origin gets CORS headers; any other origin doesn't."""
    ok = client.get("/health", headers={"origin": "http://localhost:3000"})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:3000"
    other = client.get("/health", headers={"origin": "https://evil.example"})
    assert "access-control-allow-origin" not in other.headers


def test_non_local_origins_are_refused(demo_cache: Path) -> None:
    """Configuring a non-localhost origin is an error at startup."""
    with pytest.raises(ApiConfigError, match="localhost"):
        create_app(ApiSettings(cache_dir=demo_cache, runner=None, redact_logs=False,
                               origins=("https://my-site.vercel.app",)))  # fmt: skip


def test_settings_from_env_without_live(tmp_path: Path) -> None:
    """``PAIR_LIVE`` unset means no runner; the cache folder and origins come from the environment."""
    settings = ApiSettings.from_env({"PAIR_DEMO_CACHE": str(tmp_path), "PAIR_WEB_ORIGINS": "http://127.0.0.1:3000"})
    assert settings.runner is None and settings.cache_dir == tmp_path
    assert settings.origins == ("http://127.0.0.1:3000",) and settings.redact_logs


def test_redaction_is_installed_when_asked(demo_cache: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With ``redact_logs`` the app installs the Presidio filter at startup."""
    from pair.api import app as app_module

    calls: list[Any] = []
    monkeypatch.setattr(app_module, "install_log_redaction", lambda target=None: calls.append(target))
    create_app(dataclasses.replace(ApiSettings(cache_dir=demo_cache, runner=None), redact_logs=True))
    names = [getattr(target, "name", "root") for target in calls]
    assert "root" in names and "uvicorn.error" in names
    assert "uvicorn.access" not in names  # its formatter needs the 5 args the filter clears; `make api` turns it off


def test_make_api_turns_off_the_access_log() -> None:
    """Access lines can't go through the redaction filter, so the server runs without them."""
    from tests.conftest import REPO_ROOT

    recipe = (REPO_ROOT / "Makefile").read_text().split("\napi:", 1)[1].split("\n\n", 1)[0]
    assert "--no-access-log" in recipe and "--host 127.0.0.1" in recipe
