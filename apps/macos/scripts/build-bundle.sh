#!/usr/bin/env bash
#
# build-bundle.sh — assemble the embedded Python + ggml model that the
# NoteAgent.app needs to run standalone on a machine with no developer tools.
#
# Output tree (relative to the repo root):
#
#   apps/macos/BuiltResources/
#   ├── python/                     # python-build-standalone install
#   │   ├── bin/python3
#   │   ├── lib/python3.<minor>/site-packages/
#   │   │   ├── noteagent/          # editable repo source
#   │   │   ├── noteagent_audio.so  # whisper-rs PyO3 wheel
#   │   │   ├── fastapi/, uvicorn/, …
#   │   └── …
#   ├── static/                     # web UI assets (copy of repo's static/)
#   └── models/
#       └── ggml-base.en.bin        # bundled default model
#
# The Xcode build phase copies BuiltResources/{python,static,models} into
# NoteAgent.app/Contents/Resources/ at archive time.
#
# Idempotent: re-running skips steps whose output already exists.
# Honors PYTHON_VERSION and PBS_RELEASE env vars for pinning.

set -euo pipefail

# ── Paths ──────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
OUT_DIR="$REPO_ROOT/apps/macos/BuiltResources"
PY_DIR="$OUT_DIR/python"
STATIC_DIR="$OUT_DIR/static"
MODELS_DIR="$OUT_DIR/models"

# ── Pinned versions ────────────────────────────────────────────────────────
# python-build-standalone tag, e.g. "20251002". Bump intentionally so builds
# are reproducible; see https://github.com/astral-sh/python-build-standalone/releases
PBS_RELEASE="${PBS_RELEASE:-20260510}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12.13}"
DEFAULT_MODEL="${DEFAULT_MODEL:-base.en}"

# Apple Silicon only per the Phase 2 plan. install_only is the slim,
# pre-configured variant with no headers / static libs.
PBS_FILENAME="cpython-${PYTHON_VERSION}+${PBS_RELEASE}-aarch64-apple-darwin-install_only.tar.gz"
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_RELEASE}/${PBS_FILENAME}"

# ── Helpers ────────────────────────────────────────────────────────────────
log() { printf "\033[1;36m[build-bundle]\033[0m %s\n" "$*" >&2; }
die() { printf "\033[1;31m[build-bundle]\033[0m %s\n" "$*" >&2; exit 1; }

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

require_cmd curl
require_cmd tar
require_cmd cargo
[[ "$(uname -m)" == "arm64" ]] || die "This script targets Apple Silicon only; got $(uname -m)"

# maturin doesn't need to be on PATH — search common venv locations. A
# developer with `make build` will have it under venv_test/, .noteagent/,
# or a custom venv. NOTEAGENT_MATURIN can override.
find_maturin() {
    if [[ -n "${NOTEAGENT_MATURIN:-}" && -x "$NOTEAGENT_MATURIN" ]]; then
        echo "$NOTEAGENT_MATURIN"; return
    fi
    if command -v maturin >/dev/null 2>&1; then
        command -v maturin; return
    fi
    local candidates=(
        "$REPO_ROOT/venv_test/bin/maturin"
        "$REPO_ROOT/.venv/bin/maturin"
        "$REPO_ROOT/dist/buildvenv/bin/maturin"
        "$HOME/.noteagent/venv/bin/maturin"
        "$HOME/.local/bin/maturin"
    )
    for c in "${candidates[@]}"; do
        [[ -x "$c" ]] && echo "$c" && return
    done
    return 1
}
MATURIN="$(find_maturin)" || die "maturin not found. Set NOTEAGENT_MATURIN or run \`make build\`."
log "Using maturin: $MATURIN"

mkdir -p "$OUT_DIR" "$MODELS_DIR"

# ── Step 1: python-build-standalone ────────────────────────────────────────
PY_VERSION_MARKER="$PY_DIR/.pbs-version"
EXPECTED_MARKER="${PYTHON_VERSION}+${PBS_RELEASE}"

if [[ -d "$PY_DIR" && -f "$PY_VERSION_MARKER" && "$(cat "$PY_VERSION_MARKER")" == "$EXPECTED_MARKER" ]]; then
    log "python-build-standalone $EXPECTED_MARKER already present"
else
    log "Fetching python-build-standalone $EXPECTED_MARKER"
    TARBALL="$OUT_DIR/.pbs.tar.gz"
    curl --fail --location --silent --show-error -o "$TARBALL" "$PBS_URL" \
        || die "Download failed: $PBS_URL"

    rm -rf "$PY_DIR"
    mkdir -p "$PY_DIR"
    # The tarball unpacks to ./python/ — extract its contents directly into
    # $PY_DIR by stripping that prefix into the target.
    tar -xzf "$TARBALL" -C "$PY_DIR" --strip-components=1 python
    rm -f "$TARBALL"
    echo -n "$EXPECTED_MARKER" > "$PY_VERSION_MARKER"
    log "Extracted to $PY_DIR"
fi

PY_BIN="$PY_DIR/bin/python3"
[[ -x "$PY_BIN" ]] || die "Bundled python not executable: $PY_BIN"

PY_MINOR="$("$PY_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
SITE_PACKAGES="$PY_DIR/lib/python${PY_MINOR}/site-packages"
[[ -d "$SITE_PACKAGES" ]] || die "site-packages not found: $SITE_PACKAGES"

# ── Step 2: build the PyO3 wheel against the bundled Python ────────────────
log "Building noteagent-py wheel for bundled Python $PY_MINOR"
WHEEL_DIR="$REPO_ROOT/target/wheels"
mkdir -p "$WHEEL_DIR"

# maturin needs the *interpreter* path to pick the right ABI tag.
(
    cd "$REPO_ROOT/crates/noteagent-py"
    "$MATURIN" build --release --interpreter "$PY_BIN" --out "$WHEEL_DIR" >&2
)

WHEEL_FILE="$(ls -t "$WHEEL_DIR"/noteagent_py-*-cp${PY_MINOR/./}*-*macosx*arm64*.whl 2>/dev/null | head -1)"
[[ -n "$WHEEL_FILE" ]] || die "noteagent-py wheel not found in $WHEEL_DIR"
log "Built wheel: $(basename "$WHEEL_FILE")"

# ── Step 3: install noteagent + deps into the bundled site-packages ────────
log "Installing noteagent + deps into bundled site-packages"
"$PY_BIN" -m ensurepip --upgrade >/dev/null 2>&1 || true
"$PY_BIN" -m pip install --upgrade --quiet pip wheel

# Install the PyO3 wheel first so the noteagent dep on noteagent_audio
# (via import) resolves. --force-reinstall is cheap and keeps re-runs sane.
"$PY_BIN" -m pip install --quiet --force-reinstall --no-deps "$WHEEL_FILE"

# Now noteagent itself + its declared deps. We install non-editable so the
# resulting site-packages is self-contained.
"$PY_BIN" -m pip install --quiet "$REPO_ROOT"

# ── Step 4: slim the bundle ────────────────────────────────────────────────
log "Stripping caches"
find "$PY_DIR" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find "$PY_DIR" -type f -name '*.pyc' -delete 2>/dev/null || true
# pip and its vendored deps live in site-packages and aren't needed at
# runtime. Keep them on disk for now in case install-time issues surface —
# trim later if bundle size matters.

# ── Step 5: copy static web UI assets ──────────────────────────────────────
log "Syncing static/ web UI assets"
rm -rf "$STATIC_DIR"
cp -R "$REPO_ROOT/static" "$STATIC_DIR"

# ── Step 6: bundle the default ggml model ──────────────────────────────────
MODEL_FILE="$MODELS_DIR/ggml-${DEFAULT_MODEL}.bin"
if [[ -f "$MODEL_FILE" ]]; then
    log "Default model already present: $(basename "$MODEL_FILE")"
else
    log "Downloading ggml-${DEFAULT_MODEL}.bin via the bundled noteagent CLI"
    NOTEAGENT_MODEL_DIR="$MODELS_DIR" \
        "$PY_BIN" -m noteagent.cli download-model "$DEFAULT_MODEL" \
        || die "Model download failed"
fi

# ── Done ───────────────────────────────────────────────────────────────────
log "Bundle ready at $OUT_DIR"
log "Python:  $PY_BIN"
log "Wheel:   $(basename "$WHEEL_FILE")"
log "Model:   $(basename "$MODEL_FILE")"

# Quick smoke test: can the bundled Python import noteagent + noteagent_audio?
"$PY_BIN" -c 'import noteagent; import noteagent_audio; print("smoke test OK", noteagent.__file__)' >&2
