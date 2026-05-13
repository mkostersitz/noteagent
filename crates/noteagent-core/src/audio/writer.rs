//! WAV file sink — platform-agnostic.
//!
//! Used by both the desktop `CpalRecorder` and (eventually) the iOS Swift side
//! when capturing through `AVAudioEngine`.

use std::path::Path;

use hound::{WavSpec, WavWriter};

use crate::error::CoreError;

type FileWriter = WavWriter<std::io::BufWriter<std::fs::File>>;

/// A mono 16-bit PCM WAV sink writing to a file on disk.
pub struct WavSink {
    writer: Option<FileWriter>,
}

impl WavSink {
    /// Create a new WAV file at `path` ready to receive samples at `sample_rate` Hz.
    pub fn create(path: &Path, sample_rate: u32) -> Result<Self, CoreError> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }

        let spec = WavSpec {
            channels: 1,
            sample_rate,
            bits_per_sample: 16,
            sample_format: hound::SampleFormat::Int,
        };

        let writer = WavWriter::create(path, spec)?;
        Ok(Self {
            writer: Some(writer),
        })
    }

    /// Write a slice of mono `f32` samples in the range `[-1.0, 1.0]`.
    pub fn write_samples(&mut self, samples: &[f32]) -> Result<(), CoreError> {
        if let Some(ref mut w) = self.writer {
            for &sample in samples {
                let amplitude = (sample * i16::MAX as f32) as i16;
                w.write_sample(amplitude)?;
            }
        }
        Ok(())
    }

    /// Finalize and close the WAV file. Safe to call multiple times.
    pub fn finalize(&mut self) -> Result<(), CoreError> {
        if let Some(writer) = self.writer.take() {
            writer.finalize()?;
        }
        Ok(())
    }
}

impl Drop for WavSink {
    fn drop(&mut self) {
        let _ = self.finalize();
    }
}
