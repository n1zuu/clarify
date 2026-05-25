"""
models/diarizer.py
------------------
Speaker diarization using pyannote.audio.

Identifies WHO spoke WHEN and re-segments the transcript into
per-speaker turns for accurate speaker attribution.
"""

from __future__ import annotations

import os
from typing import Optional
from utils.logger import get_logger

logger = get_logger(__name__)


class Diarizer:

    def __init__(
        self,
        model_name: str = "pyannote/speaker-diarization-3.1",
        hf_token: Optional[str] = None,
    ):
        self.model_name = model_name
        self.hf_token = hf_token or os.environ.get("HF_TOKEN")
        self._pipeline = None

    def _load_pipeline(self):
        if self._pipeline is not None:
            return

        if not self.hf_token:
            raise RuntimeError(
                "HuggingFace token is required for pyannote diarization.\n"
                "1. Create a token at https://huggingface.co/settings/tokens\n"
                "2. Accept terms at https://huggingface.co/pyannote/speaker-diarization-3.1\n"
                "3. Pass it as hf_token= or set HF_TOKEN environment variable."
            )

        try:
            from pyannote.audio import Pipeline  # type: ignore
        except ImportError:
            raise RuntimeError(
                "pyannote.audio is not installed. Install with:\n"
                "  pip install pyannote.audio"
            )

        logger.info(f"Loading diarization pipeline: {self.model_name}")
        try:
            # pyannote.audio >= 3.1 uses 'token' instead of 'use_auth_token'
            self._pipeline = Pipeline.from_pretrained(
                self.model_name,
                token=self.hf_token,
            )
        except TypeError:
            self._pipeline = Pipeline.from_pretrained(
                self.model_name,
                use_auth_token=self.hf_token,
            )

        try:
            import torch
            if torch.cuda.is_available():
                self._pipeline = self._pipeline.to(torch.device("cuda"))
                logger.info("Diarization pipeline moved to GPU.")
        except Exception as e:
            logger.warning(f"Could not move diarization to GPU: {e}")

        logger.info("Diarization pipeline loaded.")

    def assign_speakers(self, audio_path: str, segments: list[dict]) -> list[dict]:
        """
        Rebuild segments based on pyannote speaker turn boundaries.

        Instead of assigning one speaker label per large Parakeet segment,
        we use diarization turns as split points and re-group words into
        one segment per speaker turn. This accurately captures every
        speaker change rather than just the dominant speaker per batch.
        """
        self._load_pipeline()
        logger.info(f"Running diarization on: {audio_path}")

        try:
            import torchaudio
            waveform, sample_rate = torchaudio.load(audio_path)
            audio_input = {"waveform": waveform, "sample_rate": sample_rate}
            logger.info(f"Audio loaded: {waveform.shape}, {sample_rate}Hz")
        except Exception as e:
            logger.warning(f"torchaudio.load failed ({e}), falling back to file path")
            audio_input = audio_path

        diarization = self._pipeline(audio_input)
        turns = _extract_turns(diarization)
        logger.info(
            f"Diarization found {len(set(t[2] for t in turns))} speakers, "
            f"{len(turns)} turns"
        )

        if not turns:
            logger.warning("No turns extracted, falling back to majority-overlap assignment.")
            for seg in segments:
                seg["speaker"] = _assign_speaker_majority(seg, [])
            return segments

        # Collect all words from all Parakeet segments
        all_words = []
        for seg in segments:
            all_words.extend(seg.get("words", []))

        if all_words:
            # Best path: re-group words by speaker turn boundaries
            new_segments = _split_words_by_turns(all_words, turns)
        else:
            # Fallback: split segments at turn boundaries without word timestamps
            new_segments = _split_segments_by_turns(segments, turns)

        logger.info(
            f"Rebuilt {len(new_segments)} turn-aligned segments "
            f"from {len(segments)} original segments"
        )
        return new_segments

    def get_speaker_list(self, segments: list[dict]) -> list[str]:
        """Return unique speaker labels in order of first appearance."""
        seen = set()
        ordered = []
        for seg in segments:
            sp = seg.get("speaker")
            if sp and sp not in seen:
                seen.add(sp)
                ordered.append(sp)
        return ordered


# ------------------------------------------------------------------
# Turn extraction — handles all pyannote output versions
# ------------------------------------------------------------------

def _extract_turns(diarization) -> list[tuple]:
    """
    Extract (start, end, speaker) tuples from a pyannote diarization result.
    Tries multiple strategies to handle all pyannote versions.
    """
    turns = []

    # Strategy 1: DiarizeOutput.speaker_diarization (pyannote >= 3.3)
    try:
        if hasattr(diarization, "speaker_diarization"):
            annotation = diarization.speaker_diarization
            for turn, _, speaker in annotation.itertracks(yield_label=True):
                turns.append((turn.start, turn.end, speaker))
            if turns:
                return turns
    except Exception as e:
        logger.warning(f"speaker_diarization extraction failed: {e}")

    # Strategy 2: classic Annotation.itertracks (older pyannote)
    try:
        if hasattr(diarization, "itertracks"):
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                turns.append((turn.start, turn.end, speaker))
            if turns:
                return turns
    except Exception as e:
        logger.warning(f"itertracks extraction failed: {e}")

    # Strategy 3: exclusive_speaker_diarization fallback
    try:
        if hasattr(diarization, "exclusive_speaker_diarization"):
            annotation = diarization.exclusive_speaker_diarization
            for turn, _, speaker in annotation.itertracks(yield_label=True):
                turns.append((turn.start, turn.end, speaker))
            if turns:
                return turns
    except Exception as e:
        logger.warning(f"exclusive_speaker_diarization extraction failed: {e}")

    # Strategy 4: direct iteration
    try:
        for item in diarization:
            if isinstance(item, tuple) and len(item) == 3:
                seg, _, speaker = item
                turns.append((seg.start, seg.end, speaker))
            elif hasattr(item, "start") and hasattr(item, "end") and hasattr(item, "label"):
                turns.append((item.start, item.end, item.label))
            elif hasattr(item, "start") and hasattr(item, "end") and hasattr(item, "speaker"):
                turns.append((item.start, item.end, item.speaker))
        if turns:
            return turns
    except Exception as e:
        logger.warning(f"Direct iteration extraction failed: {e}")

    logger.warning(
        f"Could not extract turns from type {type(diarization)}. "
        f"Available attrs: {[a for a in dir(diarization) if not a.startswith('_')]}"
    )
    return turns


# ------------------------------------------------------------------
# Turn-based segment splitting
# ------------------------------------------------------------------

def _split_words_by_turns(words: list[dict], turns: list[tuple]) -> list[dict]:
    """
    Assign each word to its speaker turn then group consecutive
    same-speaker words into segments. Produces one segment per
    contiguous speaker block — the most granular output possible.
    """
    labeled = []
    for word in words:
        word_mid = (word.get("start", 0.0) + word.get("end", 0.0)) / 2
        speaker = _find_speaker_at(word_mid, turns)
        labeled.append({**word, "speaker": speaker})

    if not labeled:
        return []

    segments = []
    current_words = [labeled[0]]
    current_speaker = labeled[0]["speaker"]

    for word in labeled[1:]:
        if word["speaker"] == current_speaker:
            current_words.append(word)
        else:
            segments.append(_make_turn_segment(current_words, current_speaker))
            current_words = [word]
            current_speaker = word["speaker"]

    if current_words:
        segments.append(_make_turn_segment(current_words, current_speaker))

    return segments


def _split_segments_by_turns(segments: list[dict], turns: list[tuple]) -> list[dict]:
    """
    Fallback when no word-level timestamps are available.
    Splits text proportionally at turn boundaries.
    """
    new_segments = []
    for seg in segments:
        seg_start = seg.get("start", 0.0)
        seg_end = seg.get("end", seg_start)
        text = seg.get("text", "").strip()

        overlapping = [t for t in turns if t[1] > seg_start and t[0] < seg_end]

        if not overlapping:
            new_segments.append({**seg, "speaker": None})
            continue

        if len(overlapping) == 1:
            new_segments.append({**seg, "speaker": _friendly_name(overlapping[0][2])})
            continue

        # Multiple speakers — split text proportionally by turn duration
        total_duration = sum(
            min(t[1], seg_end) - max(t[0], seg_start) for t in overlapping
        )
        words = text.split()
        pos = 0
        for turn_start, turn_end, speaker in overlapping:
            overlap = min(turn_end, seg_end) - max(turn_start, seg_start)
            proportion = overlap / total_duration if total_duration > 0 else 1
            count = max(1, round(len(words) * proportion))
            chunk = " ".join(words[pos:pos + count])
            pos += count
            if chunk.strip():
                new_segments.append({
                    "start": max(turn_start, seg_start),
                    "end": min(turn_end, seg_end),
                    "text": chunk,
                    "words": [],
                    "speaker": _friendly_name(speaker),
                })

    return new_segments


def _make_turn_segment(words: list[dict], speaker: Optional[str]) -> dict:
    return {
        "start": words[0].get("start", 0.0),
        "end": words[-1].get("end", 0.0),
        "text": " ".join(w.get("word", "") for w in words),
        "words": words,
        "speaker": speaker,
    }


def _find_speaker_at(time: float, turns: list[tuple]) -> Optional[str]:
    for turn_start, turn_end, speaker in turns:
        if turn_start <= time <= turn_end:
            return _friendly_name(speaker)
    if turns:
        nearest = min(turns, key=lambda t: min(abs(t[0] - time), abs(t[1] - time)))
        return _friendly_name(nearest[2])
    return None


def _assign_speaker_majority(segment: dict, turns: list[tuple]) -> Optional[str]:
    """Legacy fallback when turn extraction fails entirely."""
    seg_start = segment.get("start", 0.0)
    seg_end = segment.get("end", seg_start + 0.1)
    best_speaker = None
    best_overlap = 0.0
    for turn_start, turn_end, speaker in turns:
        overlap = max(0.0, min(seg_end, turn_end) - max(seg_start, turn_start))
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = speaker
    if best_speaker:
        return _friendly_name(best_speaker)
    if turns:
        nearest = min(turns, key=lambda t: abs((t[0] + t[1]) / 2 - (seg_start + seg_end) / 2))
        return _friendly_name(nearest[2])
    return None


def _friendly_name(raw_label: str) -> str:
    if not raw_label:
        return raw_label
    raw_label = raw_label.strip()
    if raw_label.upper().startswith("SPEAKER_"):
        try:
            idx = int(raw_label.split("_")[-1]) + 1
            return f"Speaker {idx}"
        except ValueError:
            pass
    return raw_label.title()