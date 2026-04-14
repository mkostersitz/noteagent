"""Tests for data models."""

from noteagent.models import AppConfig, Session, SessionMetadata, Transcript, TranscriptSegment
from pathlib import Path
from datetime import datetime


def test_transcript_segment():
    seg = TranscriptSegment(start=0.0, end=1.5, text="Hello world")
    assert seg.start == 0.0
    assert seg.end == 1.5
    assert seg.text == "Hello world"
    assert seg.confidence == 1.0


def test_transcript_full_text():
    transcript = Transcript(segments=[
        TranscriptSegment(start=0.0, end=1.0, text="Hello"),
        TranscriptSegment(start=1.0, end=2.0, text="world"),
    ])
    assert transcript.full_text == "Hello world"
    assert transcript.duration == 2.0


def test_transcript_empty():
    transcript = Transcript()
    assert transcript.full_text == ""
    assert transcript.duration == 0.0


def test_session_paths(tmp_path: Path):
    metadata = SessionMetadata(session_id="2026-03-13_14-30-00")
    session = Session(metadata=metadata, path=tmp_path / "test-session")
    assert session.audio_path == tmp_path / "test-session" / "audio.wav"
    assert session.transcript_path == tmp_path / "test-session" / "transcript.json"
    assert session.summary_path == tmp_path / "test-session" / "summary.md"
    assert session.metadata_path == tmp_path / "test-session" / "metadata.json"


def test_app_config_defaults():
    config = AppConfig()
    assert config.default_device == "BlackHole 2ch"
    assert config.sample_rate == 16000
    assert config.whisper_model == "base.en"
