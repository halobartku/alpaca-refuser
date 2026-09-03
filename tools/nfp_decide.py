#!/usr/bin/env python3
"""PLAYBOOK §4 — NFP Friday straddle gate, executed at Thursday close.

Decision point is Thursday 09-03 close (PLAYBOOK §4): buy the 1-DTE ATM SPY
straddle ONLY if Thu-close straddle mid <= 0.9 x median realized
Thu-close->10:55 move (0.875% of spot, nfp_raw.json n=13), size <= 2% of
equity. Everything else is REFUSE — this gate is designed to refuse most
weeks.

Modes:
  --live            Read live inputs (IEX spot + option snapshots), append
                    the verdict to the hash-chained journal, and — only if
                    tools/NFP_ARMED exists and every interlock holds —
                    place the <=2% mleg debit buy before the 20:00Z close.
  --fixture A B     Offline arithmetic check with spot=A, straddle_mid=B.
                    No journal write, no network, no orders.

Interlocks before any order (ALL must hold, else fail-closed REFUSE):
  1. tools/NFP_ARMED exists (operator opt-in, created explicitly).
  2. broker.get_account().account_number matches PA3Y…YVDZ (partial id —
     the git tree carries no full account id, commit 6ffd642).
  3. straddle_gate() verdict == ACCEPT.
  4. contracts >= 1 at the 2% cap (else the trade is too small to exist).
  5. Wall-clock inside Thursday 19:30-19:59 UTC (never fire late/early).
"""
import json
import math
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from refuser.live import AlpacaBroker
from refuser.log import DecisionLog
from refuser.nfp_gate import straddle_gate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOURNAL = os.path.join(ROOT, "live-decisions.jsonl")
ARM_FILE = os.path.join(ROOT, "tools", "NFP_ARMED")
EXPECTED_ACCOUNT_PREFIX = "PA3Y"   # partial id only — no full account id in the git tree
EXPECTED_ACCOUNT_SUFFIX = "YVDZ"
EXPIRY = "2026-09-04"          # the 1-DTE Friday the NFP print lands on
WEEKDAY = 3                     # Thursday
WINDOW = (19 * 60 + 30, 19 * 60 + 59)   # UTC minutes — order window


def _load_env():
    env = {}
    with open(os.path.join(ROOT, "keys", "alpaca.env")) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def _contracts_chain(broker, kind, strike_lo, strike_hi):
    """Active {kind} contracts expiring exactly EXPIRY in the strike band,
    via the same paginated endpoint the carry path uses."""
    out, token = [], None
    while True:
        params = {
            "underlying_symbols": "SPY", "status": "active",
            "type": kind, "style": "american",
            "expiration_date_gte": EXPIRY, "expiration_date_lte": EXPIRY,
            "strike_price_gte": strike_lo, "strike_price_lte": strike_hi,
            "limit": 1000,
        }
        if token:
            params["page_token"] = token
        page = broker._get(f"{broker.TRADING}/v2/options/contracts", params)
        out.extend(page.get("option_contracts", []))
        token = page.get("next_page_token")
        if not token:
            return out


def _mid(snapshot):
    """latestQuote bp/ap mid (indicative feed shape, per liquidate.py)."""
    q = (snapshot or {}).get("latestQuote") or {}
    bp, ap = q.get("bp"), q.get("ap")
    if bp is None or ap is None or bp <= 0 or ap <= 0:
        return None
    return (bp + ap) / 2.0


def _arm_ok():
    return os.path.exists(ARM_FILE)


def _in_window(now):
    if now.weekday() != WEEKDAY:
        return False, f"not Thursday (weekday={now.weekday()})"
    m = now.hour * 60 + now.minute
    if not (WINDOW[0] <= m <= WINDOW[1]):
        return False, f"{m} min outside order window {WINDOW}"
    return True, "inside Thursday 19:30-19:59Z window"


def decide(spot, straddle_mid, equity):
    verdict = straddle_gate(spot, straddle_mid)
    cap = verdict.get("size_cap_frac", 0.02) * equity
    contracts = int(math.floor(cap / (straddle_mid * 100))) if straddle_mid else 0
    verdict["inputs"] = {"spot": spot, "straddle_mid": straddle_mid,
                         "equity": equity, "expiry": EXPIRY}
    verdict["contracts_at_2pct_cap"] = contracts
    verdict["cutoff_price"] = round(verdict["gate_frac"] * spot, 2) if spot else None
    return verdict


def main(argv):
    if "--fixture" in argv:
        i = argv.index("--fixture")
        v = decide(float(argv[i + 1]), float(argv[i + 2]), 100000.0)
        print(json.dumps(v, indent=2))
        return 0

    now = datetime.now(timezone.utc)
    log = DecisionLog(JOURNAL)
    env = _load_env()
    broker = AlpacaBroker(env["APCA_API_KEY_ID"],
                          env["APCA_API_SECRET_KEY"])

    def journal(body):
        body["event"] = "nfp_gate"
        body["utc"] = now.isoformat()
        return log.append(body)

    # -- live inputs -----------------------------------------------------
    try:
        acct = broker.get_account()
        num = acct["account_number"]
        assert num.startswith(EXPECTED_ACCOUNT_PREFIX) and \
            num.endswith(EXPECTED_ACCOUNT_SUFFIX), f"unexpected account {num[:4]}…{num[-4:]}"
        spot = broker.get_underlying_quote("SPY")["last"]
        band = 1.0
        puts = _contracts_chain(broker, "put", spot - band, spot + band)
        calls = _contracts_chain(broker, "call", spot - band, spot + band)

        def nearest(contracts):
            return min(contracts, key=lambda c: abs(float(c["strike_price"]) - spot))["symbol"] \
                if contracts else None

        put_sym, call_sym = nearest(puts), nearest(calls)
        if not (put_sym and call_sym):
            raise RuntimeError(f"no ATM contracts near {spot}: put={put_sym} call={call_sym}")
        snap = broker.get_option_snapshot([put_sym, call_sym])
        put_mid, call_mid = _mid(snap.get(put_sym)), _mid(snap.get(call_sym))
        if not (put_mid and call_mid):
            raise RuntimeError(f"no usable mids: put={put_mid} call={call_mid}")
        straddle_mid = round(put_mid + call_mid, 2)
    except Exception as e:
        rec = journal({"decision": "REFUSE",
                       "reason": f"live inputs failed: {type(e).__name__}: {e}",
                       "armed": _arm_ok()})
        print(json.dumps(rec["body"], indent=2))
        print(f"REFUSED (fail-closed) — seq {rec['seq']}")
        return 0

    verdict = decide(spot, straddle_mid, acct["equity"])
    verdict["armed"] = _arm_ok()
    verdict["legs"] = {"put": put_sym, "call": call_sym,
                       "put_mid": put_mid, "call_mid": call_mid}

    # -- order path: only if armed, ACCEPT, in window, size sane ----------
    if verdict["decision"] == "ACCEPT":
        ok, why = _in_window(now)
        if not (_arm_ok() and ok and verdict["contracts_at_2pct_cap"] >= 1):
            verdict["order"] = f"NOT PLACED — armed={_arm_ok()}, window={why}, contracts={verdict['contracts_at_2pct_cap']}"
        else:
            limit = round(min(straddle_mid + 0.05, verdict["cutoff_price"]), 2)
            payload = {
                "type": "limit", "time_in_force": "day", "order_class": "mleg",
                "qty": str(verdict["contracts_at_2pct_cap"]),
                "limit_price": f"{limit:.2f}",
                "legs": [
                    {"symbol": put_sym, "ratio_qty": "1", "side": "buy",
                     "position_intent": "buy_to_open"},
                    {"symbol": call_sym, "ratio_qty": "1", "side": "buy",
                     "position_intent": "buy_to_open"},
                ],
            }
            import requests
            r = requests.post(f"{broker.TRADING}/v2/orders",
                              headers=broker._h(), data=json.dumps(payload),
                              timeout=broker.TIMEOUT)
            verdict["order"] = (f"HTTP {r.status_code} id={r.json().get('id')} "
                                f"qty={payload['qty']} limit={payload['limit_price']} "
                                f"(day order: unfilled remainder dies at the close)")
    rec = journal(verdict)
    summary = {"seq": rec["seq"], "head": log.head,
               "decision": verdict["decision"],
               "spot": spot, "straddle_mid": straddle_mid,
               "cutoff": verdict["cutoff_price"],
               "reason": verdict.get("reason"),
               "order": verdict.get("order", "n/a (REFUSE path)")}
    out = os.path.join(ROOT, "build", "nfp-decision.json")
    with open(out, "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
