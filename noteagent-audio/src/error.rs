use thiserror::Error;

#[derive(Error, Debug)]
pub enum AudioError {
    #[error("No audio device found: {0}")]
    DeviceNotFound(String),

    #[error("Audio stream error: {0}")]
    StreamError(String),

    #[error("WAV write error: {0}")]
    WavError(#[from] hound::Error),

    #[error("Device enumeration error: {0}")]
    EnumerationError(String),
}

impl From<AudioError> for pyo3::PyErr {
    fn from(err: AudioError) -> pyo3::PyErr {
        pyo3::exceptions::PyRuntimeError::new_err(err.to_string())
    }
}
