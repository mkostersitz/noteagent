# NoteAgent

Speech-to-text note-taking agent with live transcription, LLM summarization, and multi-format export. Built with Rust (audio capture) and Python (transcription, UI, CLI).

---

## Features

- **Live & batch transcription** — powered by OpenAI Whisper
- **Dual-channel meeting mode** — separate mic + system audio (via BlackHole) with speaker labels
- **LLM summarization** — via GitHub Copilot CLI
- **Multi-format export** — Markdown, Text, JSON, SRT, VTT, PDF
- **Web UI** — local dashboard for recording, browsing sessions, and managing settings
- **CLI** — full control from the terminal

---

## Prerequisites

| Requirement | Version | Check |
|---|---|---|
| **Python** | 3.10+ | `python3 --version` |
| **Rust** | stable | `rustc --version` |
| **maturin** | 1.0+ | `pip install maturin` (installed with dev deps) |
| **Git** | any | `git --version` |

### macOS-specific

- **BlackHole 2ch** — virtual audio driver for capturing system audio.
  Install from [existential.audio/blackhole](https://existential.audio/blackhole/)
  or via Homebrew: `brew install blackhole-2ch`
- For **meeting mode**, create a Multi-Output Device in Audio MIDI Setup
  that routes to both your speakers and BlackHole 2ch.

### Optional

- **GitHub CLI + Copilot extension** — for LLM summarization

  ```
  brew install gh
  gh extension install github/gh-copilot
  gh auth login
  ```

---

## Installation

### Quick Install (Recommended)

**macOS / Linux:**
```bash
curl -fsSL https://raw.githubusercontent.com/mkostersitz/noteagent/main/install.sh | bash
```

**Windows:**
```cmd
git clone https://github.com/mkostersitz/noteagent.git
cd noteagent
install.bat
```

The automated installer handles everything:
- ✅ Checks prerequisites (Python 3.10+, Rust, Git)
- ✅ Builds Rust audio extension
- ✅ Installs Python package and dependencies
- ✅ Downloads Whisper model (~140 MB)
- ✅ Creates launcher scripts for CLI and Web UI
- ✅ Sets up default configuration

📖 See [INSTALL.md](docs/INSTALL.md) for detailed installation instructions, troubleshooting, and customization options.

### Development Setup

For development work:

```bash
# 1. Clone the repository
git clone https://github.com/mkostersitz/noteagent.git
cd noteagent

# 2. Run the full setup (creates venv, builds Rust extension, installs Python package, downloads Whisper model)
make setup

# 3. Activate the virtual environment
source .venv/bin/activate

# 4. Verify the installation
noteagent --help
```

This creates a local `.venv` in the project directory for development.

---

## 🔒 Authentication & Rate Limiting

NoteAgent supports optional authentication and rate limiting for secure network deployments.

### Authentication

Authentication is disabled by default but can be enabled for network deployments:

```bash
# Generate an admin token
noteagent token-generate my-laptop --role admin

# Generate a read-only token that expires in 30 days
noteagent token-generate mobile-app --role read-only --expires-days 30

# List all tokens
noteagent token-list

# Test a token
noteagent token-test na_xK7fE9mP2qR5tY8w...

# Revoke a token
noteagent token-revoke my-laptop

# Enable authentication
noteagent auth-enable

# Disable authentication
noteagent auth-disable
```

**Using tokens with the API:**

```bash
# Include token in Authorization header
curl -H "Authorization: Bearer na_your_token_here" http://localhost:8000/api/config
```

**Roles:**
- **admin**: Full access to all endpoints (read + write operations)
- **read-only**: Read-only access (cannot start recordings, update config, etc.)

### Rate Limiting

Rate limiting is enabled by default to prevent abuse:

- **Default limit**: 100 requests/minute per IP
- **Whitelisted IPs**: `127.0.0.1`, `::1` (localhost) are exempt by default
- **Per-endpoint limits**: Can be configured in `config.toml`

**Configuration** (`~/.config/noteagent/config.toml`):

```toml
[auth]
enabled = true
token_header = "Authorization"
token_prefix = "Bearer"

[[auth.tokens]]
token = "na_xK7fE9mP2qR5tY8w..."
name = "my-laptop"
role = "admin"
created_at = "2026-04-14T22:00:00"

[rate_limit]
enabled = true
default_limit = "100/minute"
whitelist_ips = ["127.0.0.1", "::1", "192.168.1.100"]

# Optional: per-endpoint limits
[[rate_limit.endpoints]]
path = "/api/record/start"
limit = "10/minute"

[[rate_limit.endpoints]]
path = "/api/sessions"
limit = "200/minute"
```

**Security Best Practices:**
- Keep tokens secret - they cannot be recovered
- Use read-only tokens for monitoring/viewing
- Enable authentication when exposing the server to a network
- Use HTTPS in production (e.g., behind nginx with SSL)
- Rotate tokens periodically
- Set expiration dates on tokens when possible

---

## Manual Setup (Advanced)

If you need manual control over the installation process (not recommended for most users):

### 1. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate    # macOS / Linux
# .venv\Scripts\activate     # Windows (PowerShell)
```

### 2. Build the Rust audio extension

```bash
pip install maturin
cd noteagent-audio
maturin develop
cd ..
```

### 3. Install the Python package

```bash
pip install -e ".[dev]"
```

### 4. Download the Whisper model

```bash
mkdir -p models
curl -fSL -o models/base.en.pt \
  "https://openaipublic.azureedge.net/main/whisper/models/25a8566e1d0c1e2231d1c762132cd20e0f96a85d16145c3a00adf5d1ac670ead/base.en.pt"
```

### 5. Verify

```bash
noteagent --help
noteagent devices          # should list your audio devices
```

---

## Usage

### Recording (CLI)

```bash
# Record with live transcription
noteagent record

# Record from a specific device
noteagent record --device "MacBook Pro Microphone"

# Meeting mode — dual-channel (mic + system audio)
noteagent record --meeting --device "MacBook Pro Microphone" --system-device "BlackHole 2ch"

# Record without live transcript (faster, less CPU)
noteagent record --no-live
```

Press **Ctrl+C** to stop. Post-recording transcription runs automatically.

### Web UI

```bash
noteagent serve              # starts at http://127.0.0.1:8765
noteagent serve --port 9000  # custom port
noteagent stop               # stop a running server
```

### Transcribe an existing file

```bash
noteagent transcribe path/to/audio.wav

# Higher quality decode + larger model
noteagent transcribe path/to/audio.wav --model medium.en --quality accurate

# Let Whisper auto-detect language
noteagent transcribe path/to/audio.wav --language auto
```

### Import and process a folder of MP3/MP4 files

```bash
# Transcribes each .mp3/.mp4 file and generates a summary per file
noteagent transcribe path/to/media-folder

# Compare model quality across runs (saved side-by-side as transcript.<model>.json/txt)
noteagent transcribe path/to/media-folder --model small.en --quality balanced
noteagent transcribe path/to/media-folder --model medium.en --quality accurate
noteagent transcribe path/to/media-folder --model large-v3 --quality accurate

# Skip summaries during import
noteagent transcribe path/to/media-folder --no-summarize

# Save imported sessions under a custom root
noteagent transcribe path/to/media-folder --output ~/notes/noteagent-imports
```

When transcribing into an existing session, NoteAgent now keeps model outputs side-by-side:

- `transcript.small.en.json` / `transcript.small.en.txt`
- `transcript.medium.en.json` / `transcript.medium.en.txt`
- `transcript.large-v3.json` / `transcript.large-v3.txt`

Imported media sessions also keep a session-local preview asset (for example `preview.mp4`
or `preview.mp3`) so the web UI can continue playing the imported media even if the
original source file moves later.

Meeting sessions now generate a mixed `preview.wav` for web playback, and the web UI
includes file actions to reveal the session folder or original source file in Finder.

### Summarize a session

```bash
noteagent summarize ~/notes/noteagent/sessions/2026-03-13_14-30-00
```

### Export a session

```bash
noteagent export ~/notes/noteagent/sessions/2026-03-13_14-30-00 --format markdown
noteagent export ~/notes/noteagent/sessions/2026-03-13_14-30-00 --format pdf
```

### Configuration

```bash
noteagent config --show                          # view current config
noteagent config --device "BlackHole 2ch"        # set default device
noteagent config --storage-path ~/my-notes       # change storage location
```

Config is stored at `~/.config/noteagent/config.toml`.

---

## Make Targets

```
  help           Show this help
  setup          Complete first-time setup (= build)
  build          Full build: Rust + Python + model download
  venv           Create Python virtual environment
  rust           Build the Rust audio extension
  python         Install the Python package in editable mode
  model          Download the Whisper model
  test           Run the test suite
  serve          Start the web UI
  clean          Remove build artifacts (keeps venv and models)
  distclean      Full clean including venv and downloaded models
```

---

## Project Structure

```
noteagent/
├── noteagent-audio/        # Rust crate — audio capture (cpal + PyO3)
│   └── src/
│       ├── capture.rs      # AudioRecorder, AudioStream
│       ├── device.rs       # Device enumeration
│       ├── error.rs        # Error types
│       └── lib.rs          # PyO3 module
├── src/noteagent/          # Python package
│   ├── cli.py              # Typer CLI
│   ├── audio.py            # Rust wrapper (Recorder, DualRecorder)
│   ├── transcript.py       # Whisper STT (live + batch + meeting)
│   ├── summary.py          # LLM summarization (GitHub Copilot)
│   ├── export.py           # Multi-format export
│   ├── storage.py          # Session & config persistence
│   ├── server.py           # FastAPI web server
│   └── models.py           # Pydantic data models
├── static/                 # Web UI (HTML, CSS, JS)
├── models/                 # Downloaded Whisper models (.pt)
├── tests/                  # Pytest suite
├── docs/                   # Specifications
├── pyproject.toml          # Python project config
└── Makefile                # Build automation
```

---

## Troubleshooting

### `maturin develop` fails

- Ensure Rust is installed: `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`
- Ensure maturin is installed: `pip install maturin`
- On macOS, Xcode command-line tools are required: `xcode-select --install`

### No audio devices listed

- On macOS, grant microphone permission to your terminal app (System Preferences → Privacy & Security → Microphone).

### Whisper model download fails (corporate proxy)

Download manually from the [OpenAI CDN](https://openaipublic.azureedge.net/main/whisper/models/25a8566e1d0c1e2231d1c762132cd20e0f96a85d16145c3a00adf5d1ac670ead/base.en.pt) and place it in `models/base.en.pt`.

### SSL certificate errors

If behind a corporate proxy with SSL inspection:

```bash
security find-certificate -a -p /System/Library/Keychains/SystemRootCertificates.keychain \
  /Library/Keychains/System.keychain > .venv/cacert.pem
export SSL_CERT_FILE=$PWD/.venv/cacert.pem
export REQUESTS_CA_BUNDLE=$PWD/.venv/cacert.pem
pip install truststore
```

Or set a CA bundle explicitly for NoteAgent model downloads:

```bash
export NOTEAGENT_CA_BUNDLE=$PWD/.venv/cacert.pem
# You can also use SSL_CERT_FILE or REQUESTS_CA_BUNDLE
```

NoteAgent now uses a custom Whisper model downloader that respects these CA bundle
environment variables and verifies model checksum after download.

---

## License

MIT
