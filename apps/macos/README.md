# NoteAgent macOS App Shell

Phase 1 of the App Store path (see [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md)
and the original plan summary in
[`docs/MACOS_APP_PLAN.md`](../../docs/MACOS_APP_PLAN.md)).

This is a thin SwiftUI shell that:

1. Launches the existing `noteagent serve` Python server as a subprocess.
2. Polls `http://127.0.0.1:8765/api/devices` until it responds (≤30 s).
3. Hosts the existing FastAPI web UI in a `WKWebView`.
4. Cleanly stops the server on app quit (sends SIGINT, then SIGTERM after
   2.5 s if it lingers).

The Python backend is **not** embedded yet. This scaffold deliberately
references the developer's existing `noteagent` install — fastest way to see
the WebView working end-to-end. A later phase replaces the subprocess with a
frozen `python-build-standalone` interpreter under
`NoteAgent.app/Contents/Resources/python/` and turns on App Sandbox.

## Requirements

| Tool | Version | Why |
|------|---------|-----|
| **macOS** | 13.0+ | Deployment target |
| **Full Xcode** | 15+ | The Command Line Tools alone aren't enough — Xcode is required to build, sign, and run `.app` bundles |
| **NoteAgent Python install** | from repo root: `make build` | Provides the `noteagent` command on `PATH` |
| **Apple Developer ID** | personal Apple ID is fine for local runs | Required for code-signing; pick "Sign to Run Locally" in Xcode if you don't have a paid account |

## First-time setup

```bash
# 1) Build the Python side (workspace root):
make build
which noteagent       # confirm it's on PATH — the app shells out to this

# 2) Open the project in Xcode:
open apps/macos/NoteAgent.xcodeproj

# 3) In Xcode:
#    - Select the NoteAgent scheme (already set as the default).
#    - Signing & Capabilities → set your Team. "Sign to Run Locally" works.
#    - ⌘R to run.
```

## How it works

```
┌────────────────────────────────────────────────────────────────┐
│ NoteAgent.app (Swift)                                          │
│ ┌────────────────────────────┐   ┌───────────────────────────┐ │
│ │ NoteAgentApp / ContentView │   │ PythonServer              │ │
│ │  ↓                         │   │  • spawns `noteagent`     │ │
│ │ WKWebView                  │←──│  • health-probes /api/    │ │
│ │  ↓ http://127.0.0.1:8765   │   │  • forwards logs to       │ │
│ │                            │   │    Xcode console          │ │
│ └────────────────────────────┘   └───────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
                 │ HTTP
                 ▼
┌────────────────────────────────────────────────────────────────┐
│ Python process (noteagent serve)                               │
│  FastAPI + uvicorn + whisper.cpp via crates/noteagent-py       │
└────────────────────────────────────────────────────────────────┘
```

## Files

| File | Purpose |
|------|---------|
| [`NoteAgent/NoteAgentApp.swift`](NoteAgent/NoteAgentApp.swift) | SwiftUI `@main` entry; owns the `PythonServer` lifecycle |
| [`NoteAgent/ContentView.swift`](NoteAgent/ContentView.swift) | Loading / ready / error states |
| [`NoteAgent/WebView.swift`](NoteAgent/WebView.swift) | `NSViewRepresentable` over `WKWebView`; opens external links in the user's browser |
| [`NoteAgent/PythonServer.swift`](NoteAgent/PythonServer.swift) | `Process` management, health-probe loop, log forwarding |
| [`NoteAgent/Info.plist`](NoteAgent/Info.plist) | Bundle metadata, microphone/documents usage strings, localhost ATS exception |
| [`NoteAgent/NoteAgent.entitlements`](NoteAgent/NoteAgent.entitlements) | Audio input + hardened-runtime exceptions (sandbox **off** for Phase 1) |
| [`NoteAgent.xcodeproj/`](NoteAgent.xcodeproj) | Hand-written Xcode project, single `NoteAgent` target |

## What's deliberately deferred

These belong to later phases:

- **App Sandbox** — currently off so the shell can spawn the dev `noteagent`.
  Will flip on when the Python interpreter is embedded inside the bundle.
- **Embedded Python runtime** — Phase 1 references the developer's venv.
  Bundling `python-build-standalone` is its own multi-day phase before App
  Store submission.
- **Code-signed `.so` files** — irrelevant until embedded Python lands.
- **Menu bar / status item** — out of scope for the smoke-test shell.

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| "Server did not respond within 30 s" | `noteagent` isn't on PATH for GUI apps; run Xcode from a terminal where `which noteagent` works |
| "Could not launch `noteagent`" | Same as above, or the Python venv was deleted |
| Microphone permission prompt missing | First launch should prompt; re-trigger via System Settings → Privacy & Security → Microphone |
| Hardened Runtime crash on launch | The `com.apple.security.cs.*` entitlements in `NoteAgent.entitlements` must be present (they are by default) |
