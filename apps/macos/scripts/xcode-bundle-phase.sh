#!/usr/bin/env bash
#
# xcode-bundle-phase.sh — runs inside Xcode's "Bundle Python + Model" build
# phase. Three jobs:
#
#   1) (Re)build apps/macos/BuiltResources/ via build-bundle.sh
#   2) Rsync python/, static/, and models/ into the .app's
#      Contents/Resources/.
#   3) Sign every nested Mach-O in Contents/Resources/python/ with the
#      hardened runtime + Xcode's current signing identity. Required for
#      notarization: Xcode's archive step does NOT recurse into
#      Resources/python/, so without this step python-build-standalone's
#      ad-hoc-signed binaries trigger "Hardened Runtime is Not Enabled"
#      when uploading to Apple Notary.
#
# All paths come from Xcode env vars ($SRCROOT, $CODESIGNING_FOLDER_PATH,
# $EXPANDED_CODE_SIGN_IDENTITY, $CODE_SIGN_ENTITLEMENTS).

set -euo pipefail

log() { printf '\033[1;36m[xcode-bundle-phase]\033[0m %s\n' "$*" >&2; }

# ── 1) Build embedded Python + ggml model (idempotent) ─────────────────────
log "Running build-bundle.sh"
"$SRCROOT/scripts/build-bundle.sh"

# ── 2) Stage into the .app bundle ──────────────────────────────────────────
log "Syncing BuiltResources/ into $CODESIGNING_FOLDER_PATH/Contents/Resources/"
mkdir -p "$CODESIGNING_FOLDER_PATH/Contents/Resources"
rsync -a --delete "$SRCROOT/BuiltResources/python/" "$CODESIGNING_FOLDER_PATH/Contents/Resources/python/"
rsync -a --delete "$SRCROOT/BuiltResources/static/" "$CODESIGNING_FOLDER_PATH/Contents/Resources/static/"
rsync -a --delete "$SRCROOT/BuiltResources/models/" "$CODESIGNING_FOLDER_PATH/Contents/Resources/models/"

# ── 3) Harden every nested Mach-O ──────────────────────────────────────────
# Xcode passes the chosen identity in $EXPANDED_CODE_SIGN_IDENTITY (a SHA-1
# hash or "-" for ad-hoc). Skip when no identity (shouldn't happen during
# Archive, but be defensive for Debug builds with signing disabled).
if [ -z "${EXPANDED_CODE_SIGN_IDENTITY:-}" ]; then
    log "EXPANDED_CODE_SIGN_IDENTITY not set; skipping nested signing"
    exit 0
fi

# Skip ad-hoc identity: those builds don't notarize anyway, and ad-hoc
# signatures lack the cert chain hardened-runtime checks need.
if [ "$EXPANDED_CODE_SIGN_IDENTITY" = "-" ]; then
    log "Ad-hoc signing identity; skipping hardened-runtime sweep"
    exit 0
fi

ENTITLEMENTS_FLAG=()
if [ -n "${CODE_SIGN_ENTITLEMENTS:-}" ] && [ -f "$CODE_SIGN_ENTITLEMENTS" ]; then
    ENTITLEMENTS_FLAG=(--entitlements "$CODE_SIGN_ENTITLEMENTS")
fi

PY_ROOT="$CODESIGNING_FOLDER_PATH/Contents/Resources/python"
[ -d "$PY_ROOT" ] || { log "No $PY_ROOT directory; nothing to sign"; exit 0; }

log "Signing nested Mach-O files in $PY_ROOT with hardened runtime"

# Collect via while-read so we work on bash 3.2 (no mapfile). Use NUL
# separation so paths with whitespace survive.
NESTED=()
while IFS= read -r -d '' bin; do
    NESTED+=("$bin")
done < <(
    find "$PY_ROOT" \
        \( -name '*.so' -o -name '*.dylib' -o -name 'python3*' \) \
        -type f -print0 2>/dev/null
)

COUNT=0
SKIPPED=0
for bin in "${NESTED[@]}"; do
    # Skip non-Mach-O entries (e.g. python3.X-config is a shell script).
    if ! /usr/bin/file "$bin" 2>/dev/null | grep -q 'Mach-O'; then
        SKIPPED=$((SKIPPED + 1))
        continue
    fi
    # --force replaces python-build-standalone's existing ad-hoc signature.
    # --timestamp is required for notarization; --options runtime enables
    # the Hardened Runtime flag that Apple Notary requires.
    if ! err="$(/usr/bin/codesign \
            --force \
            --sign "$EXPANDED_CODE_SIGN_IDENTITY" \
            --options runtime \
            --timestamp \
            "${ENTITLEMENTS_FLAG[@]}" \
            "$bin" 2>&1)"; then
        printf '\033[1;31m[xcode-bundle-phase]\033[0m codesign failed for %s\n' "$bin" >&2
        printf '%s\n' "$err" | sed 's/^/    /' >&2
        exit 1
    fi
    COUNT=$((COUNT + 1))
done

log "Hardened $COUNT nested binaries (skipped $SKIPPED non-Mach-O files)"
