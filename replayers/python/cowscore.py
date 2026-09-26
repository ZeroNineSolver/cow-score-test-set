"""Reference replayer for the CoW solver fee and score pipeline.

A line-for-line transcription of `cowprotocol/services` at the pinned commit
(README.md). Two stages, as `docs/conventions.md` defines them:

- `fee_stage`: what the driver does to a solution before it reports amounts
  (crates/driver/src/domain/competition/solution/fee.rs and trade.rs).
- `score_stage`: what winner-selection computes from the reported amounts
  (crates/winner-selection/src/arbitrator.rs, crates/chain-types).

Every amount is a Python int standing in for a U256. Checked operations raise
`MathError` with the variant name `services` uses, so an error case records
the same name. No floats except the fee factors, which are f64 in `services`
too; Python floats are IEEE-754 doubles, so `factor / (1.0 - factor)` rounds
the same way.

This file is a consumer of the test set, not its oracle. The CI check links
winner-selection itself and compares `score_native` (harness/).
"""

import math

U256_MAX = (1 << 256) - 1
WAD = 10**18


class MathError(Exception):
    """`services` error variant: Overflow, DivisionByZero, Negative, or a
    trade validation error such as InvalidExecutedAmount."""

    def __init__(self, variant: str):
        super().__init__(variant)
        self.variant = variant


def _fit(x: int) -> int:
    if x > U256_MAX:
        raise MathError("Overflow")
    return x


def checked_add(a: int, b: int) -> int:
    return _fit(a + b)


def checked_sub(a: int, b: int, err: str = "Negative") -> int:
    if b > a:
        raise MathError(err)
    return a - b


def checked_mul(a: int, b: int) -> int:
    return _fit(a * b)


def checked_div(a: int, b: int) -> int:
    if b == 0:
        raise MathError("DivisionByZero")
    return a // b


def checked_ceil_div(a: int, b: int) -> int:
    if b == 0:
        raise MathError("DivisionByZero")
    return -(-a // b)


def mul_div_floor(a: int, m: int, d: int) -> int:
    """Non-widening: the product must fit 256 bits (chain-types evm.rs:63-67)."""
    return checked_div(checked_mul(a, m), d)


def mul_div_ceil(a: int, m: int, d: int) -> int:
    """Non-widening, ceiling (chain-types evm.rs:69-75)."""
    return checked_ceil_div(checked_mul(a, m), d)


def widening_mul_div_floor(a: int, m: int, d: int) -> int:
    """512-bit intermediate; only the quotient must fit (evm.rs:77-83,
    number u256_ext.rs:75-86 for checked_mul_ratio)."""
    if d == 0:
        raise MathError("DivisionByZero")
    return _fit(a * m // d)


def _f64_to_u256(x: float) -> int:
    """ruint 1.20.0 TryFrom<f64>: round to nearest, ties to even (from.rs:523+).
    Python's round() on a float is exact and ties to even."""
    return round(x)


def checked_mul_f64(a: int, factor: float) -> int:
    """number u256_ext.rs:105-135. Identity at exactly 1.0; otherwise
    factor * 1e18 as an integer, a NON-widening multiply, then floor / 1e18."""
    if not math.isfinite(factor) or math.copysign(1.0, factor) < 0:
        raise MathError("Overflow")
    if factor == 1.0:
        return a
    scaled = _f64_to_u256(factor * 1e18)
    return checked_mul(a, scaled) // WAD


# ---------------------------------------------------------------- fee stage
# crates/driver/src/domain/competition/solution/{fee.rs,trade.rs}


class _Fulfillment:
    """trade.rs:112-166. `executed` is the target amount, `fee` the sell-token
    fee (solver fee plus protocol fees so far). Haircut is 0 in this set."""

    def __init__(self, order: dict, executed: int, fee: int):
        side = order["side"]
        with_fee = checked_add(executed, fee if side == "sell" else 0)
        if order["partially_fillable"]:
            ok = with_fee <= int(order["available"])
        else:
            target = int(order["sell_amount"] if side == "sell" else order["buy_amount"])
            ok = with_fee == target
        if not ok:
            raise MathError("InvalidExecutedAmount")
        self.order, self.executed, self.fee = order, executed, fee

    # trade.rs:197-221
    def sell_amount(self, ps: int, pb: int) -> int:
        if self.order["side"] == "sell":
            before = self.executed
        else:
            before = checked_div(checked_mul(self.executed, pb), ps)
        return checked_add(before, self.fee)

    # trade.rs:228-252 (haircut 0)
    def buy_amount(self, ps: int, pb: int) -> int:
        if self.order["side"] == "buy":
            return self.executed
        return checked_ceil_div(checked_mul(self.executed, ps), pb)

    # trade.rs:287-355; limit violations floor to 0 (:322-324, :349-351)
    def surplus_over_reference_price(self, limit_sell: int, limit_buy: int, ps: int, pb: int) -> int:
        e = self.executed
        if self.order["side"] == "buy":
            esa = checked_div(checked_mul(e, pb), ps)
        else:
            esa = e
        esaf = checked_add(esa, self.fee)
        if self.order["side"] == "buy":
            lsa = checked_div(checked_mul(limit_sell, e), limit_buy)
            return max(lsa - esaf, 0)
        lba = checked_ceil_div(checked_mul(limit_buy, esaf), limit_sell)
        eba = checked_ceil_div(checked_mul(e, ps), pb)
        return max(eba - lba, 0)


def _adjust_quote_driver(order: dict, quote: dict) -> tuple[int, int]:
    """fee.rs:249-291. Returns (limit_sell, limit_buy)."""
    s, b = int(order["sell_amount"]), int(order["buy_amount"])
    qs, qb, qf = int(quote["sell_amount"]), int(quote["buy_amount"]), int(quote["fee"])
    if order["side"] == "sell":
        qbuy = checked_sub(qb, checked_div(checked_mul(qf, qb), qs))
        scaled = checked_div(checked_mul(qbuy, s), qs)
        return s, max(b, scaled)
    qsell = checked_add(qs, qf)
    scaled = checked_div(checked_mul(qsell, b), qb)
    return min(s, scaled), b


def _driver_protocol_fee(f: _Fulfillment, policy: dict, ps: int, pb: int) -> int:
    """fee.rs:84-195, in the surplus token."""

    def volume(factor: float) -> int:
        v = f.sell_amount(ps, pb) if f.order["side"] == "buy" else f.buy_amount(ps, pb)
        return checked_mul_f64(v, factor)

    kind = policy["kind"]
    if kind == "volume":
        return volume(policy["factor"])
    if kind == "surplus":
        ls, lb = int(f.order["sell_amount"]), int(f.order["buy_amount"])
    else:
        ls, lb = _adjust_quote_driver(f.order, f.order["quote"])
    from_surplus = checked_mul_f64(f.surplus_over_reference_price(ls, lb, ps, pb), policy["factor"])
    return min(from_surplus, volume(policy["max_volume_factor"]))


def fee_stage(v: dict) -> dict:
    """The driver's forward fold (fee.rs:42-81). Returns `expected.fee_stage`."""
    order, sol = v["order"], v["solution"]
    ps = int(sol["uniform_clearing_prices"][order["sell_token"].lower()])
    pb = int(sol["uniform_clearing_prices"][order["buy_token"].lower()])
    try:
        f = _Fulfillment(order, int(sol["executed"]), int(sol["solver_fee"]))
        fees = []
        for i, policy in enumerate(order["fee_policies"]):
            in_surplus = _driver_protocol_fee(f, policy, ps, pb)
            if order["side"] == "buy":
                in_sell = in_surplus
            else:
                in_sell = widening_mul_div_floor(in_surplus, pb, ps)  # fee.rs:198-213
            fee = checked_add(f.fee, in_sell)
            executed = f.executed if order["side"] == "buy" else checked_sub(f.executed, in_sell, "Overflow")
            f = _Fulfillment(order, executed, fee)
            fees.append({"policy_index": i, "in_surplus_token": str(in_surplus), "in_sell_token": str(in_sell)})
        return {
            "protocol_fees": fees,
            "executed_after_fees": str(f.executed),
            "fee_after_fees": str(f.fee),
            # trade.rs:273-281: custom prices are {sell: buy_amount, buy: sell_amount}
            "custom_clearing_prices": {"sell": str(f.buy_amount(ps, pb)), "buy": str(f.sell_amount(ps, pb))},
        }
    except MathError as e:
        return {"protocol_fees": [], "executed_after_fees": "0", "fee_after_fees": "0",
                "custom_clearing_prices": {"sell": "0", "buy": "0"}, "error": e.variant}


# -------------------------------------------------------------- score stage
# crates/winner-selection/src/arbitrator.rs at the pinned commit


def _ws_sell_amount(o: dict, p: dict) -> int:  # :609-619
    return o["executed_sell"] if o["side"] == "sell" else mul_div_floor(o["executed_buy"], p["buy"], p["sell"])


def _ws_buy_amount(o: dict, p: dict) -> int:  # :621-632
    return mul_div_ceil(o["executed_sell"], p["sell"], p["buy"]) if o["side"] == "sell" else o["executed_buy"]


def _ws_surplus_over(o: dict, p: dict, ls: int, lb: int) -> int:  # :444-473
    if o["side"] == "buy":
        e = o["executed_buy"]
        return checked_sub(mul_div_floor(ls, e, lb), mul_div_floor(e, p["buy"], p["sell"]))
    e = o["executed_sell"]
    return checked_sub(mul_div_ceil(e, p["sell"], p["buy"]), mul_div_ceil(e, lb, ls))


def _ws_adjust_quote(o: dict, q: dict) -> tuple[int, int]:  # :492-534
    qs, qb, qf = q
    if o["side"] == "sell":
        qbuy = checked_sub(qb, mul_div_floor(qf, qb, qs))
        return o["sell_amount"], max(o["buy_amount"], mul_div_floor(qbuy, o["sell_amount"], qs))
    qsell = checked_add(qs, qf)
    return min(o["sell_amount"], mul_div_floor(qsell, o["buy_amount"], qb)), o["buy_amount"]


def _ws_volume_fee(o: dict, p: dict, factor: float) -> int:  # :551-573
    base = _ws_buy_amount(o, p) if o["side"] == "sell" else _ws_sell_amount(o, p)
    adj = factor / (1.0 - factor) if o["side"] == "sell" else factor / (1.0 + factor)
    return checked_mul_f64(base, adj)


def _ws_protocol_fee(o: dict, policy: dict, p: dict, quote) -> int:  # :399-426
    kind = policy["kind"]
    if kind == "volume":
        return _ws_volume_fee(o, p, policy["factor"])
    if kind == "surplus":
        s = _ws_surplus_over(o, p, o["sell_amount"], o["buy_amount"])
    else:
        ls, lb = _ws_adjust_quote(o, quote)
        try:
            s = _ws_surplus_over(o, p, ls, lb)
        except MathError as e:  # :478-489, Negative => 0
            if e.variant != "Negative":
                raise
            s = 0
    f = policy["factor"]
    return min(checked_mul_f64(s, f / (1.0 - f)), _ws_volume_fee(o, p, policy["max_volume_factor"]))


def _ws_custom_prices(o: dict, fee: int, base: dict) -> dict:  # :588-606
    sa, ba = _ws_sell_amount(o, base), _ws_buy_amount(o, base)
    if o["side"] == "sell":
        return {"sell": checked_add(ba, fee), "buy": sa}
    return {"sell": ba, "buy": checked_sub(sa, fee)}


def score_stage(v: dict) -> dict:
    """compute_order_score (:313-362) on the amounts the driver reports.
    Returns `expected.score_stage`."""
    order = v["order"]
    fs = v["expected"]["fee_stage"]
    o = {
        "side": order["side"],
        "sell_amount": int(order["sell_amount"]),
        "buy_amount": int(order["buy_amount"]),
        # The driver reports executed_sell = custom.buy, executed_buy = custom.sell
        # (settlement.rs:290-305); winner-selection reads them back the same way (:578-583).
        "executed_sell": int(fs["custom_clearing_prices"]["buy"]),
        "executed_buy": int(fs["custom_clearing_prices"]["sell"]),
    }
    q = order.get("quote")
    quote = (int(q["sell_amount"]), int(q["buy_amount"]), int(q["fee"])) if q else None
    policies = order["fee_policies"]
    try:
        price = v["native_prices"].get(order["buy_token"].lower())
        if price is None:
            raise MathError("MissingPrice")
        base = {"sell": o["executed_buy"], "buy": o["executed_sell"]}
        user_surplus = _ws_surplus_over(o, base, o["sell_amount"], o["buy_amount"])
        recovered = [0] * len(policies)
        total, current = 0, base
        for i in reversed(range(len(policies))):  # :367-396
            fee = _ws_protocol_fee(o, policies[i], current, quote)
            recovered[i] = fee
            total = checked_add(total, fee)
            if i != 0:
                current = _ws_custom_prices(o, total, base)
        surplus = checked_add(user_surplus, total)
        if o["side"] == "buy":
            surplus = widening_mul_div_floor(surplus, o["buy_amount"], o["sell_amount"])
        # chain-types lib.rs:43-47: widening, SATURATES to U256::MAX
        try:
            native = widening_mul_div_floor(surplus, int(price), WAD)
        except MathError:
            native = U256_MAX
        return {"user_surplus": str(user_surplus), "protocol_fees_recovered": [str(x) for x in recovered],
                "score_native": str(native)}
    except MathError as e:
        return {"user_surplus": "0", "protocol_fees_recovered": [], "score_native": "0", "error": e.variant}
