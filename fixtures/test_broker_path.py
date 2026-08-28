"""Offline integration test: the FULL decision path through the broker seam.

A.111 #1 deliverable — the whole path (account read + assertion -> chain ->
underlying -> snapshot -> gates -> sizing -> order plan -> adapter) runs
against FixtureBroker, zero network. Monday, the same path runs live by
swapping ONE constructor (FixtureBroker -> AlpacaBroker). Nothing here
reimplements gate logic; the test consumes gates.evaluate_intent +
ordermech.order_plan exactly as the runtime will.

Also encodes A.112/A.113 hard rules as standard suite items:
  - equity read from get_account() at decision time, never defaulted;
  - assert_account before any order;
  - both-equities test: same signal at $100k and $1M -> contracts differ by
    exactly 10x, identical PERCENTAGE risk (A.112 #3).
"""
import os
import sys
import tempfile
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from refuser import bs, gates, ordermech                    # noqa: E402
from refuser.broker import (BrokerError, AccountMismatch,   # noqa: E402
                            FixtureBroker, equity_now,
                            TESTER_ACCOUNT, SUBMISSION_ACCOUNT)
import make_fixtures                                         # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name} {detail}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


def make_broker(account_number):
    d = tempfile.mkdtemp(prefix="refuser_fix_")
    make_fixtures.write_fixture_broker(d, account_number)
    return FixtureBroker(d, account_number)


NOW = datetime(2026, 9, 2, 11, 30)      # Wed, inside entry window
TODAY = NOW.date()
T = 23 / 365.0


def full_path(broker, account_number, now=NOW, today=TODAY):
    """The whole trading path through the seam. Returns final record."""
    # 1. decision-time equity + account assertion (A.112 #1/#2)
    acct = equity_now(broker, account_number)
    equity = float(acct["equity"])

    # 2. state (empty book; same shape reconcile() returns)
    state = {
        "equity": equity,
        "open_positions": len(broker.get_positions()),
        "positions_by_name": set(),
        "risk_at_open": 0.0,
        "daily_stop_hit": False,
        "net_delta": 0.0,
        "now": now,
        "today": today,
    }

    # 3. chain in window
    chain = broker.get_option_chain("SPY", 505.0, 530.0, 21, 35, today=today)

    # 4. live underlying + model repricing (production sigmas)
    S = broker.get_underlying_quote("SPY")["last"]
    short = next(c for c in chain if c["symbol"].endswith("05175000"))
    long_ = next(c for c in chain if c["symbol"].endswith("05125000"))
    _, d_short, *_ = bs.bs_greeks(S, 517.5, T, 0.04, 0.40, "P")
    _, d_long, *_ = bs.bs_greeks(S, 512.5, T, 0.04, 0.40, "P")
    mark = bs.put_spread_mark(S, 517.5, 512.5, T, 0.04, 0.40)

    snap_s = broker.get_option_snapshot(short["symbol"])
    snap_l = broker.get_option_snapshot(long_["symbol"])
    mid = snap_s["mid"] - snap_l["mid"]

    intent = {
        "name": "SPY", "expiry": date(2026, 9, 25),
        "k_short": 517.5, "k_long": 512.5, "width": 5.0, "credit": mark,
        "short_delta": d_short, "spread_delta": d_long - d_short,
        "ask_short": snap_s["ask"], "bid_short": snap_s["bid"],
        "ask_long": snap_l["ask"], "bid_long": snap_l["bid"],
        "oi_short": short["open_interest"], "oi_long": long_["open_interest"],
    }
    market = {"underlying_last": S, "atm_iv": 0.40,
              "spy_atm_iv": 0.40, "spy_iv_5d_avg": 0.36}

    # 5. gates + sizing + order plan, all consuming decision-time equity.
    # COMPOSITION CONTRACT (the bug this suite exists to pin): an order goes
    # to the broker ONLY if the gates ACCEPT *and* ordermech SUBMITS. Wiring
    # plan->place without the ACCEPT check fires orders the gates refused —
    # the first version of this harness did exactly that.
    ev = gates.evaluate_intent(intent, state, market)
    plan = None
    if ev["decision"] == "ACCEPT" and ev["contracts"] >= 1:
        plan = ordermech.order_plan(mark, mid, ev["contracts"])
    if plan is not None and plan.get("decision") == "SUBMIT":
        plan["symbols_short"] = short["symbol"]
        plan["symbols_long"] = long_["symbol"]
        receipt = broker.place_option_order(plan)
    else:
        plan = plan or {"decision": "REFUSE",
                        "reason": f"gates said {ev['decision']}"}
        receipt = None
    return {"acct": acct, "equity": equity, "eval": ev,
            "chain_len": len(chain), "plan": plan, "receipt": receipt,
            "intent": intent}


print("== T1. Full path on SUBMISSION equity ($100k): ACCEPT -> order placed ==")
f_sub = make_broker(SUBMISSION_ACCOUNT)
r_sub = full_path(f_sub, SUBMISSION_ACCOUNT)
check("acct_number", r_sub["acct"]["account_number"] == SUBMISSION_ACCOUNT)
check("decision", r_sub["eval"]["decision"] == "ACCEPT",
      str([g for g in r_sub["eval"]["gates"] if not g["pass"]])[:200])
check("plan_submit", r_sub["plan"].get("decision") == "SUBMIT",
      str(r_sub["plan"].get("reason", ""))[:120])
check("order_placed", r_sub["receipt"] is not None
      and r_sub["receipt"]["status"] == "accepted",
      f"order_id={r_sub['receipt'].get('order_id') if r_sub['receipt'] else None}")
check("adapter_recorded", len(f_sub.placed_orders) == 1)
check("plan_symbols", r_sub["plan"].get("symbols_short", "").endswith("05175000")
      and r_sub["plan"].get("symbols_long", "").endswith("05125000"))
n_100k = r_sub["eval"]["contracts"]
risk_100k = n_100k * (5.0 - r_sub["intent"]["credit"]) * 100
check("submission_risk_pct", 0.006 <= risk_100k / r_sub["equity"] <= 0.0085,
      f"{risk_100k / r_sub['equity']:.4%} of equity, {n_100k} contracts")

print("== T2. Same signal on TESTER ($1M): 10x contracts, identical % risk ==")
fx = make_broker(TESTER_ACCOUNT)
r1 = full_path(fx, TESTER_ACCOUNT)
n_1m = r1["eval"]["contracts"]
risk_1m = n_1m * (5.0 - r1["intent"]["credit"]) * 100
check("contracts_10x", n_1m == 10 * n_100k, f"{n_1m} vs 10*{n_100k}")
check("pct_risk_identical", abs(risk_100k / r_sub["equity"]
                                - risk_1m / r1["equity"]) < 1e-9,
      f"{risk_100k / r_sub['equity']:.6%} vs {risk_1m / r1['equity']:.6%}")

print("== T2b. DESIGN FINDING (A.113 world): absolute net-delta cap binds ==")
print("     on the $1M tester at full 0.75% size -> the gates REFUSE and NO")
print("     order is placed. Conservative by construction; documented, not")
print("     patched. The submission account is unaffected. Decision on")
print("     scaling the cap with equity belongs to Bartosz/Claude, not here.")
nd = [g for g in r1["eval"]["gates"] if g["gate"] == "net_delta"][0]
check("tester_refused_by_net_delta", r1["eval"]["decision"] == "REFUSE"
      and not nd["pass"], nd["detail"])
check("tester_no_order", r1["receipt"] is None
      and len(fx.placed_orders) == 0)
only_diff = [g1["gate"] for g1, g2 in zip(r_sub["eval"]["gates"],
                                          r1["eval"]["gates"])
             if g1["pass"] != g2["pass"]]
check("sole_divergence_is_net_delta", only_diff == ["net_delta"],
      f"diverging gates: {only_diff}")

print("== T3. Account guard: wrong expected number -> refuse, no order ==")
fx3 = make_broker(TESTER_ACCOUNT)
try:
    equity_now(fx3, SUBMISSION_ACCOUNT)
    check("guard_raises", False, "no exception raised")
except AccountMismatch as e:
    check("guard_raises", True, str(e)[:80])
check("guard_no_orders", len(fx3.placed_orders) == 0)

print("== T4. Fail-closed: broker data missing -> BrokerError ==")
fx4 = make_broker(TESTER_ACCOUNT)
os.remove(os.path.join(fx4.dir, "underlying_SPY.json"))
try:
    fx4.get_underlying_quote("SPY")
    check("fail_closed_raises", False, "no exception")
except BrokerError as e:
    check("fail_closed_raises", True, str(e)[:60])

print("== T5. equity re-read every call; nothing cached ==")
check("equity_not_cached", fx.get_account()["equity"] == 1_000_000.0
      and f_sub.get_account()["equity"] == 100_000.0)

print(f"RESULT: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
