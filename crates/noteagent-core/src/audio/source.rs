//! Platform-agnostic audio source abstraction.
//!
//! The [`AudioSource`] trait represents anything that produces a stream of
//! mono `f32` PCM samples at a known sample rate. The transcription pipeline
//! consumes this trait and is therefore agnostic to whether samples come from
//! `cpal` (desktop) or `AVAudioEngine` via Swift (iOS).

use std::sync::{Arc, Mutex};

use ringbuf::traits::{Consumer, Observer, Producer, Split};
use ringbuf::{HeapCons, HeapProd, HeapRb};

use crate::error::CoreError;

/// Ring buffer capacity (~30 s at 48 kHz).
pub const RING_BUFFER_SIZE: usize = 48_000 * 30;

/// A producer of mono PCM samples.
///
/// Note: implementations are **not** required to be `Send`. The desktop
/// `CpalAudioSource` holds a `cpal::Stream` which is `!Send` on macOS. Workers
/// that need to drain an audio source from another thread should pull
/// `HeapCons<f32>` (or equivalent) out of the source at construction time —
/// the consumer side of the ring buffer **is** `Send`.
pub trait AudioSource {
    /// Pull whatever samples are currently buffered. Returns an empty vec
    /// when no samples are available; never blocks.
    fn read_chunk(&mut self) -> Result<Vec<f32>, CoreError>;

    /// Target sample rate of the produced stream (Hz).
    fn sample_rate(&self) -> u32;

    /// Stop the underlying capture and release resources.
    fn stop(&mut self) -> Result<(), CoreError>;
}

/// An [`AudioSource`] driven by externally-pushed PCM frames.
///
/// Used by the iOS / iPadOS Swift layer: `AVAudioEngine`'s tap pushes mono
/// `f32` samples via [`PushAudioSource::push`] (or its handle, [`PushHandle`]),
/// and the transcription pipeline drains them via [`AudioSource::read_chunk`].
pub struct PushAudioSource {
    sample_rate: u32,
    producer: Arc<Mutex<HeapProd<f32>>>,
    consumer: Option<HeapCons<f32>>,
}

impl PushAudioSource {
    pub fn new(sample_rate: u32) -> Self {
        let rb = HeapRb::<f32>::new(RING_BUFFER_SIZE);
        let (producer, consumer) = rb.split();
        Self {
            sample_rate,
            producer: Arc::new(Mutex::new(producer)),
            consumer: Some(consumer),
        }
    }

    /// Returns a clone of the producer handle so the embedding application
    /// (e.g. Swift) can push samples from its audio callback thread.
    pub fn handle(&self) -> PushHandle {
        PushHandle {
            producer: Arc::clone(&self.producer),
        }
    }

    /// Push samples directly (mainly useful for tests).
    pub fn push(&self, samples: &[f32]) {
        if let Ok(mut prod) = self.producer.lock() {
            for &s in samples {
                let _ = prod.try_push(s);
            }
        }
    }
}

impl AudioSource for PushAudioSource {
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
        self.consumer = None;
        Ok(())
    }
}

/// Cheap-to-clone handle that pushes samples into a [`PushAudioSource`] from
/// any thread.
#[derive(Clone)]
pub struct PushHandle {
    producer: Arc<Mutex<HeapProd<f32>>>,
}

impl PushHandle {
    pub fn push(&self, samples: &[f32]) {
        if let Ok(mut prod) = self.producer.lock() {
            for &s in samples {
                let _ = prod.try_push(s);
            }
        }
    }
}
