//! `cpal`-backed implementations of [`AudioSource`] and a file recorder.
//!
//! Only compiled when the `cpal-backend` feature is enabled (default on
//! macOS / Linux / Windows; off on iOS / iPadOS).

use std::path::Path;
use std::sync::{Arc, Mutex};

use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::StreamConfig;
use ringbuf::traits::{Consumer, Observer, Producer, Split};
use ringbuf::{HeapCons, HeapRb};

use crate::audio::device::find_device_by_name;
use crate::audio::dsp::{downsample, to_mono};
use crate::audio::source::{AudioSource, RING_BUFFER_SIZE};
use crate::audio::writer::WavSink;
use crate::error::CoreError;

fn get_device_config(device: &cpal::Device) -> Result<(StreamConfig, u32, u16), CoreError> {
    let supported = device
        .default_input_config()
        .map_err(|e| CoreError::StreamError(format!("No supported input config: {e}")))?;

    let native_rate = supported.sample_rate().0;
    let native_channels = supported.channels();

    let config = StreamConfig {
        channels: native_channels,
        sample_rate: cpal::SampleRate(native_rate),
        buffer_size: cpal::BufferSize::Default,
    };

    Ok((config, native_rate, native_channels))
}

fn resolve_device(device_name: Option<&str>) -> Result<cpal::Device, CoreError> {
    match device_name {
        Some(name) => find_device_by_name(name),
        None => cpal::default_host()
            .default_input_device()
            .ok_or_else(|| CoreError::DeviceNotFound("default".into())),
    }
}

/// A `cpal`-backed [`AudioSource`] that streams mono `f32` samples into a
/// ring buffer for the caller to drain.
pub struct CpalAudioSource {
    stream: Option<cpal::Stream>,
    consumer: Option<HeapCons<f32>>,
    sample_rate: u32,
}

impl CpalAudioSource {
    pub fn new(device_name: Option<&str>, sample_rate: u32) -> Result<Self, CoreError> {
        let device = resolve_device(device_name)?;
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
            .map_err(|e| CoreError::StreamError(e.to_string()))?;

        stream
            .play()
            .map_err(|e| CoreError::StreamError(e.to_string()))?;

        Ok(Self {
            stream: Some(stream),
            consumer: Some(consumer),
            sample_rate,
        })
    }
}

impl AudioSource for CpalAudioSource {
    fn read_chunk(&mut self) -> Result<Vec<f32>, CoreError> {
        let Some(ref mut consumer) = self.consumer else {
            return Ok(Vec::new());
        };
        let available = consumer.occupied_len();
        if available == 0 {
            return Ok(Vec::new());
        }
        let mut buf = vec![0.0f32; available];
        let popped = consumer.pop_slice(&mut buf);
        buf.truncate(popped);
        Ok(buf)
    }

    fn sample_rate(&self) -> u32 {
        self.sample_rate
    }

    fn stop(&mut self) -> Result<(), CoreError> {
        self.stream = None;
        self.consumer = None;
        Ok(())
    }
}

/// A `cpal`-backed recorder that captures audio directly to a WAV file.
pub struct CpalRecorder {
    sink: Arc<Mutex<Option<WavSink>>>,
    stream: Option<cpal::Stream>,
    sample_rate: u32,
}

impl CpalRecorder {
    pub fn new(sample_rate: u32) -> Self {
        Self {
            sink: Arc::new(Mutex::new(None)),
            stream: None,
            sample_rate,
        }
    }

    /// Start recording to `output_path` from the given device (or the system
    /// default if `None`).
    pub fn start(&mut self, output_path: &Path, device_name: Option<&str>) -> Result<(), CoreError> {
        let device = resolve_device(device_name)?;
        let (config, native_rate, native_channels) = get_device_config(&device)?;
        let target_rate = self.sample_rate;

        let sink = WavSink::create(output_path, target_rate)?;
        *self
            .sink
            .lock()
            .map_err(|e| CoreError::StreamError(format!("Mutex poisoned: {e}")))? = Some(sink);

        let sink_ref = Arc::clone(&self.sink);

        let stream = device
            .build_input_stream(
                &config,
                move |data: &[f32], _: &cpal::InputCallbackInfo| {
                    let mono = to_mono(data, native_channels);
                    let resampled = downsample(&mono, native_rate, target_rate);
                    if let Ok(mut guard) = sink_ref.lock() {
                        if let Some(ref mut s) = *guard {
                            let _ = s.write_samples(&resampled);
                        }
                    }
                },
                |err| eprintln!("Audio stream error: {err}"),
                None,
            )
            .map_err(|e| CoreError::StreamError(e.to_string()))?;

        stream
            .play()
            .map_err(|e| CoreError::StreamError(e.to_string()))?;

        self.stream = Some(stream);
        Ok(())
    }

    /// Stop recording and finalize the WAV file.
    pub fn stop(&mut self) -> Result<(), CoreError> {
        self.stream = None;
        if let Ok(mut guard) = self.sink.lock() {
            if let Some(mut sink) = guard.take() {
                sink.finalize()?;
            }
        }
        Ok(())
    }

    pub fn sample_rate(&self) -> u32 {
        self.sample_rate
    }
}
