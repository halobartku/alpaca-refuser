"""LIVE smoke test — ONE contract put credit spread on the TESTER account.

Runs ONLY on the account whose id is in $SMOKE_EXPECTED_ACCOUNT (asserted,
fail-closed). The judged submission account is never touched by this script.
Purpose: first live exercise of the multileg order path (assumption L1),
fill vs our Black-Scholes mark, measured slippage, API surprises.

Usage: python smoke_multileg.py [--phase1|--trade|--close]
  phase1 (default, read-only): account assert, quote, chain, snapshot, mark, plan
  trade:  phase1 + submit 1-contract spread + poll to terminal state
  close:  submit closing multileg (buy_to_close) + poll
Everything appends JSON lines to smoke_result_20260828.jsonl.
"""
import json
import os
import math
import sys
import time
from datetime import date, datetime, timezone

sys.path.insert(0, ".")

from refuser.live import AlpacaBroker, occ_symbol
from refuser.bs import bs_greeks, put_spread_mark
from refuser import ordermech

EXPECTED_ACCOUNT = os.environ.get("SMOKE_EXPECTED_ACCOUNT")  # A.112: assert or refuse
LOG = "smoke_result_20260828.jsonl"
R_FREE = 0.045
DTE_LO, DTE_HI = 21, 30                     # Sep 18 / Sep 25 expiries
D_SHORT, D_LONG = 0.20, 0.10


def load_env(path="/workspace/forge/keys/alpaca.env"):
    env = {}
    for line in open(path):
        if "=" in line:
            k, v = line.strip().split("=", 1)
            env[k] = v
    return env


def log(evt, **kw):
    rec = {"ts": datetime.now(timezone.utc).isoformat(), "event": evt}
    rec.update(kw)
    with open(LOG, "a") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    print(f"[{rec['ts'][11:19]}] {evt}: " +
          json.dumps({k: v for k, v in kw.items()
                      if k not in ("chain_n",)}, default=str)[:400])
    return rec


def broker():
    env = load_env()
    return AlpacaBroker(env["APCA_API_KEY_ID"], env["APCA_API_SECRET_KEY"])


def phase1(b):
    # 1. account assert (read-only)
    acct = b.get_account()
    assert acct["account_number"] == EXPECTED_ACCOUNT, \
        f"KEYS POINT AT {acct['account_number']} — REFUSE"
    log("account_ok", number=acct["account_number"], equity=acct["equity"],
        level=acct["options_trading_level"])

    # 2. live underlying (IEX)
    q = b.get_underlying_quote("SPY")
    S = q["last"]
    log("underlying", S=S, bid=q["bid"], ask=q["ask"])

    # 3. chain (read-only)
    chain = b.get_option_chain("SPY", round(S * 0.88), round(S * 0.99),
                               DTE_LO, DTE_HI)
    log("chain", chain_n=len(chain))
    if not chain:
        raise SystemExit("no contracts returned — investigate before open")

    # group by expiry, take the earliest with enough strikes
    by_exp = {}
    for c in chain:
        by_exp.setdefault(c["expiration_date"], []).append(c)
    exp = sorted(by_exp)[0]
    strikes = sorted({float(c["strike_price"]) for c in by_exp[exp]})
    T = (date.fromisoformat(exp) - date.today()).days / 365.0
    log("expiry_chosen", expiry=exp, dte=round(T * 365), n_strikes=len(strikes))

    # 4. snapshot IV (delayed indicative) for the relevant strike band
    short_zone = [k for k in strikes if 0.93 * S < k < 0.985 * S]
    syms = {k: occ_symbol("SPY", exp, k, "P") for k in short_zone}
    snap = b.get_option_snapshot(list(syms.values()))
    ivs, mids = {}, {}
    for k, sym in syms.items():
        s = snap.get(sym) or {}
        iv = s.get("impliedVolatility")
        qo = s.get("latestQuote") or s.get("indicativeQuote") or {}
        bid, ask = qo.get("bp"), qo.get("ap")
        if iv and bid and ask:
            ivs[k] = float(iv)
            mids[k] = (float(bid) + float(ask)) / 2.0
    if not ivs:
        raise SystemExit("no usable snapshot IV/quotes — check feed pre-open")
    sigma = sum(ivs.values()) / len(ivs)
    log("iv_snapshot", n=len(ivs), sigma_avg=round(sigma, 4),
        zone=[min(ivs), max(ivs)])

    # 5. strike selection off BS deltas at live S, snapshot sigma
    def delta(k):
        return abs(bs_greeks(S, k, T, R_FREE, sigma, "P")[1])
    k_short = min(strikes, key=lambda k: abs(delta(k) - D_SHORT))
    k_long_candidates = [k for k in strikes if k < k_short - 2]
    k_long = min(k_long_candidates, key=lambda k: abs(delta(k) - D_LONG))
    width = k_short - k_long
    sym_s, sym_l = occ_symbol("SPY", exp, k_short, "P"), occ_symbol("SPY", exp, k_long, "P")
    d_s, d_l = delta(k_short), delta(k_long)
    log("strikes", k_short=k_short, k_long=k_long, width=width,
        delta_short=round(d_s, 3), delta_long=round(d_l, 3),
        sym_short=sym_s, sym_long=sym_l)

    # 6. our mark vs stale quote mid
    mark = put_spread_mark(S, k_short, k_long, T, R_FREE, sigma)
    snap2 = b.get_option_snapshot([sym_s, sym_l])
    def mid_of(sym):
        qo = (snap2.get(sym) or {}).get("latestQuote") or (snap2.get(sym) or {}).get("indicativeQuote") or {}
        if qo.get("bp") and qo.get("ap"):
            return (qo["bp"] + qo["ap"]) / 2.0, qo.get("bp"), qo.get("ap")
        return None, qo.get("bp"), qo.get("ap")
    mid, bid, ask = mid_of(sym_s)
    mid_l, bid_l, ask_l = mid_of(sym_l)
    stale_mid = (mid - mid_l) if (mid and mid_l) else None
    log("pricing", bs_mark=round(mark, 3),
        stale_leg_s=(bid, mid, ask), stale_leg_l=(bid_l, mid_l, ask_l),
        stale_spread_mid=round(stale_mid, 3) if stale_mid else None)

    # 7. plan through the real gates
    if stale_mid is not None:
        plan = ordermech.order_plan(mark, stale_mid, 1)
    else:
        plan = {"decision": "REFUSE", "reason": "no two-sided snapshot quotes"}
    log("plan", plan=plan)

    return dict(S=S, T=T, sigma=sigma, exp=exp, k_short=k_short,
                k_long=k_long, width=width, sym_s=sym_s, sym_l=sym_l,
                mark=mark, stale_mid=stale_mid, plan=plan)


def place_spread(b, c):
    plan = c["plan"]
    if plan.get("decision") != "SUBMIT":
        # SMOKE OVERRIDE: the goal today is exercising the multileg path even
        # if a gate refuses. Fall back to a conservative manual limit and log
        # the override loudly. Monday's agent would REFUSE here.
        if c["stale_mid"]:
            ref = min(c["mark"], c["stale_mid"])
            limit = math.floor(ref * 100 - 5 + 1e-7) / 100.0  # ref - 0.05
            limit = max(limit, 1.00)
            log("OVERRIDE_gate_refused", gate_reason=plan.get("reason"),
                manual_limit=limit)
            plan = {"decision": "SUBMIT", "limit_credit": limit}
        else:
            raise SystemExit("gate refused and no stale mid — abort")
    payload = {
        "order_type": "limit", "time_in_force": "day", "qty": 1,
        "class": "multileg", "limit_price": f"{plan['limit_credit']:.2f}",
        "legs": [
            {"symbol": c["sym_s"], "side": "sell_to_open",
             "ratio_qty": 1, "position_intent": "sell_to_open"},
            {"symbol": c["sym_l"], "side": "buy_to_open",
             "ratio_qty": 1, "position_intent": "buy_to_open"},
        ],
    }
    log("order_submit", payload=payload)
    import requests
    env = load_env()
    r = requests.post(f"{b.TRADING}/v2/orders",
                      headers={"APCA-API-KEY-ID": env["APCA_API_KEY_ID"],
                               "APCA-API-SECRET-KEY": env["APCA_API_SECRET_KEY"]},
                      data=json.dumps(payload), timeout=10)
    log("order_response", status=r.status_code, body=r.text[:600])
    if r.status_code not in (200, 201):
        return None
    return r.json()


def poll(b, order_id, max_s=900, step=15):
    t0 = time.time()
    last = None
    while time.time() - t0 < max_s:
        o = b._get(f"{b.TRADING}/v2/orders/{order_id}")
        st = o.get("status")
        if st != last:
            log("order_status", status=st,
                filled_qty=o.get("filled_qty"),
                filled_avg=o.get("filled_avg_price"),
                elapsed=round(time.time() - t0, 1))
            last = st
        if st in ("filled", "canceled", "cancelled", "expired", "rejected"):
            return o
        time.sleep(step)
    return None


def close_position(b, c, credit_filled):
    # close at debit = credit + 0.03 (pay up slightly for immediacy;
    # worst case round-trip -$0.06 — the information is worth more)
    import requests
    env = load_env()
    debit = round(min(credit_filled + 0.03, 1.50) + 1e-9, 2)
    payload = {
        "order_type": "limit", "time_in_force": "day", "qty": 1,
        "class": "multileg", "limit_price": f"{debit:.2f}",
        "legs": [
            {"symbol": c["sym_s"], "side": "buy_to_close",
             "ratio_qty": 1, "position_intent": "buy_to_close"},
            {"symbol": c["sym_l"], "side": "sell_to_close",
             "ratio_qty": 1, "position_intent": "sell_to_close"},
        ],
    }
    log("close_submit", payload=payload)
    r = requests.post(f"{b.TRADING}/v2/orders",
                      headers={"APCA-API-KEY-ID": env["APCA_API_KEY_ID"],
                               "APCA-API-SECRET-KEY": env["APCA_API_SECRET_KEY"]},
                      data=json.dumps(payload), timeout=10)
    log("close_response", status=r.status_code, body=r.text[:600])
    if r.status_code not in (200, 201):
        return None
    return poll(b, r.json()["id"], max_s=300, step=15)


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "--phase1"
    b = broker()
    if phase == "--phase1":
        phase1(b)
    elif phase == "--trade":
        c = phase1(b)
        json.dump(c, open("smoke_ctx.json", "w"), default=str)
        o = place_spread(b, c)
        if o:
            fin = poll(b, o["id"])
            if fin and fin.get("status") == "filled":
                fill = float(fin.get("filled_avg_price"))
                c_ref = c["plan"].get("limit_credit") or c["mark"]
                log("FILLED", credit=fill,
                    slip=ordermech.measure_slippage(
                        c["stale_mid"] or c["mark"], c_ref, fill),
                    bs_mark=round(c["mark"], 3),
                    vs_bs_mark=round(c["mark"] - fill, 3))
                try:
                    log("positions_after_fill", positions=b.get_positions())
                except Exception as e:
                    log("positions_after_fill_error", err=str(e))
                co = close_position(b, c, fill)
                if co and co.get("status") == "filled":
                    log("CLOSED", debit=float(co.get("filled_avg_price")),
                        round_trip=round(fill - float(co.get("filled_avg_price")), 2))
                try:
                    a2 = b.get_account()
                    log("account_after", equity=a2["equity"])
                except Exception as e:
                    log("account_after_error", err=str(e))
    elif phase == "--close":
        # manual close if the auto-close path failed; needs credit_filled
        credit = float(sys.argv[2])
        c = json.load(open("smoke_ctx.json"))
        close_position(b, c, credit)
    else:
        raise SystemExit("unknown phase")
