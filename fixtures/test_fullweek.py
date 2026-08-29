"""FULL-WEEK CHAIN (2026-08-29) — the rehearsal Monday actually needs.

Every engine was unit-green, but NO test chained the judged week through
ONE broker + ONE hash-chained log:

  Monday    preflight (suspend_trade trap) -> session_open -> gates ACCEPT
            -> ordermech SUBMIT -> entry at broker -> fill -> GTC exit
            ACTUALLY placed at fill
  Wed       exit scan (hold) ... scan (profit target fires on mark touch)
  Friday    R2 10:55 ET: cancel orphans (Monday's GTC!) -> close both legs
            -> verify_flat -> postmortem -> digest -> verify.py CHAIN OK

Plus the two failure surfaces a green-piece suite hides:
  F1. R2 engine raises (unfillable leg) -> r2_liquidate logs ok=False AND
      re-raises; digest renders R2 FAILURE red.
  F2. residual position after R2 -> r2_verify logs ok=False; digest renders
      judged P&L != realized.

Zero network: FixtureBroker on the make_fixtures market, world-state
transitions simulated by rewriting fixture files (the fixtures ARE the
world in this rehearsal).
"""
import json
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from refuser import bs, digest, exits, liquidate, preflight          # noqa
from refuser.audit import AuditTrail                                 # noqa
from refuser.broker import (BrokerError, FixtureBroker,              # noqa
                            SUBMISSION_ACCOUNT)
from refuser.log import DecisionLog                                  # noqa
import make_fixtures                                                 # noqa

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name} {detail}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


def B(rec):
    return rec["body"]


SYM_SHORT = make_fixtures.SYM_SHORT
SYM_LONG = make_fixtures.SYM_LONG
ACCT = SUBMISSION_ACCOUNT

# == the world: one fixture dir that EVOLVES with the week ==================
fxdir = tempfile.mkdtemp(prefix="refuser_week_")
sc = make_fixtures.write_fixture_broker(fxdir, ACCT)
broker = FixtureBroker(fxdir, ACCT)

MON = datetime(2026, 8, 31, 10, 5)      # Monday pre-open ET
WED = datetime(2026, 9, 2, 11, 30)      # Wednesday session
FRI = datetime(2026, 9, 4, 10, 55)      # R2 hard-flat moment


def w(name, obj):
    with open(os.path.join(fxdir, name), "w") as f:
        json.dump(obj, f)


print("== MONDAY T-0. preflight: suspend_trade trap cleared first ==")
w("configurations.json", {"suspend_trade": True,
                          "no_shorting": False,
                          "fractional_trading": True,
                          "max_margin_multiplier": "4",
                          "closing_transactions_only": False})
rep = preflight.preflight(broker, ACCT)          # read-only: must FAIL
check("preflight_catches_suspend_trade", not rep["ok"]
      and "suspend_trade" in [c["check"] for c in rep["checks"]])
rep = preflight.preflight(broker, ACCT, fix=True)  # Monday authorised fix
check("preflight_fixed", rep["ok"] and "suspend_trade" in rep["fixed"]
      and broker._suspend_patched_to is False)

print("== MONDAY. session_open -> gates -> ticket -> fill -> GTC ==")
d = tempfile.mkdtemp(prefix="refuser_weeklog_")
logpath = os.path.join(d, "decisions.jsonl")
trail = AuditTrail(broker, DecisionLog(logpath))
s = trail.session_open(ACCT, role="submission")
check("session_ok", B(s)["ok"] and B(s)["equity"] == 100_000.0)

state = {"equity": B(s)["equity"], "open_positions": 0,
         "positions_by_name": set(), "risk_at_open": 0.0,
         "daily_stop_hit": False, "net_delta": 0.0,
         "now": WED, "today": WED.date()}

S = broker.get_underlying_quote("SPY")["last"]
T = 23 / 365.0
mark = bs.put_spread_mark(S, 517.5, 512.5, T, 0.04, 0.40)
_, d_short, *_ = bs.bs_greeks(S, 517.5, T, 0.04, 0.40, "P")
_, d_long, *_ = bs.bs_greeks(S, 512.5, T, 0.04, 0.40, "P")
snap_s = broker.get_option_snapshot(SYM_SHORT)
snap_l = broker.get_option_snapshot(SYM_LONG)
mid = snap_s["mid"] - snap_l["mid"]

intent = {
    "name": "SPY", "expiry": date(2026, 9, 25),
    "k_short": 517.5, "k_long": 512.5, "width": 5.0, "credit": mark,
    "short_delta": d_short, "spread_delta": d_long - d_short,
    "ask_short": snap_s["ask"], "bid_short": snap_s["bid"],
    "ask_long": snap_l["ask"], "bid_long": snap_l["bid"],
    "oi_short": 8400, "oi_long": 5100,
}
market = {"underlying_last": S, "atm_iv": 0.40,
          "spy_atm_iv": 0.40, "spy_iv_5d_avg": 0.36}

ev = trail.evaluate_entry(intent, state, market)
check("monday_accept", ev["decision"] == "ACCEPT", f"{ev['contracts']}x")
t = trail.submit_entry(ev, mark, mid, SYM_SHORT, SYM_LONG)
check("monday_ticket", B(t)["decision"] == "SUBMIT")

posplan = exits.open_position_plan(ev, ev["contracts"])
trail.fill(posplan, B(t)["receipt"]["order_id"])
g = trail.place_gtc_exit(posplan, SYM_SHORT, SYM_LONG)
check("monday_gtc_placed", B(g)["ok"]
      and B(g)["limit"] == exits.gtc_target_price(mark))
gtc_order_id = B(g)["receipt"]["id"]
check("entry_plus_gtc_at_broker", len(broker.placed_orders) == 2)

print("== WEDNESDAY. exit scans: hold, then profit-target fires ==")
pos_live = {"name": "SPY", "expiry": date(2026, 9, 25),
            "k_short": 517.5, "k_long": 512.5, "width": 5.0,
            "entry_credit": mark, "contracts": ev["contracts"],
            "short_delta": 0.20, "spread_mark": mark}
scan = trail.scan_exits([pos_live], WED)
check("wed_hold", B(scan)["fired"] == [])
pos_hit = dict(pos_live, spread_mark=0.10)
scan2 = trail.scan_exits([pos_hit], WED)
check("wed_target_fires", B(scan2)["fired"][0]["rule"] == "profit_target")

print("== FRIDAY 10:55. R2: orphan GTC cancelled FIRST, then flat ==")
# the world on Friday: position rows exist (live smoke shape), the Monday
# GTC is still a resting order -> an orphan R2 must cancel before closing
w("positions.json", [
    {"symbol": SYM_LONG, "asset_class": "us_option", "qty": "1",
     "side": "long"},
    {"symbol": SYM_SHORT, "asset_class": "us_option", "qty": "-1",
     "side": "short"},
])
w("open_orders.json", [{"id": gtc_order_id, "status": "open"}])

def snapshot_fn(syms):
    if isinstance(syms, str):
        syms = [syms]
    return {s: broker.get_option_snapshot(s) for s in syms}

r2 = trail.r2_liquidate(broker.get_positions(), snapshot_fn,
                        sleep=lambda x: None)
check("r2_cancelled_monday_gtc", B(r2)["cancelled"] == [gtc_order_id],
      str(B(r2)["cancelled"]))
check("r2_closed_both_legs", len(B(r2)["closed"]) == 2
      and B(r2)["failed"] == [])
check("r2_logged_ok", B(r2)["event"] == "r2_liquidation" and B(r2)["ok"])

# closes landed at the broker as marketable tickets (FixtureBroker strips
# _meta exactly like the live API would — identify closes by shape)
closes = [o for o in broker.placed_orders
          if o.get("order_class") == "simple"
          and o.get("legs")
          and o["legs"][0].get("position_intent") in
          ("buy_to_close", "sell_to_close")
          and o.get("time_in_force") == "day"]
check("r2_tickets_at_broker", len(closes) == 2)
buy = next(o for o in closes
           if o["legs"][0]["position_intent"] == "buy_to_close")
exp_mid = broker.get_option_snapshot(SYM_SHORT)["mid"]
check("r2_buyback_through_ask",
      float(buy["limit_price"]) == round(exp_mid + liquidate.AGGRESSION, 2),
      f"limit {buy['limit_price']} = mid {exp_mid} + aggression")

# the fills removed the positions (world transition) -> verify-flat
w("positions.json", [])
v = trail.r2_verify(broker.get_positions())
check("verify_flat_ok", B(v)["ok"] and B(v)["residual"] == [])

print("== FRIDAY 11:00. postmortem -> digest -> judge's verify ==")
trail.postmortem({"realized": 0.0, "unrealized": 0.0, "open": 0,
                  "note": "full-week fixture rehearsal"})
md = digest.render(logpath)
check("digest_full_week", all(x in md for x in (
    "Daily evidence digest", "Entries evaluated (1)", "Order tickets (1)",
    "Fills (1)", "GTC exit **placed**", "R2 liquidation (1)",
    "verify-flat 10:55", "judged P&L = realized P&L")),
    )
check("digest_no_false_claims", "no GTC exit placement" not in md
      and "R2 FAILURE" not in md)
vv = subprocess.run([sys.executable, os.path.join(HERE, "..", "verify.py"),
                     logpath], capture_output=True, text=True)
check("chain_ok_end_of_week", vv.returncode == 0
      and "CHAIN OK" in vv.stdout, vv.stdout.strip())

print("== F1. unfillable Friday leg: engine raises, chain records it ==")
fx2 = FixtureBroker(tempfile.mkdtemp(prefix="refuser_f1_"),
                    ACCT)
make_fixtures.write_fixture_broker(fx2.dir, ACCT)
fx2._next_close_status = "new"          # nothing ever fills
d2 = tempfile.mkdtemp(prefix="refuser_f1log_")
trail2 = AuditTrail(fx2, DecisionLog(os.path.join(d2, "decisions.jsonl")))
trail2.session_open(ACCT, role="r2-failure-rehearsal")
pos = [{"symbol": SYM_SHORT, "asset_class": "us_option",
        "qty": "-1", "side": "short"}]

def snap2(syms):
    if isinstance(syms, str):
        syms = [syms]
    return {s: {"bid": 2.88, "ask": 2.92} for s in syms}

raised = False
try:
    trail2.r2_liquidate(pos, snap2, sleep=lambda x: None, max_walks=2)
except BrokerError:
    raised = True
check("f1_engine_raised", raised)
rows = [json.loads(l)["body"] for l in open(os.path.join(d2,
        "decisions.jsonl"))]
r2rec = [r for r in rows if r.get("event") == "r2_liquidation"]
check("f1_failure_on_chain", r2rec and r2rec[0]["ok"] is False
      and "R2 FAILURE" in r2rec[0]["error"])
md2 = digest.render(os.path.join(d2, "decisions.jsonl"))
check("f1_digest_red", "R2 FAILURE" in md2)
vv2 = subprocess.run([sys.executable, os.path.join(HERE, "..", "verify.py"),
                      os.path.join(d2, "decisions.jsonl")],
                     capture_output=True, text=True)
check("f1_chain_still_ok", vv2.returncode == 0
      and "CHAIN OK" in vv2.stdout)

print("== F2. residual position after R2: verify records the breach ==")
v2 = trail2.r2_verify([{"symbol": SYM_SHORT, "asset_class": "us_option",
                        "qty": "-1"}])
check("f2_residual_logged", B(v2)["ok"] is False
      and B(v2)["residual"] == [SYM_SHORT])
md3 = digest.render(os.path.join(d2, "decisions.jsonl"))
check("f2_digest_shows_breach", "judged P&L ≠ realized" in md3)

print(f"\nRESULT: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
