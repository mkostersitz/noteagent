//! Shared data types serialized across the Python, Swift, and direct-Rust
//! consumers of `noteagent-core`. Mirrors the pydantic models in
//! `src/noteagent/models.py`.

mod transcript;

pub use transcript::{Segment, Transcript};
