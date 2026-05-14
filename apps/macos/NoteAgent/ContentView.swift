//
//  ContentView.swift
//  NoteAgent macOS shell
//

import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var server: PythonServer

    var body: some View {
        ZStack {
            switch server.state {
            case .starting:
                LoadingView(message: "Starting NoteAgent…")
            case .ready:
                if let url = server.url {
                    WebView(url: url)
                } else {
                    // Should be unreachable — `ready` implies a resolved URL.
                    LoadingView(message: "Connecting…")
                }
            case .failed(let message):
                ErrorView(message: message) { server.restart() }
            }
        }
    }
}

private struct LoadingView: View {
    let message: String
    var body: some View {
        VStack(spacing: 16) {
            ProgressView()
                .scaleEffect(1.2)
            Text(message)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(nsColor: .windowBackgroundColor))
    }
}

private struct ErrorView: View {
    let message: String
    let onRetry: () -> Void
    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 36))
                .foregroundStyle(.orange)
            Text("NoteAgent failed to start")
                .font(.headline)
            Text(message)
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)
            Button("Try Again", action: onRetry)
                .controlSize(.large)
                .padding(.top, 8)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
