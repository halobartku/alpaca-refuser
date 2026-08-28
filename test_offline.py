"""Offline correctness gate for the refuser package. Run: python3 test_offline.py

Standing rule (correctness_gate): before any claim, define ONE query whose
correct answer is knowable INDEPENDENTLY of the implementation, run it,
compare. Here that is:
  1. Hull's canonical textbook example (S=42,K=40,r=10%,sig=20%,T=0.5):
     call=4.76, put=0.81, N(d1)=0.7791, N(d2)=0.7340.
  2. Put-call parity C - P = S - K*exp(-rT) — an identity that must hold for
     ANY correct B-S implementation across a grid of inputs.
  3. Gate arithmetic: breakeven win rate at 0.5x/3x = 6/7 = 85.714%.
  4. Chaos test: out-of-bounds intents MUST be refused, right gate fires.
  5. Chain tamper: flipping one log byte MUST raise on reload.
  6. Reconciliation: broker state overrides our memory; divergence logged.
"""
import math
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from refuser import bs, gates
from refuser.log import DecisionLog
from refuser import reconcile as recon
from refuser import universe as U

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name} {detail}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


print("== 1. Black-Scholes vs Hull canonical example ==")
c, d, g, th, vg = bs.bs_greeks(42.0, 40.0, 0.5, 0.10, 0.20, "C")
p, pd_, _, _, _ = bs.bs_greeks(42.0, 40.0, 0.5, 0.10, 0.20, "P")
check("hull_call", abs(c - 4.76) < 0.015, f"got {c:.4f} want 4.76")
check("hull_put", abs(p - 0.81) < 0.015, f"got {p:.4f} want 0.81")
check("hull_delta", abs(d - 0.7791) < 0.0015, f"got {d:.4f} want ~0.7791")

print("== 2. Put-call parity across grid (identity, independent) ==")
worst = 0.0
for S in (30, 42, 55, 101.5):
    for K in (25, 40, 60, 100):
        for T in (0.05, 0.25, 0.75):
            for sig in (0.10, 0.23, 0.60):
                cc, *_ = bs.bs_greeks(S, K, T, 0.045, sig, "C")
                pp, *_ = bs.bs_greeks(S, K, T, 0.045, sig, "P")
                parity = S - K * math.exp(-0.045 * T)
                worst = max(worst, abs((cc - pp) - parity))
check("parity_max_err", worst < 1e-9, f"max |C-P-(S-Ke^-rT)| = {worst:.2e}")

print("== 3. Monotonicity / sign properties ==")
c_lo, *_ = bs.bs_greeks(100, 100, 0.3, 0.04, 0.10, "C")
c_hi, *_ = bs.bs_greeks(100, 100, 0.3, 0.04, 0.60, "C")
check("vega_positive", c_hi > c_lo, f"{c_hi:.2f} > {c_lo:.2f}")
p_up, *_ = bs.bs_greeks(110, 100, 0.3, 0.04, 0.25, "P")
p_dn, *_ = bs.bs_greeks(90, 100, 0.3, 0.04, 0.25, "P")
check("put_decreases_in_S", p_dn > p_up, f"{p_dn:.2f} > {p_up:.2f}")
_, dC, gC, _, _ = bs.bs_greeks(100, 100, 0.3, 0.04, 0.25, "C")
_, dP, _, _, _ = bs.bs_greeks(100, 100, 0.3, 0.04, 0.25, "P")
check("gamma_positive", gC > 0)
# differentiating put-call parity C-P = S-Ke^-rT wrt S gives dC-dP = 1 (no divs)
check("put_delta_identity", abs((dC - dP) - 1.0) < 1e-12,
      f"C-P delta = {dC - dP:.6f} = 1")

print("== 4. Breakeven arithmetic (the discipline thesis) ==")
# win +0.5c with prob w, loss -3c with prob (1-w): EV=0 -> w = 3/3.5 = 6/7
be = 3.0 / 3.5
check("breakeven_6_of_7", abs(be - 6.0 / 7.0) < 1e-12 and abs(be - 0.8571428) < 1e-6,
      f"breakeven={be:.4f}")

print("== 5. Sizing ==")
# 0.75% of 100k = $750; risk/ct = (5-1)*100 = $400; floor(750/400) = 1
check("size_1ct_5wide", bs.size_contracts(100000, 0.0075, 5.0, 1.0) == 1)
check("size_floor", bs.size_contracts(100000, 0.0075, 5.0, 1.0) == 1)
check("size_refuses_bad", bs.size_contracts(100000, 0.0075, 1.0, 1.0) == 0)

print("== 6. Gate layer: clean intent ACCEPTS ==")
intent = {
    "name": "SPY", "expiry": date(2026, 9, 25), "k_short": 640.0,
    "k_long": 635.0, "width": 5.0, "credit": 1.10,
    "ask_short": 1.30, "bid_short": 1.10, "ask_long": 0.30, "bid_long": 0.18,
    "oi_short": 8000, "oi_long": 5000, "short_delta": -0.20,
}
state = {
    "equity": 100000.0, "open_positions": 2, "positions_by_name": {"KO"},
    "risk_at_open": 0.015, "daily_stop_hit": False, "net_delta": -8.0,
    "now": datetime(2026, 8, 31, 14, 30), "today": date(2026, 8, 31),
}
market = {"underlying_last": 645.0, "atm_iv": 0.22,
          "spy_atm_iv": 0.20, "spy_iv_5d_avg": 0.19}
dec = gates.evaluate_intent(intent, state, market)
check("clean_accept", dec["decision"] == "ACCEPT",
      str([r for r in dec["gates"] if not r["pass"]]))
check("sizing_positive", dec["contracts"] >= 1, f"contracts={dec['contracts']}")

print("== 7. Chaos tests: each violation MUST refuse with right gate ==")
bad = dict(intent)
bad["short_delta"] = -0.45  # too much delta
d1_ = gates.evaluate_intent(bad, state, market)
fired = {r["gate"]: r["pass"] for r in d1_["gates"]}
check("chaos_delta_refused", d1_["decision"] == "REFUSE" and not fired["short_delta"])

bad = dict(intent); bad["credit"] = 0.55  # below floor AND <20% width
d2_ = gates.evaluate_intent(bad, state, market)
fired = {r["gate"]: r["pass"] for r in d2_["gates"]}
check("chaos_credit_refused", d2_["decision"] == "REFUSE" and not fired["width_credit"])

st = dict(state); st["open_positions"] = 6
d3_ = gates.evaluate_intent(intent, st, market)
fired = {r["gate"]: r["pass"] for r in d3_["gates"]}
check("chaos_slots_refused", d3_["decision"] == "REFUSE" and not fired["portfolio"])

st = dict(state); st["daily_stop_hit"] = True
d4_ = gates.evaluate_intent(intent, st, market)
fired = {r["gate"]: r["pass"] for r in d4_["gates"]}
check("chaos_dailystop_refused", d4_["decision"] == "REFUSE" and not fired["portfolio"])

bad = dict(intent); bad["name"] = "GME"
d5_ = gates.evaluate_intent(bad, state, market)
fired = {r["gate"]: r["pass"] for r in d5_["gates"]}
check("chaos_universe_refused", d5_["decision"] == "REFUSE" and not fired["calendar"])

# Friday entry attempt (outside Mon/Wed window)
st = dict(state); st["now"] = datetime(2026, 9, 4, 11, 0); st["today"] = date(2026, 9, 4)
d6_ = gates.evaluate_intent(intent, st, market)
fired = {r["gate"]: r["pass"] for r in d6_["gates"]}
check("chaos_window_refused", d6_["decision"] == "REFUSE" and not fired["calendar"])

# NFP blackout: Wed Sep 3 after 15:55
st = dict(state); st["now"] = datetime(2026, 9, 3, 16, 30); st["today"] = date(2026, 9, 3)
d7_ = gates.evaluate_intent(intent, st, market)
fired = {r["gate"]: r["pass"] for r in d7_["gates"]}
check("chaos_nfp_refused", d7_["decision"] == "REFUSE" and not fired["calendar"])

# IV regime gate
mk = dict(market); mk["spy_atm_iv"] = 0.17; mk["spy_iv_5d_avg"] = 0.19
d8_ = gates.evaluate_intent(intent, state, mk)
fired = {r["gate"]: r["pass"] for r in d8_["gates"]}
check("chaos_iv_refused", d8_["decision"] == "REFUSE" and not fired["iv"])

print("== 8. Hash-chained log + tamper evidence ==")
logp = "/tmp/refuser-test-log.jsonl"
if os.path.exists(logp):
    os.remove(logp)
lg = DecisionLog(logp)
lg.append({"decision": "REFUSE", "why": "test"})
lg.append({"decision": "ACCEPT", "why": "test2"})
check("chain_grows", lg.count == 2 and len(lg.head) == 64)
lg2 = DecisionLog(logp)  # reload+verify
check("chain_reloads", lg2.count == 2 and lg2.head == lg.head)
# tamper: flip one char in the middle of line 2
with open(logp) as f:
    lines = f.read().splitlines()
lines[1] = lines[1].replace("test2", "testX")
with open(logp, "w") as f:
    f.write("\n".join(lines) + "\n")
try:
    DecisionLog(logp)
    check("tamper_detected", False, "no exception raised")
except RuntimeError as e:
    check("tamper_detected", True, str(e)[:40])

print("== 9. Reconciliation: broker overrides memory ==")
logp2 = "/tmp/refuser-test-log2.jsonl"
if os.path.exists(logp2):
    os.remove(logp2)
lg3 = DecisionLog(logp2)
lg3.append({"decision": "ACCEPT", "ticket": {"symbols": ["SPY260918P00640000"]}})
broker = [{
    "symbol": "QQQ260918P00480000", "qty": -1, "underlying": "QQQ",
    "risk_at_open": 390.0, "delta": -0.19,
}]
st9, divs = recon.reconcile(broker, [], lg3)
check("recon_positions", st9["open_positions"] == 1 and st9["positions_by_name"] == {"QQQ"})
check("recon_risk", abs(st9["risk_at_open"] - 390.0) < 1e-9)
check("recon_divergence_logged",
      len(divs) == 1 and divs[0]["kind"] == "accept-without-position",
      str(divs))

print("== 10. Universe fail-closed on unknown earnings ==")
U.UNIVERSE["PFE"] = date(2026, 9, 15)  # simulate a discovered date
check("earnings_flagged", U.earnings_within("PFE", 35, date(2026, 8, 31)) is True)
U.UNIVERSE["PFE"] = None
check("earnings_clean", U.earnings_within("PFE", 35, date(2026, 8, 31)) is False)
U.UNIVERSE.pop("TSLA", None)
check("unknown_fails_closed", U.earnings_within("TSLA", 35, date(2026, 8, 31)) is None)

print("== 11. Exit engine: spec order, first-hit-fires (independent oracle) ==")
# Oracle: research brief §2 fixes the rule PRIORITY, so when two rules fire at
# once the one lower in the list must NEVER be the one reported.
from refuser import exits as X

check("breakeven_identity", abs(X.implied_breakeven_win_rate() - 6 / 7) < 1e-12,
      f"{X.implied_breakeven_win_rate():.4f} == 6/7=85.714%")
check("gtc_target_exact_half", X.gtc_target_price(1.50) == 0.75,
      f"50% of 1.50 -> {X.gtc_target_price(1.50)}")
# Boundary 1.23 -> exact half is 0.615 (not a penny tick). For a BUY limit,
# rounding DOWN is the conservative direction (never pay above the true 50%).
_t = X.gtc_target_price(1.23)
check("gtc_target_never_above_half", 0.61 <= _t <= 0.615 + 1e-9,
      f"1.23 -> {_t} (<= 0.615, conservative buy limit)")

# Wednesday 2026-08-26 12:00 ET: mid-week, no blackout, no flatten.
# (Sep 2 was WRONG here: Sep 18 expiry from Sep 2 = 16 DTE, and the time_exit
# correctly shadowed everything. From Aug 26 the same expiry = 23 DTE.)
NOW_WED = datetime(2026, 8, 26, 12, 0)
base_pos = {
    "name": "SPY", "expiry": date(2026, 9, 18), "k_short": 640.0,
    "k_long": 635.0, "width": 5.0, "entry_credit": 1.50, "contracts": 2,
    "short_delta": -0.20, "spread_mark": 1.10,
}
# For rules 5/6 isolation: an expiry far enough out that time_exit (21 DTE)
# cannot shadow them on Fri Sep 4 / Thu Sep 3 (42 DTE from Sep 4).
FAR_POS = dict(base_pos, expiry=date(2026, 10, 16))


def probe(**over):
    p = dict(base_pos)
    p.update(over)
    return X.check_position(p, {}, NOW_WED)


r = probe()  # 28 DTE, mark 1.10 vs tgt 0.75, delta .20 -> HOLD
check("healthy_hold", r is None, str(r))
r = probe(spread_mark=0.75)
check("rule1_profit_target", r and r["rule"] == "profit_target"
      and r["action"] == "BUY_TO_CLOSE", str(r))
# BOTH rule1 (mark 0.74 <= 0.75) and rule4?? no rule4; co-fire with delta:
r = probe(spread_mark=0.74, short_delta=-0.55)
check("rule1_beats_rule2", r and r["rule"] == "profit_target", str(r))
r = probe(spread_mark=1.60, short_delta=-0.44)
check("rule2_delta_stop", r and r["rule"] == "delta_stop", str(r))
r = probe(expiry=date(2026, 9, 18 - 7))  # 14 DTE
check("rule3_time_exit", r and r["rule"] == "time_exit", str(r))
# BOTH delta_stop and time_exit fire -> delta_stop wins (higher priority)
r = probe(expiry=date(2026, 9, 11), short_delta=-0.44)
check("rule2_beats_rule3", r and r["rule"] == "delta_stop", str(r))
r = probe(spread_mark=4.60)  # 4.60 >= 3.0 * 1.50
check("rule4_loss_stop", r and r["rule"] == "loss_stop", str(r))
# loss_stop co-fires with time_exit -> time_exit (3) outranks loss_stop (4)
r = probe(expiry=date(2026, 9, 11), spread_mark=4.60)
check("rule3_beats_rule4", r and r["rule"] == "time_exit", str(r))

FRI_1655 = datetime(2026, 9, 4, 16, 55)  # Friday after 15:55...
# NB 09-04 16:55 is NOT in the NFP blackout (ended 12:00) -> pure weekend probe.
r = X.check_position(dict(FAR_POS), {}, FRI_1655)
check("rule5_weekend_flatten", r and r["rule"] == "weekend_flatten", str(r))
# Thu 09-03 16:00 ET is inside the NFP blackout -> event_flatten fires
r = X.check_position(dict(FAR_POS), {}, datetime(2026, 9, 3, 16, 0))
check("rule6_event_flatten", r and r["rule"] == "event_flatten", str(r))
# weekend_flatten co-fires with event_flatten? Fri 09-04 16:00: blackout ended
# 12:00, Friday >=15:55 -> weekend wins (5 before 6).
r = X.check_position(dict(FAR_POS), {}, datetime(2026, 9, 4, 16, 0))
check("rule5_beats_rule6", r and r["rule"] == "weekend_flatten", str(r))
# Edge: exactly 15:55 -> fires (>=).
r = X.check_position(dict(FAR_POS), {}, datetime(2026, 9, 4, 15, 55))
check("rule5_boundary_inclusive", r and r["rule"] == "weekend_flatten", str(r))
# Friday 15:54 -> no flatten, and no other rule fires -> hold
r = X.check_position(dict(FAR_POS), {}, datetime(2026, 9, 4, 15, 54))
check("rule5_boundary_excl_hold", r is None, str(r))

print("== 12. Exit engine: GTC placed at fill (position plan) ==")
intent_res = {"intent": {"name": "QQQ", "expiry": "2026-09-25", "k_short": 480.0,
                         "k_long": 475.0, "width": "5.0", "credit": "1.40"}}
plan = X.open_position_plan(intent_res, 3)
check("plan_gtc_at_fill", plan["gtc_exit"]["placed_at"] == "fill"
      and plan["gtc_exit"]["type"] == "BUY_TO_CLOSE_GTC")
check("plan_gtc_limit", plan["gtc_exit"]["limit"] == 0.70,
      f"50% of 1.40 -> {plan['gtc_exit']['limit']}")
check("plan_contracts", plan["contracts"] == 3)

print("== 13. Exit engine: no rolling, refusal budget untouched ==")
# Rolling = NONE in week 1: the engine exposes no roll()/adjust() surface.
check("no_roll_api", not hasattr(X, "roll") and not hasattr(X, "adjust"),
      "module surface has no roll/adjust")
# Chaos: a corrupt position dict must raise, not silently hold.
try:
    X.check_position({"name": "XX"}, {}, NOW_WED)
    check("chaos_missing_keys_raises", False, "no exception")
except (KeyError, TypeError):
    check("chaos_missing_keys_raises", True, "raised on missing keys")

print()


print("== 16. Design gap 1: correlation (group + net-delta caps) ==")
from refuser import portfolio as pf
from refuser import ordermech as om

# group cap: holding SPY+QQQ, a third index-beta entry IWM must be refused
st3 = dict(state); st3["positions_by_name"] = {"SPY", "QQQ"}
ok, why = pf.gate_group(st3, "IWM")
check("group_cap_third_index_refused", not ok, why)
ok2, why2 = pf.gate_group(st3, "AAPL")
check("group_cap_fourth_name_ok", ok2, why2)

# group cap fires inside the full intent pipeline (regression: gate_portfolio calls it)
d_ = gates.evaluate_intent(dict(intent, name="IWM"), st3, market)
g = [x for x in d_["gates"] if x["gate"] == "portfolio"]
check("group_cap_in_pipeline", bool(g) and not g[0]["pass"] and "correlation" in g[0]["detail"],
      g[0]["detail"] if g else "no portfolio gate")

# unknown name must raise, never silently pass
try:
    pf.group_of("GME")
    check("group_of_unknown_raises", False, "no raise")
except ValueError:
    check("group_of_unknown_raises", True)

# net delta from a FLAT book: 3ct x 0.10 x 100 = +30 = exactly at cap -> pass
st4 = dict(state); st4["net_delta"] = 0.0
ok, why = pf.gate_net_delta(st4, 0.10, 3)
check("net_delta_at_cap_passes", ok, why)
ok, why = pf.gate_net_delta(st4, 0.10, 4)
check("net_delta_over_cap_refused", not ok, why)
# pre-loaded book +25, adding 1ct of +10 crosses: 35 > 30
st5 = dict(state); st5["net_delta"] = 25.0
ok, why = pf.gate_net_delta(st5, 0.10, 1)
check("net_delta_book_cross_refused", not ok, why)
# INDEPENDENT ORACLE: shares-equivalent arithmetic by hand: 25 + 0.10*1*100 = 35
check("net_delta_arithmetic", abs(pf.projected_net_delta(st5, 0.10, 1) - 35.0) < 1e-9)

# A.115: the net-delta cap SCALES with equity — 30 shares at $100k, 300 at
# $1M, same fraction of the book. Anchor division is float-exact at both
# (30.0 / 300.0), which the boundary tests above depend on.
check("net_delta_cap_anchor_100k", pf.net_delta_cap(100_000.0) == 30.0,
      f"{pf.net_delta_cap(100_000.0)!r}")
check("net_delta_cap_scales_1m", pf.net_delta_cap(1_000_000.0) == 300.0,
      f"{pf.net_delta_cap(1_000_000.0)!r}")
check("net_delta_cap_fraction_identical",
      abs(pf.net_delta_cap(1_000_000.0) / 1_000_000.0
          - pf.net_delta_cap(100_000.0) / 100_000.0) < 1e-15)
check("net_delta_cap_failclosed", pf.net_delta_cap(0.0) == 0.0
      and pf.net_delta_cap(-5_000.0) == 0.0)
# same signal, $1M book: 30ct x 0.10 x 100 = +300 = exactly at the scaled cap
st6 = dict(state); st6["equity"] = 1_000_000.0; st6["net_delta"] = 0.0
ok, why = pf.gate_net_delta(st6, 0.10, 30)
check("net_delta_1m_at_scaled_cap_passes", ok, why)
ok, why = pf.gate_net_delta(st6, 0.10, 31)
check("net_delta_1m_over_scaled_cap_refused", not ok, why)
# the SAME trade that passed at $1M is refused at $100k (cap 30, not 300)
st7 = dict(state); st7["equity"] = 100_000.0; st7["net_delta"] = 0.0
ok, why = pf.gate_net_delta(st7, 0.10, 30)
check("net_delta_100k_tightness_preserved", not ok, why)

print("== 17. Design gap 2: selection (deterministic composite) ==")
cands = [
    {"name": "SPY", "atm_iv": 0.22, "rel_spread": 0.10, "earnings_clear_days": 99},
    {"name": "QQQ", "atm_iv": 0.21, "rel_spread": 0.09, "earnings_clear_days": 99},
    {"name": "AAPL", "atm_iv": 0.28, "rel_spread": 0.20, "earnings_clear_days": 40},
    {"name": "XOM", "atm_iv": 0.30, "rel_spread": 0.35, "earnings_clear_days": 60},
    {"name": "KO", "atm_iv": 0.16, "rel_spread": 0.08, "earnings_clear_days": 50},
]
# HAND-COMPUTED ORACLE (min-max normalized, W=.5/.3/.2, all clear-days cap at 21
# so clearance term is constant 1.0 for everyone):
#   iv_n:   KO 0, QQQ .3571, SPY .4286, AAPL .8571, XOM 1.0
#   liq_n:  XOM 0, AAPL .5556, SPY .9259, QQQ .9630, KO 1.0
#   score:  KO .5 | QQQ .6675 | SPY .6921 | XOM .70 | AAPL .7952
#   => order AAPL, XOM, SPY, QQQ, KO
ranked = pf.score_candidates(cands, state)
names = [n for n, s, r in ranked]
check("selection_returns_all", len(ranked) == 5)
check("selection_deterministic",
      names == [n for n, s, r in pf.score_candidates(cands, state)], str(names))
check("selection_matches_hand_oracle", names == ["AAPL", "XOM", "SPY", "QQQ", "KO"], str(names))
# group penalty: holding SPY drops SPY & QQQ by .25 -> KO (.5) climbs above SPY (.4421)
st6 = dict(state); st6["positions_by_name"] = {"SPY"}
names6 = [n for n, s, r in pf.score_candidates(cands, st6)]
check("selection_group_penalty_reorders",
      names6 == ["AAPL", "XOM", "KO", "SPY", "QQQ"], str(names6))
# select_from respects group caps: SPY+QQQ held, IWM candidates excluded
cands_iwm = cands + [{"name": "IWM", "atm_iv": 0.25, "rel_spread": 0.12, "earnings_clear_days": 99}]
st7 = dict(state); st7["positions_by_name"] = {"SPY", "QQQ"}
picked = pf.select_from(cands_iwm, st7, 3)
check("select_respects_group_cap",
      "IWM" not in [p[0] for p in picked] and len(picked) == 3, str([p[0] for p in picked]))
check("select_empty_ok", pf.select_from([], state, 3) == [])

print("== 18. Design gap 3: order mechanics on stale data ==")
# INDEPENDENT ORACLE (hand arithmetic): mark 1.20, stale 1.26 -> ref 1.20,
# limit = floor((1.20-0.05)*100)/100 = 1.15
ok, lim, why = om.initial_limit(1.20, 1.26)
check("limit_oracle_115", ok and abs(lim - 1.15) < 1e-9, f"got {lim} want 1.15 ({why})")
# stale quote 40% diverged from live mark -> integrity refusal (fail-closed)
ok, lim, why = om.initial_limit(1.20, 1.68)
check("stale_divergence_refused", not ok and lim is None, why)
# boundary vs the $1.00 minimum credit: mark 1.00 -> limit 0.95 above the
# edge floor (0.90) but BELOW the $1.00 minimum credit -> correctly refused,
# consistent with gate_width_credit's credit>=1.00 entry rule
ok, lim, why = om.initial_limit(1.00, 1.00)
check("min_credit_beats_floor_boundary", not ok and "minimum credit" in why, why)
# thin trade: limit 0.94 above floor but below $1.00 minimum credit -> refuse
ok, lim, why = om.initial_limit(0.99, 0.99)
check("min_credit_refuses_thin", not ok, why)
# walk policy: from 1.15 vs floor 1.08 -> exactly 5 walks (1.14..1.10) then cancel
walks, cur, res_w = 0, 1.15, None
for i in range(6):
    res_w = om.walk_limit(cur, 1.20, i)
    if res_w[0] == "walk":
        cur = res_w[1]; walks += 1
check("walk_cancels_at_max", walks == 5 and res_w[0] == "cancel",
      f"{walks} walks then {res_w[0]}: {res_w[2]}")
# walk never crosses edge floor: mark 1.10, cur 1.00 -> 0.99 ok, then cancel
a = om.walk_limit(1.00, 1.10, 0)
b = om.walk_limit(0.99, 1.10, 1)
check("walk_stops_at_floor",
      a[0] == "walk" and abs(a[1] - 0.99) < 1e-9 and b[0] == "cancel", f"{a[2]} | {b[2]}")
# slippage oracle: quoted 1.20, limit 1.15, filled 1.10 -> gave up 0.10, 0.05/leg
sl = om.measure_slippage(1.20, 1.15, 1.10)
check("slippage_oracle", sl["vs_quoted"] == 0.10 and sl["per_leg"] == 0.05, str(sl))
# full plans
plan = om.order_plan(1.20, 1.26, 2)
check("plan_submits_limit",
      plan["decision"] == "SUBMIT" and plan["limit_credit"] == 1.15
      and plan["order_type"] == "limit" and plan["side"] == "sell_to_open",
      str(plan.get("limit_credit")))
plan2 = om.order_plan(1.20, 1.68, 2)
check("plan_refuses_divergent_quote", plan2["decision"] == "REFUSE", plan2["reason"])

print(f"RESULT: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
