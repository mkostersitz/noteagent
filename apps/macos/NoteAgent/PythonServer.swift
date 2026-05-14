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

        let proc = Process()
        // `noteagent` is the entry-point installed by `pip install -e .`.
        // We resolve it via /usr/bin/env so it picks up whichever venv is on
        // PATH when Xcode launches the app. A later phase will replace this
        // with an embedded interpreter under `Contents/Resources/python/`.
        proc.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        proc.arguments = ["noteagent", "serve", "--port", String(port), "--no-browser"]

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
                    self.state = .failed("Server exited (status \(code)). Check that `noteagent` is on PATH.")
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
