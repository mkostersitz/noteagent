use serde::{Deserialize, Serialize};

/// A single segment of transcribed text with timing in seconds.
///
/// `speaker` is intentionally a free-form string; meeting mode tags segments
/// with "You" / "Remote" at the Python layer.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Segment {
    pub start: f64,
    pub end: f64,
    pub text: String,
    #[serde(default = "default_confidence")]
    pub confidence: f32,
    #[serde(default)]
    pub speaker: String,
}

fn default_confidence() -> f32 {
    1.0
}

impl Segment {
    pub fn new(start: f64, end: f64, text: impl Into<String>) -> Self {
        Self {
            start,
            end,
            text: text.into(),
            confidence: 1.0,
            speaker: String::new(),
        }
    }
}

/// A complete transcript composed of segments.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Transcript {
    #[serde(default)]
    pub segments: Vec<Segment>,
    #[serde(default = "default_language")]
    pub language: String,
    #[serde(default = "default_model")]
    pub model: String,
}

fn default_language() -> String {
    "en".to_string()
}

fn default_model() -> String {
    "base.en".to_string()
}

impl Default for Transcript {
    fn default() -> Self {
        Self {
            segments: Vec::new(),
            language: default_language(),
            model: default_model(),
        }
    }
}

impl Transcript {
    /// Concatenate all segment text with speaker labels (if any), space-joined.
    pub fn full_text(&self) -> String {
        let mut parts = Vec::with_capacity(self.segments.len());
        for seg in &self.segments {
            let trimmed = seg.text.trim();
            if seg.speaker.is_empty() {
                parts.push(trimmed.to_string());
            } else {
                parts.push(format!("[{}] {}", seg.speaker, trimmed));
            }
        }
        parts.join(" ")
    }

    /// Duration in seconds (end of the last segment, or 0.0 if empty).
    pub fn duration(&self) -> f64 {
        self.segments.last().map(|s| s.end).unwrap_or(0.0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_transcript_has_zero_duration_and_empty_text() {
        let t = Transcript::default();
        assert_eq!(t.duration(), 0.0);
        assert_eq!(t.full_text(), "");
    }

    #[test]
    fn full_text_joins_segments_with_spaces() {
        let t = Transcript {
            segments: vec![
                Segment::new(0.0, 1.0, "Hello"),
                Segment::new(1.0, 2.0, "world"),
            ],
            ..Default::default()
        };
        assert_eq!(t.full_text(), "Hello world");
    }

    #[test]
    fn full_text_trims_each_segment() {
        let t = Transcript {
            segments: vec![
                Segment::new(0.0, 1.0, "  Hello  "),
                Segment::new(1.0, 2.0, " world "),
            ],
            ..Default::default()
        };
        assert_eq!(t.full_text(), "Hello world");
    }

    #[test]
    fn full_text_prepends_speaker_label_when_set() {
        let mut s1 = Segment::new(0.0, 1.0, "Hi");
        s1.speaker = "You".to_string();
        let mut s2 = Segment::new(1.0, 2.0, "Hello");
        s2.speaker = "Remote".to_string();
        let t = Transcript {
            segments: vec![s1, s2],
            ..Default::default()
        };
        assert_eq!(t.full_text(), "[You] Hi [Remote] Hello");
    }

    #[test]
    fn duration_is_end_of_last_segment() {
        let t = Transcript {
            segments: vec![Segment::new(0.0, 1.0, "a"), Segment::new(1.0, 3.5, "b")],
            ..Default::default()
        };
        assert_eq!(t.duration(), 3.5);
    }

    #[test]
    fn segment_new_defaults_confidence_and_speaker() {
        let s = Segment::new(0.0, 1.0, "x");
        assert_eq!(s.confidence, 1.0);
        assert_eq!(s.speaker, "");
    }
}
