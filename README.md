# Clarify — AI-Powered Meeting Transcription

Clarify is a Windows desktop-grade meeting recorder and transcription tool
with a React frontend and a Python AI backend.

```
clarify/
├── frontend/   React + Express bridge server (this UI)
└── backend/    Python AI engine (Parakeet + Ollama + pyannote)
```

---

## Quick Start

### 1. Start the Python Backend

```bash
cd backend

# Create virtual environment and install dependencies
python -m venv .venv
.venv\Scripts\activate
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
pip install nemo_toolkit[asr] pyannote.audio python-docx reportlab fastapi uvicorn

# Pull the LLM (do once)
ollama pull gemma3:4b

# Set your HuggingFace token (required for diarization)
set HF_TOKEN=hf_your_token_here

# Start the backend API server
python server_api.py
# → Running at http://localhost:8000
```

### 2. Start the Frontend

```bash
cd frontend

# Install Node dependencies
npm install

# Copy and configure environment
cp .env.example .env
# Edit .env: set PYTHON_BACKEND_URL=http://localhost:8000

# Start the dev server
npm run dev
# → Open http://localhost:3000
```

---

## Architecture

```
Browser (React UI)
      │  HTTP fetch
      ▼
frontend/server.ts   (Express bridge — port 3000)
      │  HTTP fetch + ffmpeg WAV conversion
      ▼
backend/server_api.py   (FastAPI — port 8000)
      │
      ├── core/audio_capture.py   → pyaudiowpatch WASAPI
      ├── models/transcriber.py   → NVIDIA Parakeet (NeMo)
      ├── models/diarizer.py      → pyannote speaker diarization
      ├── models/summarizer.py    → Llama/Gemma via Ollama
      └── export/exporter.py      → DOCX / PDF / TXT
```

## Remote Mode (RTX 5060 PC as server)

1. Run `python server_api.py` on your PC
2. In the frontend Settings panel, enable **Remote Mode** and enter your PC's IP
3. The frontend bridge will route all processing to that machine

## Requirements

### Backend
- Windows 10/11 64-bit
- Python 3.10 or 3.11
- NVIDIA GPU with CUDA 12.8 (RTX 5060 recommended)
- Ollama installed and running

### Frontend
- Node.js 18+
- ffmpeg installed and on PATH (for WebM→WAV conversion)
  - Windows: https://ffmpeg.org/download.html
  - Or: `winget install ffmpeg`
