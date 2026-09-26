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
