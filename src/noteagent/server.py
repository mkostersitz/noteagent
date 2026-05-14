"""FastAPI web server for NoteAgent UI."""

from __future__ import annotations

import asyncio
import mimetypes
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, Depends
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response

from noteagent import get_version
from noteagent.auth import validate_token, is_admin_role
from noteagent.models import AppConfigExtended, AuthToken, Session

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"

# Global config - will be loaded on startup
_app_config: Optional[AppConfigExtended] = None


def get_app_config() -> AppConfigExtended:
    """Get or load application configuration."""
    global _app_config
    if _app_config is None:
        from noteagent.storage import load_config_extended
        _app_config = load_config_extended()
    return _app_config


def require_admin(request: Request) -> None:
    """Dependency to require admin role for protected endpoints."""
    config = get_app_config()
    
    # If auth is disabled, allow all requests
    if not config.auth.enabled:
        return
    
    # Check if auth_token was set by AuthMiddleware
    auth_token = getattr(request.state, "auth_token", None)
    
    if not auth_token or not is_admin_role(auth_token):
        raise HTTPException(
            status_code=403,
            detail="Admin role required for this operation"
        )


def get_rate_limit(endpoint: str) -> str:
    """Get rate limit for a specific endpoint."""
    config = get_app_config()
    
    if not config.rate_limit.enabled:
        return "0/second"  # No limit
    
    # Check for endpoint-specific limit
    for endpoint_config in config.rate_limit.endpoints:
        if endpoint_config.path == endpoint:
            return endpoint_config.limit
    
    return config.rate_limit.default_limit


# ---------------------------------------------------------------------------
# Middleware classes
# ---------------------------------------------------------------------------

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""
    
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        return response


class AuthMiddleware(BaseHTTPMiddleware):
    """Authentication middleware - validates Bearer tokens."""
    
    async def dispatch(self, request: StarletteRequest, call_next) -> Response:
        # Load config
        config = get_app_config()
        
        # Skip auth if disabled or for public paths
        if not config.auth.enabled or self._is_public_path(request.url.path):
            return await call_next(request)
        
        # Extract token from Authorization header
        auth_header = request.headers.get(config.auth.token_header, "")
        
        if not auth_header.startswith(f"{config.auth.token_prefix} "):
            return Response(
                content='{"detail":"Missing or invalid authorization header"}',
                status_code=401,
                media_type="application/json"
            )
        
        token = auth_header[len(config.auth.token_prefix) + 1:]
        
        # Validate token
        auth_token = validate_token(token, config.auth.tokens)
        
        if not auth_token:
            return Response(
                content='{"detail":"Invalid or expired token"}',
                status_code=401,
                media_type="application/json"
            )
        
        # Store auth info in request state
        request.state.auth_token = auth_token
        request.state.user_id = auth_token.name
        request.state.role = auth_token.role
        
        return await call_next(request)
    
    def _is_public_path(self, path: str) -> bool:
        """Check if path is public (no auth required)."""
        public_prefixes = [
            "/static/",
            "/docs",
            "/openapi.json",
            "/redoc",
        ]
        return any(path.startswith(prefix) for prefix in public_prefixes)


class RateLimitBypassMiddleware(BaseHTTPMiddleware):
    """Bypass rate limiting for whitelisted IPs."""
    
    async def dispatch(self, request: StarletteRequest, call_next) -> Response:
        config = get_app_config()
        
        if not config.rate_limit.enabled:
            return await call_next(request)
        
        # Check if IP is whitelisted
        client_ip = get_remote_address(request)
        if client_ip in config.rate_limit.whitelist_ips:
            # Bypass rate limiting by setting a flag
            request.state.rate_limit_bypass = True
        
        return await call_next(request)


# ---------------------------------------------------------------------------
# FastAPI app initialization
# ---------------------------------------------------------------------------

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="NoteAgent", version=get_version())
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.on_event("startup")
def _ensure_default_model() -> None:
    """Kick off a background ggml model download on first launch.

    Idempotent: returns immediately if the configured model is already on
    disk. Skipped when `NOTEAGENT_SKIP_AUTO_DOWNLOAD=1` is set (CI, tests).
    """
    from noteagent.model_download import auto_download_enabled, ensure_model_async
    from noteagent.storage import load_config

    if not auto_download_enabled():
        return

    try:
        cfg = load_config()
        ensure_model_async(cfg.whisper_model)
    except Exception:
        # Never block server startup on a model-download issue.
        pass

# Add security middleware - order matters, execute from bottom to top
app.add_middleware(RateLimitBypassMiddleware)  # Check IP whitelist first
app.add_middleware(AuthMiddleware)  # Then auth
app.add_middleware(SecurityHeadersMiddleware)  # Then security headers
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "*"])  # * for local dev


# ---------------------------------------------------------------------------
# Recording state
# ---------------------------------------------------------------------------

@dataclass
class RecordingState:
    active: bool = False
    session: Optional[Session] = None
    recorder: object | None = None
    stream: object | None = None
    transcriber: object | None = None
    start_time: Optional[float] = None
    ws_clients: list[WebSocket] = field(default_factory=list)
    _live_thread: Optional[threading.Thread] = None
    _msg_queue: queue.Queue = field(default_factory=queue.Queue)


_state = RecordingState()
_state_lock = threading.Lock()  # Thread-safe access to _state
_whisper_model = None
_model_lock = threading.Lock()
_PREVIEWABLE_SUFFIXES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".webm": "video/webm",
    ".mp4": "video/mp4",
}

# Allowed config fields for API updates (security whitelist)
_ALLOWED_CONFIG_FIELDS = {
    "storage_path",
    "default_device",
    "sample_rate",
    "channels",
    "language",
    "summary_style",
}


# ---------------------------------------------------------------------------
# Security validation functions
# ---------------------------------------------------------------------------

def _validate_session_id(session_id: str) -> str:
    """Validate session ID to prevent path traversal attacks.
    
    Valid formats:
    - YYYY-MM-DD_HH-MM-SS
    - YYYY-MM-DD_HH-MM-SS_NN (with suffix)
    
    Raises HTTPException if invalid.
    """
    if not re.match(r'^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(_\d{2})?$', session_id):
        raise HTTPException(400, "Invalid session ID format")
    
    # Additional check: no path separators
    if '/' in session_id or '\\' in session_id or '..' in session_id:
        raise HTTPException(400, "Invalid session ID")
    
    return session_id


def _validate_source_path(source_path: Path) -> bool:
    """Validate that a source file path is safe to access.
    
    Returns True if safe, False otherwise.
    """
    if not source_path.exists():
        return False
    
    # Resolve to absolute path
    try:
        resolved = source_path.resolve()
    except (OSError, RuntimeError):
        return False
    
    # Block system directories
    str_path = str(resolved)
    forbidden_prefixes = ('/etc', '/sys', '/proc', '/dev', '/root', '/boot')
    if str_path.startswith(forbidden_prefixes):
        return False
    
    return True


def _get_model(model_size: str = "base.en"):
    """Load Whisper model once and cache it."""
    global _whisper_model
    with _model_lock:
        if _whisper_model is None:
            from noteagent.transcript import load_model
            _whisper_model = load_model(model_size)
    return _whisper_model


def _resolve_session_preview(session_id: str, session: Session) -> dict:
    """Resolve preview media metadata for a session detail view."""
    _ensure_session_preview(session)
    preview_media = session.preview_media_path()
    if preview_media:
        mime_type = _PREVIEWABLE_SUFFIXES.get(preview_media.suffix.lower()) or mimetypes.guess_type(preview_media.name)[0]
        if mime_type and (mime_type.startswith("audio/") or mime_type.startswith("video/")):
            return {
                "available": True,
                "kind": "video" if mime_type.startswith("video/") else "audio",
                "mime_type": mime_type,
                "url": f"/api/sessions/{session_id}/media",
                "filename": preview_media.name,
                "message": None,
                "source": "session-preview",
            }

    if session.audio_path.exists():
        return {
            "available": True,
            "kind": "audio",
            "mime_type": "audio/wav",
            "url": f"/api/sessions/{session_id}/media",
            "filename": session.audio_path.name,
            "message": None,
            "source": "recording",
        }

    if session.metadata.recording_mode == "meeting":
        return {
            "available": False,
            "kind": "none",
            "mime_type": None,
            "url": None,
            "filename": None,
            "message": "Meeting sessions do not have a combined playback preview yet. Transcript and summary are still available.",
        }

    if session.metadata.source_file:
        source_path = Path(session.metadata.source_file).expanduser()
        
        # Security: Validate source path
        if not _validate_source_path(source_path):
            return {
                "available": False,
                "kind": "none",
                "mime_type": None,
                "url": None,
                "filename": source_path.name if source_path else None,
                "message": "Source file access denied or not found",
                "source": "access-denied",
            }
        
        suffix = source_path.suffix.lower()
        mime_type = _PREVIEWABLE_SUFFIXES.get(suffix) or mimetypes.guess_type(source_path.name)[0]
        if mime_type and (mime_type.startswith("audio/") or mime_type.startswith("video/")):
            return {
                "available": True,
                "kind": "video" if mime_type.startswith("video/") else "audio",
                "mime_type": mime_type,
                "url": f"/api/sessions/{session_id}/media",
                "filename": source_path.name,
                "message": None,
                "source": "original-file",
            }
        
        message = f"Preview is not available for imported {suffix or 'media'} files in the web UI."
        return {
            "available": False,
            "kind": "none",
            "mime_type": None,
            "url": None,
            "filename": source_path.name,
            "message": message,
            "source": "missing",
        }

    return {
        "available": False,
        "kind": "none",
        "mime_type": None,
        "url": None,
        "filename": None,
        "message": "No preview media is available for this session.",
        "source": "none",
    }


def _resolve_session_preview_path(session: Session) -> tuple[Path, str]:
    """Return the media path and MIME type for a session preview."""
    _ensure_session_preview(session)
    preview_media = session.preview_media_path()
    if preview_media:
        mime_type = _PREVIEWABLE_SUFFIXES.get(preview_media.suffix.lower()) or mimetypes.guess_type(preview_media.name)[0]
        if mime_type and (mime_type.startswith("audio/") or mime_type.startswith("video/")):
            return preview_media, mime_type

    if session.audio_path.exists():
        return session.audio_path, "audio/wav"

    if session.metadata.source_file:
        source_path = Path(session.metadata.source_file).expanduser()
        
        # Security: Validate source path
        if not _validate_source_path(source_path):
            raise HTTPException(403, "Access to source file denied")
        
        suffix = source_path.suffix.lower()
        mime_type = _PREVIEWABLE_SUFFIXES.get(suffix) or mimetypes.guess_type(source_path.name)[0]
        if mime_type and (mime_type.startswith("audio/") or mime_type.startswith("video/")):
            return source_path, mime_type

    raise HTTPException(404, "Preview media not available")


def _ensure_session_preview(session: Session) -> None:
    """Backfill preview media for sessions created before preview support existed."""
    if session.preview_media_path() is not None:
        return

    try:
        from noteagent.storage import save_meeting_preview, save_preview_media

        if session.metadata.recording_mode == "meeting":
            save_meeting_preview(session)
        elif session.metadata.recording_mode == "import" and session.metadata.source_file:
            save_preview_media(session, Path(session.metadata.source_file).expanduser())
    except Exception:
        return


def _reveal_path(path: Path, select: bool = False) -> None:
    """Reveal a path in the local file manager."""
    target = path.expanduser().resolve()
    if not target.exists():
        raise FileNotFoundError(str(target))

    if sys.platform == "darwin":
        if select and target.is_file():
            subprocess.run(["open", "-R", str(target)], check=True)
        else:
            subprocess.run(["open", str(target if target.is_dir() else target.parent)], check=True)
        return

    if sys.platform.startswith("win"):
        if select and target.is_file():
            subprocess.run(["explorer", "/select,", str(target)], check=True)
        else:
            subprocess.run(["explorer", str(target if target.is_dir() else target.parent)], check=True)
        return

    subprocess.run(["xdg-open", str(target if target.is_dir() else target.parent)], check=True)


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class RecordStartRequest(BaseModel):
    device: Optional[str] = None
    model: str = "base.en"
    live: bool = True
    meeting: bool = False
    system_device: Optional[str] = None


class ConfigUpdate(BaseModel):
    storage_path: Optional[str] = None
    default_device: Optional[str] = None
    sample_rate: Optional[int] = None
    whisper_model: Optional[str] = None
    language: Optional[str] = None
    summary_provider: Optional[str] = None
    summary_style: Optional[str] = None


class ExportRequest(BaseModel):
    format: str = "markdown"


class SummarizeRequest(BaseModel):
    style: str = "general"


class RevealRequest(BaseModel):
    target: str = "session"


# ---------------------------------------------------------------------------
# API routes — devices
# ---------------------------------------------------------------------------

@app.get("/api/devices")
def api_devices():
    from noteagent.audio import AudioBackendUnavailable, list_devices

    try:
        return {"devices": list_devices()}
    except AudioBackendUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


# ---------------------------------------------------------------------------
# API routes — config
# ---------------------------------------------------------------------------

@app.get("/api/config")
@limiter.limit(lambda: get_rate_limit("/api/config"))
def api_get_config(request: Request):
    from noteagent.storage import load_config
    cfg = load_config()
    data = cfg.model_dump(mode="json")
    data["app_version"] = get_version()
    return data


@app.put("/api/config")
@limiter.limit(lambda: get_rate_limit("/api/config"))
def api_update_config(
    body: ConfigUpdate,
    request: Request,
    _: None = Depends(require_admin),
):
    """Update configuration with security whitelist."""
    from noteagent.storage import load_config, save_config
    cfg = load_config()
    
    for key, val in body.model_dump(exclude_none=True).items():
        # Security: Only allow whitelisted fields
        if key not in _ALLOWED_CONFIG_FIELDS:
            raise HTTPException(400, f"Cannot modify config field: {key}")
        
        if key == "storage_path":
            cfg.storage_path = Path(val)
        else:
            setattr(cfg, key, val)
    
    save_config(cfg)
    data = cfg.model_dump(mode="json")
    data["app_version"] = get_version()
    return data


# ---------------------------------------------------------------------------
# API routes — recording
# ---------------------------------------------------------------------------

@app.get("/api/record/status")
@limiter.limit(lambda: get_rate_limit("/api/record/status"))
async def api_record_status(request: Request):
    """Get current recording status with thread-safe access."""
    with _state_lock:
        elapsed = 0.0
        session_id = None
        if _state.active and _state.start_time:
            elapsed = time.time() - _state.start_time
        if _state.session:
            session_id = _state.session.metadata.session_id
        return {"active": _state.active, "elapsed": round(elapsed, 1), "session_id": session_id}


@app.post("/api/record/start")
def api_record_start(body: RecordStartRequest):
    """Start recording with thread-safe state check."""
    with _state_lock:
        if _state.active:
            raise HTTPException(409, "A recording is already in progress")

    from noteagent.audio import AudioBackendUnavailable
    from noteagent.storage import create_session, load_config

    config = load_config()
    device = body.device or config.default_device

    try:
        if body.meeting:
            system_device = body.system_device or "BlackHole 2ch"
            return _start_meeting(config, device, system_device, body)
        return _start_single(config, device, body)
    except AudioBackendUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


def _start_single(config, device: str, body: RecordStartRequest):
    from noteagent.audio import Recorder
    from noteagent.storage import create_session

    with _state_lock:
        session = create_session(config, device_name=device)
        recorder = Recorder(device_name=device, sample_rate=config.sample_rate)
        recorder.start(session.audio_path, device_name=device)

        _state.session = session
        _state.recorder = recorder
        _state.active = True
        _state.start_time = time.time()

        if body.live:
            _state._live_thread = threading.Thread(
                target=_live_loop,
                args=(device, config.sample_rate, body.model, config.language),
                daemon=True,
            )
            _state._live_thread.start()

        return {"status": "recording", "session_id": session.metadata.session_id, "mode": "single"}


def _start_meeting(config, mic_device: str, system_device: str, body: RecordStartRequest):
    from noteagent.audio import DualRecorder
    from noteagent.storage import create_session

    session = create_session(
        config,
        device_name=mic_device,
        recording_mode="meeting",
        system_device_name=system_device,
    )
    recorder = DualRecorder(
        mic_device=mic_device,
        system_device=system_device,
        sample_rate=config.sample_rate,
    )
    recorder.start(session.mic_audio_path, session.system_audio_path)

    _state.active = True
    _state.session = session
    _state.recorder = recorder
    _state.start_time = time.time()

    if body.live:
        _state._live_thread = threading.Thread(
            target=_live_loop_meeting,
            args=(mic_device, system_device, config.sample_rate, body.model, config.language),
            daemon=True,
        )
        _state._live_thread.start()

    return {"status": "recording", "session_id": session.metadata.session_id, "mode": "meeting"}


def _live_loop(device: str, sample_rate: int, model: str, language: str):
    """Background thread reading audio chunks and queuing transcript segments."""
    from noteagent.audio import StreamReader
    from noteagent.transcript import LiveTranscriber

    stream = StreamReader(device_name=device, sample_rate=sample_rate)
    transcriber = LiveTranscriber(model_size=model, language=language, sample_rate=sample_rate)

    while _state.active:
        try:
            samples = stream.read_chunk()
            if samples:
                new_segs = transcriber.feed(samples)
                for seg in new_segs:
                    msg = {
                        "type": "segment",
                        "data": {"start": seg.start, "end": seg.end, "text": seg.text, "speaker": seg.speaker},
                    }
                    _state._msg_queue.put(msg)
        except Exception as exc:
            _state._msg_queue.put({"type": "live_error", "detail": str(exc)})
            break
        time.sleep(0.1)

    try:
        stream.stop()
    except Exception:
        pass


def _live_loop_meeting(mic_device: str, system_device: str, sample_rate: int, model: str, language: str):
    """Background thread for dual-channel live transcription."""
    from noteagent.audio import DualStreamReader
    from noteagent.transcript import MeetingLiveTranscriber

    dual_stream = DualStreamReader(
        mic_device=mic_device,
        system_device=system_device,
        sample_rate=sample_rate,
    )
    transcriber = MeetingLiveTranscriber(
        model_size=model,
        language=language,
        sample_rate=sample_rate,
    )

    while _state.active:
        try:
            mic_samples = dual_stream.read_mic_chunk()
            sys_samples = dual_stream.read_system_chunk()
            new_segs = []
            if mic_samples:
                new_segs.extend(transcriber.feed_mic(mic_samples))
            if sys_samples:
                new_segs.extend(transcriber.feed_system(sys_samples))
            for seg in new_segs:
                msg = {
                    "type": "segment",
                    "data": {"start": seg.start, "end": seg.end, "text": seg.text, "speaker": seg.speaker},
                }
                _state._msg_queue.put(msg)
        except Exception as exc:
            _state._msg_queue.put({"type": "live_error", "detail": str(exc)})
            break
        time.sleep(0.1)

    try:
        dual_stream.stop()
    except Exception:
        pass


@app.post("/api/record/stop")
def api_record_stop():
    if not _state.active:
        raise HTTPException(400, "No active recording")

    from noteagent.storage import load_config, save_transcript
    from noteagent.transcript import transcribe_file

    _state.active = False  # signal live thread to exit

    if _state._live_thread:
        _state._live_thread.join(timeout=3)

    # Stop recorder
    if _state.recorder:
        _state.recorder.stop()

    session = _state.session
    duration = 0.0
    if _state.start_time:
        duration = time.time() - _state.start_time

    # Queue notification for WS clients
    _state._msg_queue.put({"type": "recording_stopped", "duration": round(duration, 1)})

    # Post-recording batch transcription
    config = load_config()
    transcript_data = None
    is_meeting = session and session.metadata.recording_mode == "meeting"

    if session and is_meeting and session.mic_audio_path.exists() and session.system_audio_path.exists():
        from noteagent.transcript import transcribe_meeting
        transcript = transcribe_meeting(
            session.mic_audio_path,
            session.system_audio_path,
            model=_get_model(config.whisper_model),
            model_size=config.whisper_model,
            language=config.language,
        )
        save_transcript(session, transcript)
        session.metadata.duration = duration
        transcript_data = {
            "segments": [s.model_dump() for s in transcript.segments],
            "full_text": transcript.full_text,
        }
        _state._msg_queue.put({
            "type": "transcription_complete",
            "segments": len(transcript.segments),
        })
    elif session and session.audio_path.exists():
        transcript = transcribe_file(
            session.audio_path,
            model=_get_model(config.whisper_model),
            model_size=config.whisper_model,
            language=config.language,
        )
        save_transcript(session, transcript)
        session.metadata.duration = duration
        transcript_data = {
            "segments": [s.model_dump() for s in transcript.segments],
            "full_text": transcript.full_text,
        }
        _state._msg_queue.put({
            "type": "transcription_complete",
            "segments": len(transcript.segments),
        })

    # Reset state
    session_id = session.metadata.session_id if session else None
    _state.session = None
    _state.recorder = None
    _state.stream = None
    _state.transcriber = None
    _state.start_time = None
    _state._live_thread = None

    return {
        "status": "stopped",
        "session_id": session_id,
        "duration": round(duration, 1),
        "transcript": transcript_data,
    }


# ---------------------------------------------------------------------------
# API routes — sessions
# ---------------------------------------------------------------------------

@app.get("/api/sessions")
def api_list_sessions():
    from noteagent.storage import list_sessions, load_config
    config = load_config()
    sessions = list_sessions(config)
    result = []
    for s in sessions:
        result.append({
            "session_id": s.metadata.session_id,
            "created_at": s.metadata.created_at.isoformat(),
            "device_name": s.metadata.device_name,
            "duration": s.metadata.duration,
            "segments": len(s.transcript.segments) if s.transcript else 0,
            "has_summary": s.summary is not None,
            "path": str(s.path),
            "recording_mode": s.metadata.recording_mode,
        })
    return {"sessions": result}


@app.get("/api/sessions/{session_id}")
def api_get_session(session_id: str):
    session = _find_session(session_id)
    preview = _resolve_session_preview(session_id, session)
    data = {
        "session_id": session.metadata.session_id,
        "created_at": session.metadata.created_at.isoformat(),
        "device_name": session.metadata.device_name,
        "duration": session.metadata.duration,
        "path": str(session.path),
        "summary": session.summary,
        "recording_mode": session.metadata.recording_mode,
        "system_device_name": session.metadata.system_device_name,
        "source_file": session.metadata.source_file,
        "media_preview": preview,
        "transcript": None,
    }
    if session.transcript:
        data["transcript"] = {
            "segments": [s.model_dump() for s in session.transcript.segments],
            "language": session.transcript.language,
            "model": session.transcript.model,
            "full_text": session.transcript.full_text,
        }
    return data


@app.delete("/api/sessions/{session_id}")
def api_delete_session(session_id: str):
    session = _find_session(session_id)
    shutil.rmtree(session.path)
    return {"status": "deleted", "session_id": session_id}


@app.get("/api/sessions/{session_id}/media")
def api_session_media(session_id: str):
    session = _find_session(session_id)
    media_path, mime_type = _resolve_session_preview_path(session)
    return FileResponse(media_path, media_type=mime_type, filename=media_path.name)


@app.get("/api/sessions/{session_id}/audio")
def api_session_audio(session_id: str):
    session = _find_session(session_id)
    if not session.audio_path.exists():
        raise HTTPException(404, "Audio file not found")
    return FileResponse(session.audio_path, media_type="audio/wav", filename="audio.wav")


@app.post("/api/sessions/{session_id}/summarize")
def api_summarize_session(session_id: str, body: SummarizeRequest):
    from noteagent.storage import load_config, save_summary
    from noteagent.summary import summarize as do_summarize

    session = _find_session(session_id)
    if not session.transcript:
        raise HTTPException(400, "No transcript for this session")

    config = load_config()
    summary = do_summarize(session.transcript, style=body.style, provider=config.summary_provider)
    save_summary(session, summary)
    return {"summary": summary}


@app.post("/api/sessions/{session_id}/export")
def api_export_session(session_id: str, body: ExportRequest):
    from noteagent.export import export_session
    session = _find_session(session_id)
    path = export_session(session, fmt=body.format)
    return FileResponse(path, filename=path.name)


@app.post("/api/sessions/{session_id}/reveal")
def api_reveal_session_path(session_id: str, body: RevealRequest):
    session = _find_session(session_id)

    if body.target == "source":
        if not session.metadata.source_file:
            raise HTTPException(404, "No source file recorded for this session")
        reveal_target = Path(session.metadata.source_file).expanduser()
        select = True
    elif body.target == "session":
        reveal_target = session.path
        select = False
    else:
        raise HTTPException(400, "Unknown reveal target")

    try:
        _reveal_path(reveal_target, select=select)
    except FileNotFoundError:
        raise HTTPException(404, f"Path not found: {reveal_target}") from None
    except subprocess.CalledProcessError as exc:
        raise HTTPException(500, f"Failed to reveal path: {exc}") from exc

    return {"status": "ok", "target": body.target, "path": str(reveal_target)}


def _find_session(session_id: str) -> Session:
    """Find and load a session by ID with path traversal protection."""
    from noteagent.storage import load_config, load_session
    
    # Validate session ID format (prevents path traversal)
    session_id = _validate_session_id(session_id)
    
    config = load_config()
    sessions_root = config.storage_path.expanduser() / "sessions"
    session_path = sessions_root / session_id
    
    # Resolve and validate path is within sessions directory
    try:
        resolved_path = session_path.resolve()
        resolved_root = sessions_root.resolve()
    except (OSError, RuntimeError):
        raise HTTPException(404, "Session not found")
    
    # Ensure resolved path is within sessions directory
    try:
        if not resolved_path.is_relative_to(resolved_root):
            raise HTTPException(403, "Access denied")
    except ValueError:
        raise HTTPException(403, "Access denied")
    
    if not resolved_path.exists():
        raise HTTPException(404, "Session not found")
    
    return load_session(resolved_path)


# ---------------------------------------------------------------------------
# WebSocket — live transcript
# ---------------------------------------------------------------------------

@app.websocket("/ws/transcript")
async def ws_transcript(websocket: WebSocket):
    await websocket.accept()
    _state.ws_clients.append(websocket)
    try:
        while True:
            # Drain the message queue and broadcast to this client
            while not _state._msg_queue.empty():
                try:
                    msg = _state._msg_queue.get_nowait()
                    # Send to all connected clients
                    for client in list(_state.ws_clients):
                        try:
                            await client.send_json(msg)
                        except Exception:
                            pass
                except queue.Empty:
                    break
            # Short sleep to avoid busy-waiting, then check for client disconnect
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=0.2)
            except asyncio.TimeoutError:
                continue
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in _state.ws_clients:
            _state.ws_clients.remove(websocket)


# ---------------------------------------------------------------------------
# Static files — serve index.html + assets
# ---------------------------------------------------------------------------

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "NoteAgent API — static files not found"}
