# cow-score-test-set

A public test set for CoW Protocol solver scoring.

Each test case gives one order, its fee policies, the native prices and one
solution, and states the protocol fees and the score that `cowprotocol/services`
computes for it at a pinned commit. Any solver, in any language, can run the
set against its own fee and score model.

Status: bootstrap. Nothing here is released yet.

## Layout

- `docs/` the `services` fee and score map at the pinned commit, and the schema notes
- `schema/` the JSON schema for a test case
- `vectors/` the test cases (CC0)
- `replayers/` reference replayers (MIT)
- `harness/` the generator that drives `services` (licence follows `winner-selection`)

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

What is not yet checked against `services`: the fee stage (the driver's
per-policy fees and post-fee amounts) and the score stage's per-policy
breakdown, since `score` is the only public entry point of `winner-selection`.
Those values are the replayer's. Driving the driver itself to check them is
the generator's job.

Run locally:

```
python3 replayers/python/build_hand_vectors.py vectors
cargo build --release --locked --manifest-path harness/Cargo.toml
harness/target/release/check-vectors vectors
```
