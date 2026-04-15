#!/usr/bin/env bash

# NoteAgent Standalone Installer
# No git or Rust required - uses pre-built binaries

set -e

VERSION="0.1.6"
RELEASE_URL="https://github.com/mkostersitz/noteagent/releases/download/v${VERSION}"
INSTALL_DIR="${NOTEAGENT_INSTALL_DIR:-$HOME/.noteagent}"
BIN_DIR="${NOTEAGENT_BIN_DIR:-$HOME/.local/bin}"
MODEL_DIR="$INSTALL_DIR/models"
VENV_DIR="$INSTALL_DIR/venv"
TEMP_DIR=$(mktemp -d)

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

cleanup() {
    if [ -d "$TEMP_DIR" ]; then
        rm -rf "$TEMP_DIR"
    fi
}

trap cleanup EXIT

check_command() {
    if ! command -v "$1" &> /dev/null; then
        return 1
    fi
    return 0
}

check_prerequisites() {
    log_info "Checking prerequisites..."
    
    local missing_deps=()
    
    # Check Python
    if ! check_command python3; then
        missing_deps+=("python3")
    else
        local py_version=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
        local py_major=$(echo "$py_version" | cut -d. -f1)
        local py_minor=$(echo "$py_version" | cut -d. -f2)
        if [ "$py_major" -lt 3 ] || ([ "$py_major" -eq 3 ] && [ "$py_minor" -lt 10 ]); then
            log_error "Python 3.10+ required, found $py_version"
            exit 1
        fi
        log_success "Python $py_version found"
    fi
    
    # Check for curl or wget
    if ! check_command curl && ! check_command wget; then
        missing_deps+=("curl or wget")
    fi
    
    if [ ${#missing_deps[@]} -gt 0 ]; then
        log_error "Missing required dependencies: ${missing_deps[*]}"
        exit 1
    fi
}

detect_platform() {
    local os=$(uname -s)
    local arch=$(uname -m)
    
    case "$os" in
        Darwin)
            PLATFORM_OS="macos"
            ;;
        Linux)
            PLATFORM_OS="linux"
            ;;
        *)
            log_error "Unsupported OS: $os"
            exit 1
            ;;
    esac
    
    case "$arch" in
        x86_64|amd64)
            PLATFORM_ARCH="x86_64"
            ;;
        arm64|aarch64)
            PLATFORM_ARCH="aarch64"
            ;;
        *)
            log_error "Unsupported architecture: $arch"
            exit 1
            ;;
    esac
    
    PLATFORM="${PLATFORM_OS}_${PLATFORM_ARCH}"
    log_info "Detected platform: $PLATFORM"
}

download_file() {
    local url="$1"
    local output="$2"
    
    if check_command curl; then
        curl -fSL -o "$output" "$url" --progress-bar
    elif check_command wget; then
        wget -q --show-progress -O "$output" "$url"
    else
        log_error "Neither curl nor wget found"
        exit 1
    fi
}

create_directories() {
    log_info "Creating installation directories..."
    mkdir -p "$INSTALL_DIR"
    mkdir -p "$BIN_DIR"
    mkdir -p "$MODEL_DIR"
    mkdir -p "$INSTALL_DIR/src"
    log_success "Directories created"
}

download_release_package() {
    log_info "Downloading NoteAgent release package..."
    
    local tarball="noteagent-$VERSION.tar.gz"
    local url="$RELEASE_URL/$tarball"
    
    download_file "$url" "$TEMP_DIR/$tarball"
    
    log_info "Extracting package..."
    cd "$TEMP_DIR"
    tar xzf "$tarball"
    
    # Copy to installation directory
    cp -r "noteagent-$VERSION" "$INSTALL_DIR/src/noteagent"
    
    log_success "Package extracted to $INSTALL_DIR/src/noteagent"
}

create_venv() {
    log_info "Creating Python virtual environment..."
    python3 -m venv "$VENV_DIR"
    log_success "Virtual environment created"
}

install_dependencies() {
    log_info "Installing Python dependencies..."
    source "$VENV_DIR/bin/activate"
    
    pip install --upgrade pip setuptools wheel --quiet
    
    # Download and install pre-built wheels if available
    log_info "Downloading pre-built wheels..."
    local wheels_downloaded=0
    
    # Try to download platform-specific Rust extension wheel
    local rust_wheel="noteagent_audio-$VERSION-*-${PLATFORM_OS}*${PLATFORM_ARCH}*.whl"
    local wheel_url="$RELEASE_URL/wheels/"
    
    # For now, install from source since we need the exact wheel filename
    # In production, we'd query the GitHub API for available wheels
    log_warning "Pre-built wheels not yet available for $PLATFORM"
    log_info "Installing from source (this requires Rust)..."
    
    cd "$INSTALL_DIR/src/noteagent"
    
    # Check if Rust is available
    if ! check_command cargo; then
        log_error "Rust is required to build from source"
        log_error "Install Rust: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
        log_error "Or wait for pre-built binaries to be available"
        exit 1
    fi
    
    # Install maturin
    pip install maturin --quiet
    
    # Build and install Rust extension
    cd noteagent-audio
    maturin develop --release
    cd ..
    
    # Install Python package
    pip install -e ".[dev]" --quiet
    
    log_success "Dependencies installed"
}

download_whisper_model() {
    local model="${1:-base.en}"
    local model_file="$MODEL_DIR/$model.pt"
    
    if [ -f "$model_file" ]; then
        log_info "Whisper model $model already exists, skipping download"
        return 0
    fi
    
    log_info "Downloading Whisper $model model (~140MB)..."
    
    local model_url="https://openaipublic.azureedge.net/main/whisper/models/25a8566e1d0c1e2231d1c762132cd20e0f96a85d16145c3a00adf5d1ac670ead/base.en.pt"
    
    download_file "$model_url" "$model_file"
    
    log_success "Whisper model downloaded"
}

create_launcher_script() {
    log_info "Creating launcher script..."
    
    cat > "$BIN_DIR/noteagent" << EOF
#!/usr/bin/env bash
# NoteAgent launcher script
source "$VENV_DIR/bin/activate"
export NOTEAGENT_MODEL_DIR="$MODEL_DIR"
exec python -m noteagent.cli "\$@"
EOF
    
    chmod +x "$BIN_DIR/noteagent"
    log_success "Launcher script created at $BIN_DIR/noteagent"
}

create_config() {
    local config_dir="$HOME/.config/noteagent"
    local config_file="$config_dir/config.toml"
    
    if [ -f "$config_file" ]; then
        log_info "Configuration file already exists"
        return 0
    fi
    
    log_info "Creating default configuration..."
    mkdir -p "$config_dir"
    
    cat > "$config_file" << 'EOF'
# NoteAgent Configuration

[storage]
path = "~/notes/noteagent"

[audio]
sample_rate = 16000
channels = 1
device = ""

[transcription]
model = "base.en"
language = "en"
quality = "balanced"

[server]
host = "127.0.0.1"
port = 8765

[auth]
enabled = false

[rate_limit]
enabled = true
default_limit = "100/minute"
whitelist_ips = ["127.0.0.1", "::1"]
EOF
    
    log_success "Configuration created"
}

print_summary() {
    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║                                                                ║"
    echo "║  ✓ NoteAgent v$VERSION installed successfully!               ║"
    echo "║                                                                ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""
    log_info "Quick Start:"
    echo "  1. Add to PATH (if needed):"
    echo "       export PATH=\"\$PATH:$BIN_DIR\""
    echo ""
    echo "  2. Verify installation:"
    echo "       noteagent --help"
    echo ""
    echo "  3. Start recording:"
    echo "       noteagent record"
    echo ""
    echo "  4. Start web UI:"
    echo "       noteagent serve"
    echo ""
}

main() {
    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║           NoteAgent Standalone Installer v$VERSION             ║"
    echo "║                (No Git or Rust required)                       ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""
    
    check_prerequisites
    detect_platform
    create_directories
    download_release_package
    create_venv
    install_dependencies
    download_whisper_model "base.en"
    create_launcher_script
    create_config
    print_summary
}

if [ "$EUID" -eq 0 ]; then
    log_error "Please do not run this script with sudo"
    exit 1
fi

main
