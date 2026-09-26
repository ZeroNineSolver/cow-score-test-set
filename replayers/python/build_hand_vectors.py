"""Build the ten hand vectors in vectors/.

Inputs are chosen by hand to cover one class each. Expected values come from
`cowscore.py`, a transcription of the cited `services` lines, and every
`score_native` is then checked against winner-selection itself by the CI
harness (harness/). Re-running this script must reproduce vectors/ byte for
byte; CI checks that too.

Usage: python3 replayers/python/build_hand_vectors.py [vectors dir]
"""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import cowscore  # noqa: E402

COMMIT = "67cd3a16ad5b5cbfec16d8404ae038ee9e7019ed"
A = "0xa0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0"  # sell token in every case
B = "0xb0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0"  # buy token in every case
OWNER = "c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0c0"
E18 = 10**18

# Uneven on purpose, so floor and ceiling give different answers.
PS, PB = 1_999_870_013, 1_000_000_123  # uniform clearing prices of A and B
NATIVE = {A: str(1_000_417 * 10**9), B: str(500_000_061 * 10**6)}  # wei per 1e18 atoms

CITE_FEE = [
    "crates/driver/src/domain/competition/solution/fee.rs:42-81",
    "crates/driver/src/domain/competition/solution/fee.rs:84-213",
    "crates/driver/src/domain/competition/solution/trade.rs:129-166",
    "crates/driver/src/domain/competition/solution/trade.rs:197-281",
    "crates/driver/src/domain/competition/solution/trade.rs:287-355",
    "crates/driver/src/domain/competition/solution/settlement.rs:290-305",
]
CITE_SCORE = [
    "crates/winner-selection/src/arbitrator.rs:313-362",
    "crates/winner-selection/src/arbitrator.rs:367-426",
    "crates/winner-selection/src/arbitrator.rs:444-473",
    "crates/winner-selection/src/arbitrator.rs:539-632",
    "crates/chain-types/src/lib.rs:43-47",
    "crates/number/src/u256_ext.rs:105-135",
]
CITE_QUOTE = [
    "crates/driver/src/domain/competition/solution/fee.rs:249-291",
    "crates/winner-selection/src/arbitrator.rs:478-534",
]


def surplus(f, mvf):
    return {"kind": "surplus", "cip": "CIP-38", "factor": f, "max_volume_factor": mvf}


def price_improvement(f, mvf):
    return {"kind": "price_improvement", "cip": "CIP-38", "factor": f, "max_volume_factor": mvf}


def volume(f):
    return {"kind": "volume", "cip": "CIP-38", "factor": f}


def uid(case_id):
    digest = hashlib.sha256(case_id.encode()).hexdigest()
    return "0x" + digest + OWNER + "ffffffff"


# (id, classes, side, sell_amount, buy_amount, partial/available, policies, quote,
#  executed, solver_fee, notes)
CASES = [
    ("sell-surplus-full-0001", ["sell", "full-fill", "policy-surplus"],
     "sell", 10 * E18, 19_900 * 10**15, None, [surplus(0.5, 0.01)], None,
     10 * E18 - 3 * 10**15, 3 * 10**15,
     "Factor 0.5 makes the score stage's adjusted factor f/(1-f) exactly 1.0, "
     "which takes the identity branch of checked_mul_f64 (u256_ext.rs:111-114)."),
    ("buy-surplus-full-0002", ["buy", "full-fill", "policy-surplus"],
     "buy", 2_560 * 10**15, 5 * E18, None, [surplus(0.2, 0.01)], None,
     5 * E18, 2 * 10**15, ""),
    ("sell-volume-0003", ["sell", "full-fill", "policy-volume"],
     "sell", 7 * E18, 13 * E18, None, [volume(0.0002)], None,
     7 * E18 - 10**15, 10**15, ""),
    ("buy-volume-0004", ["buy", "full-fill", "policy-volume"],
     "buy", 2_100 * 10**15, 4 * E18, None, [volume(0.0002)], None,
     4 * E18, 10**15,
     "The score stage recovers a buy-side volume fee with f/(1+f), not f/(1-f) "
     "(arbitrator.rs:565-568)."),
    ("sell-price-improvement-0005", ["sell", "in-market", "full-fill", "policy-price-improvement"],
     "sell", 10 * E18, 18 * E18, None, [price_improvement(0.5, 0.01)],
     {"sell_amount": str(10 * E18), "buy_amount": str(19_950 * 10**15), "fee": str(2 * 10**15)},
     10 * E18 - 2 * 10**15, 2 * 10**15,
     "The quote, net of its fee, sets the reference limit above the signed limit "
     "(fee.rs:249-270)."),
    ("buy-price-improvement-0006", ["buy", "in-market", "full-fill", "policy-price-improvement"],
     "buy", 2_560 * 10**15, 5 * E18, None, [price_improvement(0.5, 0.01)],
     {"sell_amount": str(2_505 * 10**15), "buy_amount": str(5 * E18), "fee": str(3 * 10**15)},
     5 * E18, 3 * 10**15, ""),
    ("sell-surplus-partial-0007", ["sell", "partial-fill", "policy-surplus"],
     "sell", 20 * E18, 39_700 * 10**15, 20 * E18, [surplus(0.5, 0.01)], None,
     6 * E18 - 10**15, 10**15,
     "Partially fillable: the driver accepts any executed plus fee up to "
     "`available` (trade.rs:152-155)."),
    ("sell-two-policies-0008", ["sell", "in-market", "full-fill", "policy-price-improvement", "policy-volume"],
     "sell", 10 * E18, 18 * E18, None, [price_improvement(0.5, 0.01), volume(0.00025)],
     {"sell_amount": str(10 * E18), "buy_amount": str(19_950 * 10**15), "fee": str(2 * 10**15)},
     10 * E18 - 2 * 10**15, 2 * 10**15,
     "Two policies. The driver applies them first to last (fee.rs:44); the "
     "score stage recovers them last to first (arbitrator.rs:382)."),
    ("sell-surplus-capped-0009", ["sell", "full-fill", "policy-surplus", "cap-max-volume-factor"],
     "sell", 10 * E18, 12 * E18, None, [surplus(0.5, 0.01)], None,
     10 * E18 - 10**15, 10**15,
     "Large surplus: the surplus fee exceeds the volume cap, so min() takes the "
     "volume leg (fee.rs:150, arbitrator.rs:412)."),
    ("sell-zero-score-0010", ["sell", "full-fill", "policy-surplus", "zero-score"],
     "sell", 10 * E18, None, None, [surplus(0.5, 0.01)], None,
     10 * E18 - 10**15, 10**15,
     "The signed limit equals the executed price, so surplus, fee and score are 0."),
]


def build(case):
    (cid, classes, side, sell, buy, available, policies, quote, executed, solver_fee, notes) = case
    if buy is None:  # zero-score: set the limit to exactly what the trade buys
        buy = cowscore.checked_ceil_div(executed * PS, PB)
    order = {
        "uid": uid(cid), "side": side, "sell_token": A, "buy_token": B,
        "sell_amount": str(sell), "buy_amount": str(buy),
        "partially_fillable": available is not None,
    }
    if available is not None:
        order["available"] = str(available)
    if quote:
        order["quote"] = quote
    order["fee_policies"] = policies
    v = {
        "id": cid, "version": "0.1.0",
        "oracle": {"repo": "cowprotocol/services", "commit": COMMIT, "generated_by": "hand",
                   "citations": CITE_FEE + CITE_SCORE + (CITE_QUOTE if quote else [])},
        "class": classes, "order": order, "native_prices": NATIVE,
        "solution": {"executed": str(executed), "solver_fee": str(solver_fee),
                     "uniform_clearing_prices": {A: str(PS), B: str(PB)}},
        "expected": {},
    }
    v["expected"]["fee_stage"] = cowscore.fee_stage(v)
    v["expected"]["score_stage"] = cowscore.score_stage(v)
    capped = [leg == "volume" for leg in winning_legs(v)]
    assert any(capped) == ("cap-max-volume-factor" in classes), (cid, winning_legs(v))
    fwd = [x["in_surplus_token"] for x in v["expected"]["fee_stage"]["protocol_fees"]]
    if fwd != v["expected"]["score_stage"]["protocol_fees_recovered"]:
        classes.append("roundtrip-rounding")
        diffs = ", ".join(f"policy {i}: {a} forward, {b} recovered" for i, (a, b) in
                          enumerate(zip(fwd, v["expected"]["score_stage"]["protocol_fees_recovered"])) if a != b)
        notes = (notes + " " if notes else "") + (
            "The score stage's recovered fee differs from the driver's applied fee by "
            f"rounding ({diffs}; surplus-token wei). Recovery works on post-fee amounts "
            "with f/(1-f) or f/(1+f) (arbitrator.rs:539-573).")
    if notes:
        v["expected"]["notes"] = notes
    return v


def winning_legs(v):
    """For each surplus or price-improvement policy in the driver's fold,
    'surplus' if the surplus fee is below the volume cap, 'volume' if the cap
    binds (fee.rs:139-161). Volume policies report 'volume-policy'."""
    o, sol = v["order"], v["solution"]
    ps, pb = PS, PB
    f = cowscore._Fulfillment(o, int(sol["executed"]), int(sol["solver_fee"]))
    legs = []
    for pol, fee in zip(o["fee_policies"], v["expected"]["fee_stage"]["protocol_fees"]):
        if pol["kind"] == "volume":
            legs.append("volume-policy")
        else:
            ls, lb = ((int(o["sell_amount"]), int(o["buy_amount"])) if pol["kind"] == "surplus"
                      else cowscore._adjust_quote_driver(o, o["quote"]))
            s = cowscore.checked_mul_f64(f.surplus_over_reference_price(ls, lb, ps, pb), pol["factor"])
            vol = f.sell_amount(ps, pb) if o["side"] == "buy" else f.buy_amount(ps, pb)
            legs.append("volume" if cowscore.checked_mul_f64(vol, pol["max_volume_factor"]) < s else "surplus")
        ins = int(fee["in_sell_token"])
        f = cowscore._Fulfillment(o, f.executed if o["side"] == "buy" else f.executed - ins, f.fee + ins)
    return legs


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parents[2] / "vectors")
    for case in CASES:
        v = build(case)
        (out / f"{v['id']}.json").write_text(json.dumps(v, indent=2) + "\n")
        fs, ss = v["expected"]["fee_stage"], v["expected"]["score_stage"]
        print(f"{v['id']:32} fee_err={fs.get('error', '-'):22} score_err={ss.get('error', '-'):10} "
              f"score_native={ss['score_native']}")


if __name__ == "__main__":
    main()
