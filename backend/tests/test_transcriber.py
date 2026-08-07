"""Unit tests for models/transcriber.py helpers."""

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models.transcriber import (
    _merge_words,
    _words_to_segments,
    _make_segment,
    _extract_word_timestamps,
)


# ── _merge_words ───────────────────────────────────────────────────────

def test_merge_words_empty_committed():
    new = [{"word": "a", "start": 0.0, "end": 0.5}]
    assert _merge_words([], new, 5.0) == new


def test_merge_words_empty_new():
    committed = [{"word": "a", "start": 0.0, "end": 0.5}]
    assert _merge_words(committed, [], 5.0) == []


def test_merge_words_discards_overlap():
    committed = [
        {"word": "hello", "start": 0.0, "end": 1.0},
        {"word": "world", "start": 1.0, "end": 2.0},
    ]
    # New chunk overlaps the committed region; only the tail past 2.0s survives.
    new_words = [
        {"word": "hello", "start": 0.0, "end": 1.0},
        {"word": "world", "start": 1.0, "end": 2.0},
        {"word": "again", "start": 2.5, "end": 3.0},
    ]
    merged = _merge_words(committed, new_words, 5.0)
    assert merged == [{"word": "again", "start": 2.5, "end": 3.0}]


def test_merge_words_all_overlap_discards_all():
    committed = [{"word": "a", "start": 0.0, "end": 1.0}]
    new_words = [{"word": "a", "start": 0.0, "end": 1.0}]
    assert _merge_words(committed, new_words, 5.0) == []


# ── _words_to_segments ─────────────────────────────────────────────────

def test_words_to_segments_empty():
    assert _words_to_segments([]) == []


def test_words_to_segments_single_segment():
    words = [
        {"word": "a", "start": 0.0, "end": 0.5},
        {"word": "b", "start": 0.5, "end": 1.0},
    ]
    segments = _words_to_segments(words)
    assert len(segments) == 1
    assert segments[0]["text"] == "a b"
    assert segments[0]["start"] == 0.0
    assert segments[0]["end"] == 1.0


def test_words_to_segments_splits_on_silence():
    words = [
        {"word": "a", "start": 0.0, "end": 0.5},
        {"word": "b", "start": 3.0, "end": 3.5},  # gap > 1.5s threshold
    ]
    segments = _words_to_segments(words)
    assert len(segments) == 2
    assert segments[0]["text"] == "a"
    assert segments[1]["text"] == "b"


def test_words_to_segments_splits_on_word_count():
    words = [
        {"word": f"w{i}", "start": float(i), "end": float(i) + 0.5}
        for i in range(35)  # exceeds max_words_per_segment=30
    ]
    segments = _words_to_segments(words)
    assert len(segments) == 2
    assert len(segments[0]["words"]) == 30
    assert len(segments[1]["words"]) == 5


# ── _make_segment ──────────────────────────────────────────────────────

def test_make_segment():
    words = [
        {"word": "a", "start": 0.0, "end": 0.5},
        {"word": "b", "start": 0.5, "end": 1.0},
    ]
    seg = _make_segment(words)
    assert seg["start"] == 0.0
    assert seg["end"] == 1.0
    assert seg["text"] == "a b"
    assert seg["speaker"] is None
    assert seg["words"] == words


# ── _extract_word_timestamps ──────────────────────────────────────────

class _FakeHypothesis:
    """Minimal stand-in for a NeMo Hypothesis object."""

    def __init__(self, timestep=None, words=None, segments=None):
        self.timestep = timestep
        self.words = words
        self.segments = segments


def test_extract_word_timestamps_none():
    assert _extract_word_timestamps(None) == []
    assert _extract_word_timestamps("string") == []
    assert _extract_word_timestamps(42) == []


def test_extract_word_timestamps_timestep_dict():
    h = _FakeHypothesis(timestep={
        "word": ["hello", "world"],
        "start_offset": [0, 25],
        "end_offset": [20, 45],
    })
    words = _extract_word_timestamps(h)
    assert len(words) == 2
    assert words[0]["word"] == "hello"
    assert words[0]["start"] == 0.0
    assert words[0]["end"] == 0.8  # 20 * 0.04
    assert words[1]["word"] == "world"
    assert words[1]["start"] == 1.0  # 25 * 0.04


def test_extract_word_timestamps_words_list():
    h = _FakeHypothesis(words=[
        {"word": "a", "start": 0.0, "end": 0.5},
        {"word": "b", "start": 0.5, "end": 1.0},
    ])
    words = _extract_word_timestamps(h)
    assert len(words) == 2
    assert words[0]["word"] == "a"


def test_extract_word_timestamps_segments():
    h = _FakeHypothesis(segments=[
        {"word": "x", "start": 0.0, "end": 0.4},
        {"word": "y", "start": 0.4, "end": 0.8},
    ])
    words = _extract_word_timestamps(h)
    assert len(words) == 2
    assert words[1]["word"] == "y"