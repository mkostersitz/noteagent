"""Tests for LLM summarization functionality."""

import subprocess
from unittest.mock import Mock, patch

import pytest

from noteagent.models import Transcript, TranscriptSegment
from noteagent.summary import _build_prompt, _summarize_copilot, summarize, SUMMARY_PROMPTS


@pytest.fixture
def sample_transcript():
    """Create a sample transcript for testing."""
    return Transcript(
        segments=[
            TranscriptSegment(start=0.0, end=2.0, text="Hello everyone"),
            TranscriptSegment(start=2.0, end=4.0, text="Today we'll discuss the project roadmap"),
            TranscriptSegment(start=4.0, end=6.0, text="First item is the authentication system"),
        ],
        language="en",
        model="base.en",
    )


def test_build_prompt_general_style(sample_transcript):
    """Test prompt building with general style."""
    prompt = _build_prompt(sample_transcript, "general")
    
    assert SUMMARY_PROMPTS["general"] in prompt
    assert "Hello everyone" in prompt
    assert "Today we'll discuss the project roadmap" in prompt
    assert "First item is the authentication system" in prompt


def test_build_prompt_meeting_style(sample_transcript):
    """Test prompt building with meeting style."""
    prompt = _build_prompt(sample_transcript, "meeting")
    
    assert SUMMARY_PROMPTS["meeting"] in prompt
    assert "Attendees" in prompt or "meeting" in prompt.lower()
    assert sample_transcript.full_text in prompt


def test_build_prompt_lecture_style(sample_transcript):
    """Test prompt building with lecture style."""
    prompt = _build_prompt(sample_transcript, "lecture")
    
    assert SUMMARY_PROMPTS["lecture"] in prompt
    assert "topic" in prompt.lower() or "concepts" in prompt.lower()


def test_build_prompt_truncates_long_transcript():
    """Test that very long transcripts are truncated."""
    # Create a very long transcript
    long_text = "word " * 10000  # 50k+ characters
    long_transcript = Transcript(
        segments=[TranscriptSegment(start=0.0, end=100.0, text=long_text)],
        language="en",
        model="base.en",
    )
    
    prompt = _build_prompt(long_transcript, "general")
    
    assert len(prompt) <= 30100  # 30K limit + some overhead for prompt
    assert "[... transcript truncated ...]" in prompt


def test_build_prompt_unknown_style_defaults_to_general(sample_transcript):
    """Test that unknown style falls back to general."""
    prompt = _build_prompt(sample_transcript, "unknown-style")
    
    assert SUMMARY_PROMPTS["general"] in prompt


@patch("noteagent.summary.subprocess.run")
def test_summarize_copilot_success(mock_run):
    """Test successful summarization with Copilot."""
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = "This is a test summary\n\nTotal usage est: $0.01"
    mock_result.stderr = ""
    mock_run.return_value = mock_result
    
    result = _summarize_copilot("Test prompt")
    
    assert result == "This is a test summary"
    mock_run.assert_called_once()
    
    # Verify subprocess call arguments
    call_args = mock_run.call_args[0][0]
    assert call_args[0] == "gh"
    assert call_args[1] == "copilot"
    assert "-p" in call_args
    assert "Test prompt" in call_args


@patch("noteagent.summary.subprocess.run")
def test_summarize_copilot_timeout(mock_run):
    """Test timeout handling."""
    mock_run.side_effect = subprocess.TimeoutExpired("gh", 120)
    
    result = _summarize_copilot("Test prompt")
    
    assert "[Summary generation timed out]" in result


@patch("noteagent.summary.subprocess.run")
def test_summarize_copilot_not_found(mock_run):
    """Test handling when gh CLI is not installed."""
    mock_run.side_effect = FileNotFoundError()
    
    result = _summarize_copilot("Test prompt")
    
    assert "GitHub Copilot CLI not found" in result
    assert "gh extension install" in result


@patch("noteagent.summary.subprocess.run")
def test_summarize_copilot_error(mock_run):
    """Test handling of subprocess errors."""
    mock_result = Mock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "Error: authentication required"
    mock_run.return_value = mock_result
    
    result = _summarize_copilot("Test prompt")
    
    assert "[Summary generation failed:" in result
    assert "authentication required" in result


@patch("noteagent.summary._summarize_copilot")
def test_summarize_general_style(mock_copilot, sample_transcript):
    """Test summarize() with general style."""
    mock_copilot.return_value = "Test summary"
    
    result = summarize(sample_transcript, style="general", provider="copilot")
    
    assert result == "Test summary"
    mock_copilot.assert_called_once()
    
    # Check prompt contains expected text
    call_args = mock_copilot.call_args[0][0]
    assert SUMMARY_PROMPTS["general"] in call_args
    assert sample_transcript.full_text in call_args


@patch("noteagent.summary._summarize_copilot")
def test_summarize_meeting_style(mock_copilot, sample_transcript):
    """Test summarize() with meeting style."""
    mock_copilot.return_value = "Meeting notes"
    
    result = summarize(sample_transcript, style="meeting", provider="copilot")
    
    assert result == "Meeting notes"
    call_args = mock_copilot.call_args[0][0]
    assert "Attendees" in call_args or "meeting" in call_args.lower()


@patch("noteagent.summary._summarize_copilot")
def test_summarize_lecture_style(mock_copilot, sample_transcript):
    """Test summarize() with lecture style."""
    mock_copilot.return_value = "Lecture summary"
    
    result = summarize(sample_transcript, style="lecture", provider="copilot")
    
    assert result == "Lecture summary"
    call_args = mock_copilot.call_args[0][0]
    assert "lecture" in call_args.lower()


def test_summarize_unknown_provider(sample_transcript):
    """Test that unknown provider raises error."""
    with pytest.raises(ValueError, match="Unknown summary provider"):
        summarize(sample_transcript, provider="unknown-provider")


@patch("noteagent.summary.subprocess.run")
def test_summarize_strips_usage_footer(mock_run):
    """Test that usage statistics footer is removed."""
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = """This is the actual summary content.

It has multiple lines.

Total usage est: $0.05
Tokens: 1500"""
    mock_run.return_value = mock_result
    
    result = _summarize_copilot("Test prompt")
    
    assert "This is the actual summary content" in result
    assert "It has multiple lines" in result
    assert "Total usage est" not in result
    assert "Tokens:" not in result


@patch("noteagent.summary.subprocess.run")
def test_summarize_subprocess_timeout_value(mock_run):
    """Test that subprocess has proper timeout."""
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = "Summary"
    mock_run.return_value = mock_result
    
    _summarize_copilot("Test prompt")
    
    # Verify timeout is set to 120 seconds
    call_kwargs = mock_run.call_args[1]
    assert call_kwargs["timeout"] == 120


@patch("noteagent.summary.subprocess.run")
def test_summarize_subprocess_captures_output(mock_run):
    """Test that subprocess captures stdout and stderr."""
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = "Summary"
    mock_run.return_value = mock_result
    
    _summarize_copilot("Test prompt")
    
    call_kwargs = mock_run.call_args[1]
    assert call_kwargs["capture_output"] is True
    assert call_kwargs["text"] is True


def test_summary_prompts_defined():
    """Test that all expected summary prompts are defined."""
    assert "general" in SUMMARY_PROMPTS
    assert "meeting" in SUMMARY_PROMPTS
    assert "lecture" in SUMMARY_PROMPTS
    
    # Check prompts are non-empty
    assert len(SUMMARY_PROMPTS["general"]) > 0
    assert len(SUMMARY_PROMPTS["meeting"]) > 0
    assert len(SUMMARY_PROMPTS["lecture"]) > 0


def test_summary_prompt_contains_key_elements():
    """Test that summary prompts contain expected elements."""
    # Meeting prompt should mention attendees, decisions, action items
    meeting_prompt = SUMMARY_PROMPTS["meeting"]
    assert "attendee" in meeting_prompt.lower() or "action" in meeting_prompt.lower()
    
    # Lecture prompt should mention topics, concepts
    lecture_prompt = SUMMARY_PROMPTS["lecture"]
    assert "topic" in lecture_prompt.lower() or "concept" in lecture_prompt.lower()
