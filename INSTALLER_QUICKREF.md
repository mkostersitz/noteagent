# Quick Reference: NoteAgent Installer

## Installation

### macOS / Linux
```bash
curl -fsSL https://raw.githubusercontent.com/mkostersitz/noteagent/main/install.sh | bash
```

### Windows
```cmd
git clone https://github.com/mkostersitz/noteagent.git
cd noteagent
install.bat
```

## Verification

```bash
noteagent --help
noteagent devices
```

## Usage

```bash
# CLI
noteagent record                    # Start recording
noteagent record --meeting          # Dual-channel meeting mode
noteagent transcribe audio.wav      # Transcribe existing file
noteagent summarize SESSION_DIR     # Summarize session
noteagent export SESSION_DIR --format pdf

# Web UI
noteagent serve                     # Start at http://127.0.0.1:8765
noteagent serve --port 9000         # Custom port
noteagent stop                      # Stop server

# Configuration
noteagent config --show             # View config
noteagent config --device "Device"  # Set default device
```

## Locations

| Item | Path |
|------|------|
| Install | `~/.noteagent/` |
| Binary | `~/.local/bin/noteagent` (Unix)<br>`~/.noteagent/noteagent.bat` (Windows) |
| Config | `~/.config/noteagent/config.toml` |
| Models | `~/.noteagent/models/` |
| Data | `~/notes/noteagent/` (default) |

## Uninstall

### macOS / Linux
```bash
./uninstall.sh
```

### Windows
```cmd
uninstall.bat
```

Preserves: config and session data

## Custom Install

```bash
export NOTEAGENT_INSTALL_DIR=/opt/noteagent
export NOTEAGENT_BIN_DIR=/usr/local/bin
./install.sh
```

## Prerequisites

- Python 3.10+
- Rust (stable)
- Git

### Optional
- BlackHole 2ch (macOS meeting mode)
- GitHub CLI + Copilot (LLM summaries)

## Troubleshooting

### Python version
```bash
python3 --version  # Should be 3.10+
```

### Rust not found
```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env
```

### macOS build fails
```bash
xcode-select --install
```

### PATH issues
```bash
export PATH="$PATH:$HOME/.local/bin"
```

## Building Releases

```bash
make release
```

Creates:
- `dist/release-VERSION/noteagent-VERSION.tar.gz`
- `dist/release-VERSION/noteagent-installer-VERSION.tar.gz`
- `dist/release-VERSION/noteagent-installer-VERSION.zip`
- `dist/release-VERSION/checksums.txt`

## GitHub Actions

Push version tag to trigger release:
```bash
git tag v0.1.6
git push origin v0.1.6
```

Auto-creates GitHub release with artifacts.
