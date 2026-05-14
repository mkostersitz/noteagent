fn main() {
    uniffi::generate_scaffolding("src/noteagent.udl").expect("UniFFI scaffolding generation failed");
}
