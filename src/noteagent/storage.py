"""Session persistence and configuration management."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import wave
from array import array
from datetime import datetime
from pathlib import Path
from typing import Optional

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import tomli_w

from noteagent.models import AppConfig, AppConfigExtended, Session, SessionMetadata, Transcript

CONFIG_DIR = Path.home() / ".config" / "noteagent"
CONFIG_FILE = CONFIG_DIR / "config.toml"


def _apply_storage_override(config: AppConfig) -> AppConfig:
    """Apply NOTEAGENT_STORAGE_DIR override if set.

    The macOS app sets this from the user's first-launch folder pick so the
    rest of the codebase (sessions, exports, etc.) writes to the user-chosen
    location instead of the config-file default.
    """
    env = os.environ.get("NOTEAGENT_STORAGE_DIR", "").strip()
    if env:
        config.storage_path = Path(env).expanduser()
    return config


def load_config() -> AppConfig:
    """Load config from TOML file, or return defaults."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "rb") as f:
            data = tomllib.load(f)

        flat: dict = {}
        for section in data.values():
            if isinstance(section, dict):
                flat.update(section)
            else:
                flat.update(data)
                break

        if "default_path" in flat and "storage_path" not in flat:
            flat["storage_path"] = flat.pop("default_path")

        config = AppConfig(**{k: v for k, v in flat.items() if k in AppConfig.model_fields})
        return _apply_storage_override(config)

    return _apply_storage_override(AppConfig())


def save_config(config: AppConfig) -> None:
    """Save configuration to the TOML config file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "storage": {
            "default_path": str(config.storage_path),
        },
        "audio": {
            "default_device": config.default_device,
            "sample_rate": config.sample_rate,
            "channels": config.channels,
        },
        "transcript": {
            "model": config.whisper_model,
            "language": config.language,
        },
        "summary": {
            "provider": config.summary_provider,
            "style": config.summary_style,
        },
    }
    with open(CONFIG_FILE, "wb") as f:
        tomli_w.dump(data, f)


def load_config_extended() -> AppConfigExtended:
    """Load extended config with auth and rate limiting from TOML file."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "rb") as f:
            data = tomllib.load(f)

        # Flatten nested config structure
        flat: dict = {}
        auth_data = {}
        rate_limit_data = {}
        
        for section_key, section in data.items():
            if isinstance(section, dict):
                if section_key == "auth":
                    auth_data = section
                elif section_key == "rate_limit":
                    rate_limit_data = section
                else:
                    flat.update(section)
        
        # Handle legacy default_path
        if "default_path" in flat and "storage_path" not in flat:
            flat["storage_path"] = flat.pop("default_path")

        # Build extended config
        base_fields = {k: v for k, v in flat.items() if k in AppConfig.model_fields}
        if auth_data:
            base_fields["auth"] = auth_data
        if rate_limit_data:
            base_fields["rate_limit"] = rate_limit_data
            
        return _apply_storage_override(AppConfigExtended(**base_fields))

    return _apply_storage_override(AppConfigExtended())


def save_config_extended(config: AppConfigExtended) -> None:
    """Save extended configuration to the TOML config file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    # Convert to dict with JSON-serializable values
    config_dict = config.model_dump(mode='json')
    
    # Filter out None values from auth tokens to avoid TOML serialization issues
    if 'auth' in config_dict and 'tokens' in config_dict['auth']:
        for token in config_dict['auth']['tokens']:
            # Remove None values
            token_cleaned = {k: v for k, v in token.items() if v is not None}
            token.clear()
            token.update(token_cleaned)
    
    data = {
        "storage": {
            "default_path": str(config_dict["storage_path"]),
        },
        "audio": {
            "default_device": config_dict["default_device"],
            "sample_rate": config_dict["sample_rate"],
            "channels": config_dict["channels"],
        },
        "transcript": {
            "model": config_dict["whisper_model"],
            "language": config_dict["language"],
        },
        "summary": {
            "provider": config_dict["summary_provider"],
            "style": config_dict["summary_style"],
        },
        "auth": config_dict["auth"],
        "rate_limit": config_dict["rate_limit"],
    }
    
    with open(CONFIG_FILE, "wb") as f:
        tomli_w.dump(data, f)


def create_session(
    config: AppConfig,
    output_dir: Optional[Path] = None,
    device_name: Optional[str] = None,
    recording_mode: str = "single",
    system_device_name: Optional[str] = None,
    source_file: Optional[str] = None,
) -> Session:
    """Create a new recording session directory."""
    now = datetime.now()
    storage_root = output_dir or config.storage_path
    sessions_root = Path(storage_root).expanduser() / "sessions"

    base_session_id = now.strftime("%Y-%m-%d_%H-%M-%S")
    session_id = base_session_id
    session_path = sessions_root / session_id
    suffix = 1
    while session_path.exists():
        session_id = f"{base_session_id}_{suffix:02d}"
        session_path = sessions_root / session_id
        suffix += 1

    session_path.mkdir(parents=True, exist_ok=False)

    metadata = SessionMetadata(
        session_id=session_id,
        created_at=now,
        device_name=device_name or config.default_device,
        sample_rate=config.sample_rate,
        summary_style=config.summary_style,
        recording_mode=recording_mode,
        system_device_name=system_device_name,
        source_file=source_file,
    )

    session = Session(metadata=metadata, path=session_path)
    _save_metadata(session)
    return session


def save_transcript(session: Session, transcript: Transcript) -> None:
    """Save transcript to the session directory."""
    session.transcript = transcript
    session.metadata.duration = transcript.duration
    _save_metadata(session)

    with open(session.transcript_path, "w") as f:
        json.dump(transcript.model_dump(), f, indent=2)

    with open(session.path / "transcript.txt", "w") as f:
        f.write(transcript.full_text)


def save_transcript_version(
    session: Session,
    transcript: Transcript,
    model_label: str,
    set_default_if_missing: bool = True,
) -> tuple[Path, Path]:
    """Save a model-specific transcript variant without overwriting other variants."""
    safe_label = re.sub(r"[^A-Za-z0-9._-]+", "_", model_label).strip("._") or "model"
    json_path = session.path / f"transcript.{safe_label}.json"
    text_path = session.path / f"transcript.{safe_label}.txt"

    with open(json_path, "w") as f:
        json.dump(transcript.model_dump(), f, indent=2)

    with open(text_path, "w") as f:
        f.write(transcript.full_text)

    if set_default_if_missing and not session.transcript_path.exists():
        save_transcript(session, transcript)

    return json_path, text_path


def save_summary(session: Session, summary: str) -> None:
    """Save summary to the session directory."""
    session.summary = summary
    session.summary_path.write_text(summary)


def save_preview_media(session: Session, source_path: Path) -> Optional[Path]:
    """Persist a session-local preview media file for imported sessions."""
    if not source_path.exists() or not source_path.is_file():
        return None

    suffix = source_path.suffix.lower()
    if not suffix:
        return None

    preview_path = session.path / f"preview{suffix}"
    shutil.copy2(source_path, preview_path)
    return preview_path


def save_meeting_preview(session: Session) -> Optional[Path]:
    """Create a mixed preview WAV for meeting sessions from mic and system audio."""
    mic_path = session.mic_audio_path
    system_path = session.system_audio_path
    if not mic_path.exists() or not system_path.exists():
        return None

    preview_path = session.path / "preview.wav"

    with wave.open(str(mic_path), "rb") as mic_wav, wave.open(str(system_path), "rb") as system_wav:
        params = mic_wav.getparams()
        if system_wav.getnchannels() != params.nchannels or system_wav.getsampwidth() != params.sampwidth or system_wav.getframerate() != params.framerate:
            raise ValueError("Meeting audio tracks do not share compatible WAV parameters")
        if params.sampwidth != 2:
            raise ValueError("Meeting preview generation currently supports 16-bit PCM WAV files only")

        mic_frames = array("h")
        mic_frames.frombytes(mic_wav.readframes(params.nframes))
        system_frames = array("h")
        system_frames.frombytes(system_wav.readframes(system_wav.getnframes()))

    frame_count = min(len(mic_frames), len(system_frames))
    if frame_count == 0:
        return None

    mixed = array("h")
    for index in range(frame_count):
        sample = int((int(mic_frames[index]) + int(system_frames[index])) / 2)
        if sample > 32767:
            sample = 32767
        elif sample < -32768:
            sample = -32768
        mixed.append(sample)

    with wave.open(str(preview_path), "wb") as preview_wav:
        preview_wav.setnchannels(params.nchannels)
        preview_wav.setsampwidth(params.sampwidth)
        preview_wav.setframerate(params.framerate)
        preview_wav.writeframes(mixed.tobytes())

    return preview_path


def load_session(session_path: Path) -> Session:
    """Load a session from a directory."""
    meta_path = session_path / "metadata.json"
    with open(meta_path) as f:
        meta_data = json.load(f)

    metadata = SessionMetadata(**meta_data)
    session = Session(metadata=metadata, path=session_path)

    if session.transcript_path.exists():
        with open(session.transcript_path) as f:
            session.transcript = Transcript(**json.load(f))

    if session.summary_path.exists():
        session.summary = session.summary_path.read_text()

    return session


def list_sessions(config: AppConfig) -> list[Session]:
    """List all past sessions."""
    sessions_dir = config.storage_path.expanduser() / "sessions"
    if not sessions_dir.exists():
        return []

    sessions = []
    for entry in sorted(sessions_dir.iterdir(), reverse=True):
        if entry.is_dir() and (entry / "metadata.json").exists():
            sessions.append(load_session(entry))

    return sessions


def _save_metadata(session: Session) -> None:
    """Write session metadata to disk."""
    with open(session.metadata_path, "w") as f:
        json.dump(session.metadata.model_dump(mode="json"), f, indent=2, default=str)
