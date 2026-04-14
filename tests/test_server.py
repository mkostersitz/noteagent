"""Tests for server media preview resolution."""

from pathlib import Path

from noteagent.models import Session, SessionMetadata
from noteagent.server import _resolve_session_preview, _resolve_session_preview_path


def _make_session(tmp_path: Path, recording_mode: str = "single", source_file: str | None = None) -> Session:
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    return Session(
        metadata=SessionMetadata(
            session_id="2026-04-08_15-22-53",
            recording_mode=recording_mode,
            source_file=source_file,
        ),
        path=session_dir,
    )


def test_resolve_session_preview_for_recorded_audio(tmp_path: Path):
    session = _make_session(tmp_path)
    session.audio_path.write_bytes(b"RIFF")

    preview = _resolve_session_preview(session.metadata.session_id, session)

    assert preview["available"] is True
    assert preview["kind"] == "audio"
    assert preview["url"].endswith("/media")


def test_resolve_session_preview_for_imported_mp4(tmp_path: Path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"video")
    session = _make_session(tmp_path, recording_mode="import", source_file=str(source))

    preview = _resolve_session_preview(session.metadata.session_id, session)

    assert preview["available"] is True
    assert preview["kind"] == "video"
    assert preview["filename"] == "preview.mp4"
    assert preview["source"] == "session-preview"


def test_resolve_session_preview_prefers_session_preview_asset(tmp_path: Path):
    session = _make_session(tmp_path, recording_mode="import", source_file=str(tmp_path / "missing.mp4"))
    preview_file = session.path / "preview.mp4"
    preview_file.write_bytes(b"video")

    preview = _resolve_session_preview(session.metadata.session_id, session)
    preview_path, mime_type = _resolve_session_preview_path(session)

    assert preview["available"] is True
    assert preview["source"] == "session-preview"
    assert preview_path == preview_file
    assert mime_type == "video/mp4"


def test_resolve_session_preview_for_meeting_without_preview(tmp_path: Path):
    session = _make_session(tmp_path, recording_mode="meeting")

    preview = _resolve_session_preview(session.metadata.session_id, session)

    assert preview["available"] is False
    assert "combined playback preview" in preview["message"]


def test_resolve_session_preview_for_meeting_preview_asset(tmp_path: Path):
    session = _make_session(tmp_path, recording_mode="meeting")
    preview_file = session.path / "preview.wav"
    preview_file.write_bytes(b"RIFF")

    preview = _resolve_session_preview(session.metadata.session_id, session)
    preview_path, mime_type = _resolve_session_preview_path(session)

    assert preview["available"] is True
    assert preview["source"] == "session-preview"
    assert preview_path == preview_file
    assert mime_type == "audio/wav"
