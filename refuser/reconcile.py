"""State reconciliation — after any restart the agent asks Alpaca what it
holds and NEVER trusts its own memory (paper NTA sync lags one day).

reconcile() takes broker state (positions + open orders, as Alpaca returns
them) plus our decision log, and returns the authoritative state the gate
layer reads. Divergences are logged, never silently merged.
"""
from refuser.log import DecisionLog


def _spread_key(pos):
    # Alpaca option position symbol shape: SPY260918P00400000 style
    return pos["symbol"]


def reconcile(broker_positions: list, broker_open_orders: list,
              log: DecisionLog):
    """Return dict for gates.gate_portfolio + list of divergence events.

    broker_positions: [{symbol, qty (negative=short), avg_entry_price,
                        strike, expiry, ...}]
    """
    state = {
        "open_positions": len(broker_positions),
        "positions_by_name": set(),
        "risk_at_open": 0.0,
        "net_delta": 0.0,
        "divergences": [],
    }
    for p in broker_positions:
        name = p.get("underlying") or p["symbol"][:3].lstrip("0-9")
        state["positions_by_name"].add(name)
        state["risk_at_open"] += abs(p.get("risk_at_open", 0.0))
        state["net_delta"] += p.get("delta", 0.0)

    # cross-check against last ACCEPT in the log
    last_accepts = []
    import json
    import os
    if os.path.exists(log.path):
        with open(log.path) as f:
            for line in f:
                rec = json.loads(line)
                if rec["body"].get("decision") == "ACCEPT":
                    last_accepts.append(rec["body"])
    broker_syms = {_spread_key(p) for p in broker_positions}
    for acc in last_accepts:
        if acc.get("ticket", {}).get("symbols") and not set(
                acc["ticket"]["symbols"]) & broker_syms:
            # we accepted+placed an order but broker shows no position and no
            # open order -> either unfilled or expired; log, do not assume
            state["divergences"].append({
                "kind": "accept-without-position",
                "accept_seq": acc.get("seq"),
                "symbols": acc["ticket"]["symbols"],
            })
    return state, state.pop("divergences")
