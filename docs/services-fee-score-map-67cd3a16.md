# cowprotocol/services — fee & score pipeline map

**Repo:** https://github.com/cowprotocol/services  **HEAD:** `67cd3a16ad5b5cbfec16d8404ae038ee9e7019ed`  **Commit date:** 2026-09-23T14:55:54Z ("split paginated trades query in 2 (#4954)")
All paths relative to the repo root. Line ranges are from this SHA. Nothing was built or run.

---

## 1. DRIVER side (`crates/driver/`)

### 1.1 Types and inputs
- `src/domain/competition/order/fees.rs:4-47` — `FeePolicy` enum: `Surplus{factor,max_volume_factor}`, `PriceImprovement{factor,max_volume_factor,quote}`, `Volume{factor}`. Factors are bare `f64` here (the `FeeFactor` newtype only exists on the autopilot/config side).
- `src/domain/competition/order/mod.rs:451-455` — `Quote{sell,buy,fee}` (all `eth::Asset`; `fee` is in sell token).
- `src/domain/competition/order/mod.rs:23-55` — `OrderData`: `buy`, `sell`, `side`, `kind`, `protocol_fees: Vec<FeePolicy>`, `quote: Option<Quote>`, `penalty_cap_native: Option<Ether>`. `Order` (:63-73) adds per-solver `app_data` and `partial: Partial`.
- `src/domain/competition/order/mod.rs:221-234` — `Partial::Yes{available: TargetAmount}` | `No`. `:136-141` `target()` = buy amount for Buy, sell amount for Sell. `:172-201` `available()` scales sell by `checked_mul_ratio(available,target)` (floor) and buy by `checked_mul_ratio_ceil` — both `unwrap_or_default()` to 0 on error.
- `src/domain/competition/order/mod.rs:324-339` — `Kind::{Market, Limit}`; `:205-207` `solver_determines_fee()` ⇔ `Kind::Limit`.
- `src/domain/competition/solution/trade.rs:112-126` — `Fulfillment{order, executed: TargetAmount, fee: SellAmount, haircut_fee: U256}`. `:129-166` `Fulfillment::new` validates `executed + (fee if Sell else 0)` `<= available` (Partial::Yes) or `== target` (Partial::No) — `checked_add` error → `InvalidExecutedAmount`.
- `src/domain/competition/solution/trade.rs:360-363` — `ClearingPrices{sell,buy}` (uniform); `:372-375` `CustomClearingPrices{sell,buy}` (fee-adjusted, per trade).

### 1.2 Solver response → domain (fee and haircut ingestion)
- `src/infra/solver/dto/solution.rs:37-76` — `Solutions::into_domain`: solver `fee` is `unwrap_or_default()` (absent ⇒ 0, :71); haircut fee = `executed_amount * haircut_bps / 10_000` via `checked_mul`/`checked_div`, `unwrap_or_default()` on overflow (:54-63); `MAX_BASE_POINT = 10_000` at `src/infra/solver/dto/mod.rs:11`.
- `src/infra/solver/dto/auction.rs:421-455` — `apply_haircut` tightens limits sent to the solver: Sell `buy.amount *= 1/(1-h)`, Buy `sell.amount *= 1/(1+h)` via `apply_factor` (f64); on `None` (overflow) falls back to **0** with a warn (:441-452). `debug_assert!(haircut_bps <= 10_000)` (:425).
- `src/domain/competition/solution/mod.rs:150-194` — surplus-capturing JIT trades are rewritten into `Fulfillment` with `kind: Limit`, `protocol_fees: vec![]`, `quote: None`, `haircut_fee: 0`.
- `src/domain/competition/solution/mod.rs:211-217` — every user trade must have clearing prices for both tokens, else `InvalidClearingPrices`. `:219-222` protocol fees only applied when `fee_handler == FeeHandler::Driver`. `:224-240` per-fulfillment `with_protocol_fees(prices)` with `prices` looked up by `as_erc20(weth)`.

### 1.3 Protocol fee application (`src/domain/competition/solution/fee.rs`)
- `:42-48` `with_protocol_fees`: folds all `order.protocol_fees` **in forward order**, each step rebuilding the fulfillment.
- `:51-81` `with_protocol_fee`: fee_in_sell_token computed; `fee = fee.checked_add(protocol_fee)` (Overflow err); `executed` for **Sell** is `executed.checked_sub(protocol_fee)` (Overflow err on underflow — note it maps to `Math::Overflow`, not `Negative`), for **Buy** unchanged. Re-validated through `Fulfillment::new` (haircut preserved).
- `:84-133` `protocol_fee` (in **surplus token**): Surplus → `calculate_fee(order limits)`; PriceImprovement → `calculate_fee(adjust_quote_to_order_limits(...))`; Volume → `fee_from_volume`.
- `:139-161` `calculate_fee` = `min(fee_from_surplus, fee_from_volume(max_volume_factor))`.
- `:164-176` `fee_from_surplus` = `surplus_over_reference_price(...).apply_factor(factor)`; `:182-195` `fee_from_volume` volume = `sell_amount(prices)` for Buy, `buy_amount(prices)` for Sell, then `apply_factor(factor)`. `apply_factor` → `checked_mul_f64` (`crates/eth-domain-types/src/token_amount.rs:15-17`), `None`→`Math::Overflow`.
- `:198-213` `protocol_fee_in_sell_token`: Buy → as-is; Sell → `fee.checked_mul_ratio(prices.buy, prices.sell)` (**floor**, 512-bit widening).
- `:249-291` `adjust_quote_to_order_limits`: Sell: `quote_buy = quote.buy − quote.fee*quote.buy/quote.sell` (floor; `Negative` if sub fails), `scaled = quote_buy*order.sell/quote.sell` (floor), limit buy = `max(order.buy, scaled)`. Buy: `quote_sell = quote.sell + quote.fee`, `scaled = quote_sell*order.buy/quote.buy` (floor), limit sell = `min(order.sell, scaled)`. All `checked_mul`/`checked_div` → `Overflow`/`DivisionByZero`.
- `src/domain/competition/solution/trade.rs:287-355` `surplus_over_reference_price`: executed_sell = executed (Sell) or `executed*prices.buy/prices.sell` floor (Buy); `+ fee` (checked_add). Buy: `limit_sell = limit_sell*executed/limit_buy` (floor), `surplus = limit_sell − executed_sell_with_fee`, **`unwrap_or(0)` on underflow** (:322-324). Sell: `limit_buy = limit_buy*executed_sell_with_fee` `checked_ceil_div(limit_sell)`; `executed_buy = executed*prices.sell` `checked_ceil_div(prices.buy)`; `surplus = executed_buy − limit_buy`, **`unwrap_or(0)`** (:349-351).
- `src/domain/competition/solution/trade.rs:197-252` — `sell_amount(prices)`: Sell = executed; Buy = `executed*prices.buy/prices.sell` (floor); `+ fee`; Buy adds haircut converted `haircut*prices.buy/prices.sell` (floor, :256-266). `buy_amount(prices)`: Buy = executed; Sell = `executed*prices.sell` **ceil_div** `prices.buy` minus `haircut*prices.sell/prices.buy` (floor), `Negative` on underflow. `:273-281` `custom_prices` = `{sell: buy_amount, buy: sell_amount}`.
- JIT trades: `trade.rs:390-427` `Jit::new` same validation; `:437-470` `executed_buy`/`executed_sell` use the order's own limit ratio (`checked_ceil_div` for buy leg); `:477-518` `sell_amount`/`buy_amount`/`custom_prices` no haircut. `Trade::protocol_fees()` returns `vec![]` for Jit (`trade.rs:33-38`).

### 1.4 Score (`src/domain/competition/solution/scoring.rs`, entry in `mod.rs`)
- **Entry points:** `src/domain/competition/solution/settlement.rs:243-250` `Settlement::score(prices, jit_owners)` → `Solution::scoring` at `src/domain/competition/solution/mod.rs:310-346`.
- `mod.rs:316-318` only trades passing `trade_count_for_scorable` (`:296-307`: every Fulfillment; Jit only if signer ∈ surplus-capturing owners). `:321-324` executed for Sell = `executed + fee` — **unchecked `+`** on U256. `:327-334` uniform prices via `clearing_price` (ETH→WETH aliasing, `:678-682`); missing → `Scoring::InvalidClearingPrices`. `:335-342` builds `scoring::Trade{signed_sell, signed_buy, side, executed, custom_price = trade.custom_prices(uniform), policies}`.
- `scoring.rs:29-34` `compute_score` = `Σ trade.score(native_prices)` — `Ether::sum` is a plain `Add` fold (`crates/eth-domain-types/src/ether.rs:62-66`), **not checked/saturating**.
- `scoring.rs:83-123` `Trade::score`: `native_price_buy` required (else `MissingPrice`); `surplus_in_surplus_token = user_surplus + fees` (checked_add). Sell → `price.in_eth(surplus)`. Buy → `surplus.widening_mul(signed_buy).checked_div(U512(signed_sell))` then `U256::uint_try_from` (Overflow) → `in_eth`.
- `src/domain/competition/auction.rs:248-250` `Price::in_eth(amount) = amount * price / 10^18` — **unchecked `*` and `/`** on U256. `Price::try_new` rejects zero (:219-225).
- `scoring.rs:127-173` `surplus_over(limits)`: Buy: `limit_sell = limits.sell*executed/limits.buy` (floor), `sold = executed*cp.buy/cp.sell` (floor), `limit_sell − sold` → `Negative`. Sell: `limit_buy = executed*limits.buy` ceil_div `limits.sell`; `bought = executed*cp.sell` ceil_div `cp.buy`; `bought − limit_buy` → `Negative`.
- `scoring.rs:176-188` `fees()`: iterates `policies.iter().rev()`, accumulates `total` (checked_add), and after **every** iteration recomputes `custom_price = calculate_custom_prices(total)` (driver recomputes even after the last policy; autopilot/winsel skip the last — see §2).
- `scoring.rs:230-252` `calculate_custom_prices(fee)`: Sell → `{sell: buy_amount + fee, buy: sell_amount}`; Buy → `{sell: buy_amount, buy: sell_amount − fee}` (`Negative`). `:193-224` `sell_amount`/`buy_amount` from `executed` and custom prices (floor / ceil_div respectively).
- `scoring.rs:255-281` `protocol_fee(policy)`: Surplus → `min(fee(user_surplus,f), volume_fee(mvf))`; PriceImprovement → `min(fee(price_improvement,f), volume_fee(mvf))`; Volume → `volume_fee(f)`.
- `scoring.rs:283-303` `price_improvement`: `adjust_quote_to_order_limits` then `surplus_over`; `Math::Negative` ⇒ **0**, other errors propagate.
- `scoring.rs:316-344` `fee(surplus, factor)` = `surplus.checked_mul_f64(factor / (1.0 − factor))` (Overflow). `:347-391` `volume_fee(factor)`: base = `sell_amount` (Buy) / `buy_amount` (Sell); adjusted factor Sell `f/(1−f)`, Buy `f/(1+f)`; `checked_mul_f64`.
- Error enums: `mod.rs:848-864` `Math{Overflow,DivisionByZero,Negative}` (`From<number::MathError>` maps only the two variants that crate has); `:877-885` `Scoring{InvalidClearingPrices, Math, MissingPrice}`; `:899-901` `Trade::InvalidExecutedAmount`.

---

## 2. AUTOPILOT side (`crates/autopilot/`, `crates/winner-selection/`, `crates/chain-types/`)

### 2.1 Winner selection / score (CIP-38 + CIP-67 fairness + reference scores)
- Adapter: `src/domain/competition/winner_selection.rs:41-115` `Arbitrator::arbitrate` converts `Bid<Unscored>` → `winsel::Solution`, runs `winsel::Arbitrator::arbitrate`, then `compute_reference_scores`. `:117-146` `AuctionContext` from `domain::Auction`: `fee_policies` per order uid, `surplus_capturing_jit_order_owners`, `native_prices = auction.prices[token].get().0` (raw wei-per-1e18 U256). `:162-176` `to_winsel_order` maps `TradedOrder{limit sell/buy, executed_sell, executed_buy, side}` — executed amounts come **straight from the driver's `/solve` response** (`src/infra/solvers/dto/solve.rs:335-372`; no recomputation by autopilot).
- `src/domain/competition/winner_selection.rs:178-207` `fee::Policy` → `winsel::FeePolicy` (`FeeFactor::get()` → f64).
- `crates/winner-selection/src/arbitrator.rs:40-59` `arbitrate`: partition unfair → mark winners → sort by `(Reverse(is_winner), Reverse(score))`.
- `arbitrator.rs:63-115` `partition_unfair_solutions`: score per solution or **discard on any math error** (:143-175, warn only); retain only solutions settling ≥1 order with `contributes_to_score` (`auction.rs:54-58`: has fee-policy entry OR JIT owner allowlisted); sort desc; `compute_baseline_scores` (:647-666 — best score among solutions that trade **exactly one** directed pair); keep if solution has 1 pair OR every pair score ≥ baseline (missing baseline ⇒ pass) (:101-107).
- `arbitrator.rs:181-215` `pick_winners`: greedy by score, a solution wins only if none of its **directed** `(sell,buy)` pairs (canonicalised via `canonical_token`/`as_erc20`) was already covered, up to `max_winners`.
- `arbitrator.rs:219-259` `compute_reference_scores`: for each winning solver, rerun `pick_winners` without that solver, `saturating_add` the winners' scores; `unwrap_or(0)`.
- `arbitrator.rs:282-305` `score_by_token_pair`: `saturating_add` per directed pair; `:638-642` `sum_by_pair` saturating fold.
- `arbitrator.rs:313-362` `compute_order_score`: needs `native_prices[buy_token]` (else error → solution discarded); `custom_prices = {sell: executed_buy, buy: executed_sell}` (:578-583); `surplus_over_limit_price + protocol_fees` (`try_add` Overflow); Sell → `value_in_native(price, surplus)`; Buy → `surplus.try_widening_mul_div_floor(buy_amount, sell_amount)` then `value_in_native`.
- `crates/chain-types/src/lib.rs:43-47` `value_in_native = amount.try_widening_mul_div_floor(price, 10^18)` **saturating to `U256::MAX`** on overflow (denominator at `evm.rs:51`). Contrast: driver `in_eth` is unchecked.
- `arbitrator.rs:367-396` `protocol_fees`: iterate policies **reversed**, `try_add` total, recompute custom prices only when `i != 0` (skips after last policy). `:399-426` `protocol_fee`: same three arms as driver (`min(surplus_fee, volume_fee)` for Surplus/PriceImprovement; Volume alone).
- `arbitrator.rs:444-473` `surplus_over`: Buy: `limits.sell.try_mul_div_floor(executed, limits.buy)` − `executed.try_mul_div_floor(prices.buy, prices.sell)` (`Negative`). Sell: `executed.try_mul_div_ceil(limits.buy, limits.sell)`, `executed.try_mul_div_ceil(prices.sell, prices.buy)`, `bought − limit_buy` (`Negative`). Non-widening: `Overflow` on intermediate (`crates/chain-types/src/evm.rs:63-75`).
- `arbitrator.rs:478-489` `price_improvement_over_quote`: `Negative` ⇒ 0. `:492-534` `adjust_quote_to_order_limits` mirrors driver (floor mul-div, `try_sub` → `Negative`). `:539-548` `surplus_fee = surplus.try_mul_f64(f/(1−f))`; `:551-573` `volume_fee` adjusted `f/(1−f)` Sell, `f/(1+f)` Buy. `evm.rs:85-87` `try_mul_f64` → `checked_mul_f64`, `None`⇒`Overflow`. `:588-606` `calculate_custom_prices` identical to driver; `:609-632` `sell_amount`/`buy_amount` floor/ceil.
- `src/domain/competition/mod.rs:54-65` `TradedOrder`; `:67-100` `Score(Ether)` with `saturating_add`.

### 2.2 Fee-policy assignment per order (`src/domain/fee/`)
- Call site: `src/solvable_orders.rs:324-329` `protocol_fees.apply(order, quote, jit_owners)` per order at auction build; `:320-323` penalty cap computed alongside.
- `src/domain/fee/mod.rs:205-229` `apply`: if no quote → synthetic quote with `buy_amount = 0` (order treated as out-of-market, :211-219); partner fees from app-data (`get_partner_fee`); **surplus-capturing JIT owners get only partner fees** (:224-226); else `apply_policies`.
- `mod.rs:231-251` `apply_policies`: uses `upcoming_fee_policies` if `effective_from_timestamp <= now` else configured `fee_policies`; per policy `protocol_fee_into_policy` (class gate) → `variant_fee_apply`; then **partner fees appended after protocol policies**.
- `mod.rs:266-279` class gate: `outside_market_price = shared::is_order_outside_market_price(order, quote, kind)`; `(_, Any)` | `(true, Limit)` | `(false, Market)` ⇒ apply, else skip. So "limit" = out-of-market vs quote, "market" = in-market — **not** `OrderKind`, and `model::OrderClass` is deprecated (`crates/model/src/order.rs:707-712`, `class: ()`).
- `crates/shared/src/order_validation.rs:1233-1255` `is_order_outside_market_price`: Buy: `order.sell*quote.buy < (quote.sell+quote.fee)*order.buy` (512-bit widening; `quote.sell+quote.fee` is unchecked `+`); Sell: `quote_buy = quote.buy − quote.fee*quote.buy/quote.sell` (checked; **any `None` ⇒ `true`/outside**), `order.sell*quote_buy < quote.sell*order.buy`.
- `mod.rs:253-264` + `src/domain/fee/policy.rs:52-85`: Surplus/PriceImprovement applied unconditionally; Volume passes through `shared::fee::VolumeFeePolicy::get_applicable_volume_fee_factor` (`crates/shared/src/fee.rs:96-131`: skip same-token trades unless flag; ETH→WETH alias; bucket override first-match; else given factor).
- Partner fees `mod.rs:106-202`: parse `full_app_data`; Volume → `capped_fee_factor(bps/10000, max_partner_fee, acc)`; Surplus/PriceImprovement → `factor = clamp(bps, ≤9999)/10000` (`:114-119`, **not** capped) and `max_volume_factor = capped_fee_factor(max_volume_bps/10000, ...)`. `crates/shared/src/fee.rs:235-239` `capped_fee_factor`: `remaining = (1+cap)/(1+acc) − 1`, `acc += min(value, cap−acc)`, returns `clamp(value, 0, remaining)` (rust_decimal, `f64::try_from(...).unwrap()`).
- `crates/configs/src/fee_factor.rs:7-53` `FeeFactor(f64)` invariant `[0,1)` via `TryFrom`; `to_high_precision` = `round(f*1e6)`.
- `src/domain/fee/mod.rs:282-326` `fee::Policy` / `fee::Quote{sell_amount, buy_amount, fee, solver}` as sent to drivers.

### 2.3 CIP-87 penalty cap (`src/domain/penalty_cap.rs`)
- `:15` `WAD = 10^18`. `:24-36` `PenaltyCapCalculator{default_factor, overrides, absolute_cap_atoms, usd_reference_token, native_token, usd_reference_price: Mutex<U256>}`.
- `:44-73` `new`: `absolute_cap_atoms = round(absolute_cap_usd * 10^decimals)` as u128 (`expect` on failure).
- `:94-116` `calculate(order, prices)`: volume token/amount = sell (Sell) or buy (Buy); `volume_cap = amount.checked_mul(price) / WAD` then `factor.apply_to(volume)`; `cap = min(volume_cap, absolute_cap)`; if price missing or `checked_mul` overflow ⇒ `absolute_cap`. `:121-132` factor = first override containing both tokens (buy side ETH→WETH aliased, :136-142) else default. `:147-153` `absolute_cap_in_native = absolute_cap_atoms.checked_mul(usd_price)/WAD`, **`U256::MAX` on overflow**.
- Wiring: `src/run.rs:493-529, 803-827`; USD price refreshed each auction from the native-price map `src/solvable_orders.rs:280-284`.

### 2.4 Native prices used for score
- `src/solvable_orders.rs:261-273, 528-542` — fetched via `NativePriceUpdater::update_tokens_and_fetch_prices`, converted with `to_normalized_price` (`crates/price-estimation/src/native/mod.rs:47-53`: `U256::saturating_from(1e18 * price)`, rejects non-normal, `<1`, `≥2^256`). `:277-279` WETH price forced to `1e18`. `:333-336` wrapped as `auction::Price::try_new` (zero rejected, `src/domain/auction/mod.rs:52-58`). `src/domain/auction/mod.rs:86-88` `Price::in_eth = amount * price / 1e18` (unchecked; used by settlement observation, not by winner selection which uses `value_in_native`).

### 2.5 Settlement observation (post-hoc, same math family)
- `src/domain/settlement/trade/math.rs:21-28` `Trade{uid, sell, buy, side, executed, prices: {uniform, custom}}` decoded from calldata. `:34-72` `surplus_over` uses `checked_mul_ratio` / `checked_mul_ratio_ceil` (widening). `:76-95` `surplus_in_ether` / `fee_in_ether` via `Price::in_eth`. `:121-128` total fee = `surplus(uniform) − surplus(custom)` (`Negative` on underflow). `:133-170` `protocol_fees` reversed loop, custom prices recomputed only when `i != 0`. `:98-110` fee → sell token by `checked_mul_ratio(uniform.buy, uniform.sell)`.

---

## 3. SHARED (`crates/model/`, `crates/shared/`, `crates/number/`, `crates/eth-domain-types/`)
- `crates/model/src/order.rs:185-208` `OrderData{sell_token, buy_token, sell_amount, buy_amount, app_data, fee_amount, kind: OrderKind, partially_fillable, ...}`; `:873-880` `OrderKind::{Buy (default), Sell}`; `:680-738` `OrderMetadata` incl. `executed_*`, `full_app_data: Option<String>` (partner fees parsed from it), `quote: Option<OrderQuote>`, deprecated `class: ()`.
- `crates/autopilot/src/domain/auction/order.rs:9-33` autopilot `Order{sell, buy, protocol_fees: Vec<fee::Policy>, side, partially_fillable, executed, app_data, quote, penalty_cap_native}`.
- `crates/winner-selection/src/solution.rs:89-122` minimal `Order{uid, sell_token, buy_token, sell_amount, buy_amount, executed_sell, executed_buy, side}`; `primitives.rs:26-46` `FeePolicy`/`Quote`.
- `crates/number/src/u256_ext.rs:71-135` `U256Ext`: `checked_ceil_div` (`None` on zero divisor); `checked_mul_ratio` (floor; fast path if product fits 256 bits else 512-bit, `Overflow` if quotient >256 bits, `DivisionByZero`); `checked_mul_ratio_ceil`; `checked_mul_f64` (rejects non-finite/negative; `1.0` identity; `scaled = factor*1e18` cast to U256 (`U256::from(f64)` if ≤ u128::MAX else `BigUint::from_f64`); `self.checked_mul(scaled)` **non-widening** → `None` on overflow; then `/1e18` floor).
- `crates/shared/src/fee.rs:137-165` `compute_volume_fee` (widening `base*to_high_precision(f)/1e6`, floor) and `apply_volume_fee` (saturating sub/add) — used only by the **fast-path limit check** (`:203-222`), not by the score path. `:182-191` `satisfies_limit_price` = `executed_sell*signed_buy <= executed_buy*signed_sell` (512-bit).
- `crates/eth-domain-types/src/token_amount.rs:15-17` `apply_factor`; `src/ether.rs:37-48, 62-66` `Ether` saturating add/sub, checked_sub, plain-Add `Sum`.

---

## 4. Existing tests
| Module | `#[test]`/`#[tokio::test]` | What |
|---|---|---|
| `crates/driver/src/domain/competition/solution/fee.rs` (:302-408) | 4 | `adjust_quote_to_order_limits` in/out-of-market × side |
| `crates/driver/src/domain/competition/solution/scoring.rs` (:404-455) | 1 | `score_problematic_buy_order` (historical Base auction, expects score 911) |
| `crates/driver/src/domain/competition/solution/trade.rs` | 0 | — |
| `crates/driver/src/domain/competition/solution/mod.rs` | 1 | `solution_id_unique` (not arithmetic) |
| `crates/driver/src/domain/competition/solution/settlement.rs` | 5 | gas-limit / submission-fee only |
| `crates/driver/src/tests/cases/protocol_fees.rs` | 39 | driver integration (mock solver, expected order amounts) |
| `crates/driver/src/tests/cases/fees.rs` / `haircut.rs` / `haircut_pre_processing.rs` / `quote.rs` | 1 / 2 / 4 / 11 | driver integration |
| `crates/number/src/u256_ext.rs` (:146-300) | 4 | ceil_div, mul_f64, mul_ratio(+ceil) edge cases |
| `crates/autopilot/src/domain/fee/mod.rs` (:339-664) | 7 | partner-fee capping |
| `crates/autopilot/src/domain/penalty_cap.rs` (:170-339) | 8 | cap selection, overflow/missing-price fallbacks |
| `crates/autopilot/src/domain/competition/winner_selection.rs` (:278-1300) | 10 | arbitration scenarios; inputs are **inline `serde_json::json!` literals** deserialised by `TestCase::from_json` (:967-980) with `expected_fair_solutions`, `expected_winners`, `expected_reference_scores` |
| `crates/winner-selection/src/tests.rs` | 6 | EVM/Solana parity, overflow, fairness, surplus-fee doubling |
| `crates/autopilot/src/domain/settlement/trade/math.rs` (:557-613) | 2 | hugely-scaled clearing prices |
| `crates/autopilot/src/domain/settlement/mod.rs` | 6 | settlement observation incl. `settlement_with_protocol_fee` |
| `crates/shared/src/fee.rs` (:268-) | 11 | volume-fee buckets / caps |
| `crates/e2e/tests/e2e/protocol_fee.rs` | 8 | full-stack e2e |

**Test-vector fixtures:** none. No `*.json`/`*.yaml`/`*.yml` under any test directory (repo-wide non-target hits are only `openapi.yml` files and `crates/event-bus-dto/schemas/events.json`); no directory or file named `*fixture*`/`*vector*`; `include_str!`/`include_bytes!` occur only in `crates/s3/src/lib.rs` and `crates/solana-solvers/src/config.rs` (unrelated). The closest thing to a vector format is the inline-JSON `TestCase` schema in `winner_selection.rs:967-980`.

---

## 5. Rounding / overflow / checked sites (individually)
Driver fee path (`solution/fee.rs`): `:62 checked_add` (fee) · `:75 checked_sub` (executed, Sell; error = Overflow) · `:172-174 apply_factor`→`checked_mul_f64` · `:191-193` same · `:208 checked_mul_ratio` (floor) · `:150 std::cmp::min` · `:254-262 checked_sub/checked_mul/checked_div` (→Negative/Overflow/DivByZero) · `:263-268 checked_mul/checked_div`, `.max` · `:275-284 checked_add/checked_mul/checked_div`, `.min`.
Driver trade math (`solution/trade.rs`): `:147 checked_add` · `:203-206 checked_mul/checked_div` (floor) · `:209 checked_add` · `:218 checked_add` · `:236-239 checked_mul/checked_ceil_div` · `:244-248 checked_mul/checked_div/checked_sub`(Negative) · `:261-264 checked_mul/checked_div` · `:298-302, :309, :314-318, :322-324 unwrap_or(0)` · `:334-338 checked_mul/checked_ceil_div` · `:341-345` same · `:349-351 unwrap_or(0)` · Jit `:406 checked_add` · `:443-448 checked_add/checked_mul/checked_ceil_div` · `:458-461 checked_mul/checked_div` · `:466 checked_add` · `:483-489` · `:500-503 checked_ceil_div`.
Driver scoring (`solution/scoring.rs`): `:33 .sum()` (**unchecked Add fold**) · `:92 checked_add` · `:111-115 widening_mul / checked_div(U512) / uint_try_from` · `:134-145 checked_mul/checked_div/checked_sub` · `:158-169 checked_mul/checked_ceil_div/checked_sub` · `:182 checked_add` · `:199-202, :217-220` · `:239, :248 checked_add/checked_sub` · `:262, :273 min` · `:341 checked_mul_f64(f/(1−f))` · `:388 checked_mul_f64`. `solution/mod.rs:322` **unchecked `+`** (executed+fee). `auction.rs:249` **unchecked `* /`** in `in_eth`. DTO: `dto/solution.rs:56-60 checked_mul/checked_div/unwrap_or_default` · `dto/auction.rs:441-452 apply_factor` fallback to 0. Order: `order/mod.rs:184-198 checked_mul_ratio / checked_mul_ratio_ceil / unwrap_or_default`; `competition/mod.rs:837 checked_mul_ratio.unwrap_or_default()`.
Number crate (`u256_ext.rs`): `:72 div_ceil` guarded by zero check · `:80-84` fast path `checked_mul` else `widening_mul`/`U512` div/`uint_try_from` · `:92-102 div_rem` + `checked_add(1)` · `:106 !is_finite || is_sign_negative` → None · `:112 is_one` identity · `:122-130 U256::from(f64)` vs `BigUint::from_f64` · `:133 checked_mul` (non-widening) · `:134 checked_div(1e18)`.
Winner-selection / chain-types: `arbitrator.rs:252 saturating_add`, `:301 saturating_add`, `:331 try_add`, `:352 try_widening_mul_div_floor`, `:385 try_add`, `:412/:422 .min`, `:457-461 try_mul_div_floor ×2, try_sub`, `:466-470 try_mul_div_ceil ×2, try_sub`, `:486 Negative⇒0`, `:499-510 try_sub/try_mul_div_floor ×2, .max`, `:519-526 try_add/try_mul_div_floor, .min`, `:547 try_mul_f64(f/(1−f))`, `:572 try_mul_f64`, `:598/:603 try_add/try_sub`, `:617 try_mul_div_floor`, `:629 try_mul_div_ceil`, `:641 saturating_add`. `chain-types/lib.rs:44-46 try_widening_mul_div_floor` **`unwrap_or_else(max_value)`** · `:62 checked_add`→Overflow · `:67 checked_sub`→Negative. `chain-types/evm.rs:64-67 checked_mul/checked_div` · `:71-74 checked_mul/checked_ceil_div` · `:78-82 widening_mul/checked_div(U512)/uint_try_from` · `:86 checked_mul_f64`.
Autopilot fee/penalty: `fee/mod.rs:115 bps.min(9999)`, `:117-118 f64 division + FeeFactor::try_from`, `:140/:154/:176 Decimal division`; `shared/fee.rs:236-238 Decimal ops, .min/.max, f64::try_from(...).unwrap()`; `penalty_cap.rs:64-67 f64 powi/round/to_u128().expect`, `:106-109 checked_mul, / WAD, factor.apply_to`, `:112 .min`, `:149-152 checked_mul, / WAD, unwrap_or(U256::MAX)`. `shared/order_validation.rs:1240-1249 widening_mul (512-bit)`, `:1241 unchecked quote.sell + quote.fee`, `:1246 checked_sub/checked_mul/checked_div` with `unwrap_or(true)`. `price-estimation/src/native/mod.rs:50-52 1e18*price f64, saturating_from`. `auction/mod.rs:87 unchecked * /`.
Settlement observation (`settlement/trade/math.rs`): `:45, :49, :106, :181 checked_mul_ratio` · `:63, :67, :196 checked_mul_ratio_ceil` · `:50, :68, :125, :224 checked_sub` · `:156, :215 checked_add` · `:337, :386 checked_mul_f64` · `:429-457 checked_sub/checked_mul/checked_div/checked_add`.

### Cross-implementation divergences worth a vector each (all observed in code above)
1. Native conversion: driver `in_eth` unchecked (`auction.rs:249`) vs winsel `value_in_native` saturating to `U256::MAX` (`chain-types/lib.rs:46`).
2. Driver `fees()` recomputes custom prices after the last policy (`scoring.rs:185`); winsel/autopilot skip when `i == 0` (`arbitrator.rs:390`, `math.rs:163`) — affects only whether a final `Negative` error can surface.
3. Sum of trade scores: driver plain `Add` (`ether.rs:64`), winsel `saturating_add` (`arbitrator.rs:301,641`).
4. Driver surplus-for-fee uses `unwrap_or(0)` on limit violation (`trade.rs:322-324, 349-351`) while scoring/winsel `surplus_over` returns `Negative` (`scoring.rs:145,169`; `arbitrator.rs:461,470`).
5. Driver `with_protocol_fee` applies policies forward (`fee.rs:44`); scoring/winsel/settlement iterate reversed (`scoring.rs:179`, `arbitrator.rs:382`, `math.rs:144`).
6. `surplus_over` mul-div: driver scoring & winsel are non-widening (`checked_mul` then div); settlement observation uses widening `checked_mul_ratio*` (`math.rs:45-67`).
