#!/usr/bin/env bash

# NoteAgent Release Builder
# Creates distributable packages for all platforms

set -e

VERSION="0.1.6"
BUILD_DIR="dist"
RELEASE_DIR="$BUILD_DIR/release-$VERSION"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║              NoteAgent Release Builder v$VERSION              ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Clean and create release directory
log_info "Preparing release directory..."
rm -rf "$RELEASE_DIR"
mkdir -p "$RELEASE_DIR"

# Create source tarball
log_info "Creating source tarball..."
git archive --format=tar.gz --prefix="noteagent-$VERSION/" -o "$RELEASE_DIR/noteagent-$VERSION.tar.gz" HEAD
log_success "Source tarball created"

# Create installer package
log_info "Creating installer package..."
mkdir -p "$RELEASE_DIR/installer"
cp install.sh "$RELEASE_DIR/installer/"
cp install.bat "$RELEASE_DIR/installer/"
cp uninstall.sh "$RELEASE_DIR/installer/"
cp README.md "$RELEASE_DIR/installer/"
cp docs/INSTALL.md "$RELEASE_DIR/installer/"

# Create installer archive
cd "$RELEASE_DIR"
tar czf "noteagent-installer-$VERSION.tar.gz" installer/
zip -r "noteagent-installer-$VERSION.zip" installer/ > /dev/null
cd - > /dev/null

log_success "Installer packages created"

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

### Quick Install

**macOS / Linux:**
\`\`\`bash
curl -fsSL https://raw.githubusercontent.com/mkostersitz/noteagent/main/install.sh | bash
\`\`\`

**Windows:**
Download \`noteagent-installer-$VERSION.zip\`, extract, and run \`install.bat\`

### Manual Installation

Download \`noteagent-$VERSION.tar.gz\` and follow the [Installation Guide](INSTALL.md)

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
- Rust (stable)
- Git

### Optional
- BlackHole 2ch (macOS, for meeting mode)
- GitHub CLI + Copilot extension (for LLM summaries)

## Files

| File | Description | Size |
|------|-------------|------|
| \`noteagent-$VERSION.tar.gz\` | Full source code | $(du -h "$RELEASE_DIR/noteagent-$VERSION.tar.gz" | cut -f1) |
| \`noteagent-installer-$VERSION.tar.gz\` | Installer scripts (Unix) | $(du -h "$RELEASE_DIR/noteagent-installer-$VERSION.tar.gz" | cut -f1) |
| \`noteagent-installer-$VERSION.zip\` | Installer scripts (Windows) | $(du -h "$RELEASE_DIR/noteagent-installer-$VERSION.zip" | cut -f1) |
| \`checksums.txt\` | SHA-256 checksums | - |

## Checksums

\`\`\`
$(cat "$RELEASE_DIR/checksums.txt")
\`\`\`

## Documentation

- [README.md](README.md) - Overview and quick start
- [INSTALL.md](INSTALL.md) - Detailed installation guide
- [Troubleshooting](INSTALL.md#troubleshooting) - Common issues

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
echo "  📦 $RELEASE_DIR/noteagent-$VERSION.tar.gz"
echo "  📦 $RELEASE_DIR/noteagent-installer-$VERSION.tar.gz"
echo "  📦 $RELEASE_DIR/noteagent-installer-$VERSION.zip"
echo "  📄 $RELEASE_DIR/checksums.txt"
echo "  📄 $RELEASE_DIR/RELEASE_NOTES.md"
echo ""
log_info "Next steps:"
echo "  1. Test installation on target platforms"
echo "  2. Create GitHub release with these artifacts"
echo "  3. Update release notes with changelog"
echo ""
log_success "Release v$VERSION ready for distribution"
