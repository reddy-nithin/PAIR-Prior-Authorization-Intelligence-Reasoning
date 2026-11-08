"""Demo API routes (Phase 4 T7).

``GET /health``, ``GET /cases``, ``GET /cases/{id}``, ``GET /cases/{id}/files/{docx|pdf}``,
``POST /run`` (live, through the lab tunnel) and ``POST /export/{docx|pdf}``.

Uploads arrive as base64 inside a JSON body read straight from the request stream
with a size cap. Starlette's ``UploadFile`` would spool large files to a temp file
on disk, so it isn't used. Nothing from an upload is logged or echoed in an error.
"""

import base64
import binascii
import logging
import time
import uuid
from pathlib import PurePath
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from starlette.concurrency import run_in_threadpool

from pair.ingest.documents import DocumentError, read_upload
from pair.llm import LLMError
from pair.rules.active import ContextFlag
from pair.ui.cache import (
    CacheError,
    case_file,
    case_ids,
    case_index,
    load_view,
    verify_cache,
)
from pair.ui.export import ExportError, to_docx, to_pdf
from pair.ui.view import CaseView

logger = logging.getLogger(__name__)

router = APIRouter()

MEDIA = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}
EXPORTERS = {"docx": to_docx, "pdf": to_pdf}
MAX_DOCUMENTS = 20
MAX_EXPORT_BYTES = 5_000_000
FlagName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class ApiError(Exception):
    """An error the app returns as ``{"error": {"code", "message"}}``."""

    def __init__(self, status: int, code: str, message: str) -> None:
        """Keep the HTTP status, a stable code and a message with no case content."""
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class Upload(BaseModel):
    """One file: its name and base64 bytes."""

    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    data: str


class RunRequest(BaseModel):
    """A live run: the denial letter, the record files and the user's context answers."""

    model_config = ConfigDict(extra="forbid")
    denial: Upload
    documents: list[Upload] = Field(default_factory=list, max_length=MAX_DOCUMENTS)
    context: dict[FlagName, bool | None] = Field(default_factory=dict, max_length=32)


async def _body(request: Request, cap: int) -> bytes:
    """The request body, read from the stream into memory, refused past ``cap`` bytes.

    Raises:
        ApiError: 413 if the body is too large.
    """
    too_large = ApiError(413, "too_large", f"request is larger than {cap // 1_000_000} MB")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > cap:
        raise too_large
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > cap:
            raise too_large
        chunks.append(chunk)
    return b"".join(chunks)


def _cache(request: Request) -> Any:
    """The demo cache folder from the app settings."""
    return request.app.state.settings.cache_dir


def _cache_unavailable(error: CacheError) -> ApiError:
    """503 for a missing or failing cache, with the fix."""
    logger.warning("demo cache unavailable: %s", error)
    return ApiError(503, "cache_unavailable", f"{error}. Build it with `make demo-cache` (data/demo-cache).")


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    """Whether the cache verifies and how many cases it has, and whether live runs can reach the model."""
    try:
        cache = {"ok": not verify_cache(_cache(request)), "cases": len(case_ids(_cache(request)))}
    except CacheError:
        cache = {"ok": False, "cases": 0}
    runner = request.app.state.settings.runner
    live = {"enabled": runner is not None, "reachable": bool(runner and runner.reachable())}
    return {"status": "ok", "cache": cache, "live": live}


@router.get("/cases")
def cases(request: Request) -> dict[str, Any]:
    """The cached demo cases."""
    try:
        return {"cases": case_index(_cache(request))}
    except CacheError as error:
        raise _cache_unavailable(error) from error


def _known(request: Request, case_id: str) -> None:
    """404 unless ``case_id`` is cached.

    Raises:
        ApiError: 503 if the cache is unavailable, 404 if the case isn't in it.
    """
    try:
        ids = case_ids(_cache(request))
    except CacheError as error:
        raise _cache_unavailable(error) from error
    if case_id not in ids:
        raise ApiError(404, "not_found", f"no cached case {case_id!r}")


@router.get("/cases/{case_id}")
def case(request: Request, case_id: str) -> dict[str, Any]:
    """One cached CaseView."""
    _known(request, case_id)
    try:
        return load_view(_cache(request), case_id).model_dump(mode="json")
    except CacheError as error:
        raise _cache_unavailable(error) from error


@router.get("/cases/{case_id}/files/{fmt}")
def case_download(request: Request, case_id: str, fmt: str) -> Response:
    """A cached letter file."""
    if fmt not in MEDIA:
        raise ApiError(404, "not_found", f"no {fmt!r} download; use docx or pdf")
    _known(request, case_id)
    try:
        data = case_file(_cache(request), case_id, fmt)
    except CacheError as error:
        raise _cache_unavailable(error) from error
    return _attachment(data, fmt, case_id)


def _attachment(data: bytes, fmt: str, case_id: str) -> Response:
    """A file download response."""
    headers = {"Content-Disposition": f'attachment; filename="appeal-letter-{case_id}.{fmt}"'}
    return Response(content=data, media_type=MEDIA[fmt], headers=headers)


def _decode(upload: Upload) -> str:
    """The upload's text, read in memory.

    Raises:
        ApiError: 400 if the base64 is invalid or the file can't be read (the message names the file only).
    """
    try:
        data = base64.b64decode(upload.data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ApiError(400, "bad_request", f"{PurePath(upload.name).name}: not valid base64") from exc
    try:
        return read_upload(upload.name, data)
    except DocumentError as error:
        raise ApiError(400, "bad_upload", str(error)) from error


def _parse_run(body: bytes) -> RunRequest:
    """The run request.

    Raises:
        ApiError: 400 if the JSON is invalid or doesn't match ``RunRequest``.
    """
    try:
        return RunRequest.model_validate_json(body)
    except ValidationError as exc:
        raise ApiError(400, "bad_request", f"invalid run request ({exc.error_count()} problem(s))") from exc


@router.post("/run")
async def run(request: Request) -> Response:
    """Run steps 1 to 7 live on uploaded files (one run at a time)."""
    settings = request.app.state.settings
    runner = settings.runner
    if runner is None:
        raise ApiError(503, "live_off", "Live mode is off. The cached demo cases still work.")
    parsed = _parse_run(await _body(request, settings.max_body_bytes))
    denial_text = _decode(parsed.denial)
    notes, titles = {}, {}
    for i, upload in enumerate(parsed.documents, start=1):
        doc_id = f"doc-{i}"
        notes[doc_id] = _decode(upload)
        titles[doc_id] = PurePath(upload.name.replace("\\", "/")).stem or doc_id
    if not await run_in_threadpool(runner.reachable):
        raise ApiError(503, "model_unavailable", "The lab model isn't reachable (is the tunnel up?). "
                       "The cached demo cases still work.")  # fmt: skip
    lock = request.app.state.live_lock
    if not lock.acquire(blocking=False):
        raise ApiError(429, "busy", "Another run is in progress. Try again in a minute.")
    flags = {name: ContextFlag(value, "user input") for name, value in parsed.context.items()}
    case_id = f"live-{uuid.uuid4().hex[:8]}"
    start = time.perf_counter()
    try:
        view = await run_in_threadpool(runner.view, case_id, denial_text, notes, titles, flags, "live")
    except LLMError as error:
        logger.error("live run %s failed: %s", case_id, type(error).__name__)
        raise ApiError(502, "model_failed", "The model server failed during the run. Try again, "
                       "or use a cached demo case.") from error  # fmt: skip
    finally:
        lock.release()
    seconds = time.perf_counter() - start
    logger.info("live run %s: %.1f s, supported=%s", case_id, seconds, view.supported)
    return Response(content=view.model_dump_json(), media_type="application/json",
                    headers={"X-Run-Seconds": f"{seconds:.2f}"})  # fmt: skip


@router.post("/export/{fmt}")
async def export(request: Request, fmt: Literal["docx", "pdf"] | str) -> Response:
    """The letter of a posted CaseView as DOCX or PDF."""
    if fmt not in EXPORTERS:
        raise ApiError(404, "not_found", f"no {fmt!r} export; use docx or pdf")
    body = await _body(request, MAX_EXPORT_BYTES)
    try:
        view = CaseView.model_validate_json(body)
    except ValidationError as exc:
        raise ApiError(400, "bad_request", f"not a CaseView ({exc.error_count()} problem(s))") from exc
    try:
        data = await run_in_threadpool(EXPORTERS[fmt], view)
    except ExportError as error:
        raise ApiError(422, "export_failed", str(error)) from error
    return _attachment(data, fmt, view.case_id)
