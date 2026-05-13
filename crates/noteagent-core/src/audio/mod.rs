//! Audio capture and processing primitives.
//!
//! ## Cross-platform design
//!
//! Audio sources are abstracted behind the [`AudioSource`] trait. Two impls ship
//! with the crate:
//!
//! - [`CpalAudioSource`] — desktop (macOS / Linux / Windows). Behind feature
//!   flag `cpal-backend` (on by default).
//! - [`PushAudioSource`] — frames are pushed in from the embedding application.
//!   Used by iOS / iPadOS where capture happens via `AVAudioEngine` on the
//!   Swift side, then forwarded to Rust through the UniFFI bindings.
//!
//! Both impls produce a stream of mono `f32` PCM samples at the target sample
//! rate, ready to feed into the transcription pipeline.

pub mod dsp;
pub mod source;
pub mod writer;

#[cfg(feature = "cpal-backend")]
pub mod cpal_source;

#[cfg(feature = "cpal-backend")]
pub mod device;

pub use source::{AudioSource, PushAudioSource};
pub use writer::WavSink;

#[cfg(feature = "cpal-backend")]
pub use cpal_source::{CpalAudioSource, CpalRecorder};
#[cfg(feature = "cpal-backend")]
pub use device::{find_device_by_name, list_audio_devices};
