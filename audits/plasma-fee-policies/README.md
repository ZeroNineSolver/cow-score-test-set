# Protocol fee policies on settled Plasma trades

Which fee policies did the autopilot attach to orders that settled on Plasma,
and with which factors? Answered from public data only: the solver-competition
record (`GET /api/v2/solver_competition/{auction}`) for the winning solution
and its settlement transaction, and `GET /api/v1/trades?orderUid=` for the
trade in that transaction. The trade record's `executedProtocolFees` lists
every policy attached to the order, with `factor`, `maxVolumeFactor` and the
quote where the policy has one, and the amount charged under it.

- `auctions.txt` the 59 auction ids; the trades settled in Plasma blocks 30721153 to 30964066
- `audit.py` the script (Python 3, standard library only)
- `trades.jsonl` its output: one line per settled trade, the API's own record
  plus the auction id

## Result

59 auctions. Two, 8741186 and 8759045, have no settlement transaction on
record; their orders settled in the next auction on the list (8741189 and
8759048), which counts them. That leaves 57 settled trades.

| policy | factor | maxVolumeFactor | trades |
|---|---|---|---|
| priceImprovement | 0.5 | 0.0098 | 52 |
| volume | 0.0002 | | 50 |
| surplus | 0.5 | 0.0098 | 5 |
| volume | 0.007 | | 3 |
| volume | 0.00003 | | 3 |
| priceImprovement | 0.99 | 0.01 | 1 |

Every one of the 57 trades carries a surplus or price-improvement policy at
factor 0.5 with `maxVolumeFactor` 0.0098. 50 of the 57 also carry a volume
policy at factor 0.0002. One trade (auction 8759048) carries two
price-improvement policies.

## Reproduce

```
python3 audit.py
```

The API serves these records today; the output is committed in case it stops.
