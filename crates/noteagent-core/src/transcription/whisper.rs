//! whisper.cpp-backed transcription (via `whisper-rs`).
//!
//! Loads a ggml `.bin` model once and exposes both batch (`transcribe_file`,
//! `transcribe_samples`) and streaming (via [`super::LiveTranscriber`]) entry
//! points.
//!
//! Replaces the previous `openai-whisper` / PyTorch path in
//! `src/noteagent/transcript.py`. The hallucination filter and quality
//! presets are ported one-to-one; only the underlying engine changed.

use std::path::Path;

use whisper_rs::{
    FullParams, SamplingStrategy, WhisperContext, WhisperContextParameters,
};

use crate::error::CoreError;
use crate::models::{Segment, Transcript};
use crate::transcription::filter::is_hallucination;
use crate::transcription::presets::TranscribeOptions;

/// Whisper expects 16 kHz mono PCM in the range `[-1.0, 1.0]`.
pub const WHISPER_SAMPLE_RATE: u32 = 16_000;

/// A generic transcription backend. `WhisperTranscriber` is the only
/// implementation today, but the trait lets future backends (cloud STT,
/// alternative on-device engines) drop in without touching call sites.
pub trait Transcriber {
    /// Transcribe a buffer of 16 kHz mono `f32` samples.
    ///
    /// `time_offset` is added to every segment's `start`/`end` so that the
    /// streaming chunker can produce continuous timestamps across windows.
    fn transcribe_samples(
        &mut self,
        samples: &[f32],
        opts: &TranscribeOptions,
        time_offset: f64,
    ) -> Result<Vec<Segment>, CoreError>;

    /// Identifier of the loaded model (e.g. "base.en").
    fn model_id(&self) -> &str;

    /// Sample rate the transcriber expects. Always 16 kHz for whisper.
    fn sample_rate(&self) -> u32 {
        WHISPER_SAMPLE_RATE
    }
}

/// whisper.cpp-backed [`Transcriber`].
pub struct WhisperTranscriber {
    context: WhisperContext,
    model_id: String,
}

impl WhisperTranscriber {
    /// Load a ggml `.bin` model from disk.
    pub fn load(model_path: &Path, model_id: impl Into<String>) -> Result<Self, CoreError> {
        let path_str = model_path.to_str().ok_or_else(|| {
            CoreError::Transcription(format!(
                "Model path is not valid UTF-8: {}",
                model_path.display()
            ))
        })?;

        let context = WhisperContext::new_with_params(path_str, WhisperContextParameters::default())
            .map_err(|e| {
                CoreError::Transcription(format!("Failed to load whisper model {path_str}: {e}"))
            })?;

        Ok(Self {
            context,
            model_id: model_id.into(),
        })
    }

    /// Transcribe a WAV file. Mono and stereo are supported (stereo is mixed
    /// down). Sample rate is converted to 16 kHz if needed.
    pub fn transcribe_file(
        &mut self,
        path: &Path,
        opts: &TranscribeOptions,
    ) -> Result<Transcript, CoreError> {
        let samples = load_wav_as_mono_16k(path)?;
        let segments = self.transcribe_samples(&samples, opts, 0.0)?;
        Ok(Transcript {
            segments,
            language: opts.language.clone().unwrap_or_else(|| "en".to_string()),
            model: self.model_id.clone(),
        })
    }
}

impl Transcriber for WhisperTranscriber {
    fn transcribe_samples(
        &mut self,
        samples: &[f32],
        opts: &TranscribeOptions,
        time_offset: f64,
    ) -> Result<Vec<Segment>, CoreError> {
        if samples.is_empty() {
            return Ok(Vec::new());
        }

        let mut state = self
            .context
            .create_state()
            .map_err(|e| CoreError::Transcription(format!("Failed to create whisper state: {e}")))?;

        let strategy = if opts.beam_size > 1 {
            SamplingStrategy::BeamSearch {
                beam_size: opts.beam_size,
                patience: -1.0,
            }
        } else {
            SamplingStrategy::Greedy {
                best_of: opts.best_of.max(1),
            }
        };

        let mut params = FullParams::new(strategy);
        if let Some(lang) = &opts.language {
            params.set_language(Some(lang.as_str()));
        }
        params.set_temperature(opts.temperature);
        params.set_print_progress(false);
        params.set_print_realtime(false);
        params.set_print_special(false);
        params.set_print_timestamps(false);
        // condition_on_previous_text on whisper.cpp is the "no_context" flag,
        // inverted: false means "use prior context".
        params.set_no_context(!opts.condition_on_previous_text);
        params.set_single_segment(false);

        state
            .full(params, samples)
            .map_err(|e| CoreError::Transcription(format!("whisper.full failed: {e}")))?;

        let num_segments = state
            .full_n_segments()
            .map_err(|e| CoreError::Transcription(format!("full_n_segments failed: {e}")))?;

        let mut segments = Vec::with_capacity(num_segments as usize);
        for i in 0..num_segments {
            let text = state
                .full_get_segment_text(i)
                .map_err(|e| CoreError::Transcription(format!("get_segment_text failed: {e}")))?;
            if is_hallucination(&text) {
                continue;
            }
            let t0 = state
                .full_get_segment_t0(i)
                .map_err(|e| CoreError::Transcription(format!("get_segment_t0 failed: {e}")))?;
            let t1 = state
                .full_get_segment_t1(i)
                .map_err(|e| CoreError::Transcription(format!("get_segment_t1 failed: {e}")))?;
            // whisper.cpp reports timestamps in centiseconds.
            let start = (t0 as f64) / 100.0 + time_offset;
            let end = (t1 as f64) / 100.0 + time_offset;
            segments.push(Segment::new(start, end, text));
        }

        Ok(segments)
    }

    fn model_id(&self) -> &str {
        &self.model_id
    }
}

/// Load a WAV file and return 16 kHz mono `f32` samples in `[-1.0, 1.0]`.
fn load_wav_as_mono_16k(path: &Path) -> Result<Vec<f32>, CoreError> {
    let mut reader = hound::WavReader::open(path).map_err(CoreError::WavError)?;
    let spec = reader.spec();
    let channels = spec.channels as usize;
    let src_rate = spec.sample_rate;

    let mut interleaved: Vec<f32> = match spec.sample_format {
        hound::SampleFormat::Int => {
            let max = match spec.bits_per_sample {
                16 => i16::MAX as f32,
                24 => 8_388_607.0,
                32 => i32::MAX as f32,
                bps => {
                    return Err(CoreError::Transcription(format!(
                        "Unsupported PCM bit depth: {bps}"
                    )))
                }
            };
            reader
                .samples::<i32>()
                .map(|s| s.map(|v| v as f32 / max))
                .collect::<Result<Vec<_>, _>>()
                .map_err(CoreError::WavError)?
        }
        hound::SampleFormat::Float => reader
            .samples::<f32>()
            .collect::<Result<Vec<_>, _>>()
            .map_err(CoreError::WavError)?,
    };

    if channels > 1 {
        interleaved = crate::audio::dsp::to_mono(&interleaved, spec.channels);
    }

    if src_rate != WHISPER_SAMPLE_RATE {
        interleaved = crate::audio::dsp::downsample(&interleaved, src_rate, WHISPER_SAMPLE_RATE);
    }

    Ok(interleaved)
}
