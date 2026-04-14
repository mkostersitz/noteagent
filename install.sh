#!/usr/bin/env bash

set -e

VERSION="0.1.6"
REPO_URL="https://github.com/mkostersitz/noteagent"
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
NC='\033[0m' # No Color

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
    
    # Check Rust
    if ! check_command rustc; then
        missing_deps+=("rust")
    else
        local rust_version=$(rustc --version | cut -d' ' -f2)
        log_success "Rust $rust_version found"
    fi
    
    # Check Git
    if ! check_command git; then
        missing_deps+=("git")
    else
        log_success "Git found"
    fi
    
    # Check Cargo
    if ! check_command cargo; then
        missing_deps+=("cargo")
    fi
    
    if [ ${#missing_deps[@]} -gt 0 ]; then
        log_error "Missing required dependencies: ${missing_deps[*]}"
        log_info "Please install the missing dependencies and try again:"
        for dep in "${missing_deps[@]}"; do
            case $dep in
                python3)
                    echo "  - Python 3.10+: https://www.python.org/downloads/"
                    ;;
                rust|cargo)
                    echo "  - Rust: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
                    ;;
                git)
                    echo "  - Git: https://git-scm.com/downloads"
                    ;;
            esac
        done
        exit 1
    fi
}

check_macos_dependencies() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        log_info "Checking macOS-specific dependencies..."
        
        # Check for BlackHole (optional)
        if ! system_profiler SPAudioDataType 2>/dev/null | grep -q "BlackHole"; then
            log_warning "BlackHole not found - required for meeting mode (dual-channel recording)"
            log_info "Install with: brew install blackhole-2ch"
            log_info "Or download from: https://existential.audio/blackhole/"
        else
            log_success "BlackHole audio driver found"
        fi
    fi
}

create_directories() {
    log_info "Creating installation directories..."
    mkdir -p "$INSTALL_DIR"
    mkdir -p "$BIN_DIR"
    mkdir -p "$MODEL_DIR"
    log_success "Directories created"
}

clone_repository() {
    log_info "Cloning NoteAgent repository..."
    cd "$TEMP_DIR"
    git clone --depth 1 --branch main "$REPO_URL" noteagent
    cd noteagent
    log_success "Repository cloned"
}

create_venv() {
    log_info "Creating Python virtual environment..."
    python3 -m venv "$VENV_DIR"
    log_success "Virtual environment created at $VENV_DIR"
}

install_python_dependencies() {
    log_info "Installing Python dependencies..."
    source "$VENV_DIR/bin/activate"
    
    # Install maturin first
    pip install --upgrade pip setuptools wheel --quiet
    pip install maturin --quiet
    
    log_success "Base dependencies installed"
}

copy_source_files() {
    log_info "Copying source files to installation directory..."
    
    # Ensure src directory exists
    mkdir -p "$INSTALL_DIR/src"
    
    # Verify source exists
    if [ ! -d "$TEMP_DIR/noteagent" ]; then
        log_error "Source directory $TEMP_DIR/noteagent not found"
        exit 1
    fi
    
    # Copy the entire noteagent directory to install location
    cp -r "$TEMP_DIR/noteagent" "$INSTALL_DIR/src/"
    
    # Verify copy succeeded
    if [ ! -d "$INSTALL_DIR/src/noteagent" ]; then
        log_error "Failed to copy source files to $INSTALL_DIR/src/noteagent"
        exit 1
    fi
    
    log_success "Source files copied to $INSTALL_DIR/src/noteagent"
}

build_rust_extension() {
    log_info "Building Rust audio extension..."
    source "$VENV_DIR/bin/activate"
    
    # Verify directory exists before changing to it
    if [ ! -d "$INSTALL_DIR/src/noteagent/noteagent-audio" ]; then
        log_error "Rust audio directory not found at $INSTALL_DIR/src/noteagent/noteagent-audio"
        log_error "Contents of $INSTALL_DIR/src/noteagent:"
        ls -la "$INSTALL_DIR/src/noteagent" 2>&1 || echo "Directory doesn't exist"
        exit 1
    fi
    
    cd "$INSTALL_DIR/src/noteagent/noteagent-audio"
    
    # Build the Rust extension
    maturin develop --release
    
    log_success "Rust extension built"
}

install_noteagent() {
    log_info "Installing NoteAgent Python package..."
    source "$VENV_DIR/bin/activate"
    cd "$INSTALL_DIR/src/noteagent"
    
    # Install the package in editable mode from permanent location
    pip install -e ".[dev]" --quiet
    
    log_success "NoteAgent package installed"
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
    
    if check_command curl; then
        curl -fSL -o "$model_file" "$model_url" --progress-bar
    elif check_command wget; then
        wget -q --show-progress -O "$model_file" "$model_url"
    else
        log_error "Neither curl nor wget found. Cannot download model."
        exit 1
    fi
    
    log_success "Whisper model downloaded to $model_file"
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
        log_info "Configuration file already exists at $config_file"
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
token_header = "Authorization"
token_prefix = "Bearer"

[rate_limit]
enabled = true
default_limit = "100/minute"
whitelist_ips = ["127.0.0.1", "::1"]
EOF
    
    log_success "Configuration created at $config_file"
}

check_path() {
    if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
        log_warning "$BIN_DIR is not in your PATH"
        log_info "Add the following to your shell profile (~/.bashrc, ~/.zshrc, etc.):"
        echo ""
        echo "    export PATH=\"\$PATH:$BIN_DIR\""
        echo ""
    fi
}

print_summary() {
    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║                                                                ║"
    echo "║  ✓ NoteAgent v$VERSION installed successfully!               ║"
    echo "║                                                                ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""
    log_info "Installation Details:"
    echo "  • Install directory: $INSTALL_DIR"
    echo "  • Binary directory:  $BIN_DIR"
    echo "  • Virtual env:       $VENV_DIR"
    echo "  • Models:            $MODEL_DIR"
    echo "  • Config:            ~/.config/noteagent/config.toml"
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
    log_info "Optional:"
    echo "  • Install GitHub CLI for LLM summaries:"
    echo "      brew install gh"
    echo "      gh extension install github/gh-copilot"
    echo ""
    echo "  • For meeting mode, install BlackHole:"
    echo "      brew install blackhole-2ch"
    echo ""
}

main() {
    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║                    NoteAgent Installer                         ║"
    echo "║                        v$VERSION                                 ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""
    
    check_prerequisites
    check_macos_dependencies
    create_directories
    clone_repository
    copy_source_files
    create_venv
    install_python_dependencies
    build_rust_extension
    install_noteagent
    download_whisper_model "base.en"
    create_launcher_script
    create_config
    check_path
    print_summary
}

# Check if running with sudo (not recommended)
if [ "$EUID" -eq 0 ]; then
    log_error "Please do not run this script with sudo"
    log_info "The installer will create files in your home directory"
    exit 1
fi

main
