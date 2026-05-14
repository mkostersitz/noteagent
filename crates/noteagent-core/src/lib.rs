//! NoteAgent core library — platform-agnostic audio capture and (eventually) transcription.
//!
//! This crate has no Python, Swift, or UI dependencies. It is consumed by:
//!   - `noteagent-py`  → PyO3 bindings used by the Python CLI and FastAPI server.
//!   - `noteagent-ffi` → UniFFI bindings used by macOS / iOS / iPadOS Swift apps (future).
//!   - Direct Rust consumers (CLI tools, tests).
//!
//! Audio I/O is abstracted behind the [`audio::AudioSource`] trait so the same
//! transcription pipeline can be driven by `cpal` on desktop or by
//! `AVAudioEngine` (via push from Swift) on iOS.

pub mod audio;
pub mod error;
pub mod models;
pub mod transcription;

pub use error::CoreError;
