# NoteAgent — Local Web UI Spec

## Overview

A lightweight local web UI served by a FastAPI backend. Runs on `localhost`, no auth needed. Provides start/stop recording, session management, live transcript view, and settings — everything the CLI does, but in the browser.

## Technology Choices

| Layer    | Choice           | Rationale                                              |
|----------|------------------|--------------------------------------------------------|
| Backend  | **FastAPI**      | Async, WebSocket support for live transcript, minimal  |
| Frontend | **Vanilla JS + CSS** | No build step, single-page, fast to iterate       |
| Realtime | **WebSocket**    | Stream live transcript segments to the browser         |
| Styling  | **Pico CSS**     | Classless/minimal CSS, clean defaults, tiny (~10 KB)   |

No React, no npm, no bundler. A few static files served by FastAPI.

---

## Pages / Views

All views live in a single-page app with tab navigation.

### 1. Dashboard (default view)

The landing page. Shows:

- **Recording controls**: Big Start/Stop button, device selector dropdown, live/batch toggle
- **Live transcript panel**: Scrolling text area that updates via WebSocket during recording
- **Current session info**: Session ID, duration timer, device name
- **Quick stats**: Total sessions, last recording date

```
┌─────────────────────────────────────────────────────┐
│  NoteAgent              [Dashboard] [Sessions] [Settings] │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Device: [BlackHole 2ch ▾]   Model: [base.en ▾]    │
│                                                     │
│         [ ● Start Recording ]    00:00:00           │
│                                                     │
│  ┌─ Live Transcript ──────────────────────────────┐ │
│  │                                                │ │
│  │  [0.0s] Welcome to the meeting...              │ │
│  │  [3.2s] Today we'll discuss the roadmap...     │ │
│  │  [6.5s] First item on the agenda...            │ │
│  │                                                │ │
│  └────────────────────────────────────────────────┘ │
│                                                     │
│  Sessions: 12 total │ Last: 2026-03-12 14:30        │
└─────────────────────────────────────────────────────┘
```

### 2. Sessions

Browse, search, and manage past recording sessions.

- **Session list**: Table with date, duration, device, segment count, actions
- **Session detail** (expand/modal): Full transcript, summary, audio playback, export buttons
- **Actions per session**: Summarize, Export (format picker), Delete

```
┌─────────────────────────────────────────────────────┐
│  Sessions                              [Search... ] │
├──────────┬──────────┬────────┬──────┬───────────────┤
│  Date    │ Duration │ Device │ Segs │ Actions       │
├──────────┼──────────┼────────┼──────┼───────────────┤
│  Mar 12  │ 12:34    │ BH 2ch │  47  │ [▶] [Σ] [↓] [✕]│
│  Mar 11  │  5:20    │ MBP    │  18  │ [▶] [Σ] [↓] [✕]│
│  Mar 10  │ 45:01    │ BH 2ch │ 203  │ [▶] [Σ] [↓] [✕]│
└──────────┴──────────┴────────┴──────┴───────────────┘

Legend: [▶] View  [Σ] Summarize  [↓] Export  [✕] Delete
```

**Session detail panel** (when a session is expanded):

```
┌─────────────────────────────────────────────────────┐
│  Session: 2026-03-12_14-30-00                       │
├─────────────────────────────────────────────────────┤
│  Audio: [▶ Play] [⏸ Pause]  ━━━━━━━○━━━━  8:20     │
│                                                     │
│  Transcript                          [Copy] [Export]│
│  ┌────────────────────────────────────────────────┐ │
│  │ [0.0s] Welcome everyone to today's standup...  │ │
│  │ [3.1s] Let's start with updates from...        │ │
│  │ ...                                            │ │
│  └────────────────────────────────────────────────┘ │
│                                                     │
│  Summary                     [Regenerate] [Copy]    │
│  ┌────────────────────────────────────────────────┐ │
│  │ ## Meeting Summary                             │ │
│  │ Key points discussed: ...                      │ │
│  └────────────────────────────────────────────────┘ │
│                                                     │
│  Export: [Markdown] [Text] [JSON] [SRT] [VTT] [PDF] │
└─────────────────────────────────────────────────────┘
```

### 3. Settings

Edit app configuration (persisted to `config.toml`).

- **Audio**: Default device (dropdown from live device list), sample rate
- **Transcription**: Model size selector, language
- **Summary**: Provider, default style (general / meeting / lecture)
- **Storage**: Base storage path (with browse/edit)
- **Save** button with confirmation toast

```
┌─────────────────────────────────────────────────────┐
│  Settings                                           │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Audio                                              │
│    Default Device   [BlackHole 2ch ▾]               │
│    Sample Rate      [16000    ]                     │
│                                                     │
│  Transcription                                      │
│    Whisper Model    [base.en ▾]                     │
│    Language         [en       ]                     │
│                                                     │
│  Summary                                            │
│    Provider         [copilot ▾]                     │
│    Default Style    [general ▾]                     │
│                                                     │
│  Storage                                            │
│    Path             [~/notes/noteagent         ]    │
│                                                     │
│              [ Save Settings ]                      │
└─────────────────────────────────────────────────────┘
```

---

## API Endpoints

### REST

| Method | Path                          | Description                          |
|--------|-------------------------------|--------------------------------------|
| GET    | `/api/devices`                | List audio input devices             |
| GET    | `/api/config`                 | Get current config                   |
| PUT    | `/api/config`                 | Update config                        |
| POST   | `/api/record/start`           | Start a recording session            |
| POST   | `/api/record/stop`            | Stop current recording               |
| GET    | `/api/record/status`          | Current recording state + duration   |
| GET    | `/api/sessions`               | List all sessions                    |
| GET    | `/api/sessions/{id}`          | Get session detail                   |
| DELETE | `/api/sessions/{id}`          | Delete a session                     |
| POST   | `/api/sessions/{id}/summarize`| Run LLM summary on session           |
| POST   | `/api/sessions/{id}/export`   | Export session (format in body)       |
| GET    | `/api/sessions/{id}/audio`    | Stream/download session audio file   |
| POST   | `/api/transcribe`             | Transcribe an uploaded audio file    |

### WebSocket

| Path                | Description                                      |
|---------------------|--------------------------------------------------|
| `/ws/transcript`    | Live transcript segments pushed during recording |

**WebSocket message format** (server → client):

```json
{
  "type": "segment",
  "data": {
    "start": 3.2,
    "end": 6.1,
    "text": "Today we'll discuss the roadmap..."
  }
}
```

**Control messages** (server → client):

```json
{"type": "recording_started", "session_id": "2026-03-12_14-30-00"}
{"type": "recording_stopped", "duration": 120.5}
{"type": "transcription_complete", "segments": 47}
```

---

## Module Layout

```
src/noteagent/
├── server.py          # FastAPI app, endpoints, WebSocket handler
├── cli.py             # Existing CLI (add `serve` command)
└── ...

static/
├── index.html         # Single-page app
├── style.css          # Custom overrides on top of Pico CSS
└── app.js             # All client-side logic
```

### New CLI command

```
noteagent serve [--port 8765] [--no-browser]
```

Starts the FastAPI server and opens the browser to `http://localhost:8765`.

---

## Server State

The server holds a small amount of in-memory state for the active recording:

```python
@dataclass
class RecordingState:
    active: bool = False
    session: Optional[Session] = None
    recorder: Optional[Recorder] = None
    stream: Optional[StreamReader] = None
    transcriber: Optional[LiveTranscriber] = None
    start_time: Optional[float] = None
```

Only one recording can be active at a time. Starting a new recording while one is active returns `409 Conflict`.

---

## Behavior Notes

- **Auto-transcribe on stop**: When recording stops, the server automatically runs batch transcription (same as CLI `record` command). The WebSocket sends a `transcription_complete` message when done.
- **Audio playback**: Sessions serve the WAV file directly via `/api/sessions/{id}/audio` with proper `Content-Type: audio/wav` and range request support for seeking.
- **No auth**: This is a localhost-only tool. The server binds to `127.0.0.1` only.
- **Graceful shutdown**: Stopping the server while recording auto-stops the recording first.
- **Model preloading**: The Whisper model is loaded once at server startup and reused across requests to avoid repeated load times.

---

## Dependencies to Add

| Package       | Purpose                |
|---------------|------------------------|
| `fastapi`     | Web framework          |
| `uvicorn`     | ASGI server            |
| `websockets`  | WebSocket support      |

All three are lightweight. No frontend build dependencies.

---

## Milestones

| #  | Milestone                  | Scope                                                        |
|----|----------------------------|--------------------------------------------------------------|
| U1 | Server skeleton            | FastAPI app, `serve` command, static file serving, device API |
| U2 | Recording API              | Start/stop endpoints, recording state, WebSocket live stream |
| U3 | Dashboard UI               | index.html with recording controls + live transcript panel   |
| U4 | Sessions API + UI          | List/detail/delete endpoints, sessions page, audio playback  |
| U5 | Settings UI                | Config get/put endpoints, settings page                      |
| U6 | Summary + Export           | Summarize/export endpoints, UI buttons                       |
