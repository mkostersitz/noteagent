"""Tests for transcription utilities."""

from pathlib import Path

from noteagent.transcript import _resolve_ca_bundle


def test_resolve_ca_bundle_precedence(tmp_path: Path, monkeypatch):
    noteagent_ca = tmp_path / "noteagent.pem"
    requests_ca = tmp_path / "requests.pem"
    ssl_ca = tmp_path / "ssl.pem"

    noteagent_ca.write_text("A")
    requests_ca.write_text("B")
    ssl_ca.write_text("C")

    monkeypatch.setenv("SSL_CERT_FILE", str(ssl_ca))
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(requests_ca))
    monkeypatch.setenv("NOTEAGENT_CA_BUNDLE", str(noteagent_ca))

    assert _resolve_ca_bundle() == noteagent_ca


def test_resolve_ca_bundle_missing_returns_none(monkeypatch):
    monkeypatch.delenv("NOTEAGENT_CA_BUNDLE", raising=False)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)

    assert _resolve_ca_bundle() is None
