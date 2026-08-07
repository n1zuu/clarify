"""Unit tests for models/summarizer.py helpers."""

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models.summarizer import _split_into_chunks, Summarizer


# ── _split_into_chunks ─────────────────────────────────────────────────

def test_split_into_chunks_empty():
    assert _split_into_chunks("", 100) == []


def test_split_into_chunks_single_chunk():
    text = "line one\nline two\nline three"
    chunks = _split_into_chunks(text, 1000)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_split_into_chunks_multiple():
    # Each line is ~10 chars; chunk_size=30 forces multiple chunks.
    text = "\n".join(f"line {i}" for i in range(10))
    chunks = _split_into_chunks(text, 30)
    assert len(chunks) > 1
    # Reconstructing all chunks should preserve every line.
    assert "\n".join(chunks) == text


def test_split_into_chunks_respects_boundary():
    text = "\n".join(f"line {i}" for i in range(5))
    chunks = _split_into_chunks(text, 1000)
    assert len(chunks) == 1


# ── Summarizer config ──────────────────────────────────────────────────

def test_summarizer_defaults():
    s = Summarizer()
    assert s.model == "llama3.3"
    assert s.host == "http://localhost:11434"
    assert s.timeout == 300


def test_summarizer_host_strips_trailing_slash():
    s = Summarizer(host="http://localhost:11434/")
    assert s.host == "http://localhost:11434"


def test_summarizer_empty_transcript():
    s = Summarizer()
    assert s.summarize("") == "No transcript content to summarize."
    assert s.summarize("   ") == "No transcript content to summarize."