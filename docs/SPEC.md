# NoteAgent — Project Specification

## Overview

NoteAgent is a speech-to-text note-taking agent that captures audio (via BlackHole Audio multiplexer or microphone), produces live and post-recording transcripts, summarizes content using an LLM (GitHub Copilot), and exports notes in multiple formats.

**Tech Stack:** Rust (audio capture, performance-critical paths) + Python (STT, LLM integration, orchestration)

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    noteagent CLI                     │
│                  (Python - typer)                    │
├──────────┬──────────┬───────────┬───────────────────┤
│  Audio   │Transcript│  Summary  │      Export        │
│  Capture │  Engine  │  (LLM)    │                    │
│  (Rust)  │ (Python) │  (Python) │     (Python)       │
├──────────┴──────────┴───────────┴───────────────────┤
│              Storage Layer (Python)                  │
│         configurable path, per-session override      │
└─────────────────────────────────────────────────────┘
```

### Component Breakdown

#### 1. Audio Capture — Rust (`noteagent-audio`)

- **Purpose:** Low-latency audio capture from BlackHole virtual audio device or system mic
- **Library:** `cpal` (cross-platform audio I/O)
- **Output:** Raw PCM audio chunks streamed to Python via PyO3 bindings
- **Features:**
  - List available audio devices (including BlackHole)
  - Select device by name or index
  - Stream audio in real-time via callback → ring buffer → Python consumer
  - Record to WAV file for post-recording processing
- **Build:** Compiled as a Python extension module via `maturin` + `PyO3`

#### 2. Transcript Engine — Python (`noteagent.transcript`)

- **Purpose:** Convert audio to text, both live (streaming) and post-recording (batch)
- **Backend:** OpenAI Whisper (via `faster-whisper` for performance)
- **Modes:**
  - **Live:** Processes audio chunks in near-real-time, appends partial results
  - **Post-recording:** Processes full WAV file for higher accuracy
- **Output:** Timestamped transcript segments

#### 3. Storage Layer — Python (`noteagent.storage`)

- **Purpose:** Persist transcripts, summaries, and session metadata
- **Config:**
  - Default storage path set in `~/.config/noteagent/config.toml`
  - Per-session override via `--output-dir` CLI flag
- **Structure:**

  ```
  <storage_root>/
  ├── sessions/
  │   ├── 2026-03-13_14-30-00/
  │   │   ├── audio.wav
  │   │   ├── transcript.json
  │   │   ├── transcript.txt
  │   │   ├── summary.md
  │   │   └── metadata.json
  │   └── ...
  └── config.toml
  ```

- **Metadata:** session name, date, duration, device used, storage path

#### 4. LLM Summary — Python (`noteagent.summary`)

- **Purpose:** Generate concise summaries from transcripts
- **Backend:** GitHub Copilot LLM API (via `requests` or Copilot extension protocol)
- **Features:**
  - Summarize full transcript
  - Extract action items / key points
  - Customizable prompts (e.g., "meeting notes", "lecture summary")
- **Fallback:** Local model support for offline use (optional, future)

#### 5. Export — Python (`noteagent.export`)

- **Purpose:** Export notes to various formats
- **Formats:**
  - Markdown (`.md`)
  - Plain text (`.txt`)
  - JSON (structured with timestamps)
  - PDF (via `weasyprint` or `fpdf2`)
  - SRT/VTT subtitles
- **Options:** Include/exclude summary, timestamps, metadata

#### 6. CLI — Python (`noteagent.cli`)

- **Framework:** `typer`
- **Commands:**

  ```
  noteagent record       # Start recording + live transcript
  noteagent transcribe   # Transcribe an existing audio file
  noteagent summarize    # Summarize a transcript
  noteagent export       # Export session to a format
  noteagent devices      # List available audio devices
  noteagent config       # View/set default storage path
  noteagent sessions     # List past sessions
  ```

## Configuration

**File:** `~/.config/noteagent/config.toml`

```toml
[storage]
default_path = "~/notes/noteagent"

[audio]
default_device = "BlackHole 2ch"
sample_rate = 16000
channels = 1

[transcript]
model = "base.en"       # Whisper model size
language = "en"

[summary]
provider = "copilot"    # or "local"
style = "meeting"       # meeting | lecture | general
```

## Platform Considerations

- **Primary target:** macOS (BlackHole is macOS-native)
- **Portable components:** Transcript, summary, export, storage are platform-independent
- **Audio capture:** `cpal` supports macOS/Linux/Windows; BlackHole is macOS-only but the device selection is dynamic
- **Future:** PulseAudio/PipeWire support on Linux via same `cpal` abstraction

## Dependencies

### Rust

- `cpal` — cross-platform audio
- `hound` — WAV encoding
- `ringbuf` — lock-free ring buffer
- `pyo3` — Python bindings

### Python

- `maturin` — build Rust extensions
- `faster-whisper` — Whisper STT
- `typer` — CLI framework
- `rich` — terminal UI (live transcript display)
- `tomli` / `tomli-w` — TOML config
- `fpdf2` — PDF export
- `webvtt-py` — subtitle export
- `pydantic` — data models

## Milestones

1. **M1 — Audio Capture:** Rust crate captures audio, exposes to Python via PyO3
2. **M2 — Transcription:** Live + batch transcription working end-to-end
3. **M3 — Storage & Config:** Session persistence, configurable paths
4. **M4 — LLM Summary:** Copilot-powered summarization
5. **M5 — Export:** Multi-format export
6. **M6 — CLI Polish:** Full CLI with all commands wired up
