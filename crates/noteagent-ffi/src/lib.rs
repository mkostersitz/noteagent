//! UniFFI bindings for `noteagent-core`. Consumed by the macOS / iOS / iPadOS
//! Swift apps.
//!
//! The surface here is intentionally narrow: it mirrors only what the Swift
//! UI actually needs and wraps `noteagent-core` types in thread-safe handles
//! so they're `Send + Sync` (a UniFFI requirement for `Object` types).
//!
//! See [`noteagent.udl`](./noteagent.udl) for the public interface.

use std::path::PathBuf;
use std::sync::Mutex;

use noteagent_core::models::{Segment as CoreSegment, Transcript as CoreTranscript};
use noteagent_core::transcription::{
    QualityPreset as CoreQuality, TranscribeOptions, Transcriber as TranscriberTrait,
    WhisperTranscriber as CoreWhisperTranscriber,
};
use noteagent_core::CoreError;

uniffi::include_scaffolding!("noteagent");

/// Library version, surfaced to Swift via the namespace function.
pub fn library_version() -> String {
    env!("CARGO_PKG_VERSION").to_string()
}

#[derive(Debug, thiserror::Error)]
pub enum FfiError {
    #[error("Model load failed: {0}")]
    ModelLoad(String),
    #[error("Transcription failed: {0}")]
    Transcription(String),
    #[error("I/O error: {0}")]
    Io(String),
    #[error("Invalid argument: {0}")]
    InvalidArgument(String),
}

impl From<CoreError> for FfiError {
    fn from(e: CoreError) -> Self {
        match e {
            CoreError::Transcription(m) => FfiError::Transcription(m),
            CoreError::Io(io) => FfiError::Io(io.to_string()),
            CoreError::WavError(w) => FfiError::Io(w.to_string()),
            CoreError::StreamError(m)
            | CoreError::DeviceNotFound(m)
            | CoreError::EnumerationError(m) => FfiError::Transcription(m),
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub enum QualityPreset {
    Fast,
    Balanced,
    Accurate,
}

impl From<QualityPreset> for CoreQuality {
    fn from(q: QualityPreset) -> Self {
        match q {
            QualityPreset::Fast => CoreQuality::Fast,
            QualityPreset::Balanced => CoreQuality::Balanced,
            QualityPreset::Accurate => CoreQuality::Accurate,
        }
    }
}

#[derive(Debug, Clone)]
pub struct Segment {
    pub start: f64,
    pub end: f64,
    pub text: String,
    pub confidence: f32,
    pub speaker: String,
}

impl From<CoreSegment> for Segment {
    fn from(s: CoreSegment) -> Self {
        Self {
            start: s.start,
            end: s.end,
            text: s.text,
            confidence: s.confidence,
            speaker: s.speaker,
        }
    }
}

#[derive(Debug, Clone)]
pub struct Transcript {
    pub segments: Vec<Segment>,
    pub language: String,
    pub model: String,
}

impl From<CoreTranscript> for Transcript {
    fn from(t: CoreTranscript) -> Self {
        Self {
            segments: t.segments.into_iter().map(Segment::from).collect(),
            language: t.language,
            model: t.model,
        }
    }
}

/// Thread-safe handle around the core `WhisperTranscriber`.
///
/// UniFFI requires `Object` types to be `Send + Sync`. The core transcriber's
/// inference method takes `&mut self` (it creates a fresh `WhisperState` per
/// call), so we serialize callers with a `Mutex`. Transcription is CPU-bound
/// and would not benefit from parallel calls on the same model anyway.
pub struct WhisperTranscriber {
    inner: Mutex<CoreWhisperTranscriber>,
}

impl WhisperTranscriber {
    pub fn new(model_path: String, model_id: String) -> Result<Self, FfiError> {
        let core = CoreWhisperTranscriber::load(&PathBuf::from(&model_path), model_id)
            .map_err(|e| FfiError::ModelLoad(e.to_string()))?;
        Ok(Self {
            inner: Mutex::new(core),
        })
    }

    pub fn transcribe_file(
        &self,
        audio_path: String,
        language: Option<String>,
        quality: QualityPreset,
    ) -> Result<Transcript, FfiError> {
        let opts = TranscribeOptions::from_preset(quality.into(), language.as_deref());
        let mut inner = self
            .inner
            .lock()
            .map_err(|_| FfiError::Transcription("mutex poisoned".into()))?;
        let t = inner
            .transcribe_file(&PathBuf::from(audio_path), &opts)
            .map_err(FfiError::from)?;
        Ok(Transcript::from(t))
    }

    pub fn transcribe_samples(
        &self,
        samples: Vec<f32>,
        time_offset: f64,
        language: Option<String>,
        quality: QualityPreset,
    ) -> Result<Vec<Segment>, FfiError> {
        let opts = TranscribeOptions::from_preset(quality.into(), language.as_deref());
        let mut inner = self
            .inner
            .lock()
            .map_err(|_| FfiError::Transcription("mutex poisoned".into()))?;
        let segs = inner
            .transcribe_samples(&samples, &opts, time_offset)
            .map_err(FfiError::from)?;
        Ok(segs.into_iter().map(Segment::from).collect())
    }

    pub fn model_id(&self) -> String {
        // Cheap to lock — the field is small and there is no contention with
        // long-running inference here.
        self.inner
            .lock()
            .map(|i| i.model_id().to_string())
            .unwrap_or_default()
    }
}
