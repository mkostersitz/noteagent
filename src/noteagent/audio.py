"""Audio capture wrapper around the Rust noteagent_audio module."""

from __future__ import annotations

from pathlib import Path
from typing import Optional


class AudioBackendUnavailable(RuntimeError):
    """Raised when the Rust audio backend is not installed in the active environment."""


def _load_backend():
    """Import the Rust audio backend with an actionable error message."""
    try:
        import noteagent_audio  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        raise AudioBackendUnavailable(
            "The Rust audio backend is not installed in the active environment. "
            "Build it with 'cd noteagent-audio && maturin develop' in the same environment "
            "that runs noteagent, or reinstall the editable pipx app from this repo."
        ) from exc
    return noteagent_audio


def list_devices() -> list[str]:
    """List available audio input devices."""
    noteagent_audio = _load_backend()
    return noteagent_audio.list_audio_devices()


class Recorder:
    """Records audio to a WAV file via the Rust backend."""

    def __init__(
        self,
        device_name: Optional[str] = None,
        sample_rate: int = 16000,
    ) -> None:
        noteagent_audio = _load_backend()

        self._recorder = noteagent_audio.AudioRecorder(
            device_name=device_name,
            sample_rate=sample_rate,
        )
        self._recording = False

    def start(self, output_path: Path, device_name: Optional[str] = None) -> None:
        """Start recording audio to the given path."""
        self._recorder.start(str(output_path), device_name=device_name)
        self._recording = True

    def stop(self) -> None:
        """Stop recording and finalize WAV."""
        if self._recording:
            self._recorder.stop()
            self._recording = False

    @property
    def is_recording(self) -> bool:
        return self._recording


class DualRecorder:
    """Records two audio channels simultaneously (mic + system audio) for meeting mode."""

    def __init__(
        self,
        mic_device: Optional[str] = None,
        system_device: Optional[str] = None,
        sample_rate: int = 16000,
    ) -> None:
        self._mic = Recorder(device_name=mic_device, sample_rate=sample_rate)
        self._system = Recorder(device_name=system_device, sample_rate=sample_rate)

    def start(self, mic_path: Path, system_path: Path) -> None:
        """Start recording both channels."""
        self._mic.start(mic_path, device_name=None)
        self._system.start(system_path, device_name=None)

    def stop(self) -> None:
        """Stop both recordings."""
        self._mic.stop()
        self._system.stop()

    @property
    def is_recording(self) -> bool:
        return self._mic.is_recording or self._system.is_recording


class DualStreamReader:
    """Streams audio chunks from two devices for live meeting transcription."""

    def __init__(
        self,
        mic_device: Optional[str] = None,
        system_device: Optional[str] = None,
        sample_rate: int = 16000,
    ) -> None:
        self._mic_stream = StreamReader(device_name=mic_device, sample_rate=sample_rate)
        self._system_stream = StreamReader(device_name=system_device, sample_rate=sample_rate)

    def read_mic_chunk(self) -> list[float]:
        return self._mic_stream.read_chunk()

    def read_system_chunk(self) -> list[float]:
        return self._system_stream.read_chunk()

    def stop(self) -> None:
        self._mic_stream.stop()
        self._system_stream.stop()


class StreamReader:
    """Streams audio chunks from the Rust ring buffer for live processing."""

    def __init__(
        self,
        device_name: Optional[str] = None,
        sample_rate: int = 16000,
    ) -> None:
        noteagent_audio = _load_backend()

        self._stream = noteagent_audio.AudioStream(
            device_name=device_name,
            sample_rate=sample_rate,
        )

    def read_chunk(self) -> list[float]:
        """Read available PCM samples from the ring buffer."""
        return self._stream.read_chunk()

    @property
    def sample_rate(self) -> int:
        return self._stream.get_sample_rate()

    def stop(self) -> None:
        """Stop the stream."""
        self._stream.stop()
