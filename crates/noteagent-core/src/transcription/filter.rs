//! Filter known whisper hallucinations produced on silence.
//!
//! Ported verbatim from `src/noteagent/transcript.py::_is_hallucination`,
//! extended to catch whisper.cpp's bracket-style non-speech tags.

const HALLUCINATIONS: &[&str] = &[
    "thank you",
    "thanks for watching",
    "goodbye",
    "bye",
    "thank you for watching",
    "please subscribe",
    "the end",
    "thanks",
    "thank you so much",
    "subtitles by",
    "subtitle",
    "subtitles",
];

/// Returns true if `text` is empty, whitespace, matches one of the known
/// whisper hallucination phrases (after stripping trailing punctuation), or
/// is one of whisper.cpp's non-speech bracket tags (e.g. `[BLANK_AUDIO]`,
/// `[Music]`, `(silence)`).
pub fn is_hallucination(text: &str) -> bool {
    let stripped = text
        .trim()
        .trim_end_matches(|c: char| matches!(c, '.' | '!' | ','))
        .trim()
        .to_lowercase();

    if stripped.is_empty() {
        return true;
    }

    // whisper.cpp wraps non-speech events in brackets or parentheses, e.g.
    // "[BLANK_AUDIO]", "[ Music ]", "(silence)". If the entire segment is
    // such a tag, treat it as a hallucination.
    if is_bracket_tag(&stripped) {
        return true;
    }

    HALLUCINATIONS.iter().any(|h| *h == stripped)
}

fn is_bracket_tag(text: &str) -> bool {
    let bytes = text.as_bytes();
    if bytes.len() < 2 {
        return false;
    }
    let first = bytes[0];
    let last = bytes[bytes.len() - 1];
    matches!(
        (first, last),
        (b'[', b']') | (b'(', b')') | (b'<', b'>') | (b'{', b'}')
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_is_hallucination() {
        assert!(is_hallucination(""));
        assert!(is_hallucination("   "));
    }

    #[test]
    fn known_phrases_are_hallucinations() {
        assert!(is_hallucination("Thank you."));
        assert!(is_hallucination("thanks for watching!"));
        assert!(is_hallucination(" Subtitles "));
    }

    #[test]
    fn real_text_is_not_hallucination() {
        assert!(!is_hallucination("Today we discussed the roadmap."));
        assert!(!is_hallucination("Thanks for the update on the deploy."));
    }

    #[test]
    fn whisper_cpp_bracket_tags_are_hallucinations() {
        assert!(is_hallucination("[BLANK_AUDIO]"));
        assert!(is_hallucination(" [ Music ] "));
        assert!(is_hallucination("(silence)"));
        assert!(is_hallucination("<inaudible>"));
    }
}
