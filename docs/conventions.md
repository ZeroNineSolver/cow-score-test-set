# Conventions

Every test case follows these rules. They are written out so that a mismatch
is never a units problem.

## Amounts

- Every amount is a decimal string of an integer number of wei (atoms) of the
  named token. No floats, no scientific notation.
- A native price is the autopilot's normalized price: wei of the native token
  per 1e18 atoms of the token. The wrapped native token is forced to 1e18.
- `score_native` is in wei of the native token.

## Sides

- A sell order fixes `sell_amount` and treats `buy_amount` as the limit
  (minimum to receive). `executed` is a sell amount.
- A buy order fixes `buy_amount` and treats `sell_amount` as the limit
  (maximum to pay). `executed` is a buy amount.

## Surplus token

- The surplus token is the buy token for a sell order and the sell token for a
  buy order. Protocol fees are computed in the surplus token, then converted to
  the sell token for the trade.

## Fee policies

- `order.fee_policies` is the list the autopilot attached, in its order. The
  driver applies the policies forward, in that order, on the pre-fee amounts.
- Scoring recovers the fees from post-fee prices, last policy first, with the
  adjusted factor. The two directions are inverses by design. A test case
  records both.
- `cip` names the CIP a policy kind comes from.

## Two stages

- `expected.fee_stage` is what the driver produces from the solution.
- `expected.score_stage` is what `winner-selection` produces from the executed
  amounts.
- Where a copy of the arithmetic gives a different result at a boundary, the
  case states each result in `expected.notes` and cites the lines.

## Provenance

- `oracle.commit` is the `services` commit that produced the expected values.
- `oracle.generated_by` is `hand` (built and cited by a person) or `harness`.
- `oracle.citations` lists path:line ranges in `services`.
