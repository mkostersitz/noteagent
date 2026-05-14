//
//  StoragePicker.swift
//  NoteAgent macOS shell
//
//  Resolves the on-disk location where NoteAgent stores recordings,
//  transcripts, and exports. The user picks it on first launch (or any time
//  the previous choice has gone away — moved, renamed, unmounted, etc.).
//
//  The chosen path is passed to the Python backend via NOTEAGENT_STORAGE_DIR
//  (see src/noteagent/storage.py::_apply_storage_override). This intentionally
//  keeps storage decisions out of the config TOML so the macOS app and the
//  developer CLI can coexist on the same machine without stepping on each
//  other's defaults.
//

import AppKit
import Foundation

@MainActor
enum StoragePicker {
    /// UserDefaults key holding the absolute path to the chosen folder.
    /// Plain path (not a bookmark) is fine until App Sandbox is enabled —
    /// when it is (Phase 3 of the App Store plan), switch to a
    /// security-scoped bookmark.
    static let defaultsKey = "NoteAgentStoragePath"

    /// Return a usable storage path, prompting the user when needed.
    ///
    /// - Reads the saved choice from UserDefaults.
    /// - If the path still exists on disk, returns it.
    /// - Otherwise pops the picker. If the user cancels, returns `nil`.
    static func resolve() -> URL? {
        if let saved = UserDefaults.standard.string(forKey: defaultsKey) {
            let url = URL(fileURLWithPath: saved)
            var isDir: ObjCBool = false
            if FileManager.default.fileExists(atPath: url.path, isDirectory: &isDir), isDir.boolValue {
                return url
            }
            // Stale entry — folder was moved or deleted. Fall through to the
            // picker; clearing now keeps the previous value from sticking
            // around if the user cancels (cancel should mean "not now",
            // not "use stale path").
            UserDefaults.standard.removeObject(forKey: defaultsKey)
        }
        return runPicker()
    }

    /// Explicitly trigger the directory picker. Useful for a "Change Storage
    /// Folder…" menu item (not wired into the UI yet — exposed for the
    /// later UX work).
    @discardableResult
    static func runPicker() -> URL? {
        let panel = NSOpenPanel()
        panel.message = "Choose a folder for your NoteAgent recordings, transcripts, and exports. You can change this later."
        panel.prompt = "Choose"
        panel.canCreateDirectories = true
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.directoryURL = FileManager.default
            .urls(for: .documentDirectory, in: .userDomainMask).first

        guard panel.runModal() == .OK, let url = panel.url else { return nil }

        // Persist the choice so subsequent launches go straight to the
        // WebView without prompting.
        UserDefaults.standard.set(url.path, forKey: defaultsKey)
        return url
    }
}
