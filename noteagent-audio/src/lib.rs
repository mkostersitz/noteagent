use pyo3::prelude::*;

mod capture;
mod device;
mod error;

use capture::{AudioRecorder, AudioStream};
use device::list_audio_devices;

#[pymodule]
fn noteagent_audio(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(list_audio_devices, m)?)?;
    m.add_class::<AudioRecorder>()?;
    m.add_class::<AudioStream>()?;
    Ok(())
}

