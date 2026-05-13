//! Desktop audio device enumeration (cpal-backed).

use cpal::traits::{DeviceTrait, HostTrait};

use crate::error::CoreError;

/// List all available audio input devices by name.
pub fn list_audio_devices() -> Result<Vec<String>, CoreError> {
    let host = cpal::default_host();
    let devices = host
        .input_devices()
        .map_err(|e| CoreError::EnumerationError(e.to_string()))?;

    let names: Vec<String> = devices.filter_map(|d| d.name().ok()).collect();
    Ok(names)
}

/// Find an input device by name (case-insensitive substring match).
pub fn find_device_by_name(name: &str) -> Result<cpal::Device, CoreError> {
    let host = cpal::default_host();
    let devices = host
        .input_devices()
        .map_err(|e| CoreError::EnumerationError(e.to_string()))?;

    for device in devices {
        if let Ok(dev_name) = device.name() {
            if dev_name.to_lowercase().contains(&name.to_lowercase()) {
                return Ok(device);
            }
        }
    }

    Err(CoreError::DeviceNotFound(name.to_string()))
}
