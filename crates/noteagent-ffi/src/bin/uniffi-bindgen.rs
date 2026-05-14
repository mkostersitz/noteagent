//! Binding-generation CLI. Build with `--features cli` and invoke:
//!
//! ```bash
//! cargo run -p noteagent-ffi --features cli --bin uniffi-bindgen -- \
//!     generate src/noteagent.udl --language swift --out-dir ./generated/swift
//! ```

fn main() {
    uniffi::uniffi_bindgen_main()
}
