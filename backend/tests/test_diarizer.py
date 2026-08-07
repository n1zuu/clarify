"""Unit tests for models/diarizer.py helpers."""

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models.diarizer import (
    _friendly_name,
    _find_speaker_at,
    _split_words_by_turns,
    _make_turn_segment,
)


# ── _friendly_name ─────────────────────────────────────────────────────

def test_friendly_name_speaker_index():
    assert _friendly_name("SPEAKER_00") == "Speaker 1"
    assert _friendly_name("SPEAKER_01") == "Speaker 2"
    assert _friendly_name("SPEAKER_09") == "Speaker 10"


def test_friendly_name_plain_label():
    assert _friendly_name("alice") == "Alice"
    assert _friendly_name("") == ""


def test_friendly_name_none():
    assert _friendly_name(None) is None


# ── _find_speaker_at ───────────────────────────────────────────────────

def test_find_speaker_at_inside_turn():
    turns = [(0.0, 5.0, "SPEAKER_00"), (5.0, 10.0, "SPEAKER_01")]
    assert _find_speaker_at(2.0, turns) == "Speaker 1"
    assert _find_speaker_at(7.0, turns) == "Speaker 2"


def test_find_speaker_at_boundary():
    turns = [(0.0, 5.0, "SPEAKER_00"), (5.0, 10.0, "SPEAKER_01")]
    # Exactly on the boundary — first matching turn wins.
    assert _find_speaker_at(5.0, turns) == "Speaker 1"


def test_find_speaker_at_nearest_when_outside():
    turns = [(10.0, 20.0, "SPEAKER_00")]
    # 0.0 is outside all turns — nearest turn is (10,20).
    assert _find_speaker_at(0.0, turns) == "Speaker 1"


def test_find_speaker_at_no_turns():
    assert _find_speaker_at(1.0, []) is None


# ── _split_words_by_turns ──────────────────────────────────────────────

def test_split_words_by_turns_groups_consecutive_speakers():
    words = [
        {"word": "a", "start": 0.0, "end": 0.5},
        {"word": "b", "start": 0.5, "end": 1.0},
        {"word": "c", "start": 6.0, "end": 6.5},
        {"word": "d", "start": 6.5, "end": 7.0},
    ]
    turns = [(0.0, 5.0, "SPEAKER_00"), (5.0, 10.0, "SPEAKER_01")]
    segments = _split_words_by_turns(words, turns)
    assert len(segments) == 2
    assert segments[0]["speaker"] == "Speaker 1"
    assert segments[0]["text"] == "a b"
    assert segments[1]["speaker"] == "Speaker 2"
    assert segments[1]["text"] == "c d"


def test_split_words_by_turns_empty():
    assert _split_words_by_turns([], [(0.0, 1.0, "SPEAKER_00")]) == []


# ── _make_turn_segment ─────────────────────────────────────────────────

def test_make_turn_segment():
    words = [
        {"word": "a", "start": 0.0, "end": 0.5},
        {"word": "b", "start": 0.5, "end": 1.0},
    ]
    seg = _make_turn_segment(words, "Speaker 1")
    assert seg["start"] == 0.0
    assert seg["end"] == 1.0
    assert seg["text"] == "a b"
    assert seg["speaker"] == "Speaker 1"