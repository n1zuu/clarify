# MeetScribe — Setup & Integration Guide

## Overview

MeetScribe is a Windows desktop application that:
1. **Captures** system audio (what you hear in Google Meet) via WASAPI loopback
2. **Transcribes** it with NVIDIA Parakeet (NeMo ASR)
3. **Diarizes** speakers with pyannote.audio
4. **Summarizes** with Llama 3.3 (via Ollama)
5. **Exports** to DOCX, PDF, or TXT

---

## Prerequisites

### 1. Python
- **Python 3.10 or 3.11** (recommended)
- Python 3.12 has some NeMo compatibility issues as of mid-2025

### 2. NVIDIA GPU (strongly recommended)
- Parakeet runs on CPU but is very slow (~10x real-time on good hardware)
- A GPU with **4+ GB VRAM** is recommended for Parakeet 1.1B
- Install **CUDA 12.x** from https://developer.nvidia.com/cuda-downloads
- Install **cuDNN** from https://developer.nvidia.com/cudnn

### 3. Ollama (for Llama 3.3 summarization)
```bash
# Download and install from:
https://ollama.com/download

# Then pull Llama 3.3 (requires ~20GB disk):
ollama pull llama3.3

# Verify it runs:
ollama run llama3.3 "Hello, who are you?"
```

> **Note:** Llama 3.3 (70B) requires ~40GB RAM or a high-VRAM GPU to run
> at reasonable speed. For lighter machines, use `llama3.2` (3B) or
> `llama3.2:1b` instead — just change `ollama_model` in the config.

### 4. HuggingFace Token (for speaker diarization)
Pyannote's diarization model requires accepting their terms:
1. Create an account at https://huggingface.co
2. Go to https://huggingface.co/pyannote/speaker-diarization-3.1
3. Click "Accept" on the model card
4. Create a token at https://huggingface.co/settings/tokens
5. Pass it as `hf_token` in `engine.configure()` or set `HF_TOKEN` env var

---

## Installation

```bash
# 1. Clone / download the project
cd meetscribe

# 2. Create virtual environment
python -m venv .venv
.venv\Scripts\activate

# 3. Install PyTorch with CUDA first (visit https://pytorch.org/get-started/locally/)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# 4. Install NeMo (this is large — ~2GB, takes several minutes)
pip install nemo_toolkit[asr]

# 5. Install remaining dependencies
pip install -r requirements.txt
```

---

## Project Structure

```
meetscribe/
├── main.py                  # Entry point (CLI/headless mode)
├── requirements.txt
├── meetscribe.spec          # PyInstaller build spec
│
├── core/
│   ├── engine.py            # ← YOUR GUI CONNECTS HERE
│   └── audio_capture.py     # WASAPI loopback via pyaudiowpatch
│
├── models/
│   ├── transcriber.py       # NVIDIA Parakeet STT
│   ├── diarizer.py          # pyannote speaker diarization
│   └── summarizer.py        # Llama 3.3 via Ollama
│
├── export/
│   └── exporter.py          # DOCX / PDF / TXT export
│
└── utils/
    └── logger.py
```

---

## GUI Integration

Your GUI should interact exclusively with `MeetScribeEngine` from `core/engine.py`.

### Minimal Integration Example

```python
from core.engine import MeetScribeEngine

engine = MeetScribeEngine()

# Wire up callbacks (called from background threads — use thread-safe UI updates)
engine.on_progress = lambda stage, pct, msg: update_progress_bar(pct, msg)
engine.on_complete = lambda result: show_results(result)
engine.on_error    = lambda err: show_error_dialog(err)

# Configure once at startup or when user changes settings
engine.configure(
    output_dir="C:/Users/Me/MeetScribe/output",
    export_format="docx",       # "pdf" | "docx" | "txt" | "all"
    diarization=True,
    hf_token="hf_your_token_here",
    ollama_model="llama3.3",    # or "llama3.2" for lighter machines
)

# List available audio devices (for a device-picker dropdown)
devices = engine.list_audio_devices()

# Start recording when user clicks Record
engine.start_recording()

# Poll this for a live duration counter in the UI
current_duration = engine.recording_duration   # float seconds

# Stop and process asynchronously (non-blocking)
# Results delivered via on_complete callback
engine.stop_and_process_async()
```

### ProcessingResult Fields

```python
@dataclass
class ProcessingResult:
    audio_path: str          # path to raw WAV recording
    transcript_path: str     # path to transcript.txt
    summary_path: str        # path to summary.txt
    export_path: str         # path to the exported document
    transcript_text: str     # full transcript as string
    summary_text: str        # summary as string
    speakers: list[str]      # ["Speaker 1", "Speaker 2", ...]
    duration_seconds: float  # recording duration
    error: str | None        # set if something failed
```

### Progress Stages

The `on_progress(stage, pct, message)` callback fires with these stages:

| stage               | pct  | meaning                        |
|---------------------|------|--------------------------------|
| `recording`         | 0.00 | Recording started              |
| `saving_audio`      | 0.05 | Saving WAV to disk             |
| `transcribing`      | 0.15 | Parakeet running               |
| `diarizing`         | 0.45 | pyannote speaker ID            |
| `building_transcript` | 0.60 | Merging transcript text       |
| `summarizing`       | 0.70 | Llama 3.3 summarizing          |
| `exporting`         | 0.90 | Writing output document        |
| `done`              | 1.00 | All complete                   |

---

## Building the Executable

```bash
pip install pyinstaller

# Build (takes 5-15 minutes; output in dist/MeetScribe/)
pyinstaller meetscribe.spec

# The output folder dist/MeetScribe/ contains MeetScribe.exe
# and all required DLLs. Distribute the whole folder, not just the .exe.
```

> **Important:** ML model weights are NOT bundled. On first run, Parakeet
> downloads ~2.2GB to the NeMo cache (`~/.cache/huggingface/hub/`).
> Subsequent runs are instant.

---

## Troubleshooting

### "No loopback device found"
- Make sure audio is playing through Windows default speakers/headphones
- Open Sound settings → ensure the right output device is set as default
- Try running `python main.py --list-devices` to see what's available

### Parakeet is very slow
- Check that CUDA is detected: `python -c "import torch; print(torch.cuda.is_available())"`
- If False, reinstall PyTorch with the correct CUDA version

### Ollama connection refused
- Start Ollama: open the Ollama tray icon or run `ollama serve`
- Check it's running: visit http://localhost:11434 in a browser

### Diarization fails / HF token error
- Make sure you accepted the pyannote model terms on HuggingFace
- Verify your token is correct at https://huggingface.co/settings/tokens

### NeMo install fails
- Try installing with `--no-build-isolation`: `pip install nemo_toolkit[asr] --no-build-isolation`
- NeMo requires `Cython` pre-installed: `pip install Cython` first

---

## Performance Expectations (RTX 3080, 16GB RAM)

| Step             | ~Time for 1hr meeting |
|------------------|-----------------------|
| Audio capture    | Real-time             |
| Parakeet STT     | 3-5 minutes           |
| Diarization      | 2-4 minutes           |
| Llama 3.3 summary | 1-3 minutes          |
| Export (DOCX)    | <5 seconds            |
| **Total**        | **~7-12 minutes**     |
