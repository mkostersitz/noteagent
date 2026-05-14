//
//  WebView.swift
//  NoteAgent macOS shell
//
//  Thin NSViewRepresentable wrapper around WKWebView. The web UI is the
//  existing FastAPI + vanilla-JS frontend served by the embedded Python
//  server at http://127.0.0.1:<port>/.
//

import SwiftUI
@preconcurrency import WebKit

struct WebView: NSViewRepresentable {
    let url: URL

    func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        // Allow audio elements (transcript preview) to play without a user
        // gesture — the app itself is the user interaction.
        configuration.mediaTypesRequiringUserActionForPlayback = []

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = true
        webView.setValue(false, forKey: "drawsBackground")
        webView.load(URLRequest(url: url))
        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        // Reload when the server URL changes (e.g. after a restart on a
        // different port).
        if webView.url != url {
            webView.load(URLRequest(url: url))
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    final class Coordinator: NSObject, WKNavigationDelegate {
        func webView(_ webView: WKWebView,
                     decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            // Open external (non-localhost) links in the default browser.
            if let target = navigationAction.request.url,
               navigationAction.navigationType == .linkActivated,
               target.host != "127.0.0.1" && target.host != "localhost" {
                NSWorkspace.shared.open(target)
                decisionHandler(.cancel)
                return
            }
            decisionHandler(.allow)
        }
    }
}
