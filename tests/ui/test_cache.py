"""Tests for the demo cache: manifest + SHA-256 per file, verify, load, publish (Phase 4 T5, ADR-0023)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from pair.ui.cache import (
    MANIFEST,
    SCHEMA_VERSION,
    CacheEntry,
    CacheError,
    case_file,
    input_digest,
    load_view,
    publish,
    read_manifest,
    verify_cache,
    write_cache,
)
from pair.ui.view import CaseView

META = {"drafter": "gemma4:e4b", "verifier_backend": "minicheck", "threshold": "fitted", "git_commit": "abc1234"}


@pytest.fixture
def cache(tmp_path: Path, view: CaseView) -> Path:
    """A one-case cache with a view and a fake DOCX."""
    entry = CacheEntry(view=view, input_sha256="0" * 64, extras={"docx": b"PK fake docx"})
    return write_cache(tmp_path / "demo-cache", [entry], META)


def test_input_digest_is_stable_and_order_free() -> None:
    """The same inputs in any dict order give the same digest; any change gives another."""
    a = input_digest("denial", {"a": "x", "b": "y"}, {"initial": True})
    assert a == input_digest("denial", {"b": "y", "a": "x"}, {"initial": True})
    assert a != input_digest("denial", {"a": "x", "b": "z"}, {"initial": True})
    assert a != input_digest("denial", {"a": "x", "b": "y"}, {"initial": False})
    assert len(a) == 64


def test_manifest_records_versions_models_and_every_file_hash(cache: Path, view: CaseView) -> None:
    """The manifest names the schema, the run metadata and a SHA-256 for each file."""
    manifest = read_manifest(cache)
    assert manifest["schema_version"] == SCHEMA_VERSION
    assert manifest["run"] == META and manifest["generated_at"]
    (item,) = manifest["items"]
    assert item["case_id"] == view.case_id and item["policy_id"] == "pap-osa"
    assert set(item["files"]) == {"view", "docx"}
    for path, digest in item["sha256"].items():
        assert (cache / path).is_file() and len(digest) == 64


def test_clean_cache_verifies_and_loads(cache: Path, view: CaseView) -> None:
    """A fresh cache has no problems and loads the view back unchanged."""
    assert verify_cache(cache) == []
    assert load_view(cache, view.case_id) == view


def test_tampered_file_is_caught(cache: Path, view: CaseView) -> None:
    """Editing a cached file after the build is a hash mismatch, and loading it refuses."""
    path = cache / read_manifest(cache)["items"][0]["files"]["view"]
    path.write_text(path.read_text().replace("Met", "Mett"))
    assert any("hash" in problem for problem in verify_cache(cache))
    with pytest.raises(CacheError, match="hash"):
        load_view(cache, view.case_id)


def test_missing_and_unlisted_files_are_problems(cache: Path) -> None:
    """A deleted file and a stray file the manifest doesn't list are both reported."""
    item = read_manifest(cache)["items"][0]
    (cache / item["files"]["docx"]).unlink()
    (cache / "views" / "stray.json").write_text("{}")
    problems = verify_cache(cache)
    assert any("missing" in p for p in problems) and any("stray.json" in p for p in problems)


def test_unsupported_schema_is_refused(cache: Path) -> None:
    """A manifest from an unknown schema version can't be read."""
    path = cache / MANIFEST
    data = json.loads(path.read_text())
    path.write_text(json.dumps({**data, "schema_version": 99}))
    with pytest.raises(CacheError, match="schema"):
        read_manifest(cache)


def test_missing_cache_and_unknown_case_are_errors(tmp_path: Path, cache: Path) -> None:
    """No manifest, or a case the manifest doesn't list, raise ``CacheError``."""
    with pytest.raises(CacheError, match="manifest"):
        read_manifest(tmp_path / "nothing")
    with pytest.raises(CacheError, match="not in"):
        load_view(cache, "no-such-case")


def test_duplicate_case_ids_are_refused(tmp_path: Path, view: CaseView) -> None:
    """Two entries for one case would overwrite each other."""
    entry = CacheEntry(view=view, input_sha256="0" * 64)
    with pytest.raises(CacheError, match="duplicate"):
        write_cache(tmp_path / "c", [entry, entry], META)


def test_rebuild_replaces_the_old_cache(cache: Path, view: CaseView) -> None:
    """Writing again replaces the folder, so files from an old build don't linger."""
    write_cache(cache, [CacheEntry(view=view, input_sha256="1" * 64)], META)
    assert verify_cache(cache) == []
    assert set(read_manifest(cache)["items"][0]["files"]) == {"view"}


def test_publish_copies_a_verified_cache_with_an_index(cache: Path, tmp_path: Path, view: CaseView) -> None:
    """The web folder gets the views, the extras, the manifest and an index of demo cases."""
    web = tmp_path / "web" / "public" / "demo"
    (web / "old.json").parent.mkdir(parents=True)
    (web / "old.json").write_text("{}")
    publish(cache, web)
    index = json.loads((web / "index.json").read_text())
    assert index["cases"] == [{
        "case_id": view.case_id, "policy_id": "pap-osa", "policy_title": view.policy_title,
        "service": view.denial.service if view.denial else None,
        "overall": view.overall.label if view.overall else None,
        "files": {"view": f"views/{view.case_id}.json", "docx": f"files/{view.case_id}.docx"},
    }]  # fmt: skip
    assert CaseView.model_validate_json((web / "views" / f"{view.case_id}.json").read_text()) == view
    assert (web / MANIFEST).is_file() and not (web / "old.json").exists()


def test_publish_refuses_a_broken_cache(cache: Path, tmp_path: Path) -> None:
    """An unverified cache never reaches the web folder."""
    (cache / read_manifest(cache)["items"][0]["files"]["view"]).write_text("{}")
    web = tmp_path / "web-demo"
    with pytest.raises(CacheError, match="verify"):
        publish(cache, web)
    assert not web.exists()


def test_cache_module_loads_no_llm_code() -> None:
    """Cached mode works with Ollama off: reading the cache imports no LLM, extraction or verifier code."""
    code = (
        "import sys, pair.ui.cache; "
        "bad = sorted(m for m in sys.modules if m == 'langextract' or m.startswith(('langextract.', 'pair.llm', "
        "'pair.pipeline', 'pair.verify', 'pair.extract', 'google.genai', 'presidio'))); print(','.join(bad))"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == ""


@pytest.mark.parametrize("bad", ["../escape", "a/b", ""])
def test_unsafe_case_ids_are_refused_and_leave_nothing(tmp_path: Path, view: CaseView, bad: str) -> None:
    """A case id that could escape the folder is refused, and no half-built cache is left."""
    entry = CacheEntry(view=view.model_copy(update={"case_id": bad}), input_sha256="0" * 64)
    with pytest.raises(CacheError, match="safe"):
        write_cache(tmp_path / "c", [entry], META)
    assert list(tmp_path.iterdir()) == []


def test_stale_temp_folders_are_cleared(tmp_path: Path, view: CaseView) -> None:
    """A temp folder left by a crashed build or publish doesn't block the next one."""
    (tmp_path / "c.tmp" / "junk").mkdir(parents=True)
    (tmp_path / "web.tmp").mkdir()
    cache = write_cache(tmp_path / "c", [CacheEntry(view=view, input_sha256="0" * 64)], META)
    publish(cache, tmp_path / "web")
    assert not (tmp_path / "c.tmp").exists() and not (tmp_path / "web.tmp").exists()
    assert verify_cache(tmp_path / "web") == []


def test_manifest_that_is_not_json_is_an_error(cache: Path) -> None:
    """A corrupt manifest raises ``CacheError``, not a JSON error."""
    (cache / MANIFEST).write_text("{not json")
    with pytest.raises(CacheError, match="JSON"):
        read_manifest(cache)


def test_view_that_is_not_a_caseview_is_an_error(cache: Path, view: CaseView) -> None:
    """A view file whose hash matches but whose content isn't a CaseView is refused."""
    import hashlib

    item = read_manifest(cache)["items"][0]
    path = item["files"]["view"]
    data = b'{"schema_version": 1}'
    (cache / path).write_bytes(data)
    manifest = json.loads((cache / MANIFEST).read_text())
    manifest["items"][0]["sha256"][path] = hashlib.sha256(data).hexdigest()
    (cache / MANIFEST).write_text(json.dumps(manifest))
    with pytest.raises(CacheError, match="valid CaseView"):
        load_view(cache, view.case_id)


def test_case_file_checks_key_and_hash(cache: Path, view: CaseView) -> None:
    """A cached extra comes back intact; an unknown key or a changed file is refused."""
    assert case_file(cache, view.case_id, "docx") == b"PK fake docx"
    with pytest.raises(CacheError, match="no cached"):
        case_file(cache, view.case_id, "pdf")
    with pytest.raises(CacheError, match="no cached"):
        case_file(cache, view.case_id, "view")
    (cache / read_manifest(cache)["items"][0]["files"]["docx"]).write_bytes(b"changed")
    with pytest.raises(CacheError, match="hash"):
        case_file(cache, view.case_id, "docx")
