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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn preset_from_str_handles_known_values() {
        assert_eq!(QualityPreset::from_str_ci("fast"), QualityPreset::Fast);
        assert_eq!(QualityPreset::from_str_ci("FAST"), QualityPreset::Fast);
        assert_eq!(QualityPreset::from_str_ci("balanced"), QualityPreset::Balanced);
        assert_eq!(QualityPreset::from_str_ci("accurate"), QualityPreset::Accurate);
        assert_eq!(QualityPreset::from_str_ci("Accurate"), QualityPreset::Accurate);
    }

    #[test]
    fn preset_from_str_defaults_to_balanced_for_unknown() {
        assert_eq!(QualityPreset::from_str_ci(""), QualityPreset::Balanced);
        assert_eq!(QualityPreset::from_str_ci("garbage"), QualityPreset::Balanced);
    }

    #[test]
    fn fast_preset_uses_greedy_search() {
        let opts = TranscribeOptions::from_preset(QualityPreset::Fast, Some("en"));
        assert_eq!(opts.beam_size, 1);
        assert_eq!(opts.best_of, 1);
        assert!(!opts.condition_on_previous_text);
        assert_eq!(opts.language.as_deref(), Some("en"));
    }

    #[test]
    fn balanced_preset_uses_beam_5() {
        let opts = TranscribeOptions::from_preset(QualityPreset::Balanced, None);
        assert_eq!(opts.beam_size, 5);
        assert_eq!(opts.best_of, 5);
        assert!(opts.condition_on_previous_text);
        assert!(opts.language.is_none());
    }

    #[test]
    fn accurate_preset_uses_beam_8() {
        let opts = TranscribeOptions::from_preset(QualityPreset::Accurate, Some("de"));
        assert_eq!(opts.beam_size, 8);
        assert_eq!(opts.best_of, 8);
        assert!(opts.condition_on_previous_text);
        assert_eq!(opts.language.as_deref(), Some("de"));
    }
}
