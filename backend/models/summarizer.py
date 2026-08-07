"""
models/summarizer.py
--------------------
Summarizes meeting transcripts using Llama 3.3 via Ollama.

Ollama must be running locally:
    https://ollama.com/download

Pull the model once with:
    ollama pull llama3.3

The summarizer produces a structured meeting summary with:
  - TL;DR (2-3 sentences)
  - Key discussion points
  - Action items & owners
  - Decisions made
  - Full formatted transcript (optional)

For very long transcripts (>8k tokens) we chunk and summarize
in passes before producing the final summary.
"""

from __future__ import annotations

import json
import textwrap
from typing import Optional
from utils.logger import get_logger

logger = get_logger(__name__)

SUMMARY_PROMPT_TEMPLATE = """\
You are an expert meeting analyst. Below is a transcript of a meeting.
{speaker_context}

Please produce a structured meeting summary with the following sections:

## TL;DR
A 2-3 sentence executive summary of the meeting.

## Attendees
List the speakers identified in the transcript.

## Key Discussion Points
Bullet points covering the main topics discussed.

## Action Items
A list of action items, each with an owner if identifiable.
Format: "- [Owner] Action description"

## Decisions Made
Any decisions or conclusions reached during the meeting.

## Open Questions
Unresolved questions or items needing follow-up.

---
TRANSCRIPT:
{transcript}
"""

CHUNK_SUMMARY_PROMPT = """\
Below is a partial transcript of a longer meeting. Summarize the key points,
action items, and decisions in this section only. Be concise.

PARTIAL TRANSCRIPT:
{chunk}
"""

CLEANUP_PROMPT = """\
The following is a raw speech-to-text transcript. It may be missing punctuation, 
capitalization, and proper sentence breaks. Clean it up — fix grammar, add punctuation, 
capitalize properly, and break run-on sentences. Do NOT change any words, add content, 
or summarize. Only fix formatting and grammar. Return only the corrected transcript.

TRANSCRIPT:
{transcript}
"""

FINAL_MERGE_PROMPT = """\
Below are summaries of different sections of a meeting. Combine them into
one final structured meeting summary with these sections:
## TL;DR, ## Attendees, ## Key Discussion Points, ## Action Items, 
## Decisions Made, ## Open Questions.


SECTION SUMMARIES:
{summaries}
"""

# Approximate token limit per Ollama request (conservative)
MAX_TRANSCRIPT_CHARS = 12_000   # ~3k tokens, leaves room for prompt + output
CHUNK_CHARS = 10_000


class Summarizer:
    """
    Sends transcript to Llama 3.3 via Ollama HTTP API.
    """

    def __init__(
        self,
        model: str = "llama3.3",
        host: str = "http://localhost:11434",
        timeout: int = 300,
    ):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout

    def summarize(self, transcript: str, speakers: Optional[list[str]] = None) -> str:
        """
        Produce a structured summary of the meeting transcript.
        Handles long transcripts via chunked summarization.
        """
        if not transcript.strip():
            return "No transcript content to summarize."

        if len(transcript) <= MAX_TRANSCRIPT_CHARS:
            return self._summarize_direct(transcript, speakers)
        else:
            logger.info(
                f"Transcript is long ({len(transcript)} chars), using chunked summarization."
            )
            return self._summarize_chunked(transcript, speakers)

    def _summarize_direct(self, transcript: str, speakers: Optional[list[str]]) -> str:
        speaker_context = ""
        if speakers:
            speaker_context = (
                f"The meeting had {len(speakers)} identified speakers: "
                f"{', '.join(speakers)}."
            )

        prompt = SUMMARY_PROMPT_TEMPLATE.format(
            transcript=transcript,
            speaker_context=speaker_context,
        )
        return self._call_ollama(prompt)

    def _summarize_chunked(self, transcript: str, speakers: Optional[list[str]]) -> str:
        chunks = _split_into_chunks(transcript, CHUNK_CHARS)
        logger.info(f"Split transcript into {len(chunks)} chunks.")

        chunk_summaries = []
        for i, chunk in enumerate(chunks):
            logger.info(f"Summarizing chunk {i+1}/{len(chunks)}…")
            prompt = CHUNK_SUMMARY_PROMPT.format(chunk=chunk)
            summary = self._call_ollama(prompt)
            chunk_summaries.append(f"[Section {i+1}]\n{summary}")

        combined = "\n\n".join(chunk_summaries)
        speaker_note = ""
        if speakers:
            speaker_note = f"\nSpeakers: {', '.join(speakers)}\n"

        merge_prompt = FINAL_MERGE_PROMPT.format(summaries=speaker_note + combined)
        return self._call_ollama(merge_prompt)
    
    def clean_transcript(self, transcript: str) -> str:
        if not transcript.strip():
            return transcript
        if len(transcript) > MAX_TRANSCRIPT_CHARS:
            logger.warning("Transcript too long for cleanup, skipping grammar correction.")
            return transcript  # or chunk it like _summarize_chunked does
        prompt = CLEANUP_PROMPT.format(transcript=transcript)
        return self._call_ollama(prompt)

    def _call_ollama(self, prompt: str) -> str:
        """POST to Ollama /api/generate and return the response text."""
        try:
            import urllib.request

            payload = json.dumps({
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "num_predict": 2048,
                },
            }).encode("utf-8")

            req = urllib.request.Request(
                f"{self.host}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")

            data = json.loads(body)
            response_text = data.get("response", "").strip()

            if not response_text:
                raise RuntimeError("Ollama returned an empty response.")

            return response_text

        except ConnectionRefusedError:
            raise RuntimeError(
                f"Cannot connect to Ollama at {self.host}.\n"
                "Make sure Ollama is running: https://ollama.com/download\n"
                f"Then pull the model: ollama pull {self.model}"
            )
        except Exception as e:
            raise RuntimeError(f"Ollama request failed: {e}")

    def check_ollama_available(self) -> tuple[bool, str]:
        """
        Check if Ollama is running and the model is available.
        Returns (ok: bool, message: str).
        """
        try:
            import urllib.request
            req = urllib.request.Request(f"{self.host}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            models = [m["name"] for m in data.get("models", [])]
            model_base = self.model.split(":")[0]
            found = any(model_base in m for m in models)
            if found:
                return True, f"Ollama running, model '{self.model}' available."
            else:
                available = ", ".join(models) if models else "none"
                return False, (
                    f"Ollama is running but model '{self.model}' is not pulled.\n"
                    f"Available models: {available}\n"
                    f"Run: ollama pull {self.model}"
                )
        except Exception as e:
            return False, f"Ollama not reachable at {self.host}: {e}"


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _split_into_chunks(text: str, chunk_size: int) -> list[str]:
    """
    Split transcript into chunks at sentence/line boundaries,
    trying to keep each chunk under chunk_size characters.
    """
    if not text.strip():
        return []
    lines = text.split("\n")
    chunks = []
    current = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1
        if current_len + line_len > chunk_size and current:
            chunks.append("\n".join(current))
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len

    if current:
        chunks.append("\n".join(current))

    return chunks
