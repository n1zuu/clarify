"""
models/transcriber.py
---------------------
Speech-to-text using NVIDIA Parakeet (NeMo ASR).

Model options (all via HuggingFace / NeMo):
  - nvidia/parakeet-tdt-1.1b   (recommended — best accuracy, needs ~4GB VRAM)
  - nvidia/parakeet-ctc-1.1b   (CTC variant, slightly faster)
  - nvidia/parakeet-tdt-0.6b   (smaller, faster, less accurate)
  - nvidia/parakeet-ctc-0.6b   (smallest)

Requirements:
    pip install nemo_toolkit[asr] soundfile numpy

Parakeet returns word-level timestamps which we group into sentences/segments.
Audio is processed in overlapping sliding windows to manage VRAM and avoid
Windows file-locking issues with NeMo's internal temp files.
"""

from __future__ import annotations

import gc
import json
import os
import shutil
import tempfile
from typing import Optional

from utils.logger import get_logger

logger = get_logger(__name__)

# ------------------------------------------------------------------
# Sliding window config — tune these if you hit CUDA OOM
# ------------------------------------------------------------------
WINDOW_SEC  = 30.0                       # seconds per chunk
OVERLAP_SEC = 5.0                        # overlap between consecutive chunks
STRIDE_SEC  = WINDOW_SEC - OVERLAP_SEC   # how far we advance each step (25s)


class Transcriber:
    """
    Wraps NVIDIA Parakeet for ASR.

    Returns a list of segment dicts:
        {
            "start": float,   # seconds into the original recording
            "end":   float,
            "text":  str,
            "words": [{"word": str, "start": float, "end": float}, ...]
            "speaker": None   # filled in later by Diarizer
        }

    Long files are split into overlapping 30-second chunks to stay within
    VRAM limits.  Chunks are merged using gap-aware deduplication so no
    words are dropped or doubled at boundaries.
    """

    def __init__(self, model_name: str = "nvidia/parakeet-tdt-1.1b"):
        self.model_name = model_name
        self._model = None

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------

    def _load_model(self):
        if self._model is not None:
            return
        logger.info(f"Loading Parakeet model: {self.model_name}")
        try:
            import nemo.collections.asr as nemo_asr  # type: ignore
            self._model = nemo_asr.models.ASRModel.from_pretrained(
                model_name=self.model_name
            )
            self._model.eval()
            logger.info("Parakeet model loaded.")
        except ImportError:
            raise RuntimeError(
                "NeMo ASR is not installed. Install it with:\n"
                "  pip install nemo_toolkit[asr]\n"
                "Note: this requires ~2GB disk space and a compatible CUDA install."
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to load Parakeet model '{self.model_name}': {e}"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def transcribe(self, audio_path: str) -> list[dict]:
        """
        Transcribe a WAV file.
        Splits into overlapping chunks, transcribes each, then merges
        using gap-aware deduplication.
        """
        self._load_model()
        logger.info(f"Transcribing: {audio_path}")

        chunks = _slice_audio(audio_path, WINDOW_SEC, STRIDE_SEC)
        logger.info(f"Split audio into {len(chunks)} chunk(s).")

        all_words: list[dict] = []

        for i, (chunk_path, chunk_offset) in enumerate(chunks):
            logger.info(
                f"Transcribing chunk {i + 1}/{len(chunks)} "
                f"(offset={chunk_offset:.1f}s)…"
            )
            try:
                words = self._transcribe_chunk(chunk_path)

                # Shift timestamps to position within the full recording
                for w in words:
                    w["start"] += chunk_offset
                    w["end"]   += chunk_offset

                # Merge, deduplicating the overlap region
                deduped = _merge_words(all_words, words, OVERLAP_SEC)
                all_words.extend(deduped)

            except Exception as e:
                logger.warning(f"Chunk {i + 1} failed, skipping: {e}")
            finally:
                try:
                    os.remove(chunk_path)
                except Exception:
                    pass
                # Release CUDA memory between chunks
                _flush_cuda()

        if not all_words:
            logger.warning("No words extracted from any chunk.")
            return [
                {"start": 0.0, "end": 0.0, "text": "", "words": [], "speaker": None}
            ]

        segments = _words_to_segments(all_words)
        logger.info(
            f"Transcription done: {len(segments)} segments, "
            f"{len(all_words)} words"
        )
        return segments

    # ------------------------------------------------------------------
    # Internal: transcribe one chunk
    # ------------------------------------------------------------------

    def _transcribe_chunk(self, audio_path: str) -> list[dict]:
        """
        Transcribe a single chunk WAV file.
        Manages its own temp dir so NeMo never races on manifest.json
        (avoids WinError 32 on Windows).
        Returns a list of word dicts with LOCAL timestamps (0-based).
        """
        tmp_dir = tempfile.mkdtemp()
        manifest_path = os.path.join(tmp_dir, "manifest.json")

        try:
            # Write manifest and fully flush/close before NeMo touches it
            with open(manifest_path, "w") as f:
                json.dump(
                    {"audio_filepath": audio_path, "duration": None, "text": ""},
                    f,
                )
                f.flush()
                os.fsync(f.fileno())

            try:
                output = self._model.transcribe(
                    audio=[audio_path],
                    return_hypotheses=True,
                    num_workers=0,
                )
            except TypeError:
                output = self._model.transcribe(
                    paths2audio_files=[audio_path],
                    return_hypotheses=True,
                    num_workers=0,
                )

        finally:
            # Always remove temp dir ourselves — never leave it to NeMo
            shutil.rmtree(tmp_dir, ignore_errors=True)

        # Unwrap NeMo's various output shapes
        result = output
        while isinstance(result, (list, tuple)) and len(result) > 0:
            result = result[0]

        logger.debug(f"Chunk output type after unwrap: {type(result)}")

        if isinstance(result, str):
            return [{"word": result.strip(), "start": 0.0, "end": 0.0}]

        words = _extract_word_timestamps(result)
        if not words:
            text = getattr(result, "text", None) or str(result)
            return [{"word": text.strip(), "start": 0.0, "end": 0.0}]

        return words


# ------------------------------------------------------------------
# Merge / deduplication
# ------------------------------------------------------------------

def _merge_words(
    committed: list[dict],
    new_words: list[dict],
    overlap_sec: float,
) -> list[dict]:
    """
    Merge new_words into already-committed words, discarding the portion
    of new_words that duplicates the overlap region.

    Strategy:
      1. Find the first new word whose start time is past the last
         committed word's end time (the true handoff point).
      2. Look a few words either side of that point for the largest
         natural silence gap — cut there for the cleanest seam.
      3. Return only the non-duplicate tail of new_words.
    """
    if not committed:
        return new_words

    if not new_words:
        return []

    last_committed_end = committed[-1]["end"]

    # Find the first new word that is strictly past the committed region
    handoff = None
    for i, word in enumerate(new_words):
        if word["start"] > last_committed_end:
            handoff = i
            break

    # All new words are within the already-committed region — discard all
    if handoff is None:
        return []

    # Search a small window around the handoff for the largest silence gap
    search_start = max(0, handoff - 5)
    search_end   = min(len(new_words) - 1, handoff + 5)

    best_idx = handoff
    best_gap = 0.0

    for i in range(search_start, search_end):
        gap = new_words[i + 1]["start"] - new_words[i]["end"]
        if gap > best_gap:
            best_gap = gap
            best_idx = i + 1

    return new_words[best_idx:]


# ------------------------------------------------------------------
# Audio slicing
# ------------------------------------------------------------------

def _slice_audio(
    audio_path: str,
    window_sec: float,
    stride_sec: float,
) -> list[tuple[str, float]]:
    """
    Read audio and slice it into overlapping chunks.
    Returns list of (temp_wav_path, offset_seconds_in_original).
    Each temp file is the caller's responsibility to delete.
    """
    try:
        import numpy as np      # type: ignore
        import soundfile as sf  # type: ignore
    except ImportError:
        raise RuntimeError(
            "soundfile and numpy are required for chunked transcription.\n"
            "  pip install soundfile numpy"
        )

    data, sr = sf.read(audio_path, dtype="float32")
    total_samples  = len(data)
    window_samples = int(window_sec * sr)
    stride_samples = int(stride_sec * sr)

    chunks: list[tuple[str, float]] = []
    start = 0

    while start < total_samples:
        end        = min(start + window_samples, total_samples)
        chunk_data = data[start:end]
        offset_sec = start / sr

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.close()
        sf.write(tmp.name, chunk_data, sr)
        chunks.append((tmp.name, offset_sec))

        if end == total_samples:
            break
        start += stride_samples

    return chunks


# ------------------------------------------------------------------
# CUDA memory helper
# ------------------------------------------------------------------

def _flush_cuda():
    """Release unused CUDA memory between chunks."""
    try:
        import torch  # type: ignore
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except Exception:
        pass
    gc.collect()


# ------------------------------------------------------------------
# NeMo hypothesis parsing
# ------------------------------------------------------------------

def _extract_word_timestamps(hypothesis) -> list[dict]:
    """
    Extract word-level timestamps from a NeMo Hypothesis object.
    Tries three strategies to handle different NeMo versions.
    Never raises — returns [] on complete failure.
    """
    if hypothesis is None or isinstance(hypothesis, (str, int, float)):
        return []

    words: list[dict] = []
    FRAME_DURATION = 0.04  # ~40 ms per frame for Parakeet TDT

    # ── Strategy 1: hypothesis.timestep dict (NeMo >= 1.20 TDT) ──────
    try:
        if hasattr(hypothesis, "timestep") and hypothesis.timestep:
            ts = hypothesis.timestep
            if isinstance(ts, dict):
                word_list  = ts.get("word", [])
                start_list = ts.get("start_offset", [])
                end_list   = ts.get("end_offset", [])
                for w, s, e in zip(word_list, start_list, end_list):
                    words.append({
                        "word":  str(w),
                        "start": float(s) * FRAME_DURATION,
                        "end":   float(e) * FRAME_DURATION,
                    })
                if words:
                    # Sanity-check: first timestamp should be < 120s for a 30s chunk
                    if words[0]["start"] < 120.0:
                        return words
                    else:
                        logger.warning(
                            "timestep offsets look wrong "
                            f"(first start={words[0]['start']:.1f}s) — trying next strategy."
                        )
                        words = []
    except Exception as e:
        logger.warning(f"timestep extraction failed: {e}")
        words = []

    # ── Strategy 2: hypothesis.words list ────────────────────────────
    try:
        if hasattr(hypothesis, "words") and hypothesis.words:
            raw = hypothesis.words
            if isinstance(raw, list) and len(raw) > 0:
                if isinstance(raw[0], dict):
                    # Validate required keys exist
                    if all("word" in d and "start" in d and "end" in d for d in raw):
                        return raw
                if isinstance(raw[0], (list, tuple)) and len(raw[0]) >= 3:
                    for item in raw:
                        words.append({
                            "word":  str(item[0]),
                            "start": float(item[1]),
                            "end":   float(item[2]),
                        })
                    if words:
                        return words
    except Exception as e:
        logger.warning(f"words extraction failed: {e}")
        words = []

    # ── Strategy 3: hypothesis.segments ──────────────────────────────
    try:
        if hasattr(hypothesis, "segments") and hypothesis.segments:
            for seg in hypothesis.segments:
                if isinstance(seg, dict) and "word" in seg:
                    words.append({
                        "word":  seg.get("word", ""),
                        "start": float(seg.get("start", 0.0)),
                        "end":   float(seg.get("end", 0.0)),
                    })
            if words:
                return words
    except Exception as e:
        logger.warning(f"segments extraction failed: {e}")

    return []


# ------------------------------------------------------------------
# Segment grouping
# ------------------------------------------------------------------

def _words_to_segments(
    words: list[dict],
    max_words_per_segment: int = 8,
    silence_threshold: float = 0.4,
    max_duration_seconds: float = 4.0,
) -> list[dict]:
    """
    Group a flat word list into short segments suitable for speaker assignment.

    Splits on whichever condition fires first:
      1. Silence gap >= silence_threshold (default 0.4s) — likely a speaker turn
      2. Segment duration >= max_duration_seconds (default 4s) — hard cap
      3. Word count >= max_words_per_segment (default 8 words) — safety cap

    Keeping segments short is critical for accurate diarization — if a segment
    spans 25 seconds it will be assigned to whichever speaker talked most in
    that window, losing all the other speakers' turns entirely.
    """
    if not words:
        return []

    segments: list[dict] = []
    current_words = [words[0]]

    for word in words[1:]:
        prev_end      = current_words[-1]["end"]
        seg_start     = current_words[0]["start"]
        gap           = word["start"] - prev_end
        duration      = prev_end - seg_start
        too_many_words = len(current_words) >= max_words_per_segment
        too_long       = duration >= max_duration_seconds
        natural_break  = gap >= silence_threshold

        if natural_break or too_long or too_many_words:
            segments.append(_make_segment(current_words))
            current_words = [word]
        else:
            current_words.append(word)

    if current_words:
        segments.append(_make_segment(current_words))

    return segments


def _make_segment(words: list[dict]) -> dict:
    return {
        "start":   words[0]["start"],
        "end":     words[-1]["end"],
        "text":    " ".join(w["word"] for w in words),
        "words":   words,
        "speaker": None,  # filled in by Diarizer
    }