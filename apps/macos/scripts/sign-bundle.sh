#!/usr/bin/env bash
#
# sign-bundle.sh — sign every binary inside NoteAgent.app with the hardened
# runtime and the project's entitlements, in the order Apple requires
# (inside-out: nested Mach-O files first, then the .app shell).
#
# Run after `make app` produces NoteAgent.app under apps/macos/build/.
# Requires the Developer ID Application signing identity in the keychain.
#
# Required env vars:
#   DEVELOPER_ID         — e.g. "Developer ID Application: Jane Doe (TEAMID123)"
#                          List installed identities with:
#                            security find-identity -v -p codesigning
#
# Optional env vars:
#   APP_PATH             — override the .app path (default: search build dir)
#   ENTITLEMENTS_PATH    — override the entitlements file
#   KEYCHAIN             — sign with a specific keychain (e.g. CI's temp keychain)
#
# Exit codes:
#   0   success — `codesign --verify --deep --strict` passes
#   1   missing prerequisite or input
#   2   signing failed
#   3   verification failed

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

log() { printf "\033[1;36m[sign-bundle]\033[0m %s\n" "$*" >&2; }
die() { printf "\033[1;31m[sign-bundle]\033[0m %s\n" "$*" >&2; exit "${2:-1}"; }

# ── Locate the .app ────────────────────────────────────────────────────────
APP_PATH="${APP_PATH:-}"
if [[ -z "$APP_PATH" ]]; then
    APP_PATH="$(find "$REPO_ROOT/apps/macos/build" -maxdepth 5 -name 'NoteAgent.app' -type d 2>/dev/null | head -1 || true)"
fi
[[ -d "$APP_PATH" ]] || die "NoteAgent.app not found. Run \`make app\` first, or set APP_PATH."
log "Signing $APP_PATH"

# ── Verify prerequisites ───────────────────────────────────────────────────
[[ -n "${DEVELOPER_ID:-}" ]] || die "DEVELOPER_ID env var is required. \
Set to your Developer ID Application identity name. \
List candidates with: security find-identity -v -p codesigning"

ENTITLEMENTS_PATH="${ENTITLEMENTS_PATH:-$REPO_ROOT/apps/macos/NoteAgent/NoteAgent.entitlements}"
[[ -f "$ENTITLEMENTS_PATH" ]] || die "Entitlements file not found: $ENTITLEMENTS_PATH"

KEYCHAIN_FLAG=""
if [[ -n "${KEYCHAIN:-}" ]]; then
    KEYCHAIN_FLAG="--keychain $KEYCHAIN"
fi

# ── Signing options shared by every codesign invocation ────────────────────
# Hardened Runtime, secure timestamp, and our entitlements file. --options
# library-validation is *off* because the bundled Python loads .so files at
# runtime; the entitlements file enables the corresponding cs.* exception.
CS_OPTS=(
    --force
    --sign "$DEVELOPER_ID"
    --options runtime
    --timestamp
    --entitlements "$ENTITLEMENTS_PATH"
    $KEYCHAIN_FLAG
)

# ── Step 1: sign all nested Mach-O files inside-out ────────────────────────
#
# The bundled Python ships ~hundreds of .so files (numpy, hounding, etc) plus
# the python3 interpreter itself and various .dylib helpers. macOS requires
# we sign them before the surrounding bundle, depth-first.

log "Counting nested Mach-O binaries…"
mapfile -t NESTED < <(
    find "$APP_PATH/Contents/Resources/python" \
        \( -name '*.so' -o -name '*.dylib' -o -name 'python3*' \) \
        -type f 2>/dev/null
)
log "Found ${#NESTED[@]} nested binaries"

for bin in "${NESTED[@]}"; do
    # Skip non-Mach-O files (e.g. python3.X-config which is a shell script).
    if ! file "$bin" 2>/dev/null | grep -q 'Mach-O'; then
        continue
    fi
    codesign "${CS_OPTS[@]}" "$bin" 2>/dev/null \
        || die "Failed to sign $bin" 2
done
log "Signed nested binaries"

# ── Step 2: sign the .app bundle itself ────────────────────────────────────
log "Signing top-level .app bundle"
codesign "${CS_OPTS[@]}" "$APP_PATH" || die "Failed to sign $APP_PATH" 2

# ── Step 3: verify ─────────────────────────────────────────────────────────
log "Verifying signature (--deep --strict)"
codesign --verify --deep --strict --verbose=2 "$APP_PATH" 2>&1 \
    | sed 's/^/  /' >&2 \
    || die "codesign verification failed" 3

log "spctl assessment (Gatekeeper would-allow check)"
# Pre-notarization spctl will reject the app; that's expected. Show the
# result for visibility but don't treat it as fatal here.
spctl --assess --type execute --verbose=2 "$APP_PATH" 2>&1 \
    | sed 's/^/  /' >&2 || log "(expected: spctl rejects pre-notarization)"

log "Signing complete: $APP_PATH"
