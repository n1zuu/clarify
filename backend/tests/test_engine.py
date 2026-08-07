"""Unit tests for core/engine.py helpers."""

import sys
import os
from pathlib import Path

# Ensure backend root is on sys.path so `core`, `models`, etc. import cleanly.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.engine import _segments_to_text, _fmt_time, EngineConfig, ProcessingResult


# ── _fmt_time ──────────────────────────────────────────────────────────

def test_fmt_time_minutes_seconds():
    assert _fmt_time(0) == "00:00"
    assert _fmt_time(61) == "01:01"
    assert _fmt_time(3599) == "59:59"


def test_fmt_time_hours():
    assert _fmt_time(3600) == "01:00:00"
    assert _fmt_time(3661) == "01:01:01"


def test_fmt_time_rounds_down():
    assert _fmt_time(59.9) == "00:59"


# ── _segments_to_text ──────────────────────────────────────────────────

def test_segments_to_text_with_speaker():
    segments = [
        {"start": 0.0, "end": 2.0, "text": "Hello there", "speaker": "Speaker 1"},
        {"start": 2.5, "end": 4.0, "text": "Hi", "speaker": "Speaker 2"},
    ]
    text = _segments_to_text(segments)
    assert text == "[00:00] Speaker 1: Hello there\n[00:02] Speaker 2: Hi"


def test_segments_to_text_without_speaker():
    segments = [
        {"start": 0.0, "end": 2.0, "text": "Hello there", "speaker": None},
    ]
    text = _segments_to_text(segments)
    assert text == "[00:00] Hello there"


def test_segments_to_text_empty():
    assert _segments_to_text([]) == ""


# ── EngineConfig / ProcessingResult dataclasses ────────────────────────

def test_engine_config_defaults():
    cfg = EngineConfig()
    assert cfg.output_dir == "./output"
    assert cfg.export_format == "docx"
    assert cfg.diarization is True
    assert cfg.sample_rate == 16000
    assert cfg.channels == 1


def test_processing_result_defaults():
    result = ProcessingResult()
    assert result.audio_path is None
    assert result.transcript_text == ""
    assert result.speakers == []
    assert result.duration_seconds == 0.0
    assert result.error is None