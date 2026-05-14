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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn write_and_read_back_round_trip() {
        let dir = tempdir();
        let path = dir.join("out.wav");

        {
            let mut sink = WavSink::create(&path, 16_000).unwrap();
            sink.write_samples(&[0.0, 0.5, -0.5, 1.0, -1.0]).unwrap();
            sink.finalize().unwrap();
        }

        let mut reader = hound::WavReader::open(&path).unwrap();
        let spec = reader.spec();
        assert_eq!(spec.channels, 1);
        assert_eq!(spec.sample_rate, 16_000);
        assert_eq!(spec.bits_per_sample, 16);

        let samples: Vec<i32> = reader.samples::<i32>().collect::<Result<_, _>>().unwrap();
        assert_eq!(samples.len(), 5);
        assert_eq!(samples[0], 0);
        assert!((samples[1] - 16_383).abs() <= 1);
        assert_eq!(samples[3], i16::MAX as i32);
    }

    #[test]
    fn finalize_is_idempotent() {
        let dir = tempdir();
        let path = dir.join("out.wav");
        let mut sink = WavSink::create(&path, 16_000).unwrap();
        sink.write_samples(&[0.1]).unwrap();
        sink.finalize().unwrap();
        // Calling finalize again must not error.
        sink.finalize().unwrap();
    }

    #[test]
    fn create_makes_parent_dirs() {
        let dir = tempdir();
        let nested = dir.join("nested").join("deeper");
        let path = nested.join("out.wav");
        let mut sink = WavSink::create(&path, 16_000).unwrap();
        sink.write_samples(&[0.0]).unwrap();
        sink.finalize().unwrap();
        assert!(path.exists());
    }

    /// Unique temp dir under the system temp root. Avoids adding a
    /// `tempfile` dev-dependency for three helper tests.
    fn tempdir() -> std::path::PathBuf {
        let base = std::env::temp_dir();
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir = base.join(format!("noteagent-core-test-{nanos}"));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }
}
