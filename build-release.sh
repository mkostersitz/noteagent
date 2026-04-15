#!/usr/bin/env bash

# NoteAgent Release Builder
# Creates distributable packages with pre-built binaries

set -e

VERSION="0.1.6"
BUILD_DIR="dist"
RELEASE_DIR="$BUILD_DIR/release-$VERSION"
WHEELS_DIR="$RELEASE_DIR/wheels"
STANDALONE_DIR="$RELEASE_DIR/standalone"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
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

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║              NoteAgent Release Builder v$VERSION              ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Clean and create release directory
log_info "Preparing release directory..."
rm -rf "$RELEASE_DIR"
mkdir -p "$RELEASE_DIR"
mkdir -p "$WHEELS_DIR"
mkdir -p "$STANDALONE_DIR"

# Create source tarball
log_info "Creating source tarball..."
git archive --format=tar.gz --prefix="noteagent-$VERSION/" -o "$RELEASE_DIR/noteagent-$VERSION.tar.gz" HEAD
log_success "Source tarball created"

# Build Python wheel (platform-independent, Rust extension will be built separately)
log_info "Building Python wheel..."

# Create temporary venv for building
BUILDVENV="$BUILD_DIR/buildvenv"
if [ ! -d "$BUILDVENV" ]; then
    python3 -m venv "$BUILDVENV"
fi
source "$BUILDVENV/bin/activate"

pip install --upgrade build wheel maturin --quiet

python3 -m build --wheel --outdir "$WHEELS_DIR"

deactivate
log_success "Python wheel created"

# Build Rust audio extension wheels for current platform
log_info "Building Rust audio extension wheel for current platform..."
source "$BUILDVENV/bin/activate"

cd noteagent-audio
maturin build --release --out "$WHEELS_DIR"
cd ..

deactivate
log_success "Rust extension wheel created for $(uname -s)-$(uname -m)"

# Create standalone installer package
log_info "Creating standalone installer package..."
mkdir -p "$STANDALONE_DIR"

# Copy standalone installer script
cp install-standalone.sh "$STANDALONE_DIR/install.sh"
chmod +x "$STANDALONE_DIR/install.sh"

# Copy wheels if they exist
if [ -d "$WHEELS_DIR" ] && [ "$(ls -A $WHEELS_DIR)" ]; then
    mkdir -p "$STANDALONE_DIR/wheels"
    cp "$WHEELS_DIR"/*.whl "$STANDALONE_DIR/wheels/" 2>/dev/null || true
    log_info "Pre-built wheels included in standalone package"
fi

# Copy documentation
cp README.md "$STANDALONE_DIR/"
cp docs/INSTALL.md "$STANDALONE_DIR/"
cp uninstall.sh "$STANDALONE_DIR/"
chmod +x "$STANDALONE_DIR/uninstall.sh"

# Create standalone package archives
cd "$RELEASE_DIR"
tar czf "noteagent-standalone-$VERSION.tar.gz" standalone/
zip -r "noteagent-standalone-$VERSION.zip" standalone/ > /dev/null
cd - > /dev/null

log_success "Standalone installer package created"

# Create development installer package (requires git/rust)
log_info "Creating development installer package..."
mkdir -p "$RELEASE_DIR/installer"
cp install.sh "$RELEASE_DIR/installer/"
cp install.bat "$RELEASE_DIR/installer/"
cp uninstall.sh "$RELEASE_DIR/installer/"
cp uninstall.bat "$RELEASE_DIR/installer/"
cp README.md "$RELEASE_DIR/installer/"
cp docs/INSTALL.md "$RELEASE_DIR/installer/"

# Create installer archive
cd "$RELEASE_DIR"
tar czf "noteagent-installer-dev-$VERSION.tar.gz" installer/
zip -r "noteagent-installer-dev-$VERSION.zip" installer/ > /dev/null
cd - > /dev/null

log_success "Development installer packages created"

# Generate checksums
log_info "Generating checksums..."
cd "$RELEASE_DIR"
shasum -a 256 *.tar.gz *.zip > checksums.txt
cd - > /dev/null
log_success "Checksums generated"

# Create release notes
log_info "Creating release notes..."
cat > "$RELEASE_DIR/RELEASE_NOTES.md" << EOF
# NoteAgent v$VERSION Release

## Installation

### Standalone Installer (Recommended for End Users)

**macOS / Linux:**
\`\`\`bash
# Download and extract standalone package
curl -fSL -o noteagent-standalone-$VERSION.tar.gz \\
  "$RELEASE_URL/noteagent-standalone-$VERSION.tar.gz"
tar xzf noteagent-standalone-$VERSION.tar.gz
cd standalone
./install.sh
\`\`\`

**Features:**
- ✅ No Git required
- ✅ Installs from pre-built release package
- ⚠️ Still requires Rust if pre-built wheels aren't available for your platform

### Development Installer (For Developers)

**macOS / Linux:**
\`\`\`bash
curl -fsSL https://raw.githubusercontent.com/mkostersitz/noteagent/main/install.sh | bash
\`\`\`

**Windows:**
Download \`noteagent-installer-dev-$VERSION.zip\`, extract, and run \`install.bat\`

**Features:**
- ✅ Clones from Git
- ✅ Builds from source
- ⚠️ Requires Git and Rust

## What's Included

- ✅ CLI tool for recording, transcription, and export
- ✅ Web UI for session management and configuration
- ✅ Live transcription with OpenAI Whisper
- ✅ Dual-channel meeting mode (macOS with BlackHole)
- ✅ LLM summarization (via GitHub Copilot CLI)
- ✅ Multi-format export (Markdown, Text, JSON, SRT, VTT, PDF)
- ✅ Authentication and rate limiting
- ✅ Batch transcription of media files

## Requirements

- Python 3.10+
- Rust (if pre-built wheels unavailable for your platform)

### Optional
- BlackHole 2ch (macOS, for meeting mode)
- GitHub CLI + Copilot extension (for LLM summaries)

## Files

| File | Description | Size |
|------|-------------|------|
| \`noteagent-$VERSION.tar.gz\` | Full source code | $(du -h "$RELEASE_DIR/noteagent-$VERSION.tar.gz" 2>/dev/null | cut -f1 || echo "N/A") |
| \`noteagent-standalone-$VERSION.tar.gz\` | Standalone installer (Unix) | $(du -h "$RELEASE_DIR/noteagent-standalone-$VERSION.tar.gz" 2>/dev/null | cut -f1 || echo "N/A") |
| \`noteagent-standalone-$VERSION.zip\` | Standalone installer (Windows) | $(du -h "$RELEASE_DIR/noteagent-standalone-$VERSION.zip" 2>/dev/null | cut -f1 || echo "N/A") |
| \`noteagent-installer-dev-$VERSION.tar.gz\` | Dev installer (Unix) | $(du -h "$RELEASE_DIR/noteagent-installer-dev-$VERSION.tar.gz" 2>/dev/null | cut -f1 || echo "N/A") |
| \`noteagent-installer-dev-$VERSION.zip\` | Dev installer (Windows) | $(du -h "$RELEASE_DIR/noteagent-installer-dev-$VERSION.zip" 2>/dev/null | cut -f1 || echo "N/A") |
| \`checksums.txt\` | SHA-256 checksums | - |

## Pre-built Wheels

Platform-specific wheels for the Rust audio extension:

\`\`\`
$(ls -1 "$WHEELS_DIR"/*.whl 2>/dev/null | xargs -n1 basename || echo "No pre-built wheels available yet")
\`\`\`

## Checksums

\`\`\`
$(cat "$RELEASE_DIR/checksums.txt" 2>/dev/null || echo "Checksums will be generated")
\`\`\`

## Documentation

- [README.md](README.md) - Overview and quick start
- [INSTALL.md](INSTALL.md) - Detailed installation guide

## Support

- Issues: https://github.com/mkostersitz/noteagent/issues
- Repository: https://github.com/mkostersitz/noteagent
EOF

log_success "Release notes created"

# Print summary
echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                    Release Build Complete                      ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
log_info "Release artifacts:"
echo "  📦 Source:"
echo "     • noteagent-$VERSION.tar.gz"
echo ""
echo "  📦 Standalone Installer (no Git required):"
echo "     • noteagent-standalone-$VERSION.tar.gz (Unix/macOS)"
echo "     • noteagent-standalone-$VERSION.zip (Windows)"
echo ""
echo "  📦 Development Installer (requires Git + Rust):"
echo "     • noteagent-installer-dev-$VERSION.tar.gz (Unix/macOS)"
echo "     • noteagent-installer-dev-$VERSION.zip (Windows)"
echo ""
echo "  🎯 Pre-built Wheels:"
if [ -d "$WHEELS_DIR" ] && [ "$(ls -A $WHEELS_DIR 2>/dev/null)" ]; then
    ls -1 "$WHEELS_DIR"/*.whl 2>/dev/null | xargs -n1 basename | sed 's/^/     • /'
else
    echo "     • None (build on target platform required)"
fi
echo ""
echo "  📄 Documentation:"
echo "     • checksums.txt"
echo "     • RELEASE_NOTES.md"
echo ""
log_info "All files in: $RELEASE_DIR"
echo ""
log_info "Next steps:"
echo "  1. Test standalone installer on target platforms"
echo "  2. Build platform-specific wheels (macOS/Linux/Windows)"
echo "  3. Create GitHub release and upload artifacts"
echo "  4. Update release notes with changelog"
echo ""
log_success "Release v$VERSION ready for distribution"
