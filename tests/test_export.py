"""Tests for export functionality."""

import json
from pathlib import Path

from noteagent.models import Session, SessionMetadata, Transcript, TranscriptSegment
from noteagent.export import (
    export_markdown,
    export_text,
    export_json,
    export_srt,
    export_vtt,
    export_session,
)


def _make_session(tmp_path: Path) -> Session:
    session_dir = tmp_path / "test-session"
    session_dir.mkdir()
    return Session(
        metadata=SessionMetadata(session_id="2026-03-13_14-30-00", device_name="Test Device"),
        path=session_dir,
        transcript=Transcript(segments=[
            TranscriptSegment(start=0.0, end=1.5, text="Hello world"),
            TranscriptSegment(start=1.5, end=3.0, text="This is a test"),
        ]),
        summary="Test summary content.",
    )


def test_export_markdown(tmp_path: Path):
    session = _make_session(tmp_path)
    path = export_markdown(session)
    content = path.read_text()
    assert "Hello world" in content
    assert "Test summary" in content


def test_export_text(tmp_path: Path):
    session = _make_session(tmp_path)
    path = export_text(session)
    content = path.read_text()
    assert "Hello world" in content


def test_export_json(tmp_path: Path):
    session = _make_session(tmp_path)
    path = export_json(session)
    data = json.loads(path.read_text())
    assert data["session_id"] == "2026-03-13_14-30-00"
    assert "transcript" in data


def test_export_srt(tmp_path: Path):
    session = _make_session(tmp_path)
    path = export_srt(session)
    content = path.read_text()
    assert "-->" in content
    assert "Hello world" in content


def test_export_vtt(tmp_path: Path):
    session = _make_session(tmp_path)
    path = export_vtt(session)
    content = path.read_text()
    assert "WEBVTT" in content
    assert "Hello world" in content


def test_export_session_format(tmp_path: Path):
    session = _make_session(tmp_path)
    path = export_session(session, fmt="txt")
    assert path.exists()
