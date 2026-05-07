"""Tests for audio backend error handling."""

import builtins

import pytest

from noteagent.audio import AudioBackendUnavailable, _load_backend, resolve_device


def test_load_backend_missing_raises_actionable_error(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "noteagent_audio":
            raise ModuleNotFoundError("No module named 'noteagent_audio'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(AudioBackendUnavailable) as excinfo:
        _load_backend()

    assert "maturin develop" in str(excinfo.value)


# ---------------------------------------------------------------------------
# resolve_device
# ---------------------------------------------------------------------------

FAKE_DEVICES = ["Built-in Microphone", "BlackHole 2ch", "USB Audio"]


def test_resolve_device_none_returns_none(monkeypatch):
    monkeypatch.setattr("noteagent.audio.list_devices", lambda: FAKE_DEVICES)
    assert resolve_device(None) is None


def test_resolve_device_name_passthrough(monkeypatch):
    monkeypatch.setattr("noteagent.audio.list_devices", lambda: FAKE_DEVICES)
    assert resolve_device("BlackHole 2ch") == "BlackHole 2ch"


def test_resolve_device_index_zero(monkeypatch):
    monkeypatch.setattr("noteagent.audio.list_devices", lambda: FAKE_DEVICES)
    assert resolve_device("0") == "Built-in Microphone"


def test_resolve_device_index_last(monkeypatch):
    monkeypatch.setattr("noteagent.audio.list_devices", lambda: FAKE_DEVICES)
    assert resolve_device("2") == "USB Audio"


def test_resolve_device_index_out_of_range(monkeypatch):
    monkeypatch.setattr("noteagent.audio.list_devices", lambda: FAKE_DEVICES)
    with pytest.raises(ValueError, match="out of range"):
        resolve_device("99")
