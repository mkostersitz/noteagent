#!/usr/bin/env bash

set -e

INSTALL_DIR="${NOTEAGENT_INSTALL_DIR:-$HOME/.noteagent}"
BIN_DIR="${NOTEAGENT_BIN_DIR:-$HOME/.local/bin}"
CONFIG_DIR="$HOME/.config/noteagent"

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

confirm() {
    local prompt="$1"
    read -p "$prompt [y/N] " -n 1 -r
    echo
    [[ $REPLY =~ ^[Yy]$ ]]
}

uninstall() {
    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║                   NoteAgent Uninstaller                        ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""
    
    log_warning "This will remove NoteAgent from your system"
    echo ""
    echo "The following will be deleted:"
    echo "  • $INSTALL_DIR"
    echo "  • $BIN_DIR/noteagent"
    echo ""
    echo "The following will be preserved (you can delete manually if desired):"
    echo "  • $CONFIG_DIR (configuration)"
    echo "  • ~/notes/noteagent (your sessions and recordings)"
    echo ""
    
    if ! confirm "Continue with uninstallation?"; then
        log_info "Uninstallation cancelled"
        exit 0
    fi
    
    log_info "Uninstalling NoteAgent..."
    
    # Stop any running server
    if [ -f "$INSTALL_DIR/.server.pid" ]; then
        local pid=$(cat "$INSTALL_DIR/.server.pid")
        if ps -p "$pid" > /dev/null 2>&1; then
            log_info "Stopping running server (PID: $pid)..."
            kill "$pid" 2>/dev/null || true
            sleep 1
        fi
    fi
    
    # Remove installation directory
    if [ -d "$INSTALL_DIR" ]; then
        rm -rf "$INSTALL_DIR"
        log_success "Removed $INSTALL_DIR"
    fi
    
    # Remove launcher script
    if [ -f "$BIN_DIR/noteagent" ]; then
        rm -f "$BIN_DIR/noteagent"
        log_success "Removed $BIN_DIR/noteagent"
    fi
    
    echo ""
    log_success "NoteAgent has been uninstalled"
    echo ""
    log_info "Configuration and data preserved at:"
    echo "  • $CONFIG_DIR"
    echo "  • ~/notes/noteagent"
    echo ""
    log_info "To remove these as well, run:"
    echo "  rm -rf $CONFIG_DIR"
    echo "  rm -rf ~/notes/noteagent"
    echo ""
}

# Check if running with sudo (not recommended)
if [ "$EUID" -eq 0 ]; then
    log_error "Please do not run this script with sudo"
    exit 1
fi

uninstall
