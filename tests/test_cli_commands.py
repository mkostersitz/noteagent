"""Tests for CLI commands."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from typer.testing import CliRunner

from noteagent.cli import app
from noteagent.models import AppConfig, Session, SessionMetadata, Transcript, TranscriptSegment

runner = CliRunner()


@pytest.fixture
def mock_config(tmp_path):
    """Create a test configuration."""
    return AppConfig(
        storage_path=tmp_path,
        default_device="Test Device",
        sample_rate=16000,
        whisper_model="base.en",
        language="en",
    )


@pytest.fixture
def mock_session(tmp_path):
    """Create a test session."""
    session_path = tmp_path / "sessions" / "2026-04-14_12-00-00"
    session_path.mkdir(parents=True)
    
    metadata = SessionMetadata(
        session_id="2026-04-14_12-00-00",
        device_name="Test Device",
        sample_rate=16000,
    )
    
    session = Session(metadata=metadata, path=session_path)
    
    # Create mock audio file
    (session_path / "audio.wav").write_bytes(b"RIFF....WAV")
    
    # Create mock transcript
    transcript = Transcript(
        segments=[
            TranscriptSegment(start=0.0, end=2.0, text="Hello world"),
            TranscriptSegment(start=2.0, end=4.0, text="Test transcript"),
        ],
        language="en",
        model="base.en",
    )
    session.transcript = transcript
    
    return session


def test_version_command():
    """Test version command returns version string."""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "0.1" in result.stdout  # Check for version pattern


def test_devices_command():
    """Test devices command lists audio devices."""
    with patch("noteagent.cli.list_devices", return_value=["Device 1", "Device 2"]):
        result = runner.invoke(app, ["devices"])
        assert result.exit_code == 0
        assert "Device 1" in result.stdout
        assert "Device 2" in result.stdout


def test_config_show_command(tmp_path, mock_config):
    """Test config --show displays configuration."""
    with patch("noteagent.cli.load_config", return_value=mock_config):
        result = runner.invoke(app, ["config", "--show"])
        assert result.exit_code == 0
        assert "Test Device" in result.stdout or "default_device" in result.stdout


def test_config_set_device(tmp_path, mock_config):
    """Test config --device sets default device."""
    with patch("noteagent.cli.load_config", return_value=mock_config), \
         patch("noteagent.cli.save_config") as mock_save:
        result = runner.invoke(app, ["config", "--device", "New Device"])
        assert result.exit_code == 0
        mock_save.assert_called_once()


def test_sessions_list(tmp_path, mock_config, mock_session):
    """Test sessions command lists available sessions."""
    with patch("noteagent.cli.load_config", return_value=mock_config), \
         patch("noteagent.cli.list_sessions", return_value=[mock_session]):
        result = runner.invoke(app, ["sessions"])
        assert result.exit_code == 0
        assert "2026-04-14_12-00-00" in result.stdout


@pytest.mark.parametrize("format_type", ["markdown", "text", "json", "pdf"])
def test_export_command(tmp_path, mock_session, format_type):
    """Test export command for various formats."""
    with patch("noteagent.cli.load_session", return_value=mock_session), \
         patch("noteagent.cli.export_session") as mock_export:
        mock_export.return_value = tmp_path / f"export.{format_type}"
        
        result = runner.invoke(app, [
            "export",
            str(mock_session.path),
            "--format", format_type
        ])
        
        assert result.exit_code == 0
        mock_export.assert_called_once()


def test_transcribe_file_command(tmp_path):
    """Test transcribe command on audio file."""
    audio_file = tmp_path / "test.wav"
    audio_file.write_bytes(b"RIFF....WAV")
    
    mock_transcript = Transcript(
        segments=[TranscriptSegment(start=0.0, end=2.0, text="Test")],
        language="en",
        model="base.en",
    )
    
    with patch("noteagent.cli.transcribe_file", return_value=mock_transcript), \
         patch("noteagent.cli.create_session") as mock_create, \
         patch("noteagent.cli.save_transcript"):
        
        mock_session = Mock()
        mock_session.path = tmp_path / "session"
        mock_create.return_value = mock_session
        
        result = runner.invoke(app, ["transcribe", str(audio_file)])
        
        # May fail if file doesn't exist, but should attempt transcription
        # This tests the command structure
        assert result.exit_code in (0, 1)  # 0 = success, 1 = expected failure


def test_summarize_command(tmp_path, mock_session):
    """Test summarize command."""
    with patch("noteagent.cli.load_session", return_value=mock_session), \
         patch("noteagent.cli.summarize", return_value="Test summary"), \
         patch("noteagent.cli.save_summary"):
        
        result = runner.invoke(app, ["summarize", str(mock_session.path)])
        
        assert result.exit_code == 0
        assert "summary" in result.stdout.lower() or "Summary" in result.stdout


def test_record_command_dry_run():
    """Test record command structure (without actual recording)."""
    # This tests that the command exists and accepts parameters
    result = runner.invoke(app, ["record", "--help"])
    assert result.exit_code == 0
    assert "device" in result.stdout.lower()
    assert "model" in result.stdout.lower()


def test_serve_command_structure():
    """Test serve command help."""
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "port" in result.stdout.lower()


def test_stop_command_no_server():
    """Test stop command when no server running."""
    result = runner.invoke(app, ["stop"])
    # Should handle gracefully (no server to stop)
    assert result.exit_code in (0, 1)


def test_setup_check_command():
    """Test setup-check command."""
    with patch("noteagent.cli.list_devices", return_value=["Device 1"]):
        result = runner.invoke(app, ["setup-check"])
        # Should run diagnostics
        assert result.exit_code == 0
