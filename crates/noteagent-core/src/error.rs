use thiserror::Error;

/// Errors produced by the noteagent-core library.
///
/// This enum is intentionally free of binding-layer concerns (no `PyErr`, no
/// UniFFI mapping). Binding crates are responsible for converting `CoreError`
/// into their language-native error type.
#[derive(Error, Debug)]
pub enum CoreError {
    #[error("No audio device found: {0}")]
    DeviceNotFound(String),

    #[error("Audio stream error: {0}")]
    StreamError(String),

    #[error("WAV write error: {0}")]
    WavError(#[from] hound::Error),

    #[error("Device enumeration error: {0}")]
    EnumerationError(String),

    #[error("Transcription error: {0}")]
    Transcription(String),

    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),
}
