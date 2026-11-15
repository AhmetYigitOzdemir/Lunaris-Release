from __future__ import annotations

import hashlib
import io
import urllib.error
from pathlib import Path

import pytest

from fetch_lfs_data import fetch_lfs_object


class FakeResponse:
    def __init__(self, status, chunks, headers):
        self.status = status
        self._chunks = list(chunks)
        self.headers = headers

    def read(self, size=-1):
        if not self._chunks:
            return b""
        return self._chunks.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def make_data(size=100):
    return b"a" * size


def expected_hash(data):
    return hashlib.sha256(data).hexdigest()


def test_http_200_valid_download(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("data").mkdir()
    data = make_data(100)
    digest = expected_hash(data)

    response = FakeResponse(200, [data], {"Content-Length": str(len(data))})
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: response)

    fetch_lfs_object("data/test.bin", len(data), digest, resume=True, progress=False, timeout=10)
    assert Path("data/test.bin").read_bytes() == data


def test_http_206_valid_resume(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("data").mkdir()
    data = make_data(100)
    digest = expected_hash(data)
    partial = data[:30]
    Path("data/test.bin.lfs-download").write_bytes(partial)

    response = FakeResponse(
        206,
        [data[30:]],
        {"Content-Range": f"bytes 30-99/{len(data)}", "Content-Length": "70"},
    )
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: response)

    fetch_lfs_object("data/test.bin", len(data), digest, resume=True, progress=False, timeout=10)
    assert Path("data/test.bin").read_bytes() == data


def test_http_206_missing_content_range_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("data").mkdir()
    data = make_data(100)
    Path("data/test.bin.lfs-download").write_bytes(data[:10])

    response = FakeResponse(206, [data[10:]], {"Content-Length": "90"})
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: response)

    with pytest.raises(RuntimeError, match="missing the required Content-Range"):
        fetch_lfs_object("data/test.bin", len(data), expected_hash(data), resume=True, progress=False, timeout=10)


def test_http_206_wrong_start_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("data").mkdir()
    data = make_data(100)
    Path("data/test.bin.lfs-download").write_bytes(data[:10])

    response = FakeResponse(
        206,
        [data[10:]],
        {"Content-Range": "bytes 5-99/100", "Content-Length": "90"},
    )
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: response)

    with pytest.raises(RuntimeError, match="Unexpected Content-Range start"):
        fetch_lfs_object("data/test.bin", len(data), expected_hash(data), resume=True, progress=False, timeout=10)


def test_http_206_wrong_total_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("data").mkdir()
    data = make_data(100)
    Path("data/test.bin.lfs-download").write_bytes(data[:10])

    response = FakeResponse(
        206,
        [data[10:]],
        {"Content-Range": "bytes 10-99/99", "Content-Length": "90"},
    )
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: response)

    with pytest.raises(RuntimeError, match="Unexpected Content-Range total"):
        fetch_lfs_object("data/test.bin", len(data), expected_hash(data), resume=True, progress=False, timeout=10)


def test_existing_valid_file_skips_download(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("data").mkdir()
    data = make_data(50)
    Path("data/test.bin").write_bytes(data)

    def fail_urlopen(*args, **kwargs):
        raise AssertionError("download should not be called")

    monkeypatch.setattr("urllib.request.urlopen", fail_urlopen)
    fetch_lfs_object("data/test.bin", len(data), expected_hash(data), resume=True, progress=False, timeout=10)
    assert Path("data/test.bin").read_bytes() == data


def test_invalid_hash_removes_temporary_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("data").mkdir()
    data = make_data(20)
    wrong_hash = "0" * 64
    response = FakeResponse(200, [data], {"Content-Length": str(len(data))})
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: response)

    with pytest.raises(RuntimeError, match="SHA-256"):
        fetch_lfs_object("data/test.bin", len(data), wrong_hash, resume=False, progress=False, timeout=10)
    assert not Path("data/test.bin.lfs-download").exists()
