# macOS App / App Store Plan

Reference summary of the multi-phase plan to ship NoteAgent as a macOS app
and (eventually) submit it to the Mac App Store. Phase numbering here is
distinct from the **Rust core refactor** phases tracked in
[`docs/ARCHITECTURE.md`](ARCHITECTURE.md); those are mostly complete and
this document picks up where they leave off.

## Status

| Phase | Status |
|-------|--------|
| 1. macOS app shell (Swift + WKWebView) | **Scaffolded** (`apps/macos/`) |
| 2. Embed Python runtime | Not started |
| 3. App Sandbox compliance | Not started |
| 4. Code signing + hardened runtime | Not started (basic hardened-runtime flags already on) |
| 5. Build pipeline | Not started |
| 6. App Store Connect setup | Not started |
| 7. Submission + review | Not started |

## Phase 1 — macOS app shell (✅ scaffolded)

Goal: a `WKWebView`-based macOS app that hosts the existing FastAPI web UI
served by a child `noteagent serve` process.

**What landed:** `apps/macos/` — see its [README](../apps/macos/README.md).

- SwiftUI `@main` app with a single window
- `PythonServer` actor spawns `/usr/bin/env noteagent serve --port 8765 --no-browser`
- Health-probe loop polls `/api/devices` until 200 OK, max 30 s
- `WKWebView` loads `http://127.0.0.1:8765/` once ready
- Loading / ready / error UI states
- External links open in the system browser
- Quit sends SIGINT, escalates to SIGTERM after 2.5 s
- Hardened Runtime on; App Sandbox off (next phase)
- Microphone + Documents + Desktop usage strings in `Info.plist`

**Deliberately deferred to later phases:** embedded Python, App Sandbox,
menu bar item, On-Demand Resources, App Store Connect.

## Phase 2 — Embed the Python runtime

The shell currently shells out to the developer's `noteagent` install.
For shipping, the interpreter and its `site-packages` must live inside the
`.app` bundle.

**Tasks:**
1. Use **python-build-standalone** (Indygreg) to vendor a portable CPython
   into `NoteAgent.app/Contents/Resources/python/`.
2. Pre-install the wheel from `crates/noteagent-py` (built by maturin) into
   the bundled `site-packages`.
3. Ship the `noteagent` Python package and a minimal `noteagent serve`
   launcher script.
4. Update `PythonServer.swift` to call `Contents/Resources/python/bin/python3`
   with the bundled launcher, instead of `/usr/bin/env noteagent`.
5. Pre-bundle `models/ggml-base.en.bin` (~142 MB) or document the first-run
   download path (`auto_download_enabled()` already handles this).

**Wildcard:** `whisper-rs` builds against the host's libclang/whisper.cpp.
We must verify it links cleanly against the embedded Python's extension
machinery and survives code-signing.

## Phase 3 — App Sandbox compliance

Mac App Store requires the App Sandbox entitlement. Switching it on changes
a lot:

1. Entitlements:
   - `com.apple.security.app-sandbox` → `true`
   - `com.apple.security.device.audio-input` → already on
   - `com.apple.security.network.server` (FastAPI binds 127.0.0.1)
   - `com.apple.security.network.client` (LLM API, model downloads)
   - `com.apple.security.files.user-selected.read-write` (exports, imports)
2. Move default storage from `~/notes/noteagent` to
   `~/Library/Containers/ai.ethervox.noteagent/Data/Documents/`.
3. Audit Python code for sandbox-hostile syscalls:
   - `subprocess.run(["open", "-R", …])` in `server.py` — replace with an
     `NSWorkspace.shared.activateFileViewerSelecting(...)` call exposed
     to JS via a `WKScriptMessageHandler`.
   - Any other `subprocess`/external-process spawns.

## Phase 4 — Code signing + hardened runtime

Every binary in the bundle is signed with the hardened runtime flag:

1. Sign the embedded `python3` binary, every `.so` / `.dylib` / `.pyd`,
   `whisper-rs`'s compiled artefacts, and the Rust `cdylib`.
2. Verify `@rpath` / `@executable_path` linkages — no absolute paths.
3. Add hardened-runtime exceptions if needed by PyTorch / numpy JIT
   (probably not anymore: we dropped both in Phase 6 of the Rust refactor).
4. `codesign --verify --deep --strict NoteAgent.app` must pass.
5. Notarize via `xcrun notarytool` (required for both direct distribution
   and App Store).

## Phase 5 — Build pipeline

1. `build-macos-app.sh` script chaining:
   - `cargo build --release` for `noteagent-py`
   - python-build-standalone vendoring + wheel install
   - `cp -R static/ → Resources/static/`
   - `codesign` over every binary
2. `gh-actions/release-macos.yml` workflow producing a notarized
   `.dmg` / `.pkg` artifact.
3. Either keep or replace `build-release.sh` for the existing CLI release
   bundle.

## Phase 6 — App Store Connect

1. Register `ai.ethervox.noteagent` Bundle ID in Apple Developer portal.
2. Create the App record in App Store Connect.
3. Category: Productivity (likely) or Utilities.
4. Screenshots: 1280×800 + 1440×900 (macOS sizes).
5. Privacy nutrition label: declare microphone use, accurate data-collection
   description, on-device transcription.
6. Pricing / availability.

## Phase 7 — Submission + review

1. Archive in Xcode (or `xcrun altool`).
2. Upload to App Store Connect.
3. Fill in App Review information:
   - Justify microphone use (on-device transcription).
   - Explain local server (FastAPI binds `127.0.0.1` only).
   - Confirm no third-party LLM data exfiltration (or list providers).
4. Iterate on rejections — audio apps frequently need extra justification.

## Effort estimate (still valid)

| Phase | Effort |
|-------|--------|
| 1. Shell + WebView | ~1–2 days (done) |
| 2. Python bundling | 2–4 days (biggest risk) |
| 3. Sandbox compliance | 1–2 days |
| 4. Signing + hardened runtime | 1–2 days |
| 5. Build pipeline | 1 day |
| 6. App Store Connect | 1 day |
| 7. Submission | 1 day + review-cycle calendar time |

Total: **~1–2 weeks of focused work**, most risk in Phases 2 and 3.

## Strategic call still open

Replacing `openai-whisper`/PyTorch with `whisper.cpp` is **done** (Rust
refactor Phase 3). Bundle size is no longer the constraint. The remaining
strategic question for App Store submission is whether to use:

- **Direct download (Developer ID)** first — easier to validate signing
  and notarization end-to-end.
- **Mac App Store** — adds sandbox + Apple distribution profile.

Recommendation: ship Developer ID first, then layer on MAS in a second
release.
