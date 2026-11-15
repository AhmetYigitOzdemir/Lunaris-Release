#!/usr/bin/env python3
"""Fetch and validate Git LFS objects needed by the LUNARIS Docker image."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
import urllib.request
from pathlib import Path

REPOSITORY = "AhmetYigitOzdemir/Lunaris-Release"
BRANCH = "main"

LFS_FILES = {
    "data/ldem_80s_40m_float.img": {
        "size": 924160000,
        "sha256": "efa04e6f3fdd2a8c674f230e93ce4d535a6f53c4f878dc43aba4b070d15924cc",
    },
    "data/ldem_80s_40m_float.lbl": {
        "size": 4771,
        "sha256": "718be48cc97f9323fcd369a388e019294d78d2c62aa418892cfea797915bbc52",
    },
}

PROGRESS_INTERVAL_BYTES = 10 * 1024 * 1024


def parse_lfs_pointer(path: Path) -> tuple[str, int] | None:
    try:
        with path.open("rb") as handle:
            prefix = handle.read(256)
    except OSError:
        return None
    if not prefix.startswith(b"version https://git-lfs.github.com/spec/v1"):
        return None
    oid = None
    size = None
    for line in prefix.splitlines():
        if line.startswith(b"oid sha256:"):
            oid = line.decode("ascii").split(":", 1)[1].strip()
        elif line.startswith(b"size "):
            size = int(line.decode("ascii").split(" ", 1)[1].strip())
    if oid is None or size is None:
        raise RuntimeError(f"Invalid Git LFS pointer: {path}")
    return oid, size


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_existing(path: Path, expected_size: int, expected_sha256: str) -> bool:
    if not path.is_file():
        return False
    if path.stat().st_size != expected_size:
        return False
    return sha256_file(path) == expected_sha256


def fetch_lfs_object(
    relative_path: str,
    expected_size: int,
    expected_sha256: str,
    *,
    resume: bool,
    progress: bool,
    timeout: int,
) -> None:
    path = Path(relative_path)
    pointer = parse_lfs_pointer(path)

    if pointer is not None:
        pointer_oid, pointer_size = pointer
        if pointer_oid != expected_sha256 or pointer_size != expected_size:
            raise RuntimeError(
                f"Git LFS pointer metadata does not match the expected object for {relative_path}: "
                f"pointer=({pointer_oid}, {pointer_size}), expected=({expected_sha256}, {expected_size})"
            )

    if path.is_file() and not pointer and validate_existing(path, expected_size, expected_sha256):
        print(f"{relative_path}: already present and validated")
        return

    temp_path = path.with_name(path.name + ".lfs-download")

    if not resume and temp_path.exists():
        temp_path.unlink()

    partial_size = temp_path.stat().st_size if temp_path.exists() else 0
    if partial_size > expected_size:
        raise RuntimeError(
            f"Partial download for {relative_path} is larger than expected: "
            f"{partial_size} > {expected_size}"
        )

    # A complete, valid partial file can finish without another network request.
    if partial_size == expected_size and sha256_file(temp_path) == expected_sha256:
        os.replace(temp_path, path)
        print(f"{relative_path}: resumed partial download already validated ({partial_size} bytes)")
        return

    if partial_size:
        partial_sha256 = sha256_file(temp_path)
        print(
            f"{relative_path}: resuming from {partial_size} bytes "
            f"(partial SHA-256: {partial_sha256})"
        )
    else:
        print(f"{relative_path}: starting download")

    url = f"https://media.githubusercontent.com/media/{REPOSITORY}/{BRANCH}/{relative_path}"
    request_headers = {}
    if partial_size:
        request_headers["Range"] = f"bytes={partial_size}-"

    downloaded_this_run = 0
    total_downloaded = partial_size
    digest = hashlib.sha256()

    if partial_size:
        # Hash the bytes already present before appending to them.
        with temp_path.open("rb") as existing:
            for chunk in iter(lambda: existing.read(1024 * 1024), b""):
                digest.update(chunk)

    started_at = time.monotonic()
    last_progress_bytes = total_downloaded
    last_progress_time = started_at

    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=request_headers), timeout=timeout) as response:
            if response.status not in (200, 206):
                raise RuntimeError(f"Unexpected HTTP status {response.status} for {url}")

            if response.status == 206:
                content_range = response.headers.get("Content-Range")
                if content_range is None:
                    raise RuntimeError("HTTP 206 response is missing the required Content-Range header")

                # Expected form: "bytes <start>-<end>/<total>"
                try:
                    unit, range_and_total = content_range.split(" ", 1)
                    range_spec, total_text = range_and_total.split("/", 1)
                    start_text, end_text = range_spec.split("-", 1)
                    start = int(start_text)
                    end = int(end_text)
                    total = int(total_text)
                except (ValueError, IndexError) as exc:
                    raise RuntimeError(f"Invalid Content-Range header: {content_range!r}") from exc

                if unit != "bytes":
                    raise RuntimeError(f"Unsupported Content-Range unit: {unit!r}")
                if start != partial_size:
                    raise RuntimeError(
                        f"Unexpected Content-Range start {start}; expected {partial_size}"
                    )
                if end != expected_size - 1:
                    raise RuntimeError(
                        f"Unexpected Content-Range end {end}; expected {expected_size - 1}"
                    )
                if total != expected_size:
                    raise RuntimeError(
                        f"Unexpected Content-Range total {total}; expected {expected_size}"
                    )

                output_mode = "ab"
                if partial_size == 0:
                    output_mode = "wb"
                    total_downloaded = 0
                    digest = hashlib.sha256()
            else:
                # The server ignored Range and returned the complete object.
                output_mode = "wb"
                total_downloaded = 0
                digest = hashlib.sha256()
                partial_size = 0

            content_length = response.headers.get("Content-Length")
            if content_length is not None:
                remote_chunk_size = int(content_length)
                if response.status == 206:
                    if remote_chunk_size != expected_size - partial_size:
                        raise RuntimeError(
                            f"Remote range has unexpected size {remote_chunk_size}; "
                            f"expected {expected_size - partial_size}"
                        )
                elif remote_chunk_size != expected_size:
                    raise RuntimeError(
                        f"Remote object has unexpected size {remote_chunk_size}; expected {expected_size}"
                    )

            with temp_path.open(output_mode) as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    output.flush()
                    digest.update(chunk)
                    downloaded_this_run += len(chunk)
                    total_downloaded += len(chunk)

                    if progress and total_downloaded - last_progress_bytes >= PROGRESS_INTERVAL_BYTES:
                        now = time.monotonic()
                        elapsed = max(now - last_progress_time, 1e-9)
                        speed_mbps = (total_downloaded - last_progress_bytes) / elapsed / 1_000_000
                        percent = 100.0 * total_downloaded / expected_size
                        print(
                            f"\r{relative_path}: {total_downloaded / 1_000_000:.2f} MB / "
                            f"{expected_size / 1_000_000:.2f} MB ({percent:.1f}%), "
                            f"{speed_mbps:.2f} MB/s",
                            end="",
                            flush=True,
                        )
                        last_progress_bytes = total_downloaded
                        last_progress_time = now

        if progress:
            print()

        if total_downloaded != expected_size:
            raise RuntimeError(
                f"Downloaded {total_downloaded} bytes for {relative_path}; expected {expected_size}"
            )
        actual_sha256 = digest.hexdigest()
        if actual_sha256 != expected_sha256:
            raise RuntimeError(
                f"Downloaded {relative_path} has SHA-256 {actual_sha256}; "
                f"expected {expected_sha256}"
            )

        os.replace(temp_path, path)
        print(f"{relative_path}: downloaded and validated ({total_downloaded} bytes)")
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        if progress:
            print()
        # Preserve partial data after recoverable network/filesystem interruptions.
        raise RuntimeError(f"Network error while downloading {relative_path}: {exc}") from exc
    except Exception:
        if progress:
            print()
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch and validate LUNARIS Git LFS objects.")
    parser.add_argument("--progress", action="store_true", help="Show download progress.")
    parser.add_argument("--resume", action="store_true", help="Resume from an existing partial download.")
    parser.add_argument("--timeout", type=int, default=300, help="Socket timeout in seconds.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    os.chdir(root)
    for relative_path, expected in LFS_FILES.items():
        fetch_lfs_object(
            relative_path,
            expected["size"],
            expected["sha256"],
            resume=args.resume,
            progress=args.progress,
            timeout=args.timeout,
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
