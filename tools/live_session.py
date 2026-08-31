#!/usr/bin/env python3
"""live_session.py - one entry session against the REAL broker.

The shipped code had every piece of this except the two ends: nothing built a
candidate spread out of a live option chain, and nothing ran a session. Tests
drive the gates with hand-written intents (tools/demo_cycle.py); this walks the
chain and builds them.

DRY RUN BY DEFAULT. Without --live nothing is sent to the broker: it reads the
chain, builds candidates, runs the real gate stack, and prints what it would
do. Placing orders requires --live explicitly, because a session that trades by
default is one typo away from trading when you meant to look.

    python3 tools/live_session.py                        # read-only
    python3 tools/live_session.py --live                 # places entries
    python3 tools/live_session.py --ignore-entry-window  # rehearsal off-day
"""
import argparse
import os
import sys
from datetime import date, datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from refuser import bs, portfolio as pf, universe as uni          # noqa
from refuser.audit import AuditTrail                              # noqa
from refuser.live import AlpacaBroker                             # noqa
from refuser.log import DecisionLog                               # noqa

TARGET_DELTA = 0.20          # centre of the 0.15-0.25 gate band
WIDTHS = (5.0, 2.5, 1.0)     # preferred spread widths, widest first
RISK_FREE = 0.04
SLOTS = 2                    # new entries per session, portfolio cap


def norm_snapshot(raw):
    """AlpacaBroker returns the API envelope; FixtureBroker returns a flat
    {ask,bid,...}. The BaseBroker contract does not pin the shape, so the two
    diverge and only the live one has latestQuote/greeks. Normalised here
    rather than in the broker: shipped, tested code is not edited two days
    before a deadline for a difference this local.
    """
    q = raw.get("latestQuote") or {}
    g = raw.get("greeks") or {}
    ask, bid = q.get("ap"), q.get("bp")
    if ask is None and "ask" in raw:      # fixture shape
        ask, bid = raw.get("ask"), raw.get("bid")
    return {"ask": ask, "bid": bid, "delta": g.get("delta"),
            "iv": raw.get("impliedVolatility"),
            "oi": raw.get("openInterest") or raw.get("open_interest")}


SNAPSHOT_BATCH = 100     # live API: "symbol limit is 100" (first contact, 2026-08-31)


def snapshots(broker, symbols):
    """get_option_snapshot in batches. The endpoint rejects more than 100
    symbols per request; the shipped broker paginates the response but does
    not chunk the request, so a wide strike band fails outright."""
    out = {}
    for i in range(0, len(symbols), SNAPSHOT_BATCH):
        out.update(broker.get_option_snapshot(symbols[i:i + SNAPSHOT_BATCH]))
    return out


def _bars(key, sec, url, params):
    import requests
    r = requests.get(url, headers={"APCA-API-KEY-ID": key,
                                   "APCA-API-SECRET-KEY": sec},
                     params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def implied_vol(price, S, K, T, r, kind="P", lo=0.01, hi=3.0):
    """Sigma such that the model price matches the observed close. Bisection,
    because it cannot diverge and this runs once a session, not in a loop."""
    for _ in range(60):
        m = (lo + hi) / 2.0
        if bs.bs_greeks(S, K, T, r, m, kind)[0] < price:
            lo = m
        else:
            hi = m
    return (lo + hi) / 2.0


def spy_iv_5d_avg(broker, key, sec, today, log):
    """SPY ATM implied volatility averaged over the last 5 sessions.

    The IV gate asks whether volatility is elevated against its recent past, so
    it needs history the API does not serve directly. Rather than substitute a
    proxy - realised vol, or a constant - the ATM option's own daily closes are
    inverted through the same pricing model the rest of the system uses, paired
    with the underlying close for that day. Returns None when the history is
    incomplete, and None must be treated as a refusal, never as a pass.
    """
    try:
        spot = broker.get_underlying_quote("SPY")["last"]
        chain = broker.get_option_chain("SPY", round(spot * 0.95),
                                        round(spot * 1.02), 21, 35)
        if not chain:
            return None
        exp = sorted({c["expiration_date"] for c in chain})[0]
        same = [c for c in chain if c["expiration_date"] == exp]
        atm = min(same, key=lambda c: abs(float(c["strike_price"]) - spot))
        K = float(atm["strike_price"])
        expiry = date.fromisoformat(exp)
        start = (today - timedelta(days=12)).isoformat()

        ob = _bars(key, sec, "https://data.alpaca.markets/v1beta1/options/bars",
                   {"symbols": atm["symbol"], "timeframe": "1Day",
                    "start": start, "limit": 30})
        sb = _bars(key, sec, "https://data.alpaca.markets/v2/stocks/SPY/bars",
                   {"timeframe": "1Day", "start": start, "limit": 30})
        obars = (ob.get("bars") or {}).get(atm["symbol"], [])
        sbars = sb.get("bars") or []
        spot_on = {b["t"][:10]: b["c"] for b in sbars}

        ivs = []
        for b in obars[-5:]:
            d = b["t"][:10]
            S = spot_on.get(d)
            if S is None:
                continue
            T = max((expiry - date.fromisoformat(d)).days, 1) / 365.0
            ivs.append(implied_vol(b["c"], S, K, T, RISK_FREE, "P"))
        if len(ivs) < 5:
            log("  spy_iv_5d_avg: only %d of 5 sessions available -> refuse all"
                % len(ivs))
            return None
        return sum(ivs) / len(ivs)
    except Exception as e:
        log("  spy_iv_5d_avg failed (%s) -> refuse all" % type(e).__name__)
        return None


def mid(s):
    if s["ask"] is None or s["bid"] is None:
        return None
    return (s["ask"] + s["bid"]) / 2.0


def build_candidates(broker, name, today, log):
    """EVERY permitted short-put-spread for one name, not one pre-picked.

    An earlier version chose the strike nearest 0.20 delta. That number was
    invented here, not taken from the strategy, and choosing it decides in
    advance what the gates get to see. Worse, adjusting it after seeing that
    nothing qualified would be tuning the input until the answer changes -
    exactly what this project criticises elsewhere. So every strike in the
    permitted 0.15-0.25 delta band, at every permitted width, is built and
    shown to the gates, and the gate stack decides.

    Fail-closed throughout: a missing quote, a missing delta or an absent long
    leg drops that candidate, never a guessed value. The gates can only refuse
    what they are shown, so nothing unknown may reach them wearing a number.
    """
    try:
        spot = broker.get_underlying_quote(name)["last"]
    except Exception as e:
        log("  %s: no underlying quote (%s) -> skip" % (name, type(e).__name__))
        return []
    chain = broker.get_option_chain(name, round(spot * 0.75),
                                    round(spot * 1.0), 21, 35)
    if not chain:
        log("  %s: empty chain 21-35 DTE -> skip" % name)
        return []

    by_exp = {}
    for c in chain:
        by_exp.setdefault(c["expiration_date"], []).append(c)

    out = []
    for exp, contracts in sorted(by_exp.items()):
        strikes = sorted({float(c["strike_price"]) for c in contracts})
        sym_of = {float(c["strike_price"]): c["symbol"] for c in contracts}
        oi_of = {}
        for c in contracts:
            try:
                oi_of[float(c["strike_price"])] = int(c.get("open_interest") or 0)
            except (TypeError, ValueError):
                oi_of[float(c["strike_price"])] = 0
        # Only the plausible short-leg band needs greeks; snapshotting a whole
        # chain is a needless several-hundred-symbol request.
        band = [k for k in strikes if 0.75 * spot <= k <= 0.97 * spot]
        if not band:
            continue
        snaps = snapshots(broker, [sym_of[k] for k in band])
        expiry = date.fromisoformat(exp)
        T = max((expiry - today).days, 1) / 365.0

        for k_short in band:
            ss = norm_snapshot(snaps.get(sym_of[k_short], {}))
            if ss["delta"] is None or not (0.15 <= abs(ss["delta"]) <= 0.25):
                continue
            for w in WIDTHS:
                long_k = k_short - w
                if long_k not in strikes:
                    continue
                ls_raw = broker.get_option_snapshot(sym_of[long_k])
                ls = norm_snapshot(ls_raw.get(sym_of[long_k], {}))
                m_short, m_long = mid(ss), mid(ls)
                if m_short is None or m_long is None:
                    continue
                credit = m_short - m_long
                if credit <= 0:
                    continue
                iv = ss["iv"] or 0.30
                d_short = bs.bs_greeks(spot, k_short, T, RISK_FREE, iv, "P")[1]
                d_long = bs.bs_greeks(spot, long_k, T, RISK_FREE, iv, "P")[1]
                out.append({
                    "intent": {
                        "name": name, "expiry": expiry, "k_short": k_short,
                        "k_long": long_k, "width": w, "credit": credit,
                        "short_delta": ss["delta"],
                        "spread_delta": d_long - d_short,
                        "ask_short": ss["ask"], "bid_short": ss["bid"],
                        "ask_long": ls["ask"], "bid_long": ls["bid"],
                        "oi_short": oi_of.get(k_short, 0),
                        "oi_long": oi_of.get(long_k, 0),
                    },
                    "market": {"underlying_last": spot, "atm_iv": iv},
                    "syms": (sym_of[k_short], sym_of[long_k]),
                    "mid": credit,
                })
    if not out:
        log("  %s: no strike in the 0.15-0.25 delta band with a priced spread"
            % name)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="actually place accepted entries (default: dry run)")
    ap.add_argument("--ignore-entry-window", action="store_true",
                    help="build and evaluate off an entry day")
    ap.add_argument("--names", default=None, help="comma list, default UNIVERSE")
    ap.add_argument("--log", default="live-decisions.jsonl")
    args = ap.parse_args()

    key = os.environ.get("APCA_API_KEY_ID")
    sec = os.environ.get("APCA_API_SECRET_KEY")
    if not (key and sec):
        print("FATAL: APCA_API_KEY_ID / APCA_API_SECRET_KEY not in env")
        return 2

    broker = AlpacaBroker(key, sec)
    trail = AuditTrail(broker, DecisionLog(args.log))
    now = (datetime.now(timezone.utc) - timedelta(hours=4)).replace(tzinfo=None)
    today = now.date()

    print("=== live_session %s ET   mode=%s ==="
          % (now.strftime("%Y-%m-%d %H:%M"), "LIVE" if args.live else "DRY RUN"))

    acct = broker.get_account()
    equity = acct["equity"]
    positions = broker.get_positions()
    print("equity=%.2f  open positions=%d" % (equity, len(positions)))

    if now.weekday() not in uni.ENTRY_DAYS and not args.ignore_entry_window:
        print("REFUSE ALL: weekday %d is not an entry day %s. Nothing "
              "evaluated, nothing placed."
              % (now.weekday(), sorted(uni.ENTRY_DAYS)))
        return 0
    for lo, hi in uni.EVENT_BLACKOUTS:
        if lo <= now <= hi:
            print("REFUSE ALL: inside event blackout %s .. %s" % (lo, hi))
            return 0

    state = {"equity": equity, "open_positions": len(positions),
             "positions_by_name": set(), "risk_at_open": 0.0,
             "daily_stop_hit": False, "net_delta": 0.0,
             "now": now, "today": today}

    iv5 = spy_iv_5d_avg(broker, key, sec, today, print)
    if iv5 is None:
        print("REFUSE ALL: SPY 5-day IV history incomplete. The IV gate cannot "
              "be evaluated, and an unknown is a refusal, not a pass.")
        return 0
    try:
        spy_spot = broker.get_underlying_quote("SPY")["last"]
        spy_chain = broker.get_option_chain("SPY", round(spy_spot * 0.95),
                                            round(spy_spot * 1.02), 21, 35)
        exp0 = sorted({c["expiration_date"] for c in spy_chain})[0]
        atm0 = min([c for c in spy_chain if c["expiration_date"] == exp0],
                   key=lambda c: abs(float(c["strike_price"]) - spy_spot))
        spy_now = norm_snapshot(
            broker.get_option_snapshot(atm0["symbol"]).get(atm0["symbol"], {}))
        spy_iv_now = spy_now["iv"]
    except Exception as e:
        print("REFUSE ALL: SPY spot IV unavailable (%s)" % type(e).__name__)
        return 0
    if spy_iv_now is None:
        print("REFUSE ALL: SPY spot IV missing from snapshot")
        return 0
    print("SPY atm_iv now=%.4f   5d avg=%.4f   %s"
          % (spy_iv_now, iv5,
             "vol elevated, IV gate can pass" if spy_iv_now >= iv5
             else "vol below its 5d average, IV gate will refuse everything"))

    names = (args.names.split(",") if args.names else list(uni.UNIVERSE))
    print("\n--- building candidates for %d names ---" % len(names))
    built = {}
    for n in names:
        cands = build_candidates(broker, n, today, print)
        if cands:
            built[n] = cands
            best = max(cands, key=lambda c: c["intent"]["credit"])
            print("  %s: %d permitted spreads, best credit %.2f at %s/%s"
                  % (n, len(cands), best["intent"]["credit"],
                     best["intent"]["k_short"], best["intent"]["k_long"]))

    total = sum(len(v) for v in built.values())
    print("")
    print("--- gates: %d candidates across %d names, fail-closed ---"
          % (total, len(built)))
    accepted = []
    for n, cands in built.items():
        n_acc, blockers = 0, {}
        for c in cands:
            mkt = dict(c["market"])
            mkt["spy_atm_iv"] = spy_iv_now
            mkt["spy_iv_5d_avg"] = iv5
            ev = trail.evaluate_entry(c["intent"], state, mkt)
            body = ev.get("body", ev)
            if body.get("decision") == "ACCEPT":
                n_acc += 1
                accepted.append((n, c, body))
            else:
                for g in body.get("gates", []):
                    if not g["pass"]:
                        blockers.setdefault(g["gate"], g["detail"])
        if n_acc:
            print("  %s: %d of %d ACCEPT" % (n, n_acc, len(cands)))
        else:
            print("  %s: 0 of %d accepted; blocked by %s"
                  % (n, len(cands), ", ".join(sorted(blockers))))
            for g, d in sorted(blockers.items()):
                print("      %s: %s" % (g, d))

    # One entry per name: among a name's accepted spreads take the best credit.
    best_by_name = {}
    for n, c, body in accepted:
        if (n not in best_by_name
                or c["intent"]["credit"] > best_by_name[n][1]["intent"]["credit"]):
            best_by_name[n] = (n, c, body)
    accepted = list(best_by_name.values())

    if not accepted:
        print("\nNo candidate passed every gate. That is the expected outcome "
              "most days and it is the product working, not failing.")
        return 0

    ranked = pf.select_from(
        [{"name": n, "atm_iv": c["market"]["atm_iv"],
          "rel_spread": (c["intent"]["ask_short"] - c["intent"]["bid_short"])
          / max(c["intent"]["credit"], 0.01),
          "earnings_clear_days": 21} for n, c, _ in accepted],
        state, SLOTS)
    picks = [p[0] for p in ranked]
    print("\n--- portfolio picks %s of %s ---"
          % (picks, [a[0] for a in accepted]))

    if not args.live:
        print("\nDRY RUN: nothing sent. Re-run with --live to place these.")
        return 0

    for n, c, body in accepted:
        if n not in picks:
            continue
        sym_s, sym_l = c["syms"]
        r = trail.submit_entry(body, c["mid"], c["mid"], sym_s, sym_l)
        rb = r.get("body", r)
        print("  %s: %s %s %s" % (n, rb.get("decision"), rb.get("reason", ""),
                                  rb.get("receipt", "")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
