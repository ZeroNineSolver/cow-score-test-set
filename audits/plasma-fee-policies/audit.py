"""Which protocol fee policies did the autopilot attach to settled Plasma trades?

For each auction id in auctions.txt: read the winning solution from the
public solver-competition record, then read each of its orders' trades from
`GET /api/v1/trades?orderUid=`, keeping the trade from that settlement's
transaction. The trade record carries `executedProtocolFees`: every policy the
autopilot attached to the order (kind, factor, maxVolumeFactor, quote) and the
amount charged under it.

Public API only; standard library only. Writes trades.jsonl (one line per
settled trade, the API's own record plus the auction id) and prints a summary.

Usage: python3 audit.py [auctions.txt] [trades.jsonl]
"""

import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

API = "https://api.cow.fi/plasma/api"


def get(url: str):
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code != 429 or attempt == 3:
                raise
        time.sleep(2 * (attempt + 1))


def settled_trades(auction_id: str) -> list[dict]:
    comp = get(f"{API}/v2/solver_competition/{auction_id}")
    if comp is None:
        raise SystemExit(f"auction {auction_id}: no competition record")
    winner = next(s for s in comp["solutions"] if s.get("isWinner"))
    # Some records leave the winner's txHash empty; the auction's own list
    # of settlement transactions then names it.
    tx = (winner.get("txHash") or (comp.get("transactionHashes") or [""])[0]).lower()
    if not tx:
        # No settlement on record for this auction. Its orders may have
        # settled in a later auction; that auction counts them, not this one.
        return []
    out = []
    for order in winner["orders"]:
        trades = get(f"{API}/v1/trades?orderUid={order['id']}") or []
        mine = [t for t in trades if tx and (t.get("txHash") or "").lower() == tx]
        if len(mine) != 1:
            raise SystemExit(f"auction {auction_id}: {len(mine)} trades in tx {tx} for {order['id']}")
        out.append({"auction_id": auction_id, **mine[0]})
        time.sleep(0.2)
    return out


def shape(policy: dict) -> tuple:
    (kind, body), = policy.items()
    return kind, body.get("factor"), body.get("maxVolumeFactor")


def main():
    ids_path = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).with_name("auctions.txt"))
    out_path = Path(sys.argv[2] if len(sys.argv) > 2 else Path(__file__).with_name("trades.jsonl"))
    ids = [line.strip() for line in ids_path.read_text().splitlines() if line.strip()]

    trades, unsettled = [], []
    for auction_id in ids:
        found = settled_trades(auction_id)
        trades += found
        if not found:
            unsettled.append(auction_id)
    # One trade is one (transaction, order) pair.
    assert len({(t["txHash"], t["orderUid"]) for t in trades}) == len(trades), "duplicate trade"
    out_path.write_text("".join(json.dumps(t, sort_keys=True) + "\n" for t in trades))

    n = len(trades)
    surplus_family = [t for t in trades
                      if any(shape(f["policy"])[0] in ("surplus", "priceImprovement")
                             for f in t["executedProtocolFees"])]
    print(f"{len(ids)} auctions, {n} settled trades; "
          f"no settlement on record: {', '.join(unsettled) or 'none'}")
    print(f"trades with a surplus or price-improvement policy: {len(surplus_family)} of {n}")
    counts = Counter(shape(f["policy"]) for t in trades for f in t["executedProtocolFees"])
    print("policy shapes (kind, factor, maxVolumeFactor): trades carrying it")
    for (kind, factor, mvf), c in counts.most_common():
        print(f"  {kind:17} {factor!s:8} {mvf!s:8} {c}")


if __name__ == "__main__":
    main()
