"""Tests for audio backend error handling."""

import builtins

import pytest

from noteagent.audio import AudioBackendUnavailable, _load_backend


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
