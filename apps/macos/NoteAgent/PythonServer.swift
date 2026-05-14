//
//  PythonServer.swift
//  NoteAgent macOS shell
//
//  Launches and monitors the embedded NoteAgent Python server as a child
//  process. Phase 1 references the developer's existing `noteagent` install
//  (e.g. from `pip install -e .` plus `maturin develop`). A later phase will
//  replace this with a frozen python-build-standalone bundle inside
//  `Contents/Resources/`, code-signed for App Store distribution.
//

import Foundation
import os.log

/// Observable state of the embedded server, consumed by SwiftUI views.
@MainActor
final class PythonServer: ObservableObject {
    enum State: Equatable {
        case starting
        case ready
        case failed(String)
    }

    @Published private(set) var state: State = .starting
    @Published private(set) var url: URL? = nil

    private let port: Int
    private let host = "127.0.0.1"
    private var process: Process?
    private var healthcheckTask: Task<Void, Never>?

    private let logger = Logger(subsystem: "com.noteagent.macos", category: "PythonServer")

    init(port: Int = 8765) {
        self.port = port
    }

    func start() {
        guard process == nil else { return }
        state = .starting
        url = nil

        // GUI macOS apps inherit a minimal PATH (`/usr/bin:/bin:/usr/sbin:/sbin`)
        // — not the user's shell PATH. So `/usr/bin/env noteagent` won't find
        // a pipx/venv install. Resolve to an absolute path first; fall back to
        // env with an augmented PATH if we can't find one outright.
        let resolved = Self.resolveNoteagentExecutable()

        let proc = Process()
        if let resolved = resolved {
            proc.executableURL = URL(fileURLWithPath: resolved)
            proc.arguments = ["serve", "--port", String(port), "--no-browser"]
            logger.notice("Using noteagent at \(resolved, privacy: .public)")
        } else {
            proc.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            proc.arguments = ["noteagent", "serve", "--port", String(port), "--no-browser"]
            logger.notice("No absolute path found; falling back to PATH search via /usr/bin/env")
        }

        // Augment the child's PATH so common venv / pipx locations are visible
        // even when the GUI launch context didn't include them.
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = Self.augmentedPath(existing: env["PATH"])
        proc.environment = env

        // Forward stdout / stderr to the Xcode console so the developer can
        // see Python tracebacks during dev.
        let outPipe = Pipe()
        let errPipe = Pipe()
        proc.standardOutput = outPipe
        proc.standardError = errPipe
        Self.attachLogger(outPipe, level: .info, logger: logger)
        Self.attachLogger(errPipe, level: .error, logger: logger)

        proc.terminationHandler = { [weak self] terminated in
            Task { @MainActor in
                guard let self = self else { return }
                let code = terminated.terminationStatus
                self.logger.notice("noteagent serve exited with status \(code)")
                if self.state != .ready {
                    let hint: String
                    if code == 127 {
                        hint = "`noteagent` was not found. Install with `make build` or set NOTEAGENT_BIN to its absolute path in the Xcode scheme."
                    } else {
                        hint = "Server exited (status \(code)). See the Xcode console for the Python traceback."
                    }
                    self.state = .failed(hint)
                }
                self.process = nil
            }
        }

        do {
            try proc.run()
            process = proc
            logger.notice("noteagent serve launched (pid \(proc.processIdentifier))")
            healthcheckTask = Task { [weak self] in await self?.waitForReady() }
        } catch {
            logger.error("Failed to launch noteagent: \(error.localizedDescription, privacy: .public)")
            state = .failed("Could not launch `noteagent`: \(error.localizedDescription)")
        }
    }

    /// Try to find an absolute path to the `noteagent` executable.
    ///
    /// Resolution order:
    ///   1. `NOTEAGENT_BIN` env var (set in the Xcode scheme for custom installs)
    ///   2. Common pipx / venv / Homebrew install locations under $HOME and /opt
    ///   3. `nil` — caller falls back to `/usr/bin/env noteagent` with an
    ///      augmented PATH.
    private static func resolveNoteagentExecutable() -> String? {
        let fm = FileManager.default

        if let override = ProcessInfo.processInfo.environment["NOTEAGENT_BIN"],
           !override.isEmpty,
           fm.isExecutableFile(atPath: override) {
            return override
        }

        let home = NSHomeDirectory()
        let candidates: [String] = [
            "\(home)/.local/bin/noteagent",          // pipx default
            "\(home)/.venv/bin/noteagent",
            "\(home)/venv/bin/noteagent",
            "\(home)/repos/noteagent/.venv/bin/noteagent",
            "\(home)/repos/noteagent/venv_test/bin/noteagent",
            "/opt/homebrew/bin/noteagent",
            "/usr/local/bin/noteagent",
        ]
        return candidates.first(where: { fm.isExecutableFile(atPath: $0) })
    }

    /// Add common bin directories to PATH so `/usr/bin/env` and any child
    /// shell-outs (e.g. python interpreter discovery) work.
    private static func augmentedPath(existing: String?) -> String {
        let home = NSHomeDirectory()
        let extras = [
            "\(home)/.local/bin",
            "\(home)/.venv/bin",
            "/opt/homebrew/bin",
            "/usr/local/bin",
        ]
        var parts = (existing ?? "/usr/bin:/bin:/usr/sbin:/sbin")
            .split(separator: ":")
            .map(String.init)
        for e in extras where !parts.contains(e) {
            parts.insert(e, at: 0)
        }
        return parts.joined(separator: ":")
    }

    func stop() {
        healthcheckTask?.cancel()
        healthcheckTask = nil
        if let proc = process, proc.isRunning {
            // SIGINT lets the server cleanly stop any in-progress recording.
            proc.interrupt()
            // Give it a moment to drain; force-terminate if it lingers.
            Task.detached {
                try? await Task.sleep(nanoseconds: 2_500_000_000)
                if proc.isRunning { proc.terminate() }
            }
        }
        process = nil
        url = nil
    }

    func restart() {
        stop()
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 500_000_000)
            self.start()
        }
    }

    // MARK: - Health probe

    private func waitForReady() async {
        // Poll the server's lightweight `/api/devices` endpoint until it
        // answers or we hit the timeout. 30 s is generous: it covers cold
        // imports plus the first whisper model load.
        let probeURL = URL(string: "http://\(host):\(port)/api/devices")!
        let deadline = Date().addingTimeInterval(30)
        let session = URLSession(configuration: .ephemeral)

        while Date() < deadline {
            if Task.isCancelled { return }
            do {
                let (_, response) = try await session.data(from: probeURL)
                if let http = response as? HTTPURLResponse, (200..<500).contains(http.statusCode) {
                    await MainActor.run {
                        self.url = URL(string: "http://\(self.host):\(self.port)/")
                        self.state = .ready
                    }
                    return
                }
            } catch {
                // Server not up yet — keep polling.
            }
            try? await Task.sleep(nanoseconds: 300_000_000)
        }

        await MainActor.run {
            if self.state == .starting {
                self.state = .failed("Server did not respond within 30 s.")
            }
        }
    }

    // MARK: - Output forwarding

    private static func attachLogger(_ pipe: Pipe, level: OSLogType, logger: Logger) {
        pipe.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            guard !data.isEmpty, let text = String(data: data, encoding: .utf8) else { return }
            for line in text.split(whereSeparator: \.isNewline) where !line.isEmpty {
                logger.log(level: level, "\(line, privacy: .public)")
            }
        }
    }
}
