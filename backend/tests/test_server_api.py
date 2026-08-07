"""Unit tests for server_api.py helpers and job store."""

import sys
import time
import wave
import struct
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import server_api
from server_api import (
    _load_wav_as_float32,
    _purge_old_jobs,
    _require_api_key,
    _jobs,
    _jobs_lock,
    _JOB_TTL_SECONDS,
)


# ── _load_wav_as_float32 ───────────────────────────────────────────────

def _write_wav(path: Path, samples: list[int], rate: int = 16000):
    """Write a minimal 16-bit mono WAV file."""
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def test_load_wav_as_float32(tmp_path):
    wav = tmp_path / "test.wav"
    _write_wav(wav, [0, 16384, -16384, 32767, -32768])
    data = _load_wav_as_float32(str(wav))
    assert data.dtype == "float32"
    assert len(data) == 5
    assert data[0] == 0.0
    assert abs(data[1] - 0.5) < 1e-3      # 16384 / 32768
    assert abs(data[2] - (-0.5)) < 1e-3   # -16384 / 32768
    assert abs(data[3] - 1.0) < 1e-3      # 32767 / 32768 ≈ 1.0
    assert abs(data[4] - (-1.0)) < 1e-3   # -32768 / 32768


# ── _purge_old_jobs ────────────────────────────────────────────────────

def test_purge_old_jobs_removes_expired():
    with _jobs_lock:
        _jobs.clear()
        _jobs["old"] = {"status": "done", "created_at": time.time() - _JOB_TTL_SECONDS - 10}
        _jobs["fresh"] = {"status": "done", "created_at": time.time()}
    _purge_old_jobs()
    with _jobs_lock:
        assert "old" not in _jobs
        assert "fresh" in _jobs
        _jobs.clear()


def test_purge_old_jobs_keeps_recent():
    with _jobs_lock:
        _jobs.clear()
        _jobs["recent"] = {"status": "processing", "created_at": time.time() - 30}
    _purge_old_jobs()
    with _jobs_lock:
        assert "recent" in _jobs
        _jobs.clear()


def test_purge_old_jobs_empty_store():
    with _jobs_lock:
        _jobs.clear()
    _purge_old_jobs()  # should not raise


# ── _require_api_key ───────────────────────────────────────────────────

def test_api_key_disabled_by_default():
    # When _API_KEY is empty, any request passes.
    server_api._API_KEY = ""
    assert _require_api_key(None) is True
    assert _require_api_key("anything") is True


def test_api_key_required_when_set():
    server_api._API_KEY = "secret123"
    try:
        assert _require_api_key("secret123") is True
    finally:
        server_api._API_KEY = ""


def test_api_key_rejected_when_wrong():
    server_api._API_KEY = "secret123"
    try:
        from fastapi import HTTPException
        try:
            _require_api_key("wrong")
            assert False, "Expected HTTPException"
        except HTTPException as e:
            assert e.status_code == 401
    finally:
        server_api._API_KEY = ""