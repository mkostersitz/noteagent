"""Speech-to-text transcription — thin wrapper around the Rust core.

All heavy lifting (whisper.cpp inference, hallucination filtering, streaming
chunker) happens in `noteagent-core` and is exposed via the `noteagent_audio`
PyO3 module. This file converts between the Rust dict shapes and the
pydantic models the rest of the Python codebase expects.

Meeting-mode speaker labeling ("You" / "Remote") stays in Python: it's a
trivial post-processing step and presentation concern, not core logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from noteagent.models import Transcript, TranscriptSegment

# Local ggml model cache. The model downloader (Phase 7) writes files here.
_MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "models"


def _model_path(model_size: str) -> Path:
    """Resolve the on-disk path for a ggml model.

    whisper.cpp uses files named `ggml-<size>.bin` (e.g. `ggml-base.en.bin`).
    """
    return _MODEL_DIR / f"ggml-{model_size}.bin"


def _to_segment(seg: dict) -> TranscriptSegment:
    """Convert a Rust segment dict into a pydantic TranscriptSegment."""
    return TranscriptSegment(
        start=seg["start"],
        end=seg["end"],
        text=seg["text"],
        confidence=seg.get("confidence", 1.0),
        speaker=seg.get("speaker", ""),
    )


def _to_transcript(t: dict) -> Transcript:
    """Convert a Rust transcript dict into a pydantic Transcript."""
    return Transcript(
        segments=[_to_segment(s) for s in t.get("segments", [])],
        language=t.get("language", "en"),
        model=t.get("model", "base.en"),
    )


def load_model(model_size: str = "base.en"):
    """Load a ggml whisper model.

    Returns a `noteagent_audio.WhisperTranscriber` instance that can be reused
    across multiple `transcribe_file` / `transcribe_meeting` calls.
    """
    from noteagent_audio import WhisperTranscriber

    path = _model_path(model_size)
    if not path.exists():
        raise RuntimeError(
            f"Whisper model not found at {path}. "
            f"Run the model downloader to fetch ggml-{model_size}.bin "
            f"(see `noteagent download-model {model_size}`)."
        )
    return WhisperTranscriber(str(path), model_size)


def transcribe_file(
    audio_path: Path,
    model=None,
    model_size: str = "base.en",
    language: Optional[str] = "en",
    quality: str = "balanced",
) -> Transcript:
    """Transcribe an audio file (post-recording batch mode)."""
    if model is None:
        model = load_model(model_size)

    result = model.transcribe_file(
        str(audio_path),
        language=language,
        quality=quality,
    )
    transcript = _to_transcript(result)
    # Preserve the caller's requested model_size on the returned object
    # (the Rust side records whichever id the model was loaded with).
    transcript.model = model_size
    return transcript


class LiveTranscriber:
    """Processes audio chunks in near-real-time for live transcription.

    Thin wrapper around `noteagent_audio.LiveTranscriber` that converts
    returned segment dicts into pydantic `TranscriptSegment` instances.
    """

    def __init__(
        self,
        model_size: str = "base.en",
        language: str = "en",
        sample_rate: int = 16000,
        chunk_duration: float = 5.0,
        quality: str = "balanced",
    ) -> None:
        from noteagent_audio import LiveTranscriber as _RustLive

        self.model_size = model_size
        self.language = language
        self.sample_rate = sample_rate
        self.chunk_duration = chunk_duration
        path = _model_path(model_size)
        if not path.exists():
            raise RuntimeError(
                f"Whisper model not found at {path}. "
                f"Run the model downloader to fetch ggml-{model_size}.bin."
            )
        self._inner = _RustLive(
            str(path),
            model_size,
            language,
            quality,
            chunk_duration,
        )

    @property
    def silence_seconds(self) -> float:
        return self._inner.silence_seconds

    def feed(self, samples: list[float]) -> list[TranscriptSegment]:
        """Feed audio samples and return any new transcript segments."""
        if not samples:
            return []
        new_segs = self._inner.feed(samples)
        return [_to_segment(s) for s in new_segs]

    def get_transcript(self) -> Transcript:
        """Return the accumulated transcript so far."""
        result = self._inner.transcript()
        transcript = _to_transcript(result)
        transcript.model = self.model_size
        return transcript


def transcribe_meeting(
    mic_path: Path,
    system_path: Path,
    model=None,
    model_size: str = "base.en",
    language: str = "en",
    quality: str = "balanced",
) -> Transcript:
    """Transcribe a dual-channel meeting recording.

    Transcribes mic and system audio separately, labels speakers, then merges
    segments sorted by start time. Speaker labeling lives here (not in core)
    because it's a presentation concern, not transcription logic.
    """
    if model is None:
        model = load_model(model_size)

    mic_transcript = transcribe_file(
        mic_path, model=model, model_size=model_size, language=language, quality=quality,
    )
    sys_transcript = transcribe_file(
        system_path, model=model, model_size=model_size, language=language, quality=quality,
    )

    for seg in mic_transcript.segments:
        seg.speaker = "You"
    for seg in sys_transcript.segments:
        seg.speaker = "Remote"

    merged = sorted(
        mic_transcript.segments + sys_transcript.segments,
        key=lambda s: s.start,
    )

    return Transcript(segments=merged, language=language, model=model_size)


class MeetingLiveTranscriber:
    """Dual-channel live transcriber for meeting mode.

    Owns two `LiveTranscriber` instances — one per audio channel — and tags
    their segments with "You" / "Remote" speaker labels.
    """

    def __init__(
        self,
        model_size: str = "base.en",
        language: str = "en",
        sample_rate: int = 16000,
        chunk_duration: float = 5.0,
        quality: str = "balanced",
    ) -> None:
        self._mic = LiveTranscriber(
            model_size=model_size,
            language=language,
            sample_rate=sample_rate,
            chunk_duration=chunk_duration,
            quality=quality,
        )
        self._system = LiveTranscriber(
            model_size=model_size,
            language=language,
            sample_rate=sample_rate,
            chunk_duration=chunk_duration,
            quality=quality,
        )
        self.model_size = model_size
        self.language = language

    @property
    def silence_seconds(self) -> float:
        """Seconds of continuous silence across both channels."""
        return min(self._mic.silence_seconds, self._system.silence_seconds)

    def feed_mic(self, samples: list[float]) -> list[TranscriptSegment]:
        segs = self._mic.feed(samples)
        for s in segs:
            s.speaker = "You"
        return segs

    def feed_system(self, samples: list[float]) -> list[TranscriptSegment]:
        segs = self._system.feed(samples)
        for s in segs:
            s.speaker = "Remote"
        return segs

    def get_transcript(self) -> Transcript:
        mic_t = self._mic.get_transcript()
        sys_t = self._system.get_transcript()
        for seg in mic_t.segments:
            seg.speaker = "You"
        for seg in sys_t.segments:
            seg.speaker = "Remote"
        merged = sorted(
            mic_t.segments + sys_t.segments,
            key=lambda s: s.start,
        )
        return Transcript(segments=merged, language=self.language, model=self.model_size)
