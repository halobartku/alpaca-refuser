#!/usr/bin/env python3
"""demo_cycle.py — one honest scan cycle through the PRODUCTION gate path.

Runs the real AuditTrail + gates against FixtureBroker market data (the same
rehearsal world as fixtures/test_fullweek.py). No network, no faked numbers:
every ACCEPT/REFUSE below is produced by the shipped decision code.

Used to produce the submission video when the judged account is unreachable.
"""
import os
import sys
import tempfile
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "fixtures"))

from refuser import bs                                             # noqa
from refuser.audit import AuditTrail                               # noqa
from refuser.broker import FixtureBroker, SUBMISSION_ACCOUNT       # noqa
from refuser.log import DecisionLog                                # noqa
import make_fixtures                                               # noqa

WED = datetime(2026, 9, 2, 14, 30)   # Wednesday inside the entry window
NFP_EVE = datetime(2026, 9, 3, 16, 30)  # Wednesday AFTER 15:55 ET flatten


def banner(t):
    print("\n" + "=" * 74)
    print(t)
    print("=" * 74)


def main():
    tmp = tempfile.mkdtemp(prefix="refuser_demo_")
    make_fixtures.write_fixture_broker(tmp, SUBMISSION_ACCOUNT)
    broker = FixtureBroker(tmp, SUBMISSION_ACCOUNT)
    trail = AuditTrail(broker, DecisionLog(os.path.join(tmp, "decisions.jsonl")))

    banner("PREFLIGHT — reconcile against the broker first, never memory")
    s = trail.session_open(SUBMISSION_ACCOUNT, role="demo")
    sb = s["body"] if "body" in s else s
    equity = sb["equity"]
    print(f"account={sb['account_number']}  equity={equity:,.2f}  "
          f"status={sb.get('status')}")

    state = {"equity": equity, "open_positions": 0,
             "positions_by_name": set(), "risk_at_open": 0.0,
             "daily_stop_hit": False, "net_delta": 0.0,
             "now": WED, "today": WED.date()}

    S = broker.get_underlying_quote("SPY")["last"]
    T = 23 / 365.0
    mark = bs.put_spread_mark(S, 517.5, 512.5, T, 0.04, 0.40)
    _, d_short, *_ = bs.bs_greeks(S, 517.5, T, 0.04, 0.40, "P")
    _, d_long, *_ = bs.bs_greeks(S, 512.5, T, 0.04, 0.40, "P")

    def snap(sym):
        return broker.get_option_snapshot(sym)

    ss, sl = snap("SPY260925P05175000"), snap("SPY260925P05125000")

    base = {"name": "SPY", "expiry": date(2026, 9, 25),
            "k_short": 517.5, "k_long": 512.5, "width": 5.0, "credit": mark,
            "short_delta": d_short, "spread_delta": d_long - d_short,
            "ask_short": ss["ask"], "bid_short": ss["bid"],
            "ask_long": sl["ask"], "bid_long": sl["bid"],
            "oi_short": 8400, "oi_long": 5100}
    market = {"underlying_last": S, "atm_iv": 0.40,
              "spy_atm_iv": 0.40, "spy_iv_5d_avg": 0.36}

    cands = [
        ("C1", dict(base), dict(market), state,
         "SPY 517.5/512.5 put spread, clean"),
        ("C2", dict(base), dict(market),
         {**state, "positions_by_name": {"SPY"}, "open_positions": 1},
         "same spread while already holding SPY"),
        ("C3", {**base, "ask_short": ss["ask"] + 0.60,
                "bid_short": ss["bid"] - 0.40}, dict(market), state,
         "same spread, quoted spread blows out"),
        ("C4", dict(base), dict(market), {**state, "now": NFP_EVE,
                                          "today": NFP_EVE.date()},
         "same spread, inside the NFP blackout window"),
    ]

    banner("SCAN — 4 candidates, 8 gates each, fail-closed")
    stats = {"evaluated": 0, "accepted": 0, "refused": 0}
    for tag, intent, mkt, st, label in cands:
        stats["evaluated"] += 1
        ev = trail.evaluate_entry(intent, st, mkt)
        dec = ev["decision"]
        stats["accepted" if dec == "ACCEPT" else "refused"] += 1
        n = ev["contracts"] if dec == "ACCEPT" else "-"
        print(f"\n{tag}  {label}")
        print(f"    -> {dec}  (contracts={n})")
        if dec == "REFUSE":
            for g in ev["gates"]:
                if not g["pass"]:
                    print(f"    REFUSED AT: {g['gate']:<12} {g['detail']}")

    banner("RESULT")
    print(f"evaluated={stats['evaluated']}  accepted={stats['accepted']}  "
          f"refused={stats['refused']}")
    print("every refusal above was written to the hash-chained log "
          "with its reason")

    banner("AUDIT — hash chain verify (loads and re-hashes every record)")
    from refuser.log import DecisionLog as DL
    try:
        chain = DL(os.path.join(tmp, "decisions.jsonl"))
        print(f"chain verify: OK  records={chain.count}  "
              f"head={chain.head[:16]}…")
        ok = True
    except RuntimeError as e:
        print(f"chain verify: BROKEN — {e}")
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
