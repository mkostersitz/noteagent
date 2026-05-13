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
