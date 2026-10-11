from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass(frozen=True)
class DownloadReceipt:
    path: str
    sha256: str
    size_bytes: int
    cached: bool
    checksum_verified: bool
    retrieval_url: str


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_file(
    url: str,
    destination: str | Path,
    *,
    expected_sha256: str | None = None,
    timeout: float = 300,
) -> DownloadReceipt:
    """Stream to a temporary file; never overwrite a raw cache entry."""
    target = Path(destination)
    expected = expected_sha256.lower() if expected_sha256 else None
    if target.exists():
        actual = sha256_file(target)
        if expected and actual != expected:
            raise ValueError(f"Cached file checksum mismatch: {target}")
        return DownloadReceipt(
            path=str(target.resolve()),
            sha256=actual,
            size_bytes=target.stat().st_size,
            cached=True,
            checksum_verified=bool(expected),
            retrieval_url=url,
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.part")
    digest = hashlib.sha256()
    size = 0
    try:
        with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as response:
            response.raise_for_status()
            with temporary.open("wb") as output:
                for chunk in response.iter_bytes(1024 * 1024):
                    if not chunk:
                        continue
                    output.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
        actual = digest.hexdigest()
        if expected and actual != expected:
            raise ValueError(f"Downloaded file checksum mismatch for {url}")
        os.replace(temporary, target)
        return DownloadReceipt(
            path=str(target.resolve()),
            sha256=actual,
            size_bytes=size,
            cached=False,
            checksum_verified=bool(expected),
            retrieval_url=url,
        )
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def copy_cached_file(
    source: str | Path,
    destination: str | Path,
    *,
    expected_sha256: str | None = None,
) -> DownloadReceipt:
    source_path = Path(source)
    target = Path(destination)
    if not source_path.is_file():
        raise FileNotFoundError(f"Cached source file does not exist: {source_path}")
    source_digest = sha256_file(source_path)
    expected = expected_sha256.lower() if expected_sha256 else None
    if expected and source_digest != expected:
        raise ValueError(f"Cached source checksum mismatch: {source_path}")
    if target.exists():
        target_digest = sha256_file(target)
        if target_digest != source_digest:
            raise ValueError(f"Existing raw cache entry differs from source: {target}")
        return DownloadReceipt(str(target.resolve()), target_digest, target.stat().st_size, True, bool(expected), str(source_path.resolve()))
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.part")
    try:
        shutil.copyfile(source_path, temporary)
        copied_digest = sha256_file(temporary)
        if copied_digest != source_digest:
            raise ValueError(f"Copy checksum mismatch while caching {source_path}")
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return DownloadReceipt(str(target.resolve()), source_digest, target.stat().st_size, False, bool(expected), str(source_path.resolve()))