"""Shared helpers for downloading public datasets into ``data/raw/``.

Downloads stream to a temporary file, record a SHA-256, and fail loudly. Only
HTTPS (and ``file://`` for tests) is allowed.
"""

import datetime as dt
import fnmatch
import hashlib
import json
import logging
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES: frozenset[str] = frozenset({"https", "file"})
TIMEOUT_SECONDS: int = 300
CHUNK_BYTES: int = 1 << 20
USER_AGENT: str = "PAIR-dataset-downloader/0.1 (+https://github.com/reddy-nithin)"
"""Some portals (e.g. CHHS) reject Python's default User-Agent with HTTP 403."""


DEFAULT_PORTS: dict[str, int] = {"http": 80, "https": 443}


def strip_default_port(url: str) -> str:
    """Remove an explicit default port (``:443`` for https, ``:80`` for http) from a URL.

    Presigned S3 URLs are signed for the bare host; sending ``Host: host:443``
    makes S3 answer 403 SignatureDoesNotMatch.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.port is None or parts.port != DEFAULT_PORTS.get(parts.scheme):
        return url
    host = parts.hostname or ""
    netloc = f"{parts.username}@{host}" if parts.username else host
    return urllib.parse.urlunsplit(parts._replace(netloc=netloc))


class _DefaultPortRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow redirects, dropping explicit default ports from the target URL."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        """Rewrite ``newurl`` before handing it to the standard redirect logic."""
        return super().redirect_request(req, fp, code, msg, headers, strip_default_port(newurl))  # type: ignore[arg-type]


_OPENER = urllib.request.build_opener(_DefaultPortRedirectHandler)


class DownloadError(RuntimeError):
    """A download or archive extraction failed."""


@dataclass(frozen=True)
class DownloadRecord:
    """Provenance for one downloaded file, written to the manifest."""

    url: str
    path: str
    sha256: str
    size_bytes: int
    retrieved: str


def download_file(url: str, dest_dir: Path, filename: str) -> DownloadRecord:
    """Download ``url`` to ``dest_dir / filename`` and return its provenance.

    Args:
        url: HTTPS (or ``file://``) URL to fetch.
        dest_dir: Folder to write into; created if missing.
        filename: Name of the saved file.

    Returns:
        A record with the URL, saved name, SHA-256, size and retrieval date.

    Raises:
        DownloadError: On a disallowed scheme, an HTTP or network error, or a
            non-200 status. No partial file is left behind.
    """
    scheme = urllib.parse.urlparse(url).scheme
    if scheme not in ALLOWED_SCHEMES:
        raise DownloadError(f"refusing URL scheme {scheme!r}: {url}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / filename
    digest = hashlib.sha256()
    size = 0
    with tempfile.NamedTemporaryFile(dir=dest_dir, delete=False) as handle:
        temp_path = Path(handle.name)
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with _open(request) as response:
                status = getattr(response, "status", None)
                if status not in (None, 200):
                    raise DownloadError(f"HTTP {status} for {url}")
                while chunk := response.read(CHUNK_BYTES):
                    handle.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
        except (urllib.error.URLError, OSError, DownloadError) as error:
            handle.close()
            temp_path.unlink(missing_ok=True)
            logger.error("download failed for %s: %s", url, error)
            raise DownloadError(f"download failed for {url}: {error}") from error
    temp_path.replace(target)
    logger.info("downloaded %s (%d bytes) to %s", url, size, target)
    return DownloadRecord(
        url=url,
        path=filename,
        sha256=digest.hexdigest(),
        size_bytes=size,
        retrieved=dt.date.today().isoformat(),
    )


def _open(request: urllib.request.Request) -> Any:
    """Open ``request`` with the default-port-safe redirect handler."""
    return _OPENER.open(request, timeout=TIMEOUT_SECONDS)


def extract_matching(archive_path: Path, dest_dir: Path, patterns: list[str]) -> list[Path]:
    """Extract zip members whose file name matches any of ``patterns``.

    Args:
        archive_path: The zip file to read.
        dest_dir: Folder to extract into; created if missing.
        patterns: Shell-style patterns matched against each member's base name.

    Returns:
        Paths of the extracted files, in archive order.

    Raises:
        DownloadError: If the archive is corrupt or a member would be written
            outside ``dest_dir``.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    root = dest_dir.resolve()
    extracted: list[Path] = []
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                name = Path(member.filename).name
                if member.is_dir() or not any(fnmatch.fnmatch(name, p) for p in patterns):
                    continue
                target = (dest_dir / member.filename).resolve()
                if not target.is_relative_to(root):
                    raise DownloadError(f"unsafe archive member {member.filename!r} in {archive_path}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as sink:
                    shutil.copyfileobj(source, sink)
                extracted.append(target)
    except zipfile.BadZipFile as error:
        logger.error("bad zip file %s: %s", archive_path, error)
        raise DownloadError(f"bad zip file {archive_path}: {error}") from error
    return extracted


def write_manifest(records: list[DownloadRecord], path: Path, notice: str) -> Path:
    """Write download provenance and a license notice as JSON.

    Args:
        records: One record per downloaded file.
        path: Where to write the manifest.
        notice: License or usage terms that apply to the files.

    Returns:
        The manifest path.
    """
    payload = {"notice": notice, "files": [asdict(record) for record in records]}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
