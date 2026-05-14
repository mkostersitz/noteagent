"""Tests for the thin Python wrapper in `noteagent.transcript`.

The Rust extension (`noteagent_audio`) is mocked so these tests don't need
a real ggml model on disk and don't invoke whisper.cpp.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from noteagent import transcript as wrapper
from noteagent.models import Transcript, TranscriptSegment


def test_to_segment_converts_dict_to_pydantic():
    seg = wrapper._to_segment(
        {
            "start": 1.0,
            "end": 2.5,
            "text": " hello ",
            "confidence": 0.9,
            "speaker": "You",
        }
    )
    assert isinstance(seg, TranscriptSegment)
    assert seg.start == 1.0
    assert seg.end == 2.5
    assert seg.text == " hello "  # wrapper preserves whitespace; full_text() trims
    assert seg.confidence == 0.9
    assert seg.speaker == "You"


def test_to_segment_uses_defaults_for_missing_fields():
    seg = wrapper._to_segment({"start": 0.0, "end": 1.0, "text": "x"})
    assert seg.confidence == 1.0
    assert seg.speaker == ""


def test_to_transcript_wraps_segments_and_metadata():
    t = wrapper._to_transcript(
        {
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "a"},
                {"start": 1.0, "end": 2.0, "text": "b"},
            ],
            "language": "de",
            "model": "small",
        }
    )
    assert isinstance(t, Transcript)
    assert len(t.segments) == 2
    assert t.language == "de"
    assert t.model == "small"


def test_to_transcript_handles_empty_dict():
    t = wrapper._to_transcript({})
    assert t.segments == []
    assert t.language == "en"
    assert t.model == "base.en"


def test_model_path_uses_ggml_naming(tmp_path, monkeypatch):
    monkeypatch.setattr(wrapper, "_MODEL_DIR", tmp_path)
    assert wrapper._model_path("base.en") == tmp_path / "ggml-base.en.bin"


def test_load_model_raises_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(wrapper, "_MODEL_DIR", tmp_path)
    with pytest.raises(RuntimeError, match="Whisper model not found"):
        wrapper.load_model("nonexistent")


def test_load_model_returns_rust_transcriber_when_present(tmp_path, monkeypatch):
    """`load_model` constructs `noteagent_audio.WhisperTranscriber` with the resolved path."""
    monkeypatch.setattr(wrapper, "_MODEL_DIR", tmp_path)
    model_file = tmp_path / "ggml-tiny.en.bin"
    model_file.write_bytes(b"stub")

    fake_module = MagicMock()
    sentinel = MagicMock(name="WhisperTranscriberInstance")
    fake_module.WhisperTranscriber.return_value = sentinel
    with patch.dict("sys.modules", {"noteagent_audio": fake_module}):
        result = wrapper.load_model("tiny.en")

    assert result is sentinel
    fake_module.WhisperTranscriber.assert_called_once_with(str(model_file), "tiny.en")


def test_transcribe_file_round_trips_through_wrapper():
    """`transcribe_file` delegates to the loaded model and wraps the dict result."""
    fake_model = MagicMock()
    fake_model.transcribe_file.return_value = {
        "segments": [{"start": 0.0, "end": 1.2, "text": "hi"}],
        "language": "en",
        "model": "tiny.en",
    }

    transcript = wrapper.transcribe_file(
        Path("/dev/null"),
        model=fake_model,
        model_size="tiny.en",
        language="en",
        quality="fast",
    )

    fake_model.transcribe_file.assert_called_once_with(
        "/dev/null", language="en", quality="fast"
    )
    assert isinstance(transcript, Transcript)
    assert len(transcript.segments) == 1
    assert transcript.segments[0].text == "hi"
    # Wrapper sets `.model` from the requested model_size, not the Rust dict.
    assert transcript.model == "tiny.en"


def test_transcribe_meeting_labels_speakers_and_merges_in_order():
    """Meeting mode labels mic vs system and merges by start time."""
    fake_model = MagicMock()
    # First call (mic) returns "You" content at t=1.0
    # Second call (system) returns "Remote" content at t=0.5
    fake_model.transcribe_file.side_effect = [
        {
            "segments": [{"start": 1.0, "end": 2.0, "text": "from mic"}],
            "language": "en",
            "model": "tiny.en",
        },
        {
            "segments": [{"start": 0.5, "end": 1.5, "text": "from system"}],
            "language": "en",
            "model": "tiny.en",
        },
    ]

    merged = wrapper.transcribe_meeting(
        Path("/dev/null"),
        Path("/dev/null"),
        model=fake_model,
        model_size="tiny.en",
        language="en",
    )

    assert [s.start for s in merged.segments] == [0.5, 1.0]
    assert merged.segments[0].speaker == "Remote"
    assert merged.segments[1].speaker == "You"
