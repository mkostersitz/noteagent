//! Streaming chunker for near-real-time live transcription.
//!
//! Mirrors the behavior of `LiveTranscriber` in the previous
//! `src/noteagent/transcript.py`:
//!
//! 1. Audio samples are buffered until at least `chunk_duration` seconds are
//!    available.
//! 2. The chunk is handed to the underlying [`Transcriber`].
//! 3. Segment timestamps are offset so they advance continuously across chunks.
//! 4. A simple silence counter tracks consecutive chunks that produced no
//!    accepted segments.
//!
//! `chunk_duration` is exposed at the API surface so it can be plumbed through
//! to the preferences UI later (per the agreed plan).

use crate::error::CoreError;
use crate::models::{Segment, Transcript};
use crate::transcription::presets::TranscribeOptions;
use crate::transcription::whisper::Transcriber;

/// Default chunk size when none is specified, in seconds. Matches the
/// previous Python implementation.
pub const DEFAULT_CHUNK_SECONDS: f64 = 5.0;

pub struct LiveTranscriber<T: Transcriber> {
    transcriber: T,
    options: TranscribeOptions,
    sample_rate: u32,
    chunk_duration: f64,
    buffer: Vec<f32>,
    segments: Vec<Segment>,
    time_offset: f64,
    silence_seconds: f64,
}

impl<T: Transcriber> LiveTranscriber<T> {
    pub fn new(transcriber: T, options: TranscribeOptions, chunk_duration: f64) -> Self {
        Self {
            sample_rate: transcriber.sample_rate(),
            transcriber,
            options,
            chunk_duration: if chunk_duration > 0.0 {
                chunk_duration
            } else {
                DEFAULT_CHUNK_SECONDS
            },
            buffer: Vec::new(),
            segments: Vec::new(),
            time_offset: 0.0,
            silence_seconds: 0.0,
        }
    }

    pub fn with_default_chunk(transcriber: T, options: TranscribeOptions) -> Self {
        Self::new(transcriber, options, DEFAULT_CHUNK_SECONDS)
    }

    /// Seconds of continuous silence since the last accepted segment.
    pub fn silence_seconds(&self) -> f64 {
        self.silence_seconds
    }

    /// Feed a chunk of mono `f32` samples. Returns any new segments produced
    /// while draining buffered audio.
    pub fn feed(&mut self, samples: &[f32]) -> Result<Vec<Segment>, CoreError> {
        if samples.is_empty() && self.buffer.is_empty() {
            return Ok(Vec::new());
        }

        self.buffer.extend_from_slice(samples);

        let required = (self.sample_rate as f64 * self.chunk_duration) as usize;
        if self.buffer.len() < required {
            return Ok(Vec::new());
        }

        // Drain one window. We deliberately process a single chunk per call to
        // match the prior Python behavior; the caller drives cadence.
        let chunk: Vec<f32> = self.buffer.drain(..required).collect();

        let mut new_segments =
            self.transcriber
                .transcribe_samples(&chunk, &self.options, self.time_offset)?;

        let window_end = self.time_offset + self.chunk_duration;
        for seg in &mut new_segments {
            if seg.end > window_end {
                seg.end = window_end;
            }
        }

        if new_segments.is_empty() {
            self.silence_seconds += self.chunk_duration;
        } else {
            self.silence_seconds = 0.0;
        }

        self.segments.extend(new_segments.iter().cloned());
        self.time_offset += self.chunk_duration;

        Ok(new_segments)
    }

    /// Return the accumulated transcript so far.
    pub fn transcript(&self) -> Transcript {
        Transcript {
            segments: self.segments.clone(),
            language: self
                .options
                .language
                .clone()
                .unwrap_or_else(|| "en".to_string()),
            model: self.transcriber.model_id().to_string(),
        }
    }
}

/// Convenience: how many samples make up one chunk for the given rate.
pub fn chunk_size(sample_rate: u32, chunk_duration: f64) -> usize {
    (sample_rate as f64 * chunk_duration) as usize
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::transcription::whisper::WHISPER_SAMPLE_RATE;

    /// A fake transcriber that emits one segment per call so we can exercise
    /// the chunker without loading a real model.
    struct FakeTranscriber {
        counter: usize,
    }

    impl Transcriber for FakeTranscriber {
        fn transcribe_samples(
            &mut self,
            _samples: &[f32],
            _opts: &TranscribeOptions,
            time_offset: f64,
        ) -> Result<Vec<Segment>, CoreError> {
            self.counter += 1;
            Ok(vec![Segment::new(
                time_offset,
                time_offset + 1.0,
                format!("chunk {}", self.counter),
            )])
        }

        fn model_id(&self) -> &str {
            "fake"
        }

        fn sample_rate(&self) -> u32 {
            WHISPER_SAMPLE_RATE
        }
    }

    #[test]
    fn live_chunker_drains_one_window_at_a_time() {
        let fake = FakeTranscriber { counter: 0 };
        let opts = TranscribeOptions {
            beam_size: 1,
            best_of: 1,
            temperature: 0.0,
            condition_on_previous_text: false,
            language: Some("en".into()),
        };
        let mut live = LiveTranscriber::new(fake, opts, 1.0);

        let half = vec![0.0f32; WHISPER_SAMPLE_RATE as usize / 2];
        assert!(live.feed(&half).unwrap().is_empty());

        let segs = live.feed(&half).unwrap();
        assert_eq!(segs.len(), 1);
        assert_eq!(segs[0].text, "chunk 1");
        assert_eq!(live.transcript().segments.len(), 1);
    }
}
