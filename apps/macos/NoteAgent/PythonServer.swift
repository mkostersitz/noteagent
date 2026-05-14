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

    private let logger = Logger(subsystem: "ai.ethervox.noteagent", category: "PythonServer")

    init(port: Int = 8765) {
        self.port = port
    }

    func start() {
        guard process == nil else { return }
        state = .starting
        url = nil

        // First-launch (or post-folder-move) storage prompt. Must complete
        // before we exec Python, since the path is passed via env.
        guard let storage = StoragePicker.resolve() else {
            logger.notice("Storage picker cancelled; refusing to launch server")
            state = .failed("NoteAgent needs a folder to save your recordings and transcripts. Click Try Again to choose one.")
            return
        }
        logger.notice("Storage folder: \(storage.path, privacy: .public)")

        // Launch strategy:
        //   1. Bundled Python under Contents/Resources/python/ (release builds)
        //   2. NOTEAGENT_BIN override / well-known dev install paths
        //   3. /usr/bin/env noteagent with an augmented PATH (final fallback)
        let launch = Self.resolveLaunch(port: port)

        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: launch.executable)
        proc.arguments = launch.arguments
        logger.notice("Launching: \(launch.description, privacy: .public)")

        // Augment PATH and set bundle-local env vars (model dir, static assets,
        // storage dir) so the Python side resolves resources inside the .app
        // bundle and writes user data to the user-chosen folder.
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = Self.augmentedPath(existing: env["PATH"])
        env["NOTEAGENT_STORAGE_DIR"] = storage.path
        for (k, v) in launch.extraEnv {
            env[k] = v
        }
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
                        hint = "Neither the bundled Python nor a developer `noteagent` install was found. Run `make bundle` (release builds), `make build` (dev), or set NOTEAGENT_BIN in the Xcode scheme."
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

    /// A resolved launch plan: which binary to exec, with which args, and
    /// what extra env vars to set on top of the inherited environment.
    private struct LaunchPlan {
        let executable: String
        let arguments: [String]
        let extraEnv: [String: String]
        let description: String
    }

    /// Decide how to start the Python server.
    ///
    /// Order of preference:
    ///   1. **Bundled Python** at `Contents/Resources/python/bin/python3`
    ///      with `NOTEAGENT_MODEL_DIR` / `NOTEAGENT_STATIC_DIR` pointing into
    ///      the bundle. This is what ships with release builds.
    ///   2. **`NOTEAGENT_BIN` override** — explicit absolute path set in the
    ///      Xcode scheme. Useful for dev builds that want a specific venv.
    ///   3. **Well-known dev install locations** (`~/.local/bin`, `~/.venv/bin`,
    ///      `/opt/homebrew/bin`, etc.). Lets a dev build run against `make build`.
    ///   4. **`/usr/bin/env noteagent`** with an augmented PATH — final fallback.
    private static func resolveLaunch(port: Int) -> LaunchPlan {
        let serveArgs = ["serve", "--port", String(port), "--no-browser"]
        let fm = FileManager.default

        // 1. Bundled Python under the .app bundle.
        if let resources = Bundle.main.resourceURL {
            let bundledPy = resources.appendingPathComponent("python/bin/python3").path
            if fm.isExecutableFile(atPath: bundledPy) {
                let modelDir = resources.appendingPathComponent("models").path
                let staticDir = resources.appendingPathComponent("static").path
                var env: [String: String] = [:]
                if fm.fileExists(atPath: modelDir)  { env["NOTEAGENT_MODEL_DIR"]  = modelDir }
                if fm.fileExists(atPath: staticDir) { env["NOTEAGENT_STATIC_DIR"] = staticDir }
                return LaunchPlan(
                    executable: bundledPy,
                    arguments: ["-m", "noteagent.cli"] + serveArgs,
                    extraEnv: env,
                    description: "bundled python at \(bundledPy)"
                )
            }
        }

        // 2 + 3. Override env var or well-known dev install paths.
        if let dev = resolveDevNoteagent(fm: fm) {
            return LaunchPlan(
                executable: dev,
                arguments: serveArgs,
                extraEnv: [:],
                description: "dev install at \(dev)"
            )
        }

        // 4. Last-resort PATH search.
        return LaunchPlan(
            executable: "/usr/bin/env",
            arguments: ["noteagent"] + serveArgs,
            extraEnv: [:],
            description: "PATH search via /usr/bin/env (augmented)"
        )
    }

    private static func resolveDevNoteagent(fm: FileManager) -> String? {
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
