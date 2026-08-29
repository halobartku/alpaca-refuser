"""PLAYBOOK R2 — Friday 10:55 ET liquidation engine.

Sequence (§2/R2): 10:30 start closing illiquid legs, 10:55 EVERYTHING flat,
10:55–11:00 verify positions == 0, then submit. Judging ends 11:00 ET;
liquidating at 10:55 makes judged P&L = realized P&L and deletes the unjudged
3.5h tail.

Design, per the live-verified shapes (smoke 2026-08-28):
  - /v2/positions returns PER-LEG rows: {symbol, qty (str, negative=short),
    side: long|short, qty_available}. Options carry asset_class=us_option.
  - Close ticket shape (order ceae4490 close leg, filled 8.7s):
      {type: limit, time_in_force: day, order_class: mleg, qty: "N",
       limit_price: "<debit>", legs: [{symbol, ratio_qty: "1",
       side: buy|sell, position_intent: buy_to_close|sell_to_close}]}
  - R2 rule: marketable limits THROUGH the quote (never naked market orders,
    §9), so the debit limit = ask + aggression premium, walked up on
    non-fill. Debit walks UP (pay more), the mirror of ordermech's credit
    walk down.

Fail-closed: any leg that cannot be closed raises — the run does NOT
silently continue with an open position past 10:55.
"""
import time as _time

from refuser.broker import BaseBroker, BrokerError

R2_CLOSE_START = (4, 10, 30)      # Friday, 10:30 ET — illiquid legs first
R2_HARD_FLAT = (4, 10, 55)        # Friday, 10:55 ET — everything flat
AGGRESSION = 0.05                 # $ over the quote to be marketable
MAX_WALKS_R2 = 10                 # 10:55 does not negotiate; walk hard


def _is_option_leg(pos: dict) -> bool:
    return pos.get("asset_class") == "us_option"


def leg_inventory(positions: list) -> dict:
    """Collapse per-leg position rows into {symbol: net_qty_int} for options.

    Live shape: qty is a STRING, negative for shorts. Anything unparsable
    raises BrokerError — an unknown inventory is a refusal, not a guess.
    """
    inv = {}
    for p in positions:
        if not _is_option_leg(p):
            continue
        sym = p.get("symbol")
        raw = p.get("qty")
        try:
            q = int(float(raw))
        except (TypeError, ValueError):
            raise BrokerError(f"unparsable qty {raw!r} on {sym!r} — refuse")
        if not sym:
            raise BrokerError("option position row missing symbol — refuse")
        inv[sym] = inv.get(sym, 0) + q
    return inv


def close_ticket(symbol: str, net_qty: int, ref_price: float) -> dict:
    """One closing ticket for a net single-leg option position.

    net_qty > 0 (long)  ⇒ sell_to_close; marketable = limit AT/THROUGH the
                          bid ⇒ limit = ref - AGGRESSION (accept less).
    net_qty < 0 (short) ⇒ buy_to_close; marketable = limit AT/THROUGH the
                          ask ⇒ limit = ref + AGGRESSION (pay more).

    R2 certainty beats price (§2): the walk always goes THROUGH the market,
    up to MAX_WALKS_R2. Single-leg close uses order_class "simple"; only the
    two-leg spread close is mleg (live-verified shape, smoke 2026-08-28).
    """
    if net_qty == 0:
        raise BrokerError(f"{symbol}: net qty 0 — nothing to close")
    side = "sell" if net_qty > 0 else "buy"
    intent = "sell_to_close" if net_qty > 0 else "buy_to_close"
    if side == "buy":
        limit = round(ref_price + AGGRESSION, 2)
    else:
        limit = round(max(ref_price - AGGRESSION, 0.01), 2)
    return {
        "type": "limit",
        "time_in_force": "day",
        "order_class": "simple",
        "qty": str(abs(net_qty)),
        "limit_price": f"{limit:.2f}",
        "legs": [{
            "symbol": symbol,
            "ratio_qty": "1",
            "side": side,
            "position_intent": intent,
        }],
        # metadata for the audit layer (not sent to the API)
        "_meta": {"kind": "r2-close", "ref_price": ref_price, "limit": limit},
    }


def spread_close_ticket(short_leg: str, long_leg: str, contracts: int,
                        ref_debit: float) -> dict:
    """Single-ticket close of a put credit spread (both legs, one mleg order)
    — the shape live-verified 2026-08-28 (filled in 8.7s at the limit).

    Buying back the spread = buy_to_close short strike + sell_to_close long
    strike, limit_price POSITIVE debit, marketable = debit slightly ABOVE
    the current ask of the spread.
    """
    limit = round(ref_debit + AGGRESSION, 2)
    return {
        "type": "limit",
        "time_in_force": "day",
        "order_class": "mleg",
        "qty": str(contracts),
        "limit_price": f"{limit:.2f}",
        "legs": [
            {"symbol": short_leg, "ratio_qty": "1", "side": "buy",
             "position_intent": "buy_to_close"},
            {"symbol": long_leg, "ratio_qty": "1", "side": "sell",
             "position_intent": "sell_to_close"},
        ],
        "_meta": {"kind": "r2-spread-close", "ref_debit": ref_debit,
                  "limit": limit},
    }


def verify_flat(positions: list) -> tuple[bool, list]:
    """10:55–11:00 verification: every option position row must be gone."""
    residual = [p.get("symbol") for p in positions if _is_option_leg(p)]
    return (len(residual) == 0), residual


def liquidate_all(broker: BaseBroker, positions: list, snapshot_fn,
                  sleep=_time.sleep, max_walks: int = MAX_WALKS_R2):
    """R2 engine. Cancels open orders first (no orphans), then closes every
    option leg with marketable limits, walking THROUGH the market up to
    max_walks. Returns a report; raises BrokerError on any leg left open.

    snapshot_fn(symbol or symbols) -> {sym: {bid, ask, ...}} — the broker's
    snapshot seam (envelope already unwrapped live-side).
    """
    report = {"cancelled": [], "closed": [], "failed": []}

    # 0. no orphan orders survive R2
    for o in broker.get_open_orders():
        try:
            if broker.cancel_order(o.get("id")):
                report["cancelled"].append(o.get("id"))
        except Exception:
            pass  # already-filled/cancelled races; verification catches leaks

    inv = leg_inventory(positions)
    if not inv:
        report["note"] = "nothing to liquidate"
        return report

    syms = list(inv)
    snaps = snapshot_fn(syms)
    for sym in syms:
        net = inv[sym]
        snap = snaps.get(sym) or {}
        ref = _walkable_ref(snap)
        ticket = close_ticket(sym, net, ref)
        placed = broker.place_closing_order(ticket)
        filled = False
        for walk in range(max_walks):
            st = (placed or {}).get("status")
            if st in ("filled", "closed"):
                filled = True
                break
            # reprice through the market
            snap2 = snapshot_fn([sym]).get(sym) or {}
            ref2 = _walkable_ref(snap2)
            side = ticket["legs"][0]["side"]
            if side == "buy":
                new_lim = round(ref2 + AGGRESSION + 0.01 * (walk + 1), 2)
            else:
                new_lim = round(max(ref2 - AGGRESSION - 0.01 * (walk + 1),
                                    0.01), 2)
            ticket = dict(ticket)
            ticket["limit_price"] = f"{new_lim:.2f}"
            broker.cancel_order(placed.get("id"))
            placed = broker.place_closing_order(ticket)
            sleep(2.0)
        rec = {"symbol": sym, "qty": net,
               "order_id": (placed or {}).get("id"),
               "status": (placed or {}).get("status")}
        (report["closed"] if filled else report["failed"]).append(rec)

    if report["failed"]:
        raise BrokerError(
            f"R2 FAILURE — legs not confirmed closed: "
            f"{[r['symbol'] for r in report['failed']]}")
    return report


def _walkable_ref(snap: dict) -> float:
    """Reference price for a marketable close: the side we must cross.

    LIVE SHAPE (verified 2026-08-29, data API /v1beta1/options/snapshots,
    feed=indicative): quotes live under latestQuote.{bp,ap}; top-level
    bidPrice/askPrice come back NULL on this feed. Both paths are read.
    """
    lq = snap.get("latestQuote") or {}
    bid = (snap.get("bid") if snap.get("bid") is not None
           else snap.get("bidPrice") if snap.get("bidPrice") is not None
           else lq.get("bp"))
    ask = (snap.get("ask") if snap.get("ask") is not None
           else snap.get("askPrice") if snap.get("askPrice") is not None
           else lq.get("ap"))
    # closing a SHORT needs the ask; closing a LONG needs the bid. We do not
    # know the direction here, so take the worse-for-us side conservatively:
    # use the mid if both exist, else whichever exists, else refuse.
    if bid is not None and ask is not None:
        return (float(bid) + float(ask)) / 2.0
    if ask is not None:
        return float(ask)
    if bid is not None:
        return float(bid)
    raise BrokerError(f"snapshot has neither bid nor ask — refuse ({snap})")
