# Installation Guide

NoteAgent provides automated installers for quick setup on macOS, Linux, and Windows.

## Quick Install

### macOS / Linux

```bash
curl -fsSL https://raw.githubusercontent.com/mkostersitz/noteagent/main/install.sh | bash
```

Or download and run locally:

```bash
git clone https://github.com/mkostersitz/noteagent.git
cd noteagent
./install.sh
```

### Windows

Download and run `install.bat`:

```cmd
git clone https://github.com/mkostersitz/noteagent.git
cd noteagent
install.bat
```

## What the Installer Does

The automated installer:

1. ✅ Checks prerequisites (Python 3.10+, Rust, Git)
2. ✅ Creates installation directory (`~/.noteagent`)
3. ✅ Clones the repository
4. ✅ Creates a Python virtual environment
5. ✅ Builds the Rust audio capture extension
6. ✅ Installs all Python dependencies
7. ✅ Downloads the Whisper base.en model (~140 MB)
8. ✅ Creates launcher scripts
9. ✅ Creates default configuration
10. ✅ Sets up both CLI and Web UI

## Installation Locations

### Default Directories

| Item | Location |
|------|----------|
| **Installation** | `~/.noteagent` |
| **Binary/Launcher** | `~/.local/bin/noteagent` (Unix)<br>`~/.noteagent/noteagent.bat` (Windows) |
| **Virtual Environment** | `~/.noteagent/venv` |
| **Whisper Models** | `~/.noteagent/models` |
| **Configuration** | `~/.config/noteagent/config.toml` |
| **Sessions/Data** | `~/notes/noteagent` (default, configurable) |

### Custom Installation Directory

You can customize the installation location using environment variables:

```bash
# Custom install directory
export NOTEAGENT_INSTALL_DIR=/opt/noteagent
export NOTEAGENT_BIN_DIR=/usr/local/bin
./install.sh
```

## Prerequisites

### Required

| Requirement | Version | Installation |
|-------------|---------|--------------|
| **Python** | 3.10+ | [python.org](https://www.python.org/downloads/) |
| **Rust** | stable | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh` |
| **Git** | any | [git-scm.com](https://git-scm.com/downloads) |

### Optional (macOS)

| Requirement | Purpose | Installation |
|-------------|---------|--------------|
| **BlackHole 2ch** | Dual-channel meeting mode | `brew install blackhole-2ch`<br>[existential.audio/blackhole](https://existential.audio/blackhole/) |
| **GitHub CLI + Copilot** | LLM summarization | `brew install gh`<br>`gh extension install github/gh-copilot` |

## Post-Installation

### 1. Add to PATH (if needed)

If `~/.local/bin` is not in your PATH:

```bash
# Add to ~/.bashrc, ~/.zshrc, or ~/.profile
export PATH="$PATH:$HOME/.local/bin"
```

Then reload your shell:

```bash
source ~/.bashrc  # or ~/.zshrc
```

### 2. Verify Installation

```bash
noteagent --help
noteagent devices  # List available audio devices
```

### 3. Quick Start

**Record a note:**
```bash
noteagent record
```

**Start the web UI:**
```bash
noteagent serve
# Open http://127.0.0.1:8765 in your browser
```

**Meeting mode (dual-channel):**
```bash
noteagent record --meeting \
  --device "MacBook Pro Microphone" \
  --system-device "BlackHole 2ch"
```

## Troubleshooting

### Python Version Issues

The installer requires Python 3.10 or higher. Check your version:

```bash
python3 --version
```

If you have multiple Python versions, you can specify which to use:

```bash
PYTHON=python3.11 ./install.sh
```

### Rust Not Found

Install Rust using rustup:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env
```

### macOS: maturin Build Fails

Ensure Xcode command-line tools are installed:

```bash
xcode-select --install
```

### Permission Denied

Don't run the installer with `sudo`. It installs to your home directory:

```bash
# ❌ Don't do this
sudo ./install.sh

# ✅ Do this
./install.sh
```

### Behind a Corporate Proxy

If you're behind a proxy with SSL inspection:

```bash
# Export CA bundle location
export SSL_CERT_FILE=/path/to/ca-bundle.crt
export REQUESTS_CA_BUNDLE=/path/to/ca-bundle.crt
./install.sh
```

For macOS with custom certificates:

```bash
security find-certificate -a -p \
  /System/Library/Keychains/SystemRootCertificates.keychain \
  /Library/Keychains/System.keychain > ca-bundle.crt
export SSL_CERT_FILE=$PWD/ca-bundle.crt
./install.sh
```

### Model Download Fails

If the Whisper model download fails, download manually:

```bash
mkdir -p ~/.noteagent/models
curl -fSL -o ~/.noteagent/models/base.en.pt \
  "https://openaipublic.azureedge.net/main/whisper/models/25a8566e1d0c1e2231d1c762132cd20e0f96a85d16145c3a00adf5d1ac670ead/base.en.pt"
```

## Uninstalling

### macOS / Linux

```bash
./uninstall.sh
```

### Windows

```cmd
uninstall.bat
```

### What Gets Removed

This removes:
- Installation directory (`~/.noteagent`)
- Launcher script (`~/.local/bin/noteagent` on Unix, `~/.noteagent/noteagent.bat` on Windows)

### What Gets Preserved

These are kept (you can delete manually if desired):
- Configuration (`~/.config/noteagent`)
- Your sessions and recordings (`~/notes/noteagent`)

## Manual Installation

If you prefer manual control, see [Manual Setup](../README.md#manual-setup-step-by-step) in the main README.

## Updating

To update to the latest version:

```bash
# Uninstall current version
./uninstall.sh

# Install latest version
curl -fsSL https://raw.githubusercontent.com/mkostersitz/noteagent/main/install.sh | bash
```

Your configuration and data will be preserved.

## Platform-Specific Notes

### macOS

- **Audio Permissions**: Grant microphone permission to your terminal app (System Settings → Privacy & Security → Microphone)
- **Meeting Mode**: Requires BlackHole 2ch and a Multi-Output Device configured in Audio MIDI Setup

### Linux

- **Audio Backends**: Uses ALSA/PulseAudio via cpal
- **Permissions**: May need to add user to `audio` group: `sudo usermod -a -G audio $USER`

### Windows

- **Audio API**: Uses WASAPI via cpal
- **PATH**: Add `%USERPROFILE%\.noteagent` to system PATH for global access
- **PowerShell**: Run `Set-ExecutionPolicy RemoteSigned` if scripts are blocked

## Development Installation

For development work, use the manual setup with editable installs:

```bash
git clone https://github.com/mkostersitz/noteagent.git
cd noteagent
make setup
source .venv/bin/activate
```

This creates a local `.venv` in the project directory instead of `~/.noteagent`.
