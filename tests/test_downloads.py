"""Tests for the shared dataset download helpers."""

import hashlib
import json
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Self

import pytest

from pair import downloads
from pair.downloads import (
    DownloadError,
    DownloadRecord,
    download_file,
    extract_matching,
    strip_default_port,
    write_manifest,
)


def test_download_file_saves_and_hashes(tmp_path: Path) -> None:
    """A file URL is copied to the destination and its SHA-256 recorded."""
    source = tmp_path / "src.txt"
    source.write_bytes(b"hello")
    record = download_file(source.as_uri(), tmp_path / "out", "copy.txt")
    assert (tmp_path / "out" / "copy.txt").read_bytes() == b"hello"
    assert record.sha256 == hashlib.sha256(b"hello").hexdigest()
    assert record.size_bytes == 5
    assert record.url == source.as_uri()


def test_download_http_error_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An HTTP error becomes a DownloadError naming the URL, and no file is left behind."""

    def fail(*_args: object, **_kwargs: object) -> None:
        raise urllib.error.HTTPError("https://x.test/f", 403, "Forbidden", None, None)  # type: ignore[arg-type]

    monkeypatch.setattr(downloads._OPENER, "open", fail)
    with pytest.raises(DownloadError, match="https://x.test/f"):
        download_file("https://x.test/f", tmp_path, "f.csv")
    assert not (tmp_path / "f.csv").exists()


def test_download_rejects_non_https_remote(tmp_path: Path) -> None:
    """Plain-HTTP and other schemes are refused."""
    with pytest.raises(DownloadError, match="scheme"):
        download_file("http://x.test/f", tmp_path, "f")


def test_extract_matching_handles_nested_zip(tmp_path: Path) -> None:
    """Members matching a pattern are extracted, including from a zip inside the zip."""
    inner = tmp_path / "inner_csv.zip"
    with zipfile.ZipFile(inner, "w") as archive:
        archive.writestr("lcd.csv", "a,b\n1,2\n")
    outer = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer, "w") as archive:
        archive.write(inner, "inner_csv.zip")
        archive.writestr("big.mdb", "skip me")
    extracted = extract_matching(outer, tmp_path / "out", ["*_csv.zip"])
    assert [p.name for p in extracted] == ["inner_csv.zip"]
    nested = extract_matching(extracted[0], tmp_path / "out" / "lcd_csv", ["*.csv"])
    assert (tmp_path / "out" / "lcd_csv" / "lcd.csv").read_text() == "a,b\n1,2\n"
    assert not (tmp_path / "out" / "big.mdb").exists()
    assert len(nested) == 1


def test_extract_rejects_path_traversal(tmp_path: Path) -> None:
    """Archive members that escape the destination are refused."""
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as archive:
        archive.writestr("../escape.csv", "x")
    with pytest.raises(DownloadError, match="unsafe"):
        extract_matching(evil, tmp_path / "out", ["*.csv"])


def test_write_manifest_is_json(tmp_path: Path) -> None:
    """The manifest lists every record with URL, hash and date."""
    record = DownloadRecord(url="https://x.test/f", path="f", sha256="ab", size_bytes=1, retrieved="2026-10-15")
    path = write_manifest([record], tmp_path / "manifest.json", notice="license text")
    data = json.loads(path.read_text())
    assert data["files"][0]["sha256"] == "ab"
    assert data["notice"] == "license text"


class FakeResponse:
    """A minimal urlopen response with a chosen status."""

    def __init__(self, status: int) -> None:
        """Store the status code."""
        self.status = status

    def __enter__(self) -> Self:
        """Return self as the context value."""
        return self

    def __exit__(self, *_args: object) -> None:
        """Nothing to clean up."""

    def read(self, _size: int) -> bytes:
        """Return no data."""
        return b""


def test_non_200_status_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A non-200 response is an error, not an empty file."""
    monkeypatch.setattr(downloads._OPENER, "open", lambda *_a, **_k: FakeResponse(500))
    with pytest.raises(DownloadError, match="HTTP 500"):
        download_file("https://x.test/f", tmp_path, "f.csv")
    assert list(tmp_path.iterdir()) == []


def test_bad_zip_raises(tmp_path: Path) -> None:
    """A corrupt archive fails with the file name."""
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip")
    with pytest.raises(DownloadError, match="bad zip file"):
        extract_matching(bad, tmp_path / "out", ["*"])


def test_requests_send_descriptive_user_agent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Some portals (CHHS) return 403 to Python's default User-Agent."""
    seen: list[urllib.request.Request] = []

    def capture(request: urllib.request.Request, **_kwargs: object) -> FakeResponse:
        seen.append(request)
        return FakeResponse(200)

    monkeypatch.setattr(downloads._OPENER, "open", capture)
    download_file("https://x.test/f", tmp_path, "f.csv")
    assert seen[0].get_header("User-agent", "").startswith("PAIR-dataset-downloader/")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://s3.amazonaws.com:443/b/k.csv?X-Amz-Signature=a", "https://s3.amazonaws.com/b/k.csv?X-Amz-Signature=a"),
        ("http://x.test:80/p", "http://x.test/p"),
        ("https://x.test:8443/p", "https://x.test:8443/p"),
        ("https://x.test/p", "https://x.test/p"),
    ],
)
def test_strip_default_port(url: str, expected: str) -> None:
    """Presigned S3 redirects break if the Host header carries ':443' (CHHS IMR download)."""
    assert strip_default_port(url) == expected


def test_redirect_handler_strips_default_port() -> None:
    """The redirect handler rewrites the target URL before following it."""
    handler = downloads._DefaultPortRedirectHandler()
    original = urllib.request.Request("https://data.test/f", headers={"User-Agent": "x"})
    redirected = handler.redirect_request(
        original, None, 302, "Found", {}, "https://s3.amazonaws.com:443/b/k.csv?sig=1"
    )
    assert redirected is not None
    assert redirected.full_url == "https://s3.amazonaws.com/b/k.csv?sig=1"
