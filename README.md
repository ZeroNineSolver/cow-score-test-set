# cow-score-test-set

A public test set for CoW Protocol solver scoring.

Each test case gives one order, its fee policies, the native prices and one
solution, and states the protocol fees and the score that `cowprotocol/services`
computes for it at a pinned commit. Any solver, in any language, can run the
set against its own fee and score model.

Status: ten hand-built test cases, checked in CI.

## Layout

- `docs/` the `services` fee and score map at the pinned commit, and the conventions every test case follows
- `schema/` the JSON schema for a test case
- `vectors/` the test cases (CC0)
- `replayers/` reference replayers (MIT)
- `harness/` checks every test case's score against `winner-selection` (MIT)
- `audits/` public-data audits of what `services` did on chain (MIT)

## Pinned oracle

`cowprotocol/services` at `67cd3a16ad5b5cbfec16d8404ae038ee9e7019ed` (2026-09-23).

## What is checked today

Ten hand-built test cases, one class each (`vectors/`). Their expected values
come from `replayers/python/cowscore.py`, a transcription of the cited
`services` lines. CI (`.github/workflows/check.yml`) then checks, on every push:

- every test case against `schema/vector.schema.json`;
- that `replayers/python/build_hand_vectors.py` rebuilds `vectors/` byte for byte;
- `expected.score_stage.score_native` of every case against
  `winner_selection::arbitrator::score` itself, linked from `services` at the
  pinned commit (`harness/`).

What CI does not check against `services`: the fee stage (the driver's
per-policy fees and post-fee amounts) and the score stage's per-policy
breakdown, since every fee and surplus helper in `winner-selection` is private
(`protocol_fees`, `surplus_fee`, `volume_fee`, `calculate_custom_prices`);
`score` is its public entry point for the final score. Those values come from
the replayer.

Run locally. You need Python 3 (the schema check also needs `pip install
jsonschema`), a stable Rust toolchain (the harness uses edition 2024, so rustc
1.85 or newer; `harness/rust-toolchain.toml` selects stable for rustup), and
network access on the first build to fetch `services` at the pinned commit.

```
python3 replayers/python/build_hand_vectors.py vectors
cargo build --release --locked --manifest-path harness/Cargo.toml
harness/target/release/check-vectors vectors
```
