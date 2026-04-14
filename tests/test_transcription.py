"""Tests for transcription functionality."""

from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pytest

from noteagent.models import Transcript, TranscriptSegment
from noteagent.transcript import (
    _build_transcribe_options,
    _is_hallucination,
    load_model,
    transcribe_file,
    LiveTranscriber,
)


@pytest.fixture
def mock_whisper_model():
    """Create a mock Whisper model."""
    model = Mock()
    model.transcribe = Mock(return_value={
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "Hello world"},
            {"start": 2.0, "end": 4.0, "text": "This is a test"},
        ],
        "language": "en",
    })
    return model


@pytest.fixture
def test_audio_file(tmp_path):
    """Create a test audio file."""
    audio_path = tmp_path / "test.wav"
    # Create a minimal WAV file (not valid but for testing path handling)
    audio_path.write_bytes(b"RIFF" + b"\x00" * 40 + b"WAVE")
    return audio_path


def test_is_hallucination():
    """Test hallucination detection."""
    assert _is_hallucination("thank you")
    assert _is_hallucination("Thanks for watching!")
    assert _is_hallucination("  goodbye  ")
    assert _is_hallucination("")
    
    assert not _is_hallucination("Hello world")
    assert not _is_hallucination("This is real content")


def test_build_transcribe_options():
    """Test transcription options builder."""
    # Fast quality
    opts = _build_transcribe_options("en", "fast")
    assert opts["beam_size"] == 1
    assert opts["best_of"] == 1
    assert opts["temperature"] == 0.0
    assert opts["fp16"] is False
    assert opts["language"] == "en"
    
    # Balanced quality
    opts = _build_transcribe_options("en", "balanced")
    assert opts["beam_size"] == 5
    assert opts["best_of"] == 5
    
    # Accurate quality
    opts = _build_transcribe_options("en", "accurate")
    assert opts["beam_size"] == 8
    assert opts["best_of"] == 8
    
    # No language specified
    opts = _build_transcribe_options(None, "fast")
    assert "language" not in opts


@patch("noteagent.transcript.whisper.load_model")
def test_load_model_from_local(mock_load, tmp_path):
    """Test model loading from local file."""
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    model_file = model_dir / "base.en.pt"
    model_file.write_bytes(b"fake model")
    
    with patch("noteagent.transcript._MODEL_DIR", model_dir):
        mock_model = Mock()
        mock_load.return_value = mock_model
        
        result = load_model("base.en")
        
        assert result == mock_model
        mock_load.assert_called_once_with(str(model_file))


def test_transcribe_file_filters_hallucinations(test_audio_file, mock_whisper_model):
    """Test that transcribe_file filters out hallucinations."""
    # Add hallucination to segments
    mock_whisper_model.transcribe.return_value = {
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "Real content"},
            {"start": 2.0, "end": 4.0, "text": "thank you"},  # Hallucination
            {"start": 4.0, "end": 6.0, "text": "More real content"},
        ],
        "language": "en",
    }
    
    with patch("noteagent.transcript.load_model", return_value=mock_whisper_model):
        transcript = transcribe_file(test_audio_file, model=mock_whisper_model)
    
    # Should have 2 segments (hallucination filtered)
    assert len(transcript.segments) == 2
    assert transcript.segments[0].text == "Real content"
    assert transcript.segments[1].text == "More real content"


def test_transcribe_file_filters_empty_segments(test_audio_file, mock_whisper_model):
    """Test that empty segments are filtered."""
    mock_whisper_model.transcribe.return_value = {
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "Content"},
            {"start": 2.0, "end": 4.0, "text": "   "},  # Empty
            {"start": 4.0, "end": 6.0, "text": ""},    # Empty
        ],
        "language": "en",
    }
    
    with patch("noteagent.transcript.load_model", return_value=mock_whisper_model):
        transcript = transcribe_file(test_audio_file, model=mock_whisper_model)
    
    assert len(transcript.segments) == 1
    assert transcript.segments[0].text == "Content"


def test_transcribe_file_sets_metadata(test_audio_file, mock_whisper_model):
    """Test that transcript metadata is set correctly."""
    with patch("noteagent.transcript.load_model", return_value=mock_whisper_model):
        transcript = transcribe_file(test_audio_file, model=mock_whisper_model, model_size="base.en", language="en")
    
    assert transcript.language == "en"
    assert transcript.model == "base.en"
    assert len(transcript.segments) == 2


def test_live_transcriber_initialization():
    """Test LiveTranscriber initialization."""
    mock_model = Mock()
    
    with patch("noteagent.transcript.load_model", return_value=mock_model):
        transcriber = LiveTranscriber(
            model_size="base.en",
            language="en",
            sample_rate=16000,
            chunk_duration=5.0,
        )
    
    assert transcriber.model == mock_model
    assert transcriber.language == "en"
    assert transcriber.sample_rate == 16000
    assert transcriber.chunk_duration == 5.0
    assert transcriber.silence_seconds == 0.0


def test_live_transcriber_feed_insufficient_samples():
    """Test that LiveTranscriber doesn't transcribe with insufficient samples."""
    mock_model = Mock()
    
    with patch("noteagent.transcript.load_model", return_value=mock_model):
        transcriber = LiveTranscriber(sample_rate=16000, chunk_duration=5.0)
        
        # Feed less than required samples (need 16000 * 5 = 80000)
        samples = [0.0] * 10000
        segments = transcriber.feed(samples)
        
        assert segments == []
        assert len(transcriber._buffer) == 10000


def test_live_transcriber_feed_processes_chunk():
    """Test that LiveTranscriber processes full chunk."""
    mock_model = Mock()
    mock_model.transcribe = Mock(return_value={
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "Live transcript"},
        ],
    })
    
    with patch("noteagent.transcript.load_model", return_value=mock_model):
        transcriber = LiveTranscriber(sample_rate=16000, chunk_duration=5.0)
        
        # Feed exactly required samples
        samples = [0.0] * 80000  # 16000 * 5
        segments = transcriber.feed(samples)
        
        assert len(segments) == 1
        assert segments[0].text == "Live transcript"
        assert segments[0].start == 0.0
        assert segments[0].end == 2.0
        
        # Buffer should be cleared
        assert len(transcriber._buffer) == 0


def test_live_transcriber_tracks_silence():
    """Test that LiveTranscriber tracks silence duration."""
    mock_model = Mock()
    mock_model.transcribe = Mock(return_value={"segments": []})  # No segments = silence
    
    with patch("noteagent.transcript.load_model", return_value=mock_model):
        transcriber = LiveTranscriber(sample_rate=16000, chunk_duration=5.0)
        
        samples = [0.0] * 80000
        transcriber.feed(samples)
        
        assert transcriber.silence_seconds == 5.0
        
        # Feed again - silence should accumulate
        transcriber.feed(samples)
        assert transcriber.silence_seconds == 10.0


def test_live_transcriber_resets_silence_on_speech():
    """Test that silence counter resets when speech detected."""
    mock_model = Mock()
    
    with patch("noteagent.transcript.load_model", return_value=mock_model):
        transcriber = LiveTranscriber(sample_rate=16000, chunk_duration=5.0)
        
        # First feed: silence
        mock_model.transcribe.return_value = {"segments": []}
        samples = [0.0] * 80000
        transcriber.feed(samples)
        assert transcriber.silence_seconds == 5.0
        
        # Second feed: speech detected
        mock_model.transcribe.return_value = {
            "segments": [{"start": 0.0, "end": 2.0, "text": "Speech"}],
        }
        transcriber.feed(samples)
        assert transcriber.silence_seconds == 0.0  # Reset


def test_live_transcriber_get_transcript():
    """Test getting accumulated transcript."""
    mock_model = Mock()
    mock_model.transcribe = Mock(return_value={
        "segments": [{"start": 0.0, "end": 2.0, "text": "Part 1"}],
    })
    
    with patch("noteagent.transcript.load_model", return_value=mock_model):
        transcriber = LiveTranscriber(sample_rate=16000, chunk_duration=5.0)
        
        samples = [0.0] * 80000
        transcriber.feed(samples)
        
        # Add another segment
        mock_model.transcribe.return_value = {
            "segments": [{"start": 0.0, "end": 2.0, "text": "Part 2"}],
        }
        transcriber.feed(samples)
        
        transcript = transcriber.get_transcript()
        assert len(transcript.segments) == 2
        assert transcript.segments[0].text == "Part 1"
        assert transcript.segments[1].text == "Part 2"


def test_transcribe_file_uses_quality_preset(test_audio_file, mock_whisper_model):
    """Test that quality preset is applied."""
    with patch("noteagent.transcript.load_model", return_value=mock_whisper_model):
        transcribe_file(test_audio_file, model=mock_whisper_model, quality="accurate")
        
        # Check that transcribe was called with accurate preset
        call_kwargs = mock_whisper_model.transcribe.call_args[1]
        assert call_kwargs["beam_size"] == 8
        assert call_kwargs["best_of"] == 8
