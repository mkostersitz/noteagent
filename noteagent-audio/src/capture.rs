use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::StreamConfig;
use hound::{WavSpec, WavWriter};
use pyo3::prelude::*;
use ringbuf::{HeapRb, traits::{Consumer, Observer, Producer, Split}};

use crate::device::find_device_by_name;
use crate::error::AudioError;

const RING_BUFFER_SIZE: usize = 48000 * 30; // ~30 seconds at 48kHz

/// Downsample by simple decimation (pick every Nth sample).
/// For proper use, the input should already be low-pass filtered by the device.
fn downsample(input: &[f32], from_rate: u32, to_rate: u32) -> Vec<f32> {
    if from_rate == to_rate {
        return input.to_vec();
    }
    let ratio = from_rate as f64 / to_rate as f64;
    let out_len = (input.len() as f64 / ratio).ceil() as usize;
    let mut output = Vec::with_capacity(out_len);
    let mut pos = 0.0f64;
    while (pos as usize) < input.len() {
        output.push(input[pos as usize]);
        pos += ratio;
    }
    output
}

/// Mix multi-channel interleaved samples down to mono.
fn to_mono(input: &[f32], channels: u16) -> Vec<f32> {
    if channels == 1 {
        return input.to_vec();
    }
    let ch = channels as usize;
    input
        .chunks_exact(ch)
        .map(|frame| frame.iter().sum::<f32>() / channels as f32)
        .collect()
}

/// Get the device's default input config, returning (StreamConfig, native_sample_rate, native_channels).
fn get_device_config(device: &cpal::Device) -> Result<(StreamConfig, u32, u16), AudioError> {
    let supported = device
        .default_input_config()
        .map_err(|e| AudioError::StreamError(format!("No supported input config: {e}")))?;

    let native_rate = supported.sample_rate().0;
    let native_channels = supported.channels();

    let config = StreamConfig {
        channels: native_channels,
        sample_rate: cpal::SampleRate(native_rate),
        buffer_size: cpal::BufferSize::Default,
    };

    Ok((config, native_rate, native_channels))
}

/// Records audio to a WAV file.
#[pyclass(unsendable)]
pub struct AudioRecorder {
    writer: Arc<Mutex<Option<WavWriter<std::io::BufWriter<std::fs::File>>>>>,
    stream: Option<cpal::Stream>,
    sample_rate: u32,
}

#[pymethods]
impl AudioRecorder {
    #[new]
    #[pyo3(signature = (device_name=None, sample_rate=16000))]
    fn new(device_name: Option<String>, sample_rate: u32) -> PyResult<Self> {
        let _ = device_name;
        Ok(Self {
            writer: Arc::new(Mutex::new(None)),
            stream: None,
            sample_rate,
        })
    }

    /// Start recording audio to the given WAV file path.
    #[pyo3(signature = (output_path, device_name=None))]
    fn start(&mut self, output_path: String, device_name: Option<String>) -> PyResult<()> {
        let device = match device_name {
            Some(name) => find_device_by_name(&name)?,
            None => cpal::default_host()
                .default_input_device()
                .ok_or(AudioError::DeviceNotFound("default".into()))?,
        };

        let (config, native_rate, native_channels) = get_device_config(&device)?;
        let target_rate = self.sample_rate;

        let spec = WavSpec {
            channels: 1,
            sample_rate: target_rate,
            bits_per_sample: 16,
            sample_format: hound::SampleFormat::Int,
        };

        let path = PathBuf::from(&output_path);
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|e| AudioError::StreamError(format!("Cannot create directory: {e}")))?;
        }

        let writer = WavWriter::create(&path, spec)
            .map_err(AudioError::WavError)?;
        *self.writer.lock()
            .map_err(|e| AudioError::StreamError(format!("Mutex poisoned: {e}")))? = Some(writer);

        let writer_ref = Arc::clone(&self.writer);

        let stream = device
            .build_input_stream(
                &config,
                move |data: &[f32], _: &cpal::InputCallbackInfo| {
                    let mono = to_mono(data, native_channels);
                    let resampled = downsample(&mono, native_rate, target_rate);
                    if let Ok(mut guard) = writer_ref.lock() {
                        if let Some(ref mut w) = *guard {
                            for &sample in &resampled {
                                let amplitude = (sample * i16::MAX as f32) as i16;
                                let _ = w.write_sample(amplitude);
                            }
                        }
                    }
                },
                |err| eprintln!("Audio stream error: {err}"),
                None,
            )
            .map_err(|e| AudioError::StreamError(e.to_string()))?;

        stream
            .play()
            .map_err(|e| AudioError::StreamError(e.to_string()))?;

        self.stream = Some(stream);
        Ok(())
    }

    /// Stop recording and finalize the WAV file.
    fn stop(&mut self) -> PyResult<()> {
        self.stream = None;
        if let Ok(mut guard) = self.writer.lock() {
            if let Some(writer) = guard.take() {
                writer
                    .finalize()
                    .map_err(AudioError::WavError)?;
            }
        }
        Ok(())
    }
}

/// Streams audio chunks for real-time processing.
#[pyclass(unsendable)]
pub struct AudioStream {
    stream: Option<cpal::Stream>,
    consumer: Option<ringbuf::HeapCons<f32>>,
    sample_rate: u32,
}

#[pymethods]
impl AudioStream {
    #[new]
    #[pyo3(signature = (device_name=None, sample_rate=16000))]
    fn new(device_name: Option<String>, sample_rate: u32) -> PyResult<Self> {
        let device = match device_name {
            Some(name) => find_device_by_name(&name)?,
            None => cpal::default_host()
                .default_input_device()
                .ok_or(AudioError::DeviceNotFound("default".into()))?,
        };

        let (config, native_rate, native_channels) = get_device_config(&device)?;
        let target_rate = sample_rate;

        let rb = HeapRb::<f32>::new(RING_BUFFER_SIZE);
        let (mut producer, consumer) = rb.split();

        let stream = device
            .build_input_stream(
                &config,
                move |data: &[f32], _: &cpal::InputCallbackInfo| {
                    let mono = to_mono(data, native_channels);
                    let resampled = downsample(&mono, native_rate, target_rate);
                    for &sample in &resampled {
                        let _ = producer.try_push(sample);
                    }
                },
                |err| eprintln!("Audio stream error: {err}"),
                None,
            )
            .map_err(|e| AudioError::StreamError(e.to_string()))?;

        stream
            .play()
            .map_err(|e| AudioError::StreamError(e.to_string()))?;

        Ok(Self {
            stream: Some(stream),
            consumer: Some(consumer),
            sample_rate,
        })
    }

    /// Read available audio samples from the ring buffer.
    fn read_chunk(&mut self) -> PyResult<Vec<f32>> {
        if let Some(ref mut consumer) = self.consumer {
            let available = consumer.occupied_len();
            if available == 0 {
                return Ok(Vec::new());
            }
            let mut buf = vec![0.0f32; available];
            let popped = consumer.pop_slice(&mut buf);
            buf.truncate(popped);
            Ok(buf)
        } else {
            Ok(Vec::new())
        }
    }

    /// Get the configured sample rate.
    fn get_sample_rate(&self) -> u32 {
        self.sample_rate
    }

    /// Stop the audio stream.
    fn stop(&mut self) -> PyResult<()> {
        self.stream = None;
        self.consumer = None;
        Ok(())
    }
}
