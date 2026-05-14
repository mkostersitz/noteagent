//! Pure DSP helpers used by both desktop and push-based audio sources.

/// Downsample by simple decimation. The caller is responsible for any
/// anti-aliasing required upstream.
pub fn downsample(input: &[f32], from_rate: u32, to_rate: u32) -> Vec<f32> {
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
pub fn to_mono(input: &[f32], channels: u16) -> Vec<f32> {
    if channels == 1 {
        return input.to_vec();
    }
    let ch = channels as usize;
    input
        .chunks_exact(ch)
        .map(|frame| frame.iter().sum::<f32>() / channels as f32)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn downsample_is_identity_when_rates_match() {
        let input = vec![0.1, 0.2, 0.3, 0.4];
        assert_eq!(downsample(&input, 16_000, 16_000), input);
    }

    #[test]
    fn downsample_halves_length_when_rate_halves() {
        let input: Vec<f32> = (0..100).map(|i| i as f32).collect();
        let out = downsample(&input, 32_000, 16_000);
        // Decimation picks every 2nd sample; allow ±1 for the ceil() pad.
        assert!((out.len() as i32 - 50).abs() <= 1, "got {} samples", out.len());
        assert_eq!(out[0], 0.0);
        assert_eq!(out[1], 2.0);
    }

    #[test]
    fn to_mono_passthrough_for_mono_input() {
        let input = vec![0.1, 0.2, 0.3];
        assert_eq!(to_mono(&input, 1), input);
    }

    #[test]
    fn to_mono_averages_stereo_frames() {
        let stereo = vec![1.0, -1.0, 0.5, -0.5, 0.0, 0.0];
        let mono = to_mono(&stereo, 2);
        assert_eq!(mono, vec![0.0, 0.0, 0.0]);
    }

    #[test]
    fn to_mono_averages_4ch_frames() {
        let quad = vec![1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0];
        assert_eq!(to_mono(&quad, 4), vec![1.0, 0.0]);
    }
}
