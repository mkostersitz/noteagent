# Phase 3 — App Sandbox Compliance (Plan)

This is the implementation plan for turning on App Sandbox on the macOS
app so it's eligible for Mac App Store submission. **No code changes
yet** — this doc is the audit + design step.

## Goal

`com.apple.security.app-sandbox = YES` in entitlements, the app launches
clean, records audio, saves transcripts to a user-chosen folder, exports
to user-chosen locations, and reveals files in Finder — all without
breaking on sandbox restrictions.

## Why this is non-trivial

App Sandbox confines the app to its own container at
`~/Library/Containers/ai.ethervox.noteagent/Data/`. Inside the sandbox:

- The app can read/write *only* its container + locations granted via
  explicit entitlements or security-scoped bookmarks.
- It cannot `fork`/`exec` arbitrary binaries (we already spawn the
  embedded Python — that's fine because it's inside the bundle).
- It cannot `open` external files via the shell.
- It cannot listen on arbitrary ports without `network.server`.
- `Path.home()` resolves to the container root, not the real `$HOME`.

## Inventory: every sandbox-hostile call site

Found via `grep` of `src/noteagent/`. Each row needs a fix (or
intentional skip).

### 🔴 Hard blockers — must fix before sandbox flips on

| File:line | Code | Problem | Fix |
|---|---|---|---|
| [server.py:455](../src/noteagent/server.py#L455) | `subprocess.run(["open", "-R", str(target)])` | "Reveal in Finder" via shell. `open` lives outside the sandbox. | Expose `revealInFinder(path)` as a Swift `WKScriptMessageHandler`; Python returns a sentinel value that the JS calls. |
| [server.py:457](../src/noteagent/server.py#L457) | `subprocess.run(["open", str(...)])` | Same. | Same. |
| [server.py:467](../src/noteagent/server.py#L467) | `subprocess.run(["xdg-open", ...])` | Linux path — dead on macOS but the import still loads. | Wrap entire `_reveal_path` body in a "this only runs in dev / non-sandboxed" guard; raise from the API endpoint when sandboxed. |
| [models.py:101](../src/noteagent/models.py#L101) | `storage_path: Path = Path.home() / "notes" / "noteagent"` | `Path.home()` is the sandbox container under MAS — useless as a default. | Default becomes the picker-chosen URL (already wired via `NOTEAGENT_STORAGE_DIR`). When unset, fall back to `Containers/.../Documents/`. |
| [storage.py:25](../src/noteagent/storage.py#L25) | `CONFIG_DIR = Path.home() / ".config" / "noteagent"` | Same. | Container-relative is fine here — config *should* live inside the app sandbox, not in a user-chosen folder. |
| [cli.py:635](../src/noteagent/cli.py#L635) | `_PID_FILE = Path.home() / ".config" / "noteagent" / "serve.pid"` | CLI uses this; safe under sandbox because it resolves to the container. | No change. |

### 🟡 Needs verification — probably fine but check

| File:line | Code | Why it might work | Plan |
|---|---|---|---|
| [server.py:455–467](../src/noteagent/server.py#L447) | The whole `_reveal_path` function | macOS reveals are blocked, but `NSWorkspace.activateFileViewerSelecting` works *if* the path is in a folder we have security-scoped access to. | Replace with a Swift-side handler (see below). |
| [summary.py:58](../src/noteagent/summary.py#L58) | `subprocess.run(["gh", "copilot", ...])` | LLM provider integration. Will fail under sandbox because `gh` is outside it. | Gate this provider behind `if not is_sandboxed():`. Promote a cloud-API-only summary provider for the MAS build. |
| [server.py:355,417,442,916](../src/noteagent/server.py#L355) | `Path(session.metadata.source_file).expanduser()` | Imported audio files. Saved at import time; the path is recorded but the app may no longer have access by the time it's used. | When importing, copy the file *into* the storage folder (we already have `save_preview_media`); never re-open by the original path. |
| [cli.py:667](../src/noteagent/cli.py#L667) | `uvicorn.run(host="127.0.0.1", ...)` | FastAPI binds localhost. Needs `network.server` entitlement. | Add the entitlement; no code change. |

### 🟢 Already sandbox-safe

| File:line | Why |
|---|---|
| `model_download.py` — HTTPS to HuggingFace | Needs `network.client` entitlement; otherwise fine |
| `noteagent_audio.AudioRecorder` (cpal) | Needs `device.audio-input`; we have it |
| WebSocket on `/ws/transcript` | Same socket the server already binds |
| `tempfile` usage | Always resolves to a sandbox-safe location |

## Storage path: the trickiest piece

The current `StoragePicker` saves a plain absolute path to UserDefaults.
**That doesn't work under sandbox** — even with `files.user-selected.read-write`,
the grant is per-NSOpenPanel-invocation and doesn't persist across
launches. The right primitive is a **security-scoped bookmark**.

### Design

`StoragePicker.swift` changes:

```swift
@MainActor
enum StoragePicker {
    private static let bookmarkKey = "NoteAgentStorageBookmark"  // was "NoteAgentStoragePath"

    /// Returns a URL the app has security-scoped read/write access to.
    /// Caller must balance with stopAccessingSecurityScopedResource().
    static func resolve() -> URL? {
        // 1) Try restoring from saved bookmark.
        if let data = UserDefaults.standard.data(forKey: bookmarkKey) {
            var stale = false
            if let url = try? URL(
                resolvingBookmarkData: data,
                options: [.withSecurityScope],
                bookmarkDataIsStale: &stale
            ), url.startAccessingSecurityScopedResource() {
                if !stale { return url }
                // Stale: re-save the bookmark with the fresh URL.
                if let fresh = try? url.bookmarkData(
                    options: .withSecurityScope,
                    includingResourceValuesForKeys: nil,
                    relativeTo: nil
                ) {
                    UserDefaults.standard.set(fresh, forKey: bookmarkKey)
                }
                return url
            }
        }

        // 2) Saved bookmark missing/invalid → prompt.
        return runPicker()
    }

    static func runPicker() -> URL? {
        let panel = NSOpenPanel()
        // ... existing setup ...
        guard panel.runModal() == .OK, let url = panel.url else { return nil }

        guard let data = try? url.bookmarkData(
            options: .withSecurityScope,
            includingResourceValuesForKeys: nil,
            relativeTo: nil
        ) else { return nil }

        UserDefaults.standard.set(data, forKey: bookmarkKey)
        _ = url.startAccessingSecurityScopedResource()
        return url
    }
}
```

`PythonServer` already passes `NOTEAGENT_STORAGE_DIR` via env — no change
needed there. **Critical:** `url.startAccessingSecurityScopedResource()`
must be called once per launch and the resource must be balanced with
`stopAccessingSecurityScopedResource()` at app quit (otherwise other
apps may hit a leak). Pair this with the existing `proc.terminationHandler`.

## Reveal-in-Finder: replace shell-out with WKScriptMessageHandler

Python no longer calls `subprocess.run(["open", ...])`. Instead:

**Swift side** — register a message handler when constructing the WebView:

```swift
final class FinderBridge: NSObject, WKScriptMessageHandler {
    func userContentController(_ ucc: WKUserContentController,
                                didReceive message: WKScriptMessage) {
        guard message.name == "revealInFinder",
              let path = message.body as? String else { return }
        let url = URL(fileURLWithPath: path)
        NSWorkspace.shared.activateFileViewerSelecting([url])
    }
}
```

**JS side** — `static/app.js` calls
`window.webkit.messageHandlers.revealInFinder.postMessage(absolutePath)`
instead of `POST /api/sessions/:id/reveal`.

**Python side** — `/api/sessions/:id/reveal` returns the absolute path
in the response body instead of opening it directly. The JS then calls
the bridge. Same behavior for dev (browser tab) since the bridge
gracefully no-ops there.

## Entitlements: before / after

```diff
 <key>com.apple.security.app-sandbox</key>
-<false/>
+<true/>
 <key>com.apple.security.device.audio-input</key>
 <true/>
+<key>com.apple.security.network.server</key>
+<true/>
+<key>com.apple.security.network.client</key>
+<true/>
+<key>com.apple.security.files.user-selected.read-write</key>
+<true/>
-<key>com.apple.security.cs.allow-unsigned-executable-memory</key>
-<true/>
-<key>com.apple.security.cs.disable-library-validation</key>
-<true/>
+<!-- Hardened-runtime exceptions removed; sandbox + properly-signed
+     embedded .so files cover the previous use case. Keep an eye on
+     reviewer feedback — `allow-unsigned-executable-memory` may need
+     to come back for Python's bytecode interpreter. -->
```

We'll likely need to add **`allow-unsigned-executable-memory`** back
during the first sandboxed test run — Python's bytecode JIT triggers
it. Apple reviewers accept it for embedded-Python apps when justified.

## Migration story

Users who already have data in `~/notes/noteagent/` (the pre-sandbox
default) need a way forward. Options:

1. **First-sandboxed-launch migration:** before showing the picker,
   detect a populated `~/notes/noteagent/`, offer to move it. Requires
   `files.user-selected.read-write` + a temporary user grant.
2. **Manual instructions in the picker dialog:** "If you previously
   used NoteAgent, you may want to point this at `~/notes/noteagent/`."
3. **No migration:** new install, empty state.

**Recommend (1)** for the first MAS release; (2) as fallback wording in
the picker; (3) is silently bad UX.

## Plan: implementation milestones (next PRs)

| # | Milestone | Effort | Risk |
|---|-----------|--------|------|
| **S1** | Swap StoragePicker to security-scoped bookmarks | half day | low |
| **S2** | Replace `_reveal_path` subprocess shell-outs with WebKit message bridge | half day | low |
| **S3** | Gate `summary._summarize_copilot` behind a non-sandboxed check; add cloud-API summary provider | 1 day | medium — needs API key UX |
| **S4** | Audit imported `source_file` handling — copy into storage folder on import, drop the absolute-path references | half day | low |
| **S5** | Flip sandbox entitlements; first launch + first recording + first export under sandbox | unknown | **high** — this is where the surprises live |
| **S6** | Migration prompt for pre-existing `~/notes/noteagent/` users | half day | low |
| **S7** | Run with Apple Distribution cert + MAS provisioning profile; verify entitlements survive signing | half day | low |

S5 is the wildcard. macOS sandbox failures often surface as silent
crashes or empty files rather than clean errors — budget extra time
for "wait, why did *that* break?" debugging.

## Verification checklist

Before merging S5:

- [ ] App launches under sandbox (Console.app shows no
  `sandbox violation` entries)
- [ ] Microphone permission granted on first record
- [ ] Recording produces a WAV in the user-chosen folder
- [ ] Transcript and summary save successfully
- [ ] Reveal-in-Finder opens the right path
- [ ] Export to Desktop / Downloads via NSOpenPanel works
- [ ] App relaunches: storage bookmark resolves, no re-prompt
- [ ] User moves the storage folder → app re-prompts cleanly
- [ ] `codesign --verify --deep --strict` still clean after entitlement changes
- [ ] App passes `spctl --assess --type execute` post-notarization

## Open questions

1. **Cloud LLM summary provider** — if `gh copilot` shells out, what's
   the sandbox-safe replacement? OpenAI HTTPS API, Anthropic, both?
   Need an API-key entry UX (probably a settings page).
2. **App auto-update** — Sparkle 2 has a sandbox-compatible variant.
   Out of scope for first MAS release (App Store handles updates), but
   relevant if you also ship a Developer ID direct download.
3. **iCloud sync** — `com.apple.security.application-groups` +
   `com.apple.developer.icloud-container-identifiers`. Out of scope
   for v1; flag as future.

## Effort summary

| Path | Calendar time | Engineering |
|------|---------------|-------------|
| All of Phase 3 (S1–S7) | 5–7 days | 3–4 days focused work |
| First sandboxed test build | end of day 2 | S1+S2+S5 minimum |
| Ready for App Store submission | end of day 7 | + Phase 4 (MAS signing) + Phase 5 (paperwork) |
