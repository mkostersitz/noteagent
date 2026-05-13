//! Quality presets mirroring the previous Python implementation.
//!
//! Note: whisper.cpp's `FullParams` exposes a slightly different surface than
//! openai-whisper's Python API. We map our presets onto the closest
//! equivalents (greedy vs beam search, beam size).

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum QualityPreset {
    Fast,
    Balanced,
    Accurate,
}

impl Default for QualityPreset {
    fn default() -> Self {
        Self::Balanced
    }
}

impl QualityPreset {
    pub fn from_str_ci(s: &str) -> Self {
        match s.to_ascii_lowercase().as_str() {
            "fast" => Self::Fast,
            "accurate" => Self::Accurate,
            _ => Self::Balanced,
        }
    }
}

/// Resolved transcription options derived from a [`QualityPreset`].
///
/// The chunker / batch path translate these into whisper.cpp `FullParams`.
#[derive(Debug, Clone)]
pub struct TranscribeOptions {
    pub beam_size: i32,
    pub best_of: i32,
    /// Initial sampling temperature. whisper.cpp falls back to higher
    /// temperatures internally when needed.
    pub temperature: f32,
    /// Whether to condition each window on the previously decoded text.
    pub condition_on_previous_text: bool,
    /// Optional language hint, e.g. "en". `None` lets whisper auto-detect.
    pub language: Option<String>,
}

impl TranscribeOptions {
    pub fn from_preset(preset: QualityPreset, language: Option<&str>) -> Self {
        let language = language.map(|s| s.to_string());
        match preset {
            QualityPreset::Fast => Self {
                beam_size: 1,
                best_of: 1,
                temperature: 0.0,
                condition_on_previous_text: false,
                language,
            },
            QualityPreset::Balanced => Self {
                beam_size: 5,
                best_of: 5,
                temperature: 0.0,
                condition_on_previous_text: true,
                language,
            },
            QualityPreset::Accurate => Self {
                beam_size: 8,
                best_of: 8,
                temperature: 0.0,
                condition_on_previous_text: true,
                language,
            },
        }
    }
}
