"""
core/engine.py
--------------
MeetScribeEngine: the central orchestrator.

Your GUI should instantiate this class and call:
  - engine.configure(...)
  - engine.start_recording()
  - engine.stop_and_process()  -> returns ProcessingResult

All long-running operations (transcription, summarization) happen on
background threads and report progress via the on_progress callback.
"""

from __future__ import annotations

import os
import threading
import time
import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from core.audio_capture import AudioCapture
from models.transcriber import Transcriber
from models.diarizer import Diarizer
from models.summarizer import Summarizer
from export.exporter import Exporter
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class EngineConfig:
    output_dir: str = "./output"
    export_format: str = "docx"          # "pdf" | "docx" | "txt" | "all"
    diarization: bool = True
    device_name: Optional[str] = None    # None = auto-detect loopback
    sample_rate: int = 16000
    channels: int = 1
    parakeet_model: str = "nvidia/parakeet-tdt-1.1b"
    diarization_model: str = "pyannote/speaker-diarization-3.1"
    ollama_model: str = "llama3.3"
    ollama_host: str = "http://localhost:11434"
    hf_token: Optional[str] = None       # Required for pyannote diarization


@dataclass
class ProcessingResult:
    audio_path: Optional[str] = None
    transcript_path: Optional[str] = None
    summary_path: Optional[str] = None
    export_path: Optional[str] = None
    transcript_text: str = ""
    summary_text: str = ""
    speakers: list = field(default_factory=list)
    duration_seconds: float = 0.0
    error: Optional[str] = None


class MeetScribeEngine:
    """
    Top-level engine. Thread-safe for GUI use.

    Callbacks (all optional, called from background threads):
      on_progress(stage: str, pct: float, message: str)
      on_complete(result: ProcessingResult)
      on_error(error: str)
    """

    def __init__(self):
        self.config = EngineConfig()
        self._capture = AudioCapture()
        self._recording = False
        self._processing = False
        self._lock = threading.Lock()

        # GUI hooks — assign these before calling start_recording()
        self.on_progress: Optional[Callable[[str, float, str], None]] = None
        self.on_complete: Optional[Callable[[ProcessingResult], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def configure(
        self,
        output_dir: str = "./output",
        export_format: str = "docx",
        diarization: bool = True,
        device_name: Optional[str] = None,
        ollama_model: str = "llama3.3",
        ollama_host: str = "http://localhost:11434",
        parakeet_model: str = "nvidia/parakeet-tdt-1.1b",
        hf_token: Optional[str] = None,
    ):
        self.config = EngineConfig(
            output_dir=output_dir,
            export_format=export_format,
            diarization=diarization,
            device_name=device_name,
            ollama_model=ollama_model,
            ollama_host=ollama_host,
            parakeet_model=parakeet_model,
            hf_token=hf_token,
        )
        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"Engine configured: {self.config}")

    # ------------------------------------------------------------------
    # Audio device discovery
    # ------------------------------------------------------------------

    def list_audio_devices(self) -> list[str]:
        """Return list of available loopback/output device names."""
        return self._capture.list_loopback_devices()

    # ------------------------------------------------------------------
    # Recording control
    # ------------------------------------------------------------------

    def start_recording(self) -> bool:
        """
        Begin capturing system audio. Returns True on success.
        Safe to call from GUI thread.
        """
        with self._lock:
            if self._recording:
                logger.warning("Already recording.")
                return False

            try:
                self._capture.start(
                    device_name=self.config.device_name,
                    sample_rate=self.config.sample_rate,
                    channels=self.config.channels,
                )
                self._recording = True
                self._record_start = time.time()
                logger.info("Recording started.")
                self._emit_progress("recording", 0.0, "Recording meeting audio…")
                return True
            except Exception as e:
                logger.error(f"Failed to start recording: {e}")
                self._emit_error(str(e))
                return False

    def stop_and_process(self) -> ProcessingResult:
        """
        Stop recording and synchronously process everything.
        Blocks until complete. For async use, call stop_and_process_async().
        """
        with self._lock:
            if not self._recording:
                return ProcessingResult(error="Not currently recording.")
            self._recording = False

        duration = time.time() - self._record_start
        audio_data = self._capture.stop()
        logger.info(f"Recording stopped. Duration: {duration:.1f}s")

        return self._process(audio_data, duration)

    def stop_and_process_async(self):
        """
        Stop recording and process in a background thread.
        Results delivered via on_complete / on_error callbacks.
        """
        with self._lock:
            if not self._recording:
                self._emit_error("Not currently recording.")
                return
            self._recording = False

        duration = time.time() - self._record_start
        audio_data = self._capture.stop()

        thread = threading.Thread(
            target=self._process_threaded,
            args=(audio_data, duration),
            daemon=True,
        )
        thread.start()

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def recording_duration(self) -> float:
        if not self._recording:
            return 0.0
        return time.time() - self._record_start

    # ------------------------------------------------------------------
    # Internal processing pipeline
    # ------------------------------------------------------------------

    def _process_threaded(self, audio_data, duration):
        try:
            result = self._process(audio_data, duration)
            if self.on_complete:
                self.on_complete(result)
        except Exception as e:
            logger.exception("Processing pipeline failed")
            self._emit_error(str(e))

    def _process(self, audio_data, duration: float, config: Optional[EngineConfig] = None) -> ProcessingResult:
        result = ProcessingResult(duration_seconds=duration)
        # Use a per-call config snapshot if provided (thread-safe for concurrent
        # jobs) — otherwise fall back to the engine's configured defaults.
        cfg = config if config is not None else self.config
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path(cfg.output_dir) / timestamp
        out_dir.mkdir(parents=True, exist_ok=True)

        # ── 1. Save raw audio ──────────────────────────────────────────
        self._emit_progress("saving_audio", 0.05, "Saving raw audio…")
        audio_path = out_dir / "recording.wav"
        self._capture.save_wav(audio_data, str(audio_path), cfg.sample_rate)
        result.audio_path = str(audio_path)
        logger.info(f"Audio saved: {audio_path}")

        # ── 2. Transcription (Parakeet) ────────────────────────────────
        self._emit_progress("transcribing", 0.15, "Transcribing with NVIDIA Parakeet…")
        transcriber = Transcriber(model_name=cfg.parakeet_model)
        segments = transcriber.transcribe(str(audio_path))
        logger.info(f"Transcription complete: {len(segments)} segments")

        # ── 2.1 Timestamp sanity check ─────────────────────────────────
        for i, seg in enumerate(segments[:5]):
            logger.info(
                f"Segment {i}: start={seg['start']:.2f}s end={seg['end']:.2f}s "
                f"words={len(seg['words'])} text={seg['text'][:60]!r}"
            )

        # ── 3. Speaker Diarization (optional) ─────────────────────────
        if cfg.diarization:
            self._emit_progress("diarizing", 0.45, "Identifying speakers…")
            try:
                diarizer = Diarizer(
                    model_name=cfg.diarization_model,
                    hf_token=cfg.hf_token,
                )
                segments = diarizer.assign_speakers(str(audio_path), segments)
                result.speakers = diarizer.get_speaker_list(segments)
                logger.info(f"Diarization complete. Speakers: {result.speakers}")
            except Exception as e:
                logger.warning(f"Diarization failed (continuing without): {e}")
                self._emit_progress("diarizing", 0.45, f"Diarization skipped: {e}")

        # ── 4. Build transcript text ───────────────────────────────────
        self._emit_progress("building_transcript", 0.60, "Building transcript…")
        transcript_text = _segments_to_text(segments)
        result.transcript_text = transcript_text

        transcript_path = out_dir / "transcript.txt"
        transcript_path.write_text(transcript_text, encoding="utf-8")
        result.transcript_path = str(transcript_path)

        # ── 4.1 Clean up transcript grammar ───────────────────────────
        self._emit_progress("cleaning", 0.62, "Correcting transcript grammar…")
        summarizer = Summarizer(model=cfg.ollama_model, host=cfg.ollama_host)
        cleaned = summarizer.clean_transcript(transcript_text)

        # Persist the cleaned version back to disk and result
        result.transcript_text = cleaned
        transcript_path.write_text(cleaned, encoding="utf-8")
        transcript_text = cleaned  # use cleaned text for summarization below

        # ── 5. Summarization (Llama via Ollama) ────────────────────────
        self._emit_progress("summarizing", 0.70, "Summarizing with Llama 3.3…")
        summary_text = summarizer.summarize(
            transcript=transcript_text,
            speakers=result.speakers,
        )
        result.summary_text = summary_text

        summary_path = out_dir / "summary.txt"
        summary_path.write_text(summary_text, encoding="utf-8")
        result.summary_path = str(summary_path)

        # ── 6. Export ──────────────────────────────────────────────────
        self._emit_progress("exporting", 0.90, f"Exporting as {cfg.export_format}…")
        exporter = Exporter(output_dir=str(out_dir))
        export_path = exporter.export(
            fmt=cfg.export_format,
            transcript=transcript_text,
            summary=summary_text,
            speakers=result.speakers,
            duration=duration,
            timestamp=timestamp,
        )
        result.export_path = export_path

        self._emit_progress("done", 1.0, "Processing complete.")
        logger.info(f"All outputs saved to: {out_dir}")
        return result

    # ------------------------------------------------------------------
    # Callback helpers
    # ------------------------------------------------------------------

    def _emit_progress(self, stage: str, pct: float, message: str):
        if self.on_progress:
            try:
                self.on_progress(stage, pct, message)
            except Exception:
                pass

    def _emit_error(self, error: str):
        if self.on_error:
            try:
                self.on_error(error)
            except Exception:
                pass


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _segments_to_text(segments: list[dict]) -> str:
    """Convert transcript segments to a readable string."""
    lines = []
    for seg in segments:
        speaker = seg.get("speaker", "")
        start = seg.get("start", 0.0)
        text = seg.get("text", "").strip()
        ts = _fmt_time(start)
        if speaker:
            lines.append(f"[{ts}] {speaker}: {text}")
        else:
            lines.append(f"[{ts}] {text}")
    return "\n".join(lines)


def _fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"