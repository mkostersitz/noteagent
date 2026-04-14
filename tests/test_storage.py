"""Tests for storage operations."""

import json
import wave
from pathlib import Path

from noteagent.models import AppConfig, Transcript, TranscriptSegment
from noteagent.storage import create_session, load_session, save_meeting_preview, save_preview_media, save_transcript, save_summary, save_transcript_version


def test_create_session(tmp_path: Path):
    config = AppConfig(storage_path=tmp_path)
    session = create_session(config)
    assert session.path.exists()
    assert session.metadata_path.exists()


def test_save_and_load_transcript(tmp_path: Path):
    config = AppConfig(storage_path=tmp_path)
    session = create_session(config)

    transcript = Transcript(segments=[
        TranscriptSegment(start=0.0, end=1.0, text="Hello"),
        TranscriptSegment(start=1.0, end=2.0, text="world"),
    ])

    save_transcript(session, transcript)
    assert session.transcript_path.exists()

    loaded = load_session(session.path)
    assert loaded.transcript is not None
    assert loaded.transcript.full_text == "Hello world"


def test_save_and_load_summary(tmp_path: Path):
    config = AppConfig(storage_path=tmp_path)
    session = create_session(config)

    save_summary(session, "This is a test summary.")
    assert session.summary_path.exists()

    loaded = load_session(session.path)
    assert loaded.summary == "This is a test summary."


def test_session_override_dir(tmp_path: Path):
    config = AppConfig(storage_path=tmp_path / "default")
    override = tmp_path / "custom"
    session = create_session(config, output_dir=override)
    assert str(override) in str(session.path)


def test_create_session_unique_ids(tmp_path: Path):
    config = AppConfig(storage_path=tmp_path)
    first = create_session(config)
    second = create_session(config)
    assert first.path != second.path
    assert first.metadata.session_id != second.metadata.session_id


def test_create_session_source_file_metadata(tmp_path: Path):
    config = AppConfig(storage_path=tmp_path)
    source = tmp_path / "media" / "sample.mp3"
    session = create_session(config, recording_mode="import", source_file=str(source))
    loaded = load_session(session.path)
    assert loaded.metadata.recording_mode == "import"
    assert loaded.metadata.source_file == str(source)


def test_save_transcript_version(tmp_path: Path):
    config = AppConfig(storage_path=tmp_path)
    session = create_session(config)
    transcript = Transcript(segments=[
        TranscriptSegment(start=0.0, end=1.0, text="hello"),
    ])

    json_path, txt_path = save_transcript_version(session, transcript, model_label="small.en")

    assert json_path.exists()
    assert txt_path.exists()
    assert json_path.name == "transcript.small.en.json"
    assert txt_path.name == "transcript.small.en.txt"
    assert session.transcript_path.exists()


def test_save_preview_media(tmp_path: Path):
    config = AppConfig(storage_path=tmp_path)
    session = create_session(config, recording_mode="import")
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"video")

    preview_path = save_preview_media(session, source)

    assert preview_path is not None
    assert preview_path.exists()
    assert preview_path.name == "preview.mp4"


def test_save_meeting_preview(tmp_path: Path):
    config = AppConfig(storage_path=tmp_path)
    session = create_session(config, recording_mode="meeting")

    for path, sample in [(session.mic_audio_path, 1000), (session.system_audio_path, -1000)]:
        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(int(sample).to_bytes(2, byteorder="little", signed=True) * 8)

    preview_path = save_meeting_preview(session)

    assert preview_path is not None
    assert preview_path.exists()
    assert preview_path.name == "preview.wav"
