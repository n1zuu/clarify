"""
server_api.py
─────────────
Runs on your RTX 5060 PC. Exposes MeetScribeEngine over HTTP so your
laptop can send audio and receive transcripts + summaries remotely.

Fixes in this version:
  - audio_b64 is now Optional — simulation mode (null audio) no longer 422s
  - Ollama detection tries both localhost and 127.0.0.1 with a longer timeout
  - /health no longer crashes if engine isn't fully configured yet
  - Simulation mode returns realistic sample data without touching the AI pipeline
  - Port is configurable via CLI arg: python server_api.py 8001
"""

from __future__ import annotations

import base64
import os
import sys
import time
import tempfile
import threading
import uuid
import urllib.request
import json
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.engine import MeetScribeEngine, ProcessingResult
from utils.logger import get_logger

logger = get_logger(__name__)

# ── App setup ──────────────────────────────────────────────────────────
app = FastAPI(title="MeetScribe Remote API", version="1.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Engine ─────────────────────────────────────────────────────────────
engine = MeetScribeEngine()
engine.configure(
    output_dir="./output",
    export_format="all",
    diarization=False,
    ollama_model=os.environ.get("OLLAMA_MODEL", "gemma3:4b"),
    ollama_host=os.environ.get("OLLAMA_HOST_URL", "http://localhost:11434"),
    hf_token=os.environ.get("HF_TOKEN"),
)

# ── Job store ──────────────────────────────────────────────────────────
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()

# ── Sample data for simulation mode ───────────────────────────────────
SIMULATION_SAMPLES = [
    {
        "topic": "Q3 Launch Campaign Sync",
        "transcript": (
            "[00:00] Speaker 1: Welcome everyone. Today we are syncing on our Q3 Launch Campaign for Clarify.\n"
            "[00:08] Speaker 2: The desktop integration is complete. Audio loopback via WASAPI is fully tested.\n"
            "[00:21] Speaker 3: On the marketing side, I have drafted the press release and scheduled three webinars.\n"
            "[00:35] Speaker 1: Fantastic. Jordan, please share the drafts in our shared Drive by end of week.\n"
            "[00:44] Speaker 2: I will also run final regression tests on the installer before Friday."
        ),
        "summary": (
            "## TL;DR\n"
            "The team confirmed Clarify is ready for Q3 beta launch. Marketing and engineering are aligned on next steps.\n\n"
            "## Attendees\nSpeaker 1 (Product Lead), Speaker 2 (Engineering), Speaker 3 (Marketing)\n\n"
            "## Key Discussion Points\n"
            "- WASAPI audio loopback is fully tested and stable\n"
            "- Press release drafted, three webinars scheduled targeting startup CTOs\n\n"
            "## Action Items\n"
            "- [Speaker 3] Share press release draft to shared Drive by end of week\n"
            "- [Speaker 2] Run final regression tests on installer before Friday\n\n"
            "## Decisions Made\n"
            "- Lock Clarify desktop beta builds for next week's preview cohort"
        ),
        "speakers": ["Speaker 1", "Speaker 2", "Speaker 3"],
        "duration": 48.0,
    },
    {
        "topic": "Engineering Security Review",
        "transcript": (
            "[00:00] Speaker 1: Let's review the security posture of the speech pipeline.\n"
            "[00:09] Speaker 2: All API keys have been removed from client-side code. Credentials are loaded on-device only.\n"
            "[00:22] Speaker 3: Since models run on-device via Parakeet and Ollama, no transcripts reach third-party endpoints.\n"
            "[00:38] Speaker 1: I will document this architecture for the enterprise trust page."
        ),
        "summary": (
            "## TL;DR\n"
            "The security audit confirmed Clarify's pipeline is fully air-gapped. No audio or transcript data leaves the device.\n\n"
            "## Attendees\nSpeaker 1 (Principal Architect), Speaker 2 (Backend Engineer), Speaker 3 (Security Auditor)\n\n"
            "## Key Discussion Points\n"
            "- All credentials removed from client-side PyQt code\n"
            "- On-device Parakeet + Ollama ensures zero cloud telemetry\n\n"
            "## Action Items\n"
            "- [Speaker 1] Draft updated security and architecture whitepaper\n"
            "- [Speaker 2] Encrypt HF tokens inside Windows Credentials Vault\n\n"
            "## Decisions Made\n"
            "- Standardize on local-first Ollama hosting for all enterprise installations"
        ),
        "speakers": ["Speaker 1", "Speaker 2", "Speaker 3"],
        "duration": 42.0,
    },
]


# ══════════════════════════════════════════════════════════════════════
# Pydantic models
# ══════════════════════════════════════════════════════════════════════

class AudioSubmitRequest(BaseModel):
    # Optional — None means simulation mode (no real audio)
    audio_b64: Optional[str] = None
    export_format: str = "docx"
    diarization: bool = False
    ollama_model: str = "gemma3:4b"
    is_simulated: bool = False
    sample_index: int = 0

class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    progress_pct: float = 0.0
    progress_msg: str = ""
    transcript: Optional[str] = None
    summary: Optional[str] = None
    speakers: list[str] = []
    duration_seconds: float = 0.0
    error: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════
# Ollama detection — tries multiple addresses
# ══════════════════════════════════════════════════════════════════════

def _check_ollama(model: str = "gemma3:4b") -> tuple[bool, str]:
    """
    Try to reach Ollama on both localhost and 127.0.0.1.
    Returns (reachable: bool, message: str).
    """
    candidates = [
        "http://localhost:11434",
        "http://127.0.0.1:11434",
    ]
    for host in candidates:
        try:
            req = urllib.request.Request(f"{host}/api/tags")
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read())
            models = [m["name"] for m in data.get("models", [])]
            model_base = model.split(":")[0]
            found = any(model_base in m for m in models)
            if found:
                return True, f"Ollama reachable at {host}. Model '{model}' available."
            else:
                available = ", ".join(models) if models else "none"
                return False, (
                    f"Ollama reachable at {host} but model '{model}' not found. "
                    f"Available: {available}. Run: ollama pull {model}"
                )
        except Exception:
            continue

    return False, (
        f"Ollama not reachable on localhost:11434 or 127.0.0.1:11434. "
        f"Make sure Ollama is running (check system tray or run: ollama serve)"
    )


# ══════════════════════════════════════════════════════════════════════
# Routes
# ══════════════════════════════════════════════════════════════════════

@app.get("/health")
def health():
    """Connectivity + Ollama check. Safe to call before engine is configured."""
    model = engine.config.ollama_model if hasattr(engine, "config") else "gemma3:4b"
    ok, msg = _check_ollama(model)
    return {
        "status": "ok",
        "gpu": _gpu_info(),
        "ollama": msg,
        "ollama_ok": ok,
    }


@app.post("/jobs/submit", response_model=JobStatusResponse)
def submit_job(payload: AudioSubmitRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())[:8]
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "queued",
            "progress_pct": 0.0,
            "progress_msg": "Job queued…",
            "transcript": None,
            "summary": None,
            "speakers": [],
            "duration_seconds": 0.0,
            "error": None,
        }
    background_tasks.add_task(_run_job, job_id, payload)
    return JobStatusResponse(job_id=job_id, status="queued", progress_msg="Job queued…")


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return JobStatusResponse(job_id=job_id, **job)


@app.get("/devices")
def list_devices():
    return {"devices": engine.list_audio_devices()}


# ══════════════════════════════════════════════════════════════════════
# Background job runner
# ══════════════════════════════════════════════════════════════════════

def _run_job(job_id: str, payload: AudioSubmitRequest):
    def _update(status=None, pct=None, msg=None, **kwargs):
        with _jobs_lock:
            if status: _jobs[job_id]["status"] = status
            if pct is not None: _jobs[job_id]["progress_pct"] = pct
            if msg: _jobs[job_id]["progress_msg"] = msg
            for k, v in kwargs.items():
                _jobs[job_id][k] = v

    try:
        # ── Simulation mode ────────────────────────────────────────────
        if payload.is_simulated or payload.audio_b64 is None:
            _run_simulation(job_id, payload, _update)
            return

        # ── Real audio mode ────────────────────────────────────────────
        _update(status="processing", pct=0.02, msg="Decoding audio…")

        wav_bytes = base64.b64decode(payload.audio_b64)
        tmp_dir = Path(tempfile.mkdtemp())
        wav_path = tmp_dir / "upload.wav"
        wav_path.write_bytes(wav_bytes)

        engine.configure(
            output_dir="./output",
            export_format=payload.export_format,
            diarization=payload.diarization,
            ollama_model=payload.ollama_model,
            hf_token=os.environ.get("HF_TOKEN"),
        )
        engine.on_progress = lambda stage, pct, msg: _update(pct=pct, msg=msg)

        import wave, numpy as np
        with wave.open(str(wav_path), "rb") as wf:
            duration = wf.getnframes() / wf.getframerate()

        audio_data = _load_wav_as_float32(str(wav_path))
        result: ProcessingResult = engine._process(audio_data, duration)

        _update(
            status="done", pct=1.0, msg="Processing complete.",
            transcript=result.transcript_text,
            summary=result.summary_text,
            speakers=result.speakers,
            duration_seconds=result.duration_seconds,
            error=result.error,
        )

    except Exception as e:
        logger.exception(f"Job {job_id} failed: {e}")
        _update(status="error", msg=str(e), error=str(e))
    finally:
        try:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def _run_simulation(job_id: str, payload: AudioSubmitRequest, _update):
    """Returns sample data without touching any AI model."""
    sample = SIMULATION_SAMPLES[payload.sample_index % len(SIMULATION_SAMPLES)]

    steps = [
        (0.10, "saving_audio",         "Preparing sample audio container…"),
        (0.20, "transcribing",         "Loading sample transcript…"),
        (0.50, "diarizing",            "Assigning speaker labels…"),
        (0.65, "building_transcript",  "Building formatted transcript…"),
        (0.80, "summarizing",          "Generating meeting summary…"),
        (0.95, "exporting",            f"Exporting as {payload.export_format}…"),
    ]

    _update(status="processing")
    for pct, stage, msg in steps:
        _update(pct=pct, msg=msg)
        time.sleep(0.8)

    _update(
        status="done", pct=1.0, msg="Simulation complete.",
        transcript=sample["transcript"],
        summary=sample["summary"],
        speakers=sample["speakers"],
        duration_seconds=sample["duration"],
        error=None,
    )
    logger.info(f"Simulation job {job_id} complete.")


# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════

def _load_wav_as_float32(path: str):
    import wave, numpy as np
    with wave.open(path, "rb") as wf:
        raw = wf.readframes(wf.getnframes())
        return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def _gpu_info() -> str:
    try:
        import torch
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            mem = torch.cuda.get_device_properties(0).total_memory // (1024 ** 2)
            return f"{name} ({mem} MB VRAM)"
        return "No CUDA GPU detected"
    except Exception:
        return "unknown"


# ══════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

    print("=" * 55)
    print("  MeetScribe Remote API Server v1.2")
    print("=" * 55)

    # Report Ollama status on startup instead of crashing
    model = os.environ.get("OLLAMA_MODEL", "gemma3:4b")
    ok, msg = _check_ollama(model)
    if ok:
        print(f"  ✓ Ollama: {msg}")
    else:
        print(f"  ✗ Ollama: {msg}")
        print("    → Simulation mode will work. Real transcription will fail until Ollama is reachable.")

    print(f"  Local URL  : http://localhost:{port}")
    print(f"  Network URL: http://<this-PC-local-IP>:{port}")
    print()

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
