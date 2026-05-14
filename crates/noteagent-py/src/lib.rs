//! PyO3 bindings exposing `noteagent-core` to the Python package.
//!
//! This crate is intentionally thin: it owns no audio or transcription logic,
//! only the translation between PyO3 types and `noteagent_core` types. All
//! capture, DSP, and transcription code lives in `noteagent-core`.
//!
//! The returned shapes (`dict` for `Segment`/`Transcript`) are designed to
//! splat directly into the existing pydantic models in
//! `src/noteagent/models.py` via `TranscriptSegment(**seg)` /
//! `Transcript(**t)`, so the rest of the Python codebase is unchanged.

use std::path::PathBuf;

use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use pyo3::types::PyDict;

use noteagent_core::audio::{
    list_audio_devices as core_list_devices, AudioSource, CpalAudioSource, CpalRecorder,
};
use noteagent_core::models::{Segment, Transcript};
use noteagent_core::transcription::{
    LiveTranscriber as CoreLiveTranscriber, QualityPreset, TranscribeOptions,
    Transcriber as TranscriberTrait, WhisperTranscriber as CoreWhisperTranscriber,
    DEFAULT_CHUNK_SECONDS,
};
use noteagent_core::CoreError;

fn map_err(err: CoreError) -> PyErr {
    PyRuntimeError::new_err(err.to_string())
}

// ---------------------------------------------------------------------------
// Audio (unchanged Python API)
// ---------------------------------------------------------------------------

/// List all available audio input devices by name.
#[pyfunction]
fn list_audio_devices() -> PyResult<Vec<String>> {
    core_list_devices().map_err(map_err)
}

/// Records audio to a WAV file via the cpal-backed core recorder.
#[pyclass(unsendable)]
pub struct AudioRecorder {
    inner: CpalRecorder,
}

#[pymethods]
impl AudioRecorder {
    #[new]
    #[pyo3(signature = (device_name=None, sample_rate=16000))]
    fn new(device_name: Option<String>, sample_rate: u32) -> PyResult<Self> {
        let _ = device_name; // Selected at `start()` time, matching prior behavior.
        Ok(Self {
            inner: CpalRecorder::new(sample_rate),
        })
    }

    #[pyo3(signature = (output_path, device_name=None))]
    fn start(&mut self, output_path: String, device_name: Option<String>) -> PyResult<()> {
        self.inner
            .start(&PathBuf::from(output_path), device_name.as_deref())
            .map_err(map_err)
    }

    fn stop(&mut self) -> PyResult<()> {
        self.inner.stop().map_err(map_err)
    }
}

/// Streams audio chunks for real-time processing.
#[pyclass(unsendable)]
pub struct AudioStream {
    inner: CpalAudioSource,
}

#[pymethods]
impl AudioStream {
    #[new]
    #[pyo3(signature = (device_name=None, sample_rate=16000))]
    fn new(device_name: Option<String>, sample_rate: u32) -> PyResult<Self> {
        let inner = CpalAudioSource::new(device_name.as_deref(), sample_rate).map_err(map_err)?;
        Ok(Self { inner })
    }

    fn read_chunk(&mut self) -> PyResult<Vec<f32>> {
        self.inner.read_chunk().map_err(map_err)
    }

    fn get_sample_rate(&self) -> u32 {
        self.inner.sample_rate()
    }

    fn stop(&mut self) -> PyResult<()> {
        self.inner.stop().map_err(map_err)
    }
}

// ---------------------------------------------------------------------------
// Transcription
// ---------------------------------------------------------------------------

fn segment_to_dict<'py>(py: Python<'py>, seg: &Segment) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("start", seg.start)?;
    d.set_item("end", seg.end)?;
    d.set_item("text", &seg.text)?;
    d.set_item("confidence", seg.confidence)?;
    d.set_item("speaker", &seg.speaker)?;
    Ok(d)
}

fn transcript_to_dict<'py>(py: Python<'py>, t: &Transcript) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    let segs: Vec<Bound<'py, PyDict>> = t
        .segments
        .iter()
        .map(|s| segment_to_dict(py, s))
        .collect::<PyResult<_>>()?;
    d.set_item("segments", segs)?;
    d.set_item("language", &t.language)?;
    d.set_item("model", &t.model)?;
    Ok(d)
}

fn resolve_options(language: Option<String>, quality: &str) -> TranscribeOptions {
    let preset = QualityPreset::from_str_ci(quality);
    TranscribeOptions::from_preset(preset, language.as_deref())
}

/// Batch transcriber holding a loaded ggml model.
///
/// Construct once, call `transcribe_file` or `transcribe_samples` repeatedly;
/// the underlying whisper.cpp context is reused across calls.
#[pyclass(unsendable)]
pub struct WhisperTranscriber {
    inner: CoreWhisperTranscriber,
    language: Option<String>,
    quality: String,
}

#[pymethods]
impl WhisperTranscriber {
    /// Load a ggml `.bin` model from disk.
    ///
    /// - `model_path`: path to a `ggml-*.bin` file on disk.
    /// - `model_id`: identifier stored on returned `Transcript.model`
    ///   (typically `"base.en"`, `"small"`, etc.).
    /// - `language`: optional ISO language hint. `None` lets whisper detect.
    /// - `quality`: one of `"fast"`, `"balanced"`, `"accurate"`.
    #[new]
    #[pyo3(signature = (model_path, model_id="base.en", language=None, quality="balanced"))]
    fn new(
        model_path: String,
        model_id: &str,
        language: Option<String>,
        quality: &str,
    ) -> PyResult<Self> {
        let inner = CoreWhisperTranscriber::load(&PathBuf::from(model_path), model_id)
            .map_err(map_err)?;
        Ok(Self {
            inner,
            language,
            quality: quality.to_string(),
        })
    }

    /// Transcribe a WAV file. Returns a dict shaped like
    /// `{"segments": [...], "language": "en", "model": "base.en"}`.
    ///
    /// `language` and `quality` override the construction-time defaults for
    /// this call only.
    #[pyo3(signature = (audio_path, language=None, quality=None))]
    fn transcribe_file<'py>(
        &mut self,
        py: Python<'py>,
        audio_path: String,
        language: Option<String>,
        quality: Option<String>,
    ) -> PyResult<Bound<'py, PyDict>> {
        let lang = language.or_else(|| self.language.clone());
        let qual = quality.unwrap_or_else(|| self.quality.clone());
        let opts = resolve_options(lang, &qual);
        let transcript = self
            .inner
            .transcribe_file(&PathBuf::from(audio_path), &opts)
            .map_err(map_err)?;
        transcript_to_dict(py, &transcript)
    }

    /// Transcribe a raw 16 kHz mono `f32` PCM buffer in `[-1.0, 1.0]`.
    /// Returns a list of segment dicts.
    #[pyo3(signature = (samples, time_offset=0.0, language=None, quality=None))]
    fn transcribe_samples<'py>(
        &mut self,
        py: Python<'py>,
        samples: Vec<f32>,
        time_offset: f64,
        language: Option<String>,
        quality: Option<String>,
    ) -> PyResult<Vec<Bound<'py, PyDict>>> {
        let lang = language.or_else(|| self.language.clone());
        let qual = quality.unwrap_or_else(|| self.quality.clone());
        let opts = resolve_options(lang, &qual);
        let segs = self
            .inner
            .transcribe_samples(&samples, &opts, time_offset)
            .map_err(map_err)?;
        segs.iter().map(|s| segment_to_dict(py, s)).collect()
    }

    #[getter]
    fn model_id(&self) -> &str {
        self.inner.model_id()
    }
}

/// Streaming transcriber for near-real-time live transcription.
///
/// Buffers audio internally and runs whisper.cpp on each `chunk_duration`
/// window. Call `feed(samples)` repeatedly; the returned list contains any
/// new segments produced during that call.
#[pyclass(unsendable)]
pub struct LiveTranscriber {
    inner: CoreLiveTranscriber<CoreWhisperTranscriber>,
}

#[pymethods]
impl LiveTranscriber {
    /// - `chunk_duration`: window size in seconds. Default 5.0 (matches the
    ///   prior Python implementation). Surface this in the prefs UI so users
    ///   can trade latency for accuracy.
    #[new]
    #[pyo3(signature = (model_path, model_id="base.en", language=None, quality="balanced", chunk_duration=DEFAULT_CHUNK_SECONDS))]
    fn new(
        model_path: String,
        model_id: &str,
        language: Option<String>,
        quality: &str,
        chunk_duration: f64,
    ) -> PyResult<Self> {
        let transcriber = CoreWhisperTranscriber::load(&PathBuf::from(model_path), model_id)
            .map_err(map_err)?;
        let opts = resolve_options(language, quality);
        Ok(Self {
            inner: CoreLiveTranscriber::new(transcriber, opts, chunk_duration),
        })
    }

    /// Feed `f32` mono samples at the transcriber's sample rate (16 kHz).
    /// Returns any new segments produced while draining buffered audio.
    fn feed<'py>(
        &mut self,
        py: Python<'py>,
        samples: Vec<f32>,
    ) -> PyResult<Vec<Bound<'py, PyDict>>> {
        let segs = self.inner.feed(&samples).map_err(map_err)?;
        segs.iter().map(|s| segment_to_dict(py, s)).collect()
    }

    /// Return the accumulated transcript so far.
    fn transcript<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        transcript_to_dict(py, &self.inner.transcript())
    }

    #[getter]
    fn silence_seconds(&self) -> f64 {
        self.inner.silence_seconds()
    }
}

// ---------------------------------------------------------------------------
// Module init
// ---------------------------------------------------------------------------

#[pymodule]
fn noteagent_audio(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(list_audio_devices, m)?)?;
    m.add_class::<AudioRecorder>()?;
    m.add_class::<AudioStream>()?;
    m.add_class::<WhisperTranscriber>()?;
    m.add_class::<LiveTranscriber>()?;
    Ok(())
}
