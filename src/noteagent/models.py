"""Pydantic data models for NoteAgent."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class TranscriptSegment(BaseModel):
    """A single segment of transcribed text with timing information."""

    start: float = Field(description="Start time in seconds")
    end: float = Field(description="End time in seconds")
    text: str = Field(description="Transcribed text content")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    speaker: str = Field(default="", description="Speaker label (e.g. 'You', 'Remote')")


class Transcript(BaseModel):
    """A complete transcript composed of segments."""

    segments: list[TranscriptSegment] = Field(default_factory=list)
    language: str = "en"
    model: str = "base.en"

    @property
    def full_text(self) -> str:
        parts = []
        for seg in self.segments:
            label = f"[{seg.speaker}] " if seg.speaker else ""
            parts.append(f"{label}{seg.text.strip()}")
        return " ".join(parts)

    @property
    def duration(self) -> float:
        if not self.segments:
            return 0.0
        return self.segments[-1].end


class SessionMetadata(BaseModel):
    """Metadata for a recording session."""

    session_id: str = Field(description="ISO timestamp directory name")
    created_at: datetime = Field(default_factory=datetime.now)
    device_name: str = "default"
    sample_rate: int = 16000
    duration: Optional[float] = None
    summary_style: str = "general"
    tags: list[str] = Field(default_factory=list)
    recording_mode: str = Field(default="single", description="'single', 'meeting', or 'import'")
    system_device_name: Optional[str] = Field(default=None, description="System audio device for meeting mode")
    source_file: Optional[str] = Field(default=None, description="Original imported media file path")


class Session(BaseModel):
    """A complete recording session with all artifacts."""

    metadata: SessionMetadata
    path: Path
    transcript: Optional[Transcript] = None
    summary: Optional[str] = None

    @property
    def audio_path(self) -> Path:
        return self.path / "audio.wav"

    @property
    def mic_audio_path(self) -> Path:
        return self.path / "mic.wav"

    @property
    def system_audio_path(self) -> Path:
        return self.path / "system.wav"

    @property
    def transcript_path(self) -> Path:
        return self.path / "transcript.json"

    @property
    def summary_path(self) -> Path:
        return self.path / "summary.md"

    @property
    def metadata_path(self) -> Path:
        return self.path / "metadata.json"

    def preview_media_path(self) -> Optional[Path]:
        for candidate in sorted(self.path.glob("preview.*")):
            if candidate.is_file():
                return candidate
        return None


class AppConfig(BaseModel):
    """Application configuration."""

    storage_path: Path = Path.home() / "notes" / "noteagent"
    default_device: str = "BlackHole 2ch"
    sample_rate: int = 16000
    channels: int = 1
    whisper_model: str = "base.en"
    language: str = "en"
    summary_provider: str = "copilot"
    summary_style: str = "general"


class AuthToken(BaseModel):
    """Authentication token configuration."""
    
    token: str = Field(description="The authentication token")
    name: str = Field(description="Human-readable name for this token")
    role: str = Field(default="admin", description="Role: 'admin' or 'read-only'")
    created_at: Optional[datetime] = Field(default=None, description="When token was created")
    expires_at: Optional[datetime] = Field(default=None, description="Optional expiration time")


class AuthConfig(BaseModel):
    """Authentication configuration."""
    
    enabled: bool = Field(default=False, description="Enable/disable authentication")
    tokens: list[AuthToken] = Field(default_factory=list, description="List of valid tokens")
    token_header: str = Field(default="Authorization", description="HTTP header for token")
    token_prefix: str = Field(default="Bearer", description="Token prefix (e.g., 'Bearer')")


class RateLimitEndpoint(BaseModel):
    """Rate limit configuration for a specific endpoint."""
    
    path: str = Field(description="Endpoint path pattern")
    limit: str = Field(description="Rate limit (e.g., '10/minute', '100/hour')")


class RateLimitConfig(BaseModel):
    """Rate limiting configuration."""
    
    enabled: bool = Field(default=True, description="Enable/disable rate limiting")
    default_limit: str = Field(default="100/minute", description="Default rate limit")
    endpoints: list[RateLimitEndpoint] = Field(default_factory=list, description="Per-endpoint limits")
    whitelist_ips: list[str] = Field(default_factory=lambda: ["127.0.0.1", "::1"], description="Exempt IPs")


class AppConfigExtended(AppConfig):
    """Extended application configuration with auth and rate limiting."""
    
    auth: AuthConfig = Field(default_factory=AuthConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
