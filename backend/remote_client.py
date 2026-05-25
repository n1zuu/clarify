"""
remote_client.py
────────────────
Runs on your LAPTOP. Captures audio locally, sends it to the RTX 5060
PC for AI processing, and retrieves the transcript + summary.

Your GUI should use RemoteMeetScribeClient the same way it uses
MeetScribeEngine — same callbacks, same result shape.

Usage:
    client = RemoteMeetScribeClient(server_url="http://192.168.1.X:8000")
    client.on_progress = lambda stage, pct, msg: ...
    client.on_complete = lambda result: ...
    client.on_error    = lambda err: ...

    client.configure(export_format="docx", diarization=True)
    client.start_recording()
    # ... meeting happens ...
    client.stop_and_process_async()
"""

from __future__ import annotations

import base64
import io
import json
import threading
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Callable, Optional

from core.audio_capture import AudioCapture
from core.engine import ProcessingResult
from utils.logger import get_logger

logger = get_logger(__name__)

POLL_INTERVAL = 2.0   # seconds between status polls


@dataclass
class RemoteConfig:
    server_url: str = "http://localhost:8000"
    export_format: str = "docx"
    diarization: bool = True
    ollama_model: str = "llama3.3"
    device_name: Optional[str] = None
    sample_rate: int = 16000
    channels: int = 1


class RemoteMeetScribeClient:
    """
    Drop-in replacement for MeetScribeEngine that offloads AI to the PC server.
    Audio is still captured locally on the laptop via WASAPI loopback.
    """

    def __init__(self, server_url: str = "http://localhost:8000"):
        self.config = RemoteConfig(server_url=server_url.rstrip("/"))
        self._capture = AudioCapture()
        self._recording = False
        self._record_start = 0.0
        self._lock = threading.Lock()

        # Same callback interface as MeetScribeEngine
        self.on_progress: Optional[Callable[[str, float, str], None]] = None
        self.on_complete: Optional[Callable[[ProcessingResult], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def configure(
        self,
        server_url: Optional[str] = None,
        export_format: str = "docx",
        diarization: bool = True,
        ollama_model: str = "llama3.3",
        device_name: Optional[str] = None,
        sample_rate: int = 16000,
    ):
        if server_url:
            self.config.server_url = server_url.rstrip("/")
        self.config.export_format = export_format
        self.config.diarization = diarization
        self.config.ollama_model = ollama_model
        self.config.device_name = device_name
        self.config.sample_rate = sample_rate

    # ------------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------------

    def check_server(self) -> tuple[bool, str]:
        """
        Ping the server. Call this on startup to verify the connection.
        Returns (ok: bool, message: str).
        """
        try:
            data = self._get("/health")
            gpu = data.get("gpu", "unknown")
            ollama = data.get("ollama", "unknown")
            return True, f"Connected. GPU: {gpu} | Ollama: {ollama}"
        except Exception as e:
            return False, f"Cannot reach server at {self.config.server_url}: {e}"

    def list_audio_devices(self) -> list[str]:
        """Local loopback devices on the laptop."""
        return self._capture.list_loopback_devices()

    # ------------------------------------------------------------------
    # Recording (runs locally on the laptop)
    # ------------------------------------------------------------------

    def start_recording(self) -> bool:
        with self._lock:
            if self._recording:
                return False
            try:
                self._capture.start(
                    device_name=self.config.device_name,
                    sample_rate=self.config.sample_rate,
                    channels=self.config.channels,
                )
                self._recording = True
                self._record_start = time.time()
                self._emit_progress("recording", 0.0, "Recording meeting audio…")
                logger.info("Remote client: recording started.")
                return True
            except Exception as e:
                self._emit_error(str(e))
                return False

    def stop_and_process_async(self):
        """Stop recording and send audio to the PC server for processing."""
        with self._lock:
            if not self._recording:
                self._emit_error("Not currently recording.")
                return
            self._recording = False

        duration = time.time() - self._record_start
        audio_data = self._capture.stop()

        thread = threading.Thread(
            target=self._upload_and_poll,
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
    # Upload → poll → complete
    # ------------------------------------------------------------------

    def _upload_and_poll(self, audio_data, duration: float):
        try:
            # ── 1. Encode WAV as base64 ────────────────────────────────
            self._emit_progress("encoding", 0.02, "Encoding audio for transfer…")
            wav_b64 = _audio_to_wav_b64(audio_data, self.config.sample_rate)
            size_mb = len(wav_b64) * 3 / 4 / (1024 ** 2)
            logger.info(f"Encoded audio: ~{size_mb:.1f} MB to upload")

            # ── 2. Submit job ──────────────────────────────────────────
            self._emit_progress("uploading", 0.05, f"Uploading audio to server (~{size_mb:.1f} MB)…")
            payload = {
                "audio_b64": wav_b64,
                "export_format": self.config.export_format,
                "diarization": self.config.diarization,
                "ollama_model": self.config.ollama_model,
            }
            response = self._post("/jobs/submit", payload)
            job_id = response["job_id"]
            logger.info(f"Job submitted: {job_id}")

            # ── 3. Poll for results ────────────────────────────────────
            self._emit_progress("queued", 0.08, "Job queued on server…")
            result = self._poll_job(job_id)

            # ── 4. Build ProcessingResult ──────────────────────────────
            pr = ProcessingResult(
                transcript_text=result.get("transcript", ""),
                summary_text=result.get("summary", ""),
                speakers=result.get("speakers", []),
                duration_seconds=result.get("duration_seconds", duration),
                error=result.get("error"),
            )

            if pr.error:
                self._emit_error(pr.error)
            else:
                self._emit_progress("done", 1.0, "Processing complete.")
                if self.on_complete:
                    self.on_complete(pr)

        except Exception as e:
            logger.exception("Remote processing failed")
            self._emit_error(str(e))

    def _poll_job(self, job_id: str) -> dict:
        """Poll the server until the job is done or errored."""
        while True:
            time.sleep(POLL_INTERVAL)
            try:
                data = self._get(f"/jobs/{job_id}")
            except Exception as e:
                logger.warning(f"Poll error (will retry): {e}")
                continue

            status = data.get("status", "unknown")
            pct = data.get("progress_pct", 0.0)
            msg = data.get("progress_msg", "")

            # Map server-side pct to 10%-100% range (0-10% was upload/encode)
            display_pct = 0.10 + pct * 0.90
            self._emit_progress(status, display_pct, msg)

            if status == "done":
                return data
            elif status == "error":
                raise RuntimeError(data.get("error", "Unknown server error"))

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _get(self, path: str) -> dict:
        url = self.config.server_url + path
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    def _post(self, path: str, data: dict) -> dict:
        url = self.config.server_url + path
        payload = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=payload,
                                      headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())

    # ------------------------------------------------------------------
    # Callback helpers
    # ------------------------------------------------------------------

    def _emit_progress(self, stage, pct, msg):
        if self.on_progress:
            try: self.on_progress(stage, pct, msg)
            except Exception: pass

    def _emit_error(self, error):
        if self.on_error:
            try: self.on_error(error)
            except Exception: pass


# ── Audio encoding helper ─────────────────────────────────────────────

def _audio_to_wav_b64(audio_data, sample_rate: int) -> str:
    """Convert float32 numpy array → 16-bit WAV → base64 string."""
    import wave, numpy as np

    pcm = (audio_data * 32767).clip(-32768, 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return base64.b64encode(buf.getvalue()).decode("utf-8")
