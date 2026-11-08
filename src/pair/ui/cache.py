"""Demo cache: verified ``CaseView`` JSON and exported letters for cached mode (Phase 4 T5, ADR-0023).

Layout of a cache folder::

    manifest.json          schema_version, generated_at, host, run metadata, one item per case
    views/<case_id>.json   the CaseView
    files/<case_id>.<ext>  extras such as the DOCX and PDF letter

Every file has a SHA-256 in the manifest, so a cache edited by hand after the build
is caught. Each item also records the SHA-256 of the case's inputs (denial, record
documents, context), so a rebuild can tell which cases changed. Reading a cache
imports no LLM, extraction or verifier code: cached mode runs with Ollama off.
"""

import hashlib
import json
import logging
import platform
import re
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from pair.ui.view import CaseView

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
MANIFEST = "manifest.json"
INDEX = "index.json"
VIEWS, FILES = "views", "files"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class CacheError(RuntimeError):
    """The demo cache is missing, malformed, or fails its checks."""


@dataclass(frozen=True)
class CacheEntry:
    """One demo case: its view, the digest of its inputs, and extra files by extension."""

    view: CaseView
    input_sha256: str
    extras: Mapping[str, bytes] = field(default_factory=dict)


def _sha256(data: bytes) -> str:
    """Hex SHA-256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def input_digest(denial_text: str, documents: Mapping[str, str], context: Mapping[str, Any]) -> str:
    """SHA-256 of a case's inputs; dict order doesn't matter."""
    blob = json.dumps({"denial": denial_text, "documents": documents, "context": context}, sort_keys=True, default=str)
    return _sha256(blob.encode())


def _check_id(case_id: str) -> str:
    """``case_id`` if it is safe as a file name.

    Raises:
        CacheError: If it could escape the cache folder.
    """
    if not _SAFE_ID.match(case_id):
        raise CacheError(f"case id {case_id!r} is not safe as a file name")
    return case_id


def _write_entry(root: Path, entry: CacheEntry) -> dict[str, Any]:
    """Write one case's files under ``root``; return its manifest item."""
    case_id = _check_id(entry.view.case_id)
    payloads = {"view": (f"{VIEWS}/{case_id}.json", (entry.view.model_dump_json(indent=2) + "\n").encode())}
    for ext, data in sorted(entry.extras.items()):
        payloads[_check_id(ext)] = (f"{FILES}/{case_id}.{ext}", data)
    for path, data in payloads.values():
        (root / path).write_bytes(data)
    return {
        "case_id": case_id, "policy_id": entry.view.policy_id, "input_sha256": entry.input_sha256,
        "files": {key: path for key, (path, _) in payloads.items()},
        "sha256": {path: _sha256(data) for path, data in payloads.values()},
    }  # fmt: skip


def _replace_dir(staged: Path, dest: Path) -> None:
    """Swap ``staged`` into ``dest``, removing what was there."""
    if dest.exists():
        shutil.rmtree(dest)
    staged.rename(dest)


def write_cache(root: Path, entries: Sequence[CacheEntry], run: Mapping[str, Any]) -> Path:
    """Write a fresh cache at ``root`` (replacing any old one) and return ``root``.

    ``run`` holds the build metadata: drafter, verifier, threshold key, premise rule, git commit.

    Raises:
        CacheError: On duplicate or unsafe case ids.
    """
    ids = [entry.view.case_id for entry in entries]
    if dupes := sorted({i for i in ids if ids.count(i) > 1}):
        raise CacheError(f"duplicate case ids: {', '.join(dupes)}")
    staged = root.with_name(root.name + ".tmp")
    if staged.exists():
        shutil.rmtree(staged)
    (staged / VIEWS).mkdir(parents=True)
    (staged / FILES).mkdir()
    try:
        items = [_write_entry(staged, entry) for entry in entries]
    except CacheError:
        shutil.rmtree(staged)
        raise
    manifest = {
        "schema_version": SCHEMA_VERSION, "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "host": platform.node(), "run": dict(run), "items": items,
    }  # fmt: skip
    (staged / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n")
    _replace_dir(staged, root)
    logger.info("demo cache: %d case(s) at %s", len(items), root)
    return root


def read_manifest(root: Path) -> dict[str, Any]:
    """The cache's manifest.

    Raises:
        CacheError: If it is missing, not JSON, or from another schema version.
    """
    path = root / MANIFEST
    if not path.is_file():
        raise CacheError(f"no manifest at {path}; build the cache first")
    try:
        manifest: dict[str, Any] = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        logger.error("unreadable manifest %s: %s", path, exc)
        raise CacheError(f"{path} is not valid JSON") from exc
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise CacheError(f"unsupported schema version {manifest.get('schema_version')!r} (expected {SCHEMA_VERSION})")
    return manifest


def verify_cache(root: Path) -> list[str]:
    """Problems with the cache: missing files, hash mismatches, files the manifest doesn't list. Empty means OK.

    Raises:
        CacheError: If the manifest itself can't be read.
    """
    manifest = read_manifest(root)
    problems: list[str] = []
    listed: set[str] = set()
    for item in manifest["items"]:
        for path, digest in item["sha256"].items():
            listed.add(path)
            file = root / path
            if not file.is_file():
                problems.append(f"missing: {path}")
            elif _sha256(file.read_bytes()) != digest:
                problems.append(f"hash mismatch: {path}")
    on_disk = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()} - {MANIFEST, INDEX}
    problems += [f"not in manifest: {path}" for path in sorted(on_disk - listed)]
    return problems


def _item(manifest: Mapping[str, Any], case_id: str) -> dict[str, Any]:
    """The manifest item for ``case_id``.

    Raises:
        CacheError: If the case isn't cached.
    """
    for item in manifest["items"]:
        if item["case_id"] == case_id:
            return dict(item)
    raise CacheError(f"case {case_id!r} is not in the demo cache")


def load_view(root: Path, case_id: str) -> CaseView:
    """The cached view for ``case_id``, after checking its hash.

    Raises:
        CacheError: If the case isn't cached, its file changed, or it isn't a valid CaseView.
    """
    item = _item(read_manifest(root), case_id)
    path = item["files"]["view"]
    data = (root / path).read_bytes()
    if _sha256(data) != item["sha256"][path]:
        raise CacheError(f"hash mismatch: {path}; rebuild or re-verify the cache")
    try:
        return CaseView.model_validate_json(data)
    except ValidationError as exc:
        logger.error("cached view %s is not a CaseView: %d error(s)", path, exc.error_count())
        raise CacheError(f"{path} is not a valid CaseView") from exc


def _index_row(root: Path, item: Mapping[str, Any]) -> dict[str, Any]:
    """One row of the web app's case list."""
    view = load_view(root, item["case_id"])
    return {
        "case_id": view.case_id, "policy_id": view.policy_id, "policy_title": view.policy_title,
        "service": view.denial.service if view.denial else None,
        "overall": view.overall.label if view.overall else None, "files": item["files"],
    }  # fmt: skip


def case_index(root: Path) -> list[dict[str, Any]]:
    """The web app's case list: one row per cached case (each view's hash is checked).

    Raises:
        CacheError: If the manifest can't be read or a view fails its check.
    """
    return [_index_row(root, item) for item in read_manifest(root)["items"]]


def case_ids(root: Path) -> list[str]:
    """Ids of the cached cases.

    Raises:
        CacheError: If the manifest can't be read.
    """
    return [str(item["case_id"]) for item in read_manifest(root)["items"]]


def case_file(root: Path, case_id: str, key: str) -> bytes:
    """A cached extra file (``docx``/``pdf``) after checking its hash.

    Raises:
        CacheError: If the case or file isn't cached, or the file changed.
    """
    item = _item(read_manifest(root), case_id)
    if key not in item["files"] or key == "view":
        raise CacheError(f"case {case_id!r} has no cached {key!r} file")
    path = str(item["files"][key])
    data = (root / path).read_bytes()
    if _sha256(data) != item["sha256"][path]:
        raise CacheError(f"hash mismatch: {path}; rebuild or re-verify the cache")
    return data


def publish(root: Path, dest: Path) -> Path:
    """Copy a verified cache to the web app's static folder with an ``index.json``; return ``dest``.

    Raises:
        CacheError: If the cache fails verification (``dest`` is left untouched).
    """
    if problems := verify_cache(root):
        raise CacheError(f"cache fails verify ({len(problems)} problem(s)): {'; '.join(problems[:5])}")
    manifest = read_manifest(root)
    staged = dest.with_name(dest.name + ".tmp")
    if staged.exists():
        shutil.rmtree(staged)
    shutil.copytree(root, staged)
    index = {"schema_version": SCHEMA_VERSION, "generated_at": manifest["generated_at"],
             "cases": case_index(root)}  # fmt: skip
    (staged / INDEX).write_text(json.dumps(index, indent=2) + "\n")
    dest.parent.mkdir(parents=True, exist_ok=True)
    _replace_dir(staged, dest)
    logger.info("published %d demo case(s) to %s", len(index["cases"]), dest)
    return dest
