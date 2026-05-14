#!/usr/bin/env bash
#
# notarize-bundle.sh — submit a signed NoteAgent.app to Apple Notary, wait
# for the result, and staple the ticket so the app verifies offline.
#
# Run AFTER sign-bundle.sh. Apple's notary service needs the app inside a
# zip / dmg / pkg; we use a zip because it's the simplest.
#
# Required: one of the two credential modes below.
#
# ── Mode A: keychain notary profile (recommended) ──
#   Create the profile once with:
#     xcrun notarytool store-credentials NoteAgentNotary \
#         --apple-id "you@example.com" \
#         --team-id  "TEAMID123" \
#         --password "<app-specific-password-from-appleid.apple.com>"
#   Then run:
#     NOTARY_PROFILE=NoteAgentNotary ./notarize-bundle.sh
#
# ── Mode B: explicit credentials ──
#   APPLE_ID="you@example.com"
#   APPLE_TEAM_ID="TEAMID123"
#   APPLE_PASSWORD="<app-specific-password>"   # NOT your normal Apple ID password
#
# Optional:
#   APP_PATH       — override the .app path (default: search apps/macos/build)
#
# Exit codes:
#   0   notarization accepted and ticket stapled
#   1   missing prerequisite / input
#   2   notarization rejected (logs printed)
#   3   stapling failed

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

log() { printf "\033[1;36m[notarize]\033[0m %s\n" "$*" >&2; }
die() { printf "\033[1;31m[notarize]\033[0m %s\n" "$*" >&2; exit "${2:-1}"; }

# ── Inputs ─────────────────────────────────────────────────────────────────
APP_PATH="${APP_PATH:-}"
if [[ -z "$APP_PATH" ]]; then
    APP_PATH="$(find "$REPO_ROOT/apps/macos/build" -maxdepth 5 -name 'NoteAgent.app' -type d 2>/dev/null | head -1 || true)"
fi
[[ -d "$APP_PATH" ]] || die "NoteAgent.app not found. Run \`make app\` then sign-bundle.sh first."

# ── Credential mode ────────────────────────────────────────────────────────
if [[ -n "${NOTARY_PROFILE:-}" ]]; then
    SUBMIT_CRED=(--keychain-profile "$NOTARY_PROFILE")
    log "Using keychain notary profile: $NOTARY_PROFILE"
elif [[ -n "${APPLE_ID:-}" && -n "${APPLE_TEAM_ID:-}" && -n "${APPLE_PASSWORD:-}" ]]; then
    SUBMIT_CRED=(--apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" --password "$APPLE_PASSWORD")
    log "Using explicit credentials for $APPLE_ID"
else
    die "Set NOTARY_PROFILE, or all of APPLE_ID + APPLE_TEAM_ID + APPLE_PASSWORD."
fi

# ── Zip the .app ───────────────────────────────────────────────────────────
ZIP_PATH="$(dirname "$APP_PATH")/NoteAgent.zip"
log "Packaging $APP_PATH"
rm -f "$ZIP_PATH"
# `ditto -c -k --keepParent` produces a notary-compatible zip preserving
# extended attributes / symlinks the way Apple expects.
ditto -c -k --keepParent "$APP_PATH" "$ZIP_PATH"

# ── Submit ─────────────────────────────────────────────────────────────────
log "Submitting to Apple Notary (this can take several minutes)"
SUBMIT_OUTPUT="$(mktemp)"
trap 'rm -f "$SUBMIT_OUTPUT" "$ZIP_PATH"' EXIT

if ! xcrun notarytool submit "$ZIP_PATH" \
        "${SUBMIT_CRED[@]}" \
        --wait \
        --output-format plist \
        > "$SUBMIT_OUTPUT"; then
    cat "$SUBMIT_OUTPUT" >&2 || true
    die "notarytool submit failed" 2
fi

STATUS="$(/usr/libexec/PlistBuddy -c 'Print :status' "$SUBMIT_OUTPUT" 2>/dev/null || echo unknown)"
SUBMISSION_ID="$(/usr/libexec/PlistBuddy -c 'Print :id' "$SUBMIT_OUTPUT" 2>/dev/null || echo unknown)"
log "Notarization status: $STATUS (id $SUBMISSION_ID)"

if [[ "$STATUS" != "Accepted" ]]; then
    log "Fetching rejection log…"
    xcrun notarytool log "$SUBMISSION_ID" "${SUBMIT_CRED[@]}" 2>&1 | sed 's/^/  /' >&2 || true
    die "Notarization rejected" 2
fi

# ── Staple the ticket ──────────────────────────────────────────────────────
log "Stapling notarization ticket"
xcrun stapler staple "$APP_PATH" 2>&1 | sed 's/^/  /' >&2 \
    || die "stapler staple failed" 3

log "Verifying staple"
xcrun stapler validate "$APP_PATH" 2>&1 | sed 's/^/  /' >&2 \
    || die "stapler validate failed" 3

log "spctl assessment (post-notarization should now accept):"
spctl --assess --type execute --verbose=2 "$APP_PATH" 2>&1 | sed 's/^/  /' >&2 || true

log "Done: $APP_PATH is signed, notarized, and stapled."
