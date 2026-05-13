# NoteAgent Architecture

## Cargo workspace layout

NoteAgent's native code is organized as a Cargo workspace so a single
platform-agnostic Rust core can power the Python CLI, the macOS app, and
(future) iOS / iPadOS apps with minimal duplication.

```
noteagent/
├── Cargo.toml                     # Workspace manifest
├── crates/
│   ├── noteagent-core/            # Pure-Rust core. No PyO3, no UniFFI, no UI.
│   │   └── src/
│   │       ├── audio/             # Capture, DSP, WAV writer, source traits
│   │       └── error.rs           # CoreError (no binding-layer types)
│   ├── noteagent-py/              # PyO3 bindings → `noteagent_audio` module
│   │   └── src/lib.rs             # Thin wrappers around noteagent-core
│   └── (future) noteagent-ffi/    # UniFFI bindings → Swift package / xcframework
└── src/noteagent/                 # Python package (FastAPI server, CLI, storage)
```

### Why the split?

| Crate | Depends on | Built by | Consumed by |
|-------|-----------|----------|-------------|
| `noteagent-core` | `cpal` (optional), `hound`, `ringbuf`, `serde`, `thiserror` | `cargo build` | Other Rust crates only |
| `noteagent-py` | `noteagent-core`, `pyo3` | `maturin` | Python (`import noteagent_audio`) |
| `noteagent-ffi` (future) | `noteagent-core`, `uniffi` | `cargo build` + `uniffi-bindgen` | Swift apps (macOS / iOS / iPadOS) |

`noteagent-core` is the single source of truth for audio capture, DSP, and
(in a later phase) transcription. The binding crates contain *only* the
translation between core types and their language-native equivalents.

## Cross-platform audio I/O

Audio capture is abstracted behind the `AudioSource` trait
(`crates/noteagent-core/src/audio/source.rs`). Two implementations ship with
the crate:

- **`CpalAudioSource`** — desktop platforms (macOS, Linux, Windows). Behind
  the `cpal-backend` Cargo feature, which is enabled by default. Holds a
  `cpal::Stream`; not `Send`.
- **`PushAudioSource`** — accepts PCM frames pushed in from the embedding
  application. Used by iOS / iPadOS, where capture happens in Swift via
  `AVAudioEngine` and frames are forwarded into Rust through the UniFFI
  bindings.

Both impls expose the same `read_chunk()` API, so the transcription pipeline
(added in a later phase) doesn't need to know where the samples came from.

### Building for iOS

iOS / iPadOS builds should disable the `cpal-backend` feature:

```bash
cargo build -p noteagent-core --no-default-features --target aarch64-apple-ios
```

The `PushAudioSource` is always available; cpal-specific types
(`CpalAudioSource`, `CpalRecorder`, `list_audio_devices`,
`find_device_by_name`) are gated behind `#[cfg(feature = "cpal-backend")]`.

## Build prerequisites

| Tool | Why | Install (macOS) | Install (Linux) |
|------|-----|-----------------|------------------|
| Rust toolchain | Core + bindings | `rustup default stable` | `rustup default stable` |
| `maturin` | Build the PyO3 extension | `pip install maturin` | `pip install maturin` |
| **C++ compiler + cmake** | Required once `whisper-rs` lands in core (Phase 3) — `whisper.cpp` is compiled from source as part of `cargo build` | Xcode CLT (`xcode-select --install`) | `apt-get install build-essential cmake clang` |

The C++/cmake requirement is documented up front so CI runners are
provisioned before the transcription rewrite begins.

## Building the Python extension

From the repo root:

```bash
cd crates/noteagent-py
maturin develop          # editable install into the active venv
# or
maturin build --release  # produce a wheel in ../../target/wheels/
```

The wheel installs a Python package named `noteagent-py`, but the Python
import name remains `noteagent_audio` (set via `[lib].name` in
`crates/noteagent-py/Cargo.toml`) so existing imports continue to work
unchanged.
