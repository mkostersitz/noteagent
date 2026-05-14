//! Speech-to-text transcription, backed by whisper.cpp via `whisper-rs`.
//!
//! Mirrors the behavior of the previous Python implementation in
//! `src/noteagent/transcript.py`:
//!
//! - Three quality presets (`fast`, `balanced`, `accurate`) mapping to
//!   whisper.cpp's beam-search and temperature parameters.
//! - A hallucination filter that drops the well-known phrases whisper
//!   produces on silence (e.g. "thank you", "subtitles by …").
//! - A streaming chunker ([`LiveTranscriber`]) that buffers samples until
//!   enough audio is available, then transcribes a window at a time.

pub mod filter;
pub mod live;
pub mod presets;
pub mod whisper;

pub use filter::is_hallucination;
pub use live::{LiveTranscriber, DEFAULT_CHUNK_SECONDS};
pub use presets::{QualityPreset, TranscribeOptions};
pub use whisper::{Transcriber, WhisperTranscriber};
