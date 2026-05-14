"""ggml whisper.cpp model downloader.

Models are fetched from the official whisper.cpp HuggingFace mirror at
`huggingface.co/ggerganov/whisper.cpp`. Files use the naming convention
`ggml-<size>.bin` (e.g. `ggml-base.en.bin`).

Provides both synchronous (CLI) and background (server / first-launch
migration) entry points.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

def _default_model_dir() -> Path:
    """Resolve the model directory.

    Honors `NOTEAGENT_MODEL_DIR` so a bundled macOS app (or any deployment
    where `noteagent` isn't installed editable from the repo) can point at
    a fixed location like `Contents/Resources/models/`. Falls back to the
    repo-relative `models/` dir for the developer setup.
    """
    env = os.environ.get("NOTEAGENT_MODEL_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parent.parent.parent / "models"


MODEL_DIR = _default_model_dir()

# Supported model sizes and their canonical sizes (approximate, MB).
# Source: https://github.com/ggerganov/whisper.cpp/blob/master/models/README.md
_MODELS: dict[str, int] = {
    "tiny.en": 75,
    "tiny": 75,
    "base.en": 142,
    "base": 142,
    "small.en": 466,
    "small": 466,
    "medium.en": 1500,
    "medium": 1500,
    "large-v3": 3000,
    "large-v3-turbo": 1500,
}

_HUGGINGFACE_BASE = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"

# Module-level lock + map so concurrent ensure_async() calls for the same
# model coalesce onto a single download thread.
_inflight_lock = threading.Lock()
_inflight: dict[str, threading.Thread] = {}


ProgressCallback = Callable[[int, Optional[int]], None]
"""(downloaded_bytes, total_bytes_or_None) — invoked periodically during a download."""


def known_models() -> list[str]:
    """List supported ggml model sizes."""
    return list(_MODELS.keys())


def model_path(size: str, root: Optional[Path] = None) -> Path:
    """Return the on-disk path for a ggml model of the given size.

    When `root` is None, re-resolves from `NOTEAGENT_MODEL_DIR` on every call
    so monkeypatching the env var in tests (and the macOS app setting it on
    process launch) works regardless of import order.
    """
    return (root or _default_model_dir()) / f"ggml-{size}.bin"


def is_model_present(size: str, root: Optional[Path] = None) -> bool:
    """True if the .bin for `size` exists at its expected location."""
    return model_path(size, root).exists()


def _model_url(size: str) -> str:
    if size not in _MODELS:
        raise ValueError(
            f"Unknown whisper model size: {size}. Known sizes: {', '.join(known_models())}"
        )
    return f"{_HUGGINGFACE_BASE}/ggml-{size}.bin"


def _default_progress(stderr: bool = True):
    """Build a simple stderr progress callback that throttles to ~5 Hz."""
    state = {"last": 0.0, "started": time.monotonic()}

    def _cb(downloaded: int, total: Optional[int]) -> None:
        now = time.monotonic()
        if now - state["last"] < 0.2 and (total is None or downloaded < total):
            return
        state["last"] = now
        elapsed = max(now - state["started"], 0.001)
        mb = downloaded / (1024 * 1024)
        speed = mb / elapsed
        if total:
            pct = (downloaded / total) * 100
            total_mb = total / (1024 * 1024)
            line = f"\r⬇  {pct:5.1f}% ({mb:.1f}/{total_mb:.1f} MB) {speed:.1f} MB/s"
        else:
            line = f"\r⬇  {mb:.1f} MB {speed:.1f} MB/s"
        print(line, end="", file=sys.stderr if stderr else sys.stdout, flush=True)

    return _cb


def download_model(
    size: str,
    root: Optional[Path] = None,
    on_progress: Optional[ProgressCallback] = None,
    chunk_size: int = 1024 * 1024,
) -> Path:
    """Synchronously download a ggml model file.

    Writes to `<root>/ggml-<size>.bin.part`, then atomically renames on success.
    Raises `RuntimeError` on network or I/O failure. Idempotent: if the target
    file already exists, returns immediately.
    """
    target = model_path(size, root)
    if target.exists():
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    url = _model_url(size)
    tmp = target.with_suffix(target.suffix + ".part")

    try:
        with urllib.request.urlopen(url) as src, open(tmp, "wb") as out:
            total_hdr = src.headers.get("Content-Length")
            total = int(total_hdr) if total_hdr and total_hdr.isdigit() else None
            downloaded = 0
            while True:
                chunk = src.read(chunk_size)
                if not chunk:
                    break
                out.write(chunk)
                downloaded += len(chunk)
                if on_progress is not None:
                    on_progress(downloaded, total)
    except (urllib.error.URLError, OSError) as exc:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to download {size} from {url}: {exc}") from exc

    tmp.replace(target)
    return target


def ensure_model_async(
    size: str,
    root: Optional[Path] = None,
    on_progress: Optional[ProgressCallback] = None,
) -> Optional[threading.Thread]:
    """Start a background download if the model isn't already present.

    Returns the worker thread, or `None` if the model is already on disk.
    Concurrent calls for the same `size` reuse the same thread.

    Errors are logged to stderr; callers that need to react to failure should
    use `download_model` directly.
    """
    if is_model_present(size, root):
        return None

    with _inflight_lock:
        existing = _inflight.get(size)
        if existing is not None and existing.is_alive():
            return existing

        def _worker():
            try:
                download_model(size, root=root, on_progress=on_progress)
            except Exception as exc:  # noqa: BLE001 — background log only
                print(
                    f"\n[noteagent] Background model download failed for {size}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
            finally:
                with _inflight_lock:
                    _inflight.pop(size, None)

        t = threading.Thread(
            target=_worker,
            name=f"noteagent-model-download:{size}",
            daemon=True,
        )
        _inflight[size] = t
        t.start()
        return t


def cli_download(size: str, root: Optional[Path] = None) -> Path:
    """Foreground download helper for CLI use. Prints progress to stderr."""
    if is_model_present(size, root):
        target = model_path(size, root)
        print(f"✔ Model already present: {target}", file=sys.stderr)
        return target

    print(f"⬇  Downloading whisper.cpp model: ggml-{size}.bin", file=sys.stderr)
    target = download_model(size, root=root, on_progress=_default_progress())
    # Newline after the progress carriage-return updates.
    print(f"\n✔ Saved to {target}", file=sys.stderr)
    return target


# Environment knob — set NOTEAGENT_SKIP_AUTO_DOWNLOAD=1 to disable the
# first-launch background fetch (useful in CI / tests).
def auto_download_enabled() -> bool:
    return os.environ.get("NOTEAGENT_SKIP_AUTO_DOWNLOAD", "").strip().lower() not in {"1", "true", "yes"}
