"""LLM-powered summarization via GitHub Copilot."""

from __future__ import annotations

import subprocess
from typing import Optional

from noteagent.models import Transcript

SUMMARY_PROMPTS = {
    "general": "Summarize the following transcript concisely, highlighting key points:",
    "meeting": (
        "Summarize this meeting transcript. Include:\n"
        "- Attendees mentioned\n"
        "- Key discussion points\n"
        "- Decisions made\n"
        "- Action items with owners\n"
    ),
    "lecture": (
        "Summarize this lecture transcript. Include:\n"
        "- Main topic and subtopics\n"
        "- Key concepts explained\n"
        "- Important definitions\n"
        "- Questions raised\n"
    ),
}


def summarize(
    transcript: Transcript,
    style: str = "general",
    provider: str = "copilot",
) -> str:
    """Generate a summary from a transcript."""
    prompt = _build_prompt(transcript, style)

    if provider == "copilot":
        return _summarize_copilot(prompt)
    else:
        raise ValueError(f"Unknown summary provider: {provider}")


def _build_prompt(transcript: Transcript, style: str) -> str:
    """Build the LLM prompt from transcript and style."""
    system_prompt = SUMMARY_PROMPTS.get(style, SUMMARY_PROMPTS["general"])
    text = transcript.full_text

    max_chars = 30000
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[... transcript truncated ...]"

    return f"{system_prompt}\n\n---\n\n{text}"


def _summarize_copilot(prompt: str) -> str:
    """Use GitHub Copilot CLI to generate a summary."""
    try:
        result = subprocess.run(
            ["gh", "copilot", "--", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0 and result.stdout.strip():
            # Strip the usage stats footer that gh copilot appends
            output = result.stdout.strip()
            # The footer starts with a blank line then "Total usage est:"
            parts = output.split("\nTotal usage est:")
            return parts[0].strip()
        return f"[Summary generation failed: {result.stderr.strip()}]"
    except FileNotFoundError:
        return (
            "[GitHub Copilot CLI not found. Install with: gh extension install github/gh-copilot]\n\n"
            "Transcript preview:\n" + prompt[:500]
        )
    except subprocess.TimeoutExpired:
        return "[Summary generation timed out]"
