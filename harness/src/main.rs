//! Checks every test case's score stage against `winner-selection` at the
//! pinned commit.
//!
//! For each vector it builds the inputs the autopilot builds
//! (`crates/autopilot/src/domain/competition/winner_selection.rs:117-176`):
//! one order with its limit amounts and the executed amounts the driver
//! reports, the order's fee policies, and the native prices. It then calls
//! `winner_selection::arbitrator::score` and compares the result with
//! `expected.score_stage.score_native`, or checks that it fails when the
//! vector names an error.
//!
//! `score` is the only public entry point, so the per-policy fees and the
//! user surplus in a vector are not checked here. They are checked by the
//! replayers and, from Milestone 2, by the generator.
//!
//! Usage: check-vectors <vectors dir>. Exit status 1 on any mismatch.

use {
    serde_json::Value,
    std::{collections::HashMap, path::Path, process::ExitCode, str::FromStr},
    winner_selection::{
        Address, AuctionContext, Order, OrderUid, Side, Solution, U256, arbitrator,
        primitives::{FeePolicy, Quote},
    },
};

fn u256(v: &Value) -> U256 {
    U256::from_str(v.as_str().expect("amount is a string")).expect("amount is a decimal integer")
}

fn address(s: &str) -> Address {
    Address::from_str(s).expect("token is a 20-byte hex address")
}

fn order_uid(s: &str) -> OrderUid {
    let hex = s.trim_start_matches("0x");
    let mut bytes = [0u8; 56];
    assert_eq!(hex.len(), 112, "order uid must be 56 bytes");
    for (i, b) in bytes.iter_mut().enumerate() {
        *b = u8::from_str_radix(&hex[2 * i..2 * i + 2], 16).expect("uid is hex");
    }
    OrderUid(bytes)
}

fn policy(p: &Value, quote: Option<Quote>) -> FeePolicy {
    let f = |k: &str| p[k].as_f64().expect("factor is a number");
    match p["kind"].as_str().expect("policy kind") {
        "surplus" => FeePolicy::Surplus {
            factor: f("factor"),
            max_volume_factor: f("max_volume_factor"),
        },
        "price_improvement" => FeePolicy::PriceImprovement {
            factor: f("factor"),
            max_volume_factor: f("max_volume_factor"),
            quote: quote.expect("price_improvement needs order.quote"),
        },
        "volume" => FeePolicy::Volume { factor: f("factor") },
        other => panic!("unknown policy kind {other}"),
    }
}

/// Ok(()) on a match, Err(message) otherwise.
fn check(v: &Value) -> Result<(), String> {
    let order = &v["order"];
    let fee_stage = &v["expected"]["fee_stage"];
    let score_stage = &v["expected"]["score_stage"];
    if fee_stage.get("error").is_some() {
        // The driver drops the trade; nothing reaches winner selection.
        return Ok(());
    }

    let uid = order_uid(order["uid"].as_str().unwrap());
    let quote = order.get("quote").map(|q| Quote {
        sell_amount: u256(&q["sell_amount"]),
        buy_amount: u256(&q["buy_amount"]),
        fee: u256(&q["fee"]),
        solver: Address::ZERO,
    });
    let policies = order["fee_policies"]
        .as_array()
        .unwrap()
        .iter()
        .map(|p| policy(p, quote))
        .collect();

    // Every auction order gets an entry, with or without policies
    // (autopilot winner_selection.rs:120-133).
    let context = AuctionContext {
        fee_policies: HashMap::from([(uid, policies)]),
        surplus_capturing_jit_order_owners: Default::default(),
        native_prices: v["native_prices"]
            .as_object()
            .unwrap()
            .iter()
            .map(|(token, price)| (address(token), u256(price)))
            .collect(),
    };

    // The driver reports executed_sell = custom.buy and executed_buy =
    // custom.sell (driver settlement.rs:290-305, trade.rs:273-281).
    let traded = Order {
        uid,
        sell_token: address(order["sell_token"].as_str().unwrap()),
        buy_token: address(order["buy_token"].as_str().unwrap()),
        sell_amount: u256(&order["sell_amount"]),
        buy_amount: u256(&order["buy_amount"]),
        executed_sell: u256(&fee_stage["custom_clearing_prices"]["buy"]),
        executed_buy: u256(&fee_stage["custom_clearing_prices"]["sell"]),
        side: match order["side"].as_str().unwrap() {
            "sell" => Side::Sell,
            "buy" => Side::Buy,
            other => panic!("unknown side {other}"),
        },
    };
    let solution = Solution::new(0, Address::ZERO, vec![traded]);

    match (arbitrator::score(&solution, &context), score_stage.get("error")) {
        (Ok(score), None) => {
            let expected = u256(&score_stage["score_native"]);
            if score == expected {
                Ok(())
            } else {
                Err(format!("score_native: expected {expected}, winner-selection gives {score}"))
            }
        }
        (Err(_), Some(_)) => Ok(()),
        (Ok(score), Some(e)) => Err(format!("expected error {e}, winner-selection scores {score}")),
        (Err(e), None) => Err(format!("winner-selection fails: {e:#}")),
    }
}

fn main() -> ExitCode {
    let dir = std::env::args().nth(1).unwrap_or_else(|| "vectors".into());
    let mut paths: Vec<_> = std::fs::read_dir(Path::new(&dir))
        .expect("vectors dir")
        .map(|e| e.unwrap().path())
        .filter(|p| p.extension().is_some_and(|x| x == "json"))
        .collect();
    paths.sort();

    let mut failed = 0;
    for path in &paths {
        let v: Value = serde_json::from_str(&std::fs::read_to_string(path).unwrap())
            .unwrap_or_else(|e| panic!("{}: {e}", path.display()));
        match check(&v) {
            Ok(()) => println!("ok    {}", v["id"].as_str().unwrap_or("?")),
            Err(msg) => {
                failed += 1;
                println!("FAIL  {}  {msg}", v["id"].as_str().unwrap_or("?"));
            }
        }
    }
    println!("{} vectors, {} passed, {failed} failed", paths.len(), paths.len() - failed);
    if paths.is_empty() || failed > 0 { ExitCode::FAILURE } else { ExitCode::SUCCESS }
}
