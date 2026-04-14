"""Whisper-based speech-to-text transcription (live + batch)."""

from __future__ import annotations

import hashlib
import os
import ssl
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional

import numpy as np
import whisper

from noteagent.models import Transcript, TranscriptSegment

# Local model cache — avoids HuggingFace Hub entirely
_MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "models"

# Known Whisper hallucination phrases produced when processing silence
_HALLUCINATION_PATTERNS = frozenset({
    "thank you",
    "thanks for watching",
    "goodbye",
    "bye",
    "thank you for watching",
    "please subscribe",
    "the end",
    "thanks",
    "thank you so much",
    "subtitles by",
    "subtitle",
    "subtitles",
})

_QUALITY_PRESETS: dict[str, dict[str, Any]] = {
    "fast": {
        "beam_size": 1,
        "best_of": 1,
        "temperature": 0.0,
        "condition_on_previous_text": False,
    },
    "balanced": {
        "beam_size": 5,
        "best_of": 5,
        "temperature": (0.0, 0.2, 0.4),
        "condition_on_previous_text": True,
    },
    "accurate": {
        "beam_size": 8,
        "best_of": 8,
        "temperature": (0.0, 0.2, 0.4, 0.6),
        "condition_on_previous_text": True,
    },
}


def _resolve_ca_bundle() -> Optional[Path]:
    """Resolve an optional CA bundle path from environment variables."""
    for key in ("NOTEAGENT_CA_BUNDLE", "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE"):
        raw = os.environ.get(key)
        if not raw:
            continue
        candidate = Path(raw).expanduser()
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _install_truststore_if_available() -> None:
    """Use OS trust store for TLS verification when truststore is installed."""
    try:
        import truststore  # type: ignore[import-not-found]

        truststore.inject_into_ssl()
    except Exception:
        # Best effort only; default SSL behavior still applies.
        return


def _is_hallucination(text: str) -> bool:
    """Check if text is a known Whisper hallucination on silence."""
    stripped = text.strip().rstrip(".!,").strip().lower()
    if not stripped:
        return True
    return stripped in _HALLUCINATION_PATTERNS


def _build_transcribe_options(language: Optional[str], quality: str) -> dict[str, Any]:
    """Build whisper transcribe options from quality profile."""
    profile = _QUALITY_PRESETS.get(quality, _QUALITY_PRESETS["balanced"])
    options: dict[str, Any] = {
        **profile,
        "fp16": False,
    }
    if language:
        options["language"] = language
    return options


def _download_model_file(model_size: str, destination: Path) -> None:
    """Download a Whisper model file with custom SSL trust handling.

    This avoids whisper's built-in urllib opener so corporate TLS inspection
    can be handled via a custom CA bundle.
    """
    models = getattr(whisper, "_MODELS", {})
    url = models.get(model_size)
    if not url:
        raise ValueError(f"Unknown Whisper model: {model_size}")

    _install_truststore_if_available()

    ca_bundle = _resolve_ca_bundle()
    context = ssl.create_default_context(cafile=str(ca_bundle) if ca_bundle else None)
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))

    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_target = destination.with_suffix(destination.suffix + ".part")

    with opener.open(url) as source, open(tmp_target, "wb") as output:
        total = source.headers.get("Content-Length")
        total_bytes = int(total) if total and total.isdigit() else None
        downloaded = 0
        chunk_size = 1024 * 1024
        last_update = 0.0
        started_at = time.monotonic()

        while True:
            chunk = source.read(chunk_size)
            if not chunk:
                break
            output.write(chunk)
            downloaded += len(chunk)

            now = time.monotonic()
            if now - last_update < 0.2:
                continue
            last_update = now

            elapsed = max(now - started_at, 0.001)
            speed_mbps = (downloaded / (1024 * 1024)) / elapsed
            downloaded_mb = downloaded / (1024 * 1024)
            if total_bytes:
                pct = (downloaded / total_bytes) * 100
                total_mb = total_bytes / (1024 * 1024)
                status = (
                    f"Downloading Whisper model {model_size}: "
                    f"{pct:5.1f}% ({downloaded_mb:.1f}/{total_mb:.1f} MB) "
                    f"{speed_mbps:.1f} MB/s"
                )
            else:
                status = (
                    f"Downloading Whisper model {model_size}: "
                    f"{downloaded_mb:.1f} MB {speed_mbps:.1f} MB/s"
                )
            print(f"\r{status}", end="", file=sys.stderr, flush=True)

        finished = time.monotonic()
        elapsed = max(finished - started_at, 0.001)
        downloaded_mb = downloaded / (1024 * 1024)
        speed_mbps = downloaded_mb / elapsed
        print(
            f"\rDownloaded Whisper model {model_size}: {downloaded_mb:.1f} MB in {elapsed:.1f}s ({speed_mbps:.1f} MB/s)",
            file=sys.stderr,
            flush=True,
        )

    expected_sha = url.rstrip("/").split("/")[-2]
    if len(expected_sha) == 64:
        actual_sha = hashlib.sha256(tmp_target.read_bytes()).hexdigest()
        if actual_sha != expected_sha:
            tmp_target.unlink(missing_ok=True)
            raise RuntimeError(
                f"Downloaded model checksum mismatch for {model_size}: "
                f"expected {expected_sha}, got {actual_sha}"
            )

    tmp_target.replace(destination)


def load_model(model_size: str = "base.en") -> whisper.Whisper:
    """Load a Whisper model.

    Checks for a local .pt file first, then falls back to openai-whisper's
    built-in downloader (which uses Azure CDN, not HuggingFace).
    """
    local_pt = _MODEL_DIR / f"{model_size}.pt"
    if local_pt.exists():
        return whisper.load_model(str(local_pt))

    try:
        _download_model_file(model_size, local_pt)
    except Exception as e:
        raise RuntimeError(
            "Failed to download Whisper model with TLS verification. "
            "If your network uses SSL inspection, set NOTEAGENT_CA_BUNDLE "
            "(or SSL_CERT_FILE/REQUESTS_CA_BUNDLE) to your corporate CA bundle path. "
            f"Original error: {e}"
        ) from e

    return whisper.load_model(str(local_pt))


def transcribe_file(
    audio_path: Path,
    model: Optional[whisper.Whisper] = None,
    model_size: str = "base.en",
    language: Optional[str] = "en",
    quality: str = "balanced",
) -> Transcript:
    """Transcribe an audio file (post-recording batch mode)."""
    if model is None:
        model = load_model(model_size)

    result = model.transcribe(str(audio_path), **_build_transcribe_options(language, quality))

    segments = []
    for seg in result["segments"]:
        if not seg.get("text", "").strip():
            continue
        if _is_hallucination(seg["text"]):
            continue
        segments.append(
            TranscriptSegment(
                start=seg["start"],
                end=seg["end"],
                text=seg["text"],
            )
        )

    return Transcript(
        segments=segments,
        language=result.get("language", language or "unknown"),
        model=model_size,
    )


class LiveTranscriber:
    """Processes audio chunks in near-real-time for live transcription."""

    def __init__(
        self,
        model_size: str = "base.en",
        language: str = "en",
        sample_rate: int = 16000,
        chunk_duration: float = 5.0,
    ) -> None:
        self.model = load_model(model_size)
        self.language = language
        self.sample_rate = sample_rate
        self.chunk_duration = chunk_duration
        self._buffer: list[float] = []
        self._segments: list[TranscriptSegment] = []
        self._time_offset: float = 0.0
        self._silence_seconds: float = 0.0

    @property
    def silence_seconds(self) -> float:
        """Seconds of continuous silence detected."""
        return self._silence_seconds

    def feed(self, samples: list[float]) -> list[TranscriptSegment]:
        """Feed audio samples and return any new transcript segments."""
        self._buffer.extend(samples)
        required = int(self.sample_rate * self.chunk_duration)

        if len(self._buffer) < required:
            return []

        chunk = np.array(self._buffer[:required], dtype=np.float32)
        self._buffer = self._buffer[required:]

        result = self.model.transcribe(
            chunk,
            language=self.language,
            fp16=False,
            no_speech_threshold=0.6,
        )

        new_segments = []
        for seg in result["segments"]:
            if not seg.get("text", "").strip():
                continue
            if _is_hallucination(seg["text"]):
                continue
            segment = TranscriptSegment(
                start=self._time_offset + seg["start"],
                end=self._time_offset + min(seg["end"], self.chunk_duration),
                text=seg["text"],
            )
            new_segments.append(segment)
            self._segments.append(segment)

        if not new_segments:
            self._silence_seconds += self.chunk_duration
        else:
            self._silence_seconds = 0.0

        self._time_offset += self.chunk_duration
        return new_segments

    def get_transcript(self) -> Transcript:
        """Return the accumulated transcript so far."""
        return Transcript(
            segments=list(self._segments),
            language=self.language,
        )


def transcribe_meeting(
    mic_path: Path,
    system_path: Path,
    model: Optional[whisper.Whisper] = None,
    model_size: str = "base.en",
    language: str = "en",
) -> Transcript:
    """Transcribe a dual-channel meeting recording.

    Transcribes mic and system audio separately, labels speakers,
    then merges segments sorted by start time.
    """
    if model is None:
        model = load_model(model_size)

    mic_transcript = transcribe_file(mic_path, model=model, model_size=model_size, language=language)
    sys_transcript = transcribe_file(system_path, model=model, model_size=model_size, language=language)

    for seg in mic_transcript.segments:
        seg.speaker = "You"
    for seg in sys_transcript.segments:
        seg.speaker = "Remote"

    merged = sorted(
        mic_transcript.segments + sys_transcript.segments,
        key=lambda s: s.start,
    )

    return Transcript(
        segments=merged,
        language=language,
        model=model_size,
    )


class MeetingLiveTranscriber:
    """Dual-channel live transcriber for meeting mode."""

    def __init__(
        self,
        model_size: str = "base.en",
        language: str = "en",
        sample_rate: int = 16000,
        chunk_duration: float = 5.0,
    ) -> None:
        self._mic = LiveTranscriber(
            model_size=model_size,
            language=language,
            sample_rate=sample_rate,
            chunk_duration=chunk_duration,
        )
        self._system = LiveTranscriber(
            model_size=model_size,
            language=language,
            sample_rate=sample_rate,
            chunk_duration=chunk_duration,
        )

    @property
    def silence_seconds(self) -> float:
        """Seconds of continuous silence across both channels."""
        return min(self._mic.silence_seconds, self._system.silence_seconds)

    def feed_mic(self, samples: list[float]) -> list[TranscriptSegment]:
        """Feed mic audio samples."""
        segs = self._mic.feed(samples)
        for s in segs:
            s.speaker = "You"
        return segs

    def feed_system(self, samples: list[float]) -> list[TranscriptSegment]:
        """Feed system audio samples."""
        segs = self._system.feed(samples)
        for s in segs:
            s.speaker = "Remote"
        return segs

    def get_transcript(self) -> Transcript:
        """Return merged transcript from both channels."""
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
        return Transcript(segments=merged, language=mic_t.language)
