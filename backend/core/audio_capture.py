"""
core/audio_capture.py
---------------------
Captures system audio output (loopback) on Windows using pyaudiowpatch,
which exposes WASAPI loopback devices via PyAudio.

Requirements:
    pip install pyaudiowpatch

PyAudioWPatch is a fork of PyAudio with WASAPI loopback support for Windows.
It allows capturing what the speakers are playing — exactly what you hear
in a Google Meet call — without needing any virtual cable.
"""

from __future__ import annotations

import wave
import io
import threading
import numpy as np
from typing import Optional
from utils.logger import get_logger

logger = get_logger(__name__)

# Lazy import so the module can be imported without pyaudiowpatch installed
# (e.g., during tests or on non-Windows platforms)
try:
    import pyaudiowpatch as pyaudio
    _PYAUDIO_AVAILABLE = True
except ImportError:
    _PYAUDIO_AVAILABLE = False
    logger.warning(
        "pyaudiowpatch not found. Install it with: pip install pyaudiowpatch\n"
        "Audio capture will not be available."
    )


CHUNK_SIZE = 1024   # frames per buffer read


class AudioCapture:
    """
    Records Windows WASAPI loopback audio.

    Usage:
        capture = AudioCapture()
        capture.start(device_name=None)   # None = auto-detect default speakers
        # ... meeting happens ...
        audio_data = capture.stop()
        capture.save_wav(audio_data, "meeting.wav", sample_rate=16000)
    """

    def __init__(self):
        self._pa: Optional[object] = None
        self._stream: Optional[object] = None
        self._frames: list[bytes] = []
        self._lock = threading.Lock()
        self._running = False
        self._device_info: Optional[dict] = None
        self._actual_sample_rate: int = 16000
        self._actual_channels: int = 1

    # ------------------------------------------------------------------
    # Device discovery
    # ------------------------------------------------------------------

    def list_loopback_devices(self) -> list[str]:
        """
        Return display names of available WASAPI loopback devices.
        Tries three strategies in order:
          1. Devices explicitly flagged as loopback (isLoopbackDevice)
          2. Devices whose name contains 'loopback' (case-insensitive)
          3. All WASAPI output devices as a fallback (any device with maxOutputChannels > 0)
        """
        if not _PYAUDIO_AVAILABLE:
            return ["[pyaudiowpatch not installed]"]

        pa = pyaudio.PyAudio()
        loopback_devices = []
        name_match_devices = []
        wasapi_output_devices = []

        try:
            # Find the WASAPI host API index
            wasapi_index = None
            for i in range(pa.get_host_api_count()):
                api = pa.get_host_api_info_by_index(i)
                if api.get("type") == pyaudio.paWASAPI:
                    wasapi_index = i
                    break

            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                name = info.get("name", "")

                # Strategy 1: explicitly flagged loopback
                if info.get("isLoopbackDevice", False):
                    loopback_devices.append(name)
                    continue

                # Strategy 2: name contains 'loopback'
                if "loopback" in name.lower():
                    name_match_devices.append(name)
                    continue

                # Strategy 3: WASAPI output device (can be used as loopback source)
                if wasapi_index is not None and info.get("hostApi") == wasapi_index:
                    if info.get("maxOutputChannels", 0) > 0:
                        wasapi_output_devices.append(name)

        finally:
            pa.terminate()

        # Return the most specific list that has results
        if loopback_devices:
            return loopback_devices
        if name_match_devices:
            return name_match_devices
        if wasapi_output_devices:
            return wasapi_output_devices

        return ["[No WASAPI loopback devices found — check your audio drivers]"]

    def _find_default_loopback_device(self, pa) -> dict:
        """
        Auto-detect the loopback device corresponding to the default
        output (speakers/headphones). This is what the user hears.
        """
        # Get the default WASAPI output device
        try:
            wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError:
            raise RuntimeError(
                "WASAPI is not available on this system. "
                "Make sure you are on Windows and using pyaudiowpatch."
            )

        default_output_idx = wasapi_info["defaultOutputDevice"]
        default_output_info = pa.get_device_info_by_index(default_output_idx)

        # Find the corresponding loopback device
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if (
                info.get("isLoopbackDevice", False)
                and info["name"] == default_output_info["name"]
            ):
                logger.info(f"Auto-selected loopback device: {info['name']}")
                return info

        raise RuntimeError(
            f"No loopback device found for default output: {default_output_info['name']}.\n"
            "Try specifying a device_name explicitly via list_loopback_devices()."
        )

    def _find_named_device(self, pa, name: str) -> dict:
        """Find a loopback device by (partial) name."""
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info.get("isLoopbackDevice", False) and name.lower() in info["name"].lower():
                logger.info(f"Found device '{info['name']}' for query '{name}'")
                return info
        raise RuntimeError(f"No loopback device found matching: '{name}'")

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def start(
        self,
        device_name: Optional[str] = None,
        sample_rate: int = 16000,
        channels: int = 1,
    ):
        """Open the WASAPI loopback stream and start buffering audio."""
        if not _PYAUDIO_AVAILABLE:
            raise RuntimeError(
                "pyaudiowpatch is not installed. "
                "Run: pip install pyaudiowpatch"
            )

        if self._running:
            raise RuntimeError("Already recording. Call stop() first.")

        self._pa = pyaudio.PyAudio()

        if device_name:
            device_info = self._find_named_device(self._pa, device_name)
        else:
            device_info = self._find_default_loopback_device(self._pa)

        self._device_info = device_info
        # Use the device's native sample rate to avoid resampling artifacts;
        # we'll resample to target later if needed.
        native_rate = int(device_info["defaultSampleRate"])
        native_channels = device_info["maxInputChannels"]

        self._actual_sample_rate = native_rate
        self._actual_channels = native_channels
        self._target_sample_rate = sample_rate
        self._target_channels = channels
        self._frames = []
        self._running = True

        self._stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=native_channels,
            rate=native_rate,
            frames_per_buffer=CHUNK_SIZE,
            input=True,
            input_device_index=device_info["index"],
            stream_callback=self._audio_callback,
        )
        self._stream.start_stream()
        logger.info(
            f"Capture started: {device_info['name']} "
            f"@ {native_rate}Hz, {native_channels}ch"
        )

    def _audio_callback(self, in_data, frame_count, time_info, status):
        """PyAudio callback — appends raw PCM chunks to buffer."""
        import pyaudiowpatch as pyaudio  # noqa: local import for constant
        with self._lock:
            if self._running:
                self._frames.append(in_data)
        return (None, pyaudio.paContinue)

    def stop(self) -> np.ndarray:
        """
        Stop recording and return audio as a float32 numpy array
        resampled to the target sample rate and channel count.
        """
        if not self._running:
            raise RuntimeError("Not recording.")

        self._running = False

        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None

        if self._pa:
            self._pa.terminate()
            self._pa = None

        with self._lock:
            raw = b"".join(self._frames)
            self._frames = []

        if not raw:
            logger.warning("No audio captured.")
            return np.zeros(0, dtype=np.float32)

        # Convert raw PCM int16 → float32
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

        # Reshape to (samples, channels) if multi-channel
        if self._actual_channels > 1:
            audio = audio.reshape(-1, self._actual_channels)
            # Mix down to mono if needed
            if self._target_channels == 1:
                audio = audio.mean(axis=1)
        
        # Resample if needed
        if self._actual_sample_rate != self._target_sample_rate:
            audio = _resample(audio, self._actual_sample_rate, self._target_sample_rate)

        logger.info(
            f"Captured {len(audio)/self._target_sample_rate:.1f}s of audio "
            f"({len(audio)} samples @ {self._target_sample_rate}Hz)"
        )
        return audio

    # ------------------------------------------------------------------
    # Saving
    # ------------------------------------------------------------------

    def save_wav(self, audio: np.ndarray, path: str, sample_rate: int):
        """Save a float32 numpy array as a 16-bit mono WAV file."""
        pcm = (audio * 32767).clip(-32768, 32767).astype(np.int16)
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit = 2 bytes
            wf.setframerate(sample_rate)
            wf.writeframes(pcm.tobytes())
        logger.info(f"WAV saved: {path}")


# ------------------------------------------------------------------
# Resampling helper
# ------------------------------------------------------------------

def _resample(audio: np.ndarray, orig_rate: int, target_rate: int) -> np.ndarray:
    """
    Simple linear-interpolation resample.
    For production quality, use scipy.signal.resample_poly or resampy.
    """
    try:
        from scipy.signal import resample_poly
        from math import gcd
        g = gcd(orig_rate, target_rate)
        up, down = target_rate // g, orig_rate // g
        return resample_poly(audio, up, down).astype(np.float32)
    except ImportError:
        pass

    # Fallback: numpy linear interpolation
    duration = len(audio) / orig_rate
    target_len = int(duration * target_rate)
    old_indices = np.linspace(0, len(audio) - 1, target_len)
    return np.interp(old_indices, np.arange(len(audio)), audio).astype(np.float32)