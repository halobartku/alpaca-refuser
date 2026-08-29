"""Offline test of the evidence harness (A.111 #4) + audit producers.

The full runtime loop against FixtureBroker, ZERO network:

  session_open (account assertion) -> evaluate_entry (gate anatomy)
  -> submit_entry (guarded composition: order only if ACCEPT x SUBMIT)
  -> fill (GTC exit placed at fill) -> exit scan -> post-mortem
  -> digest.render() over the REAL record shapes audit.py wrote
  -> verify.py chain check as a subprocess (the judge's command)
  -> tamper test: mutate a historical record, chain MUST break

Also pins the two refusal branches of submit_entry (gates-REFUSE and
ordermech-REFUSE) so the composition contract is tested, not assumed.
"""
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "fixtures"))

from refuser import bs, digest, exits                       # noqa: E402
from refuser.audit import AuditTrail                        # noqa: E402
from refuser.broker import (FixtureBroker,                  # noqa: E402
                            SUBMISSION_ACCOUNT)
from refuser.log import DecisionLog                         # noqa: E402
import make_fixtures                                        # noqa: E402

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
    """Producers return the chain record; the payload is under 'body'."""
    return rec["body"]


NOW = datetime(2026, 9, 2, 11, 30)      # Wed, inside entry window
TODAY = NOW.date()
T = 23 / 365.0

# == build the market picture exactly like the runtime will =================
fxdir = tempfile.mkdtemp(prefix="refuser_audit_")
sc = make_fixtures.write_fixture_broker(fxdir, SUBMISSION_ACCOUNT)
broker = FixtureBroker(fxdir, SUBMISSION_ACCOUNT)

d = tempfile.mkdtemp(prefix="refuser_log_")
logpath = os.path.join(d, "decisions.jsonl")
trail = AuditTrail(broker, DecisionLog(logpath))

print("== E1. session_open: account asserted, equity at decision time ==")
s = trail.session_open(SUBMISSION_ACCOUNT, role="submission-fixture")
check("session_recorded", B(s)["event"] == "session_open" and B(s)["ok"]
      and B(s)["account_number"] == SUBMISSION_ACCOUNT)
check("equity_at_decision_time", B(s)["equity"] == 100_000.0)

state = {
    "equity": B(s)["equity"], "open_positions": 0, "positions_by_name": set(),
    "risk_at_open": 0.0, "daily_stop_hit": False, "net_delta": 0.0,
    "now": NOW, "today": TODAY,
}

S = broker.get_underlying_quote("SPY")["last"]
mark = bs.put_spread_mark(S, 517.5, 512.5, T, 0.04, 0.40)
_, d_short, *_ = bs.bs_greeks(S, 517.5, T, 0.04, 0.40, "P")
_, d_long, *_ = bs.bs_greeks(S, 512.5, T, 0.04, 0.40, "P")
snap_s = broker.get_option_snapshot("SPY260925P05175000")
snap_l = broker.get_option_snapshot("SPY260925P05125000")
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

print("== E2. evaluate_entry: full gate anatomy recorded ==")
ev = trail.evaluate_entry(intent, state, market)
check("accept", ev["decision"] == "ACCEPT", f"{ev['contracts']} contracts")
check("all_gates_logged", len(ev["gates"]) >= 8
      and all("gate" in g and "pass" in g for g in ev["gates"]),
      f"{len(ev['gates'])} gates")

print("== E3. submit_entry ACCEPT path: ticket + measured slippage ==")
t = trail.submit_entry(ev, mark, mid,
                       "SPY260925P05175000", "SPY260925P05125000")
check("ticket_submit", B(t)["decision"] == "SUBMIT"
      and B(t)["receipt"]["status"] == "accepted")
check("slippage_measured", "vs_quoted" in B(t)["slippage"]
      and "captured_frac" in B(t)["slippage"],
      f"captured {B(t)['slippage']['captured_frac']}")
check("order_reached_broker", len(broker.placed_orders) == 1)

print("== E4. fill + GTC exit ACTUALLY PLACED at fill time ==")
posplan = exits.open_position_plan(ev, ev["contracts"])
f = trail.fill(posplan, B(t)["receipt"]["order_id"])
check("fill_recorded", B(f)["event"] == "fill")
g = trail.place_gtc_exit(posplan, "SPY260925P05175000",
                         "SPY260925P05125000")
check("gtc_placed_recorded", B(g)["event"] == "gtc_exit" and B(g)["ok"]
      and B(g)["limit"] == exits.gtc_target_price(mark))
check("gtc_reached_broker", len(broker.placed_orders) == 2)  # entry + gtc
gtc_ticket = broker.placed_orders[1]
check("gtc_ticket_shape", gtc_ticket["time_in_force"] == "gtc"
      and gtc_ticket["order_class"] == "mleg"
      and float(gtc_ticket["limit_price"])
      == exits.gtc_target_price(mark)
      and {l["position_intent"] for l in gtc_ticket["legs"]}
      == {"buy_to_close", "sell_to_close"})
check("gtc_limit_is_50pct_credit",
      abs(exits.gtc_target_price(mark) - 0.5 * mark) < 0.01)

print("== E4b. digest NEGATIVE: fill without placed GTC must NOT claim one ==")
d3 = tempfile.mkdtemp(prefix="refuser_gtcneg_")
logpath3 = os.path.join(d3, "decisions.jsonl")
fxn = FixtureBroker(tempfile.mkdtemp(prefix="refuser_gtcnegfx_"),
                    SUBMISSION_ACCOUNT)
make_fixtures.write_fixture_broker(fxn.dir, SUBMISSION_ACCOUNT)
trail3 = AuditTrail(fxn, DecisionLog(logpath3))
trail3.session_open(SUBMISSION_ACCOUNT, role="neg")
trail3.fill(posplan, "no-gtc-order")
md3 = digest.render(logpath3)
check("no_false_gtc_claim", "no GTC exit placement on record" in md3
      and "GTC exit resting" not in md3)

print("== E5. exit scan on the open position (mark far from target: hold) ==")
pos_live = {"name": "SPY", "expiry": date(2026, 9, 25),
            "k_short": 517.5, "k_long": 512.5, "width": 5.0,
            "entry_credit": mark, "contracts": ev["contracts"],
            "short_delta": 0.20, "spread_mark": mark}
scan = trail.scan_exits([pos_live], NOW)
check("scan_recorded", B(scan)["event"] == "exit_scan"
      and B(scan)["checked"] == 1 and B(scan)["fired"] == [])

print("== E5b. exit scan that FIRES (mark collapses to target) ==")
pos_hit = dict(pos_live, spread_mark=0.10)   # <= 50% target
scan2 = trail.scan_exits([pos_hit], NOW)
check("exit_fires", B(scan2)["fired"][0]["rule"] == "profit_target",
      B(scan2)["fired"][0]["note"])

print("== E6. post-mortem + digest render ==")
trail.postmortem({"realized": 0.0, "unrealized": 0.0,
                  "open": 1, "note": "fixture session"})
md = digest.render(logpath)
check("digest_sections", all(x in md for x in (
    "Daily evidence digest", "chain", "session:", "Entries evaluated (1)",
    "Order tickets (1)", "Fills (1)", "exit scan", "post-mortem")))
check("digest_gate_anatomy_shown", "`dte` pass" in md
      and "`liquidity` pass" in md)
check("digest_slippage_shown", "slippage" in md)
check("digest_disclosure_present", "AI-authored" in md)

print("== E7. verify.py as a judge would run it ==")
v = subprocess.run([sys.executable, os.path.join(HERE, "..", "verify.py"),
                    logpath], capture_output=True, text=True)
check("verify_chain_ok", v.returncode == 0 and "CHAIN OK" in v.stdout,
      v.stdout.strip())

print("== E8. TAMPER TEST: mutate a historical record ==")
with open(logpath) as f:
    lines = f.read().splitlines()
import json as _json
rec = _json.loads(lines[3])               # the gate-eval record
rec["body"]["decision"] = "ACCEPT-EVERYTHING"   # the forgery
lines[3] = _json.dumps(rec)
d2 = tempfile.mkdtemp(prefix="refuser_tamper_")
tpath = os.path.join(d2, "decisions.jsonl")
with open(tpath, "w") as f:
    f.write("\n".join(lines) + "\n")
v2 = subprocess.run([sys.executable, os.path.join(HERE, "..", "verify.py"),
                     tpath], capture_output=True, text=True)
check("tamper_detected", v2.returncode == 1 and "CHAIN BROKEN" in v2.stdout,
      v2.stdout.strip())
try:
    digest.render(tpath)
    check("digest_refuses_tampered", False, "render did not raise")
except RuntimeError as e:
    check("digest_refuses_tampered", "broken" in str(e).lower())

print("== E9. submit_entry refusal branches (composition contract) ==")
fx2 = FixtureBroker(tempfile.mkdtemp(prefix="refuser_fx2_"),
                    SUBMISSION_ACCOUNT)
make_fixtures.write_fixture_broker(fx2.dir, SUBMISSION_ACCOUNT)
trail2 = AuditTrail(fx2, DecisionLog(os.path.join(
    tempfile.mkdtemp(prefix="refuser_log2_"), "decisions.jsonl")))
ev_refuse = dict(ev, decision="REFUSE")                    # gates said no
t2 = trail2.submit_entry(ev_refuse, mark, mid, "S", "S")
check("gates_refusal_logged", B(t2)["decision"] == "REFUSE"
      and "gates said REFUSE" in B(t2)["reason"])
check("no_order_on_refusal", len(fx2.placed_orders) == 0)
ev_thin = dict(ev)                                          # ordermech: thin
ev_thin = {**ev, "contracts": 0}
t3 = trail2.submit_entry(ev_thin, mark, mid, "S", "S")
check("zero_contracts_refusal", B(t3)["decision"] == "REFUSE")
check("still_no_orders", len(fx2.placed_orders) == 0)

print(f"\nRESULT: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
