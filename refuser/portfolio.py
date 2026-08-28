"""Answers design gap 1 (correlation) + gap 2 (selection) from NEXT-TASKS §8.

Gap 1 — correlation: SPY/QQQ/IWM short-put spreads are ONE beta bet, and the
short-put book only ever accumulates POSITIVE delta, so "1 position per name"
does not cap direction. Two portfolio-level gates close it:
  a) beta-group cap: at most MAX_PER_GROUP positions per correlated group
     (never all three index ETFs at once);
  b) net-delta cap: projected |net delta| (shares-equivalent) after the new
     trade must stay <= gates.MAX_NET_DELTA_ABS. This is the cap that binds
     before portfolio heat does — deliberately: 6 slots x ~+10 deltas each
     would be +60 shares-equivalent of pure beta.

Gap 2 — selection: when >MAX_CONCURRENT names qualify, which ones? A fixed,
deterministic, NON-FITTED composite (no optimized weights — data-snooping is
the death sentence the research brief warns about): rank by IV level (VRP
harvest, weight .5), liquidity (tighter relative spread, .3), earnings
clearance (farther from the window, .2), minus a group-occupancy penalty that
forces diversification. Min-max normalized across the candidate set; ties
break alphabetically for full determinism. Same input -> same output, always.
"""
from refuser import universe as U

# Portfolio-level net-delta cap (shares-equivalent), A.115: cap SCALES with
# equity so it is a coherent fraction of the book, anchored so that $100k
# yields exactly the historical +/-30 shares (cap = equity * 3 / 10000:
# 30 at $100k, 300 at $1M). This is a NO-OP for the judged $100k account
# (PA3YVMJ3YVDZ) and unblocks the $1M tester's full-size path, which was
# previously untestable under the absolute cap. Mirrored in gates.py as
# MAX_NET_DELTA_ABS (the $100k anchor); defined here to avoid a circular
# import.
NET_DELTA_CAP = 30
NET_DELTA_CAP_EQUITY_ANCHOR = 100_000.0


def net_delta_cap(equity: float) -> float:
    """A.115: cap_shares = equity / (100000/30) — 30.0 at $100k, 300.0 at
    $1M, float-exact at both anchors (verified: anchor division, unlike
    multiplying by 30/100000, returns exactly 30.0/300.0 — this matters
    because the old absolute boundary tests must not flip on float dust).
    Fail-closed: equity <= 0 -> 0.0 (nothing can be added to a book with
    no positive equity)."""
    if equity <= 0:
        return 0.0
    return equity / (NET_DELTA_CAP_EQUITY_ANCHOR / NET_DELTA_CAP)

# --- gap 1: correlation ------------------------------------------------------

BETA_GROUPS = {
    "index_beta": ("SPY", "QQQ", "IWM"),   # the "one bet" trio
    "mega_tech": ("AAPL", "MSFT"),
    "energy": ("XOM",),
    "staples": ("KO",),
    "pharma": ("PFE",),
}
MAX_PER_GROUP = 2

_GROUP_INDEX = {n: g for g, names in BETA_GROUPS.items() for n in names}


def group_of(name: str) -> str:
    if name not in _GROUP_INDEX:
        raise ValueError(f"{name} not in universe — cannot be scored")
    return _GROUP_INDEX[name]


def gate_group(state, name: str):
    """At most MAX_PER_GROUP concurrent positions per beta group.
    Unknown name -> refusal (fail-closed), never an exception inside a gate."""
    try:
        g = group_of(name)
    except ValueError:
        return False, f"{name} not in universe — cannot be grouped"
    held = [n for n in state["positions_by_name"] if group_of(n) == g]
    ok = len(held) < MAX_PER_GROUP
    return ok, f"group {g} holds {len(held)}/{MAX_PER_GROUP} ({', '.join(held) or 'none'})"


def projected_net_delta(state, spread_delta: float, contracts: int) -> float:
    """Net delta (shares-equivalent) after adding `contracts` spreads whose
    per-spread delta is `spread_delta` (positive for short put spreads)."""
    return state["net_delta"] + spread_delta * contracts * 100.0


def gate_net_delta(state, spread_delta: float, contracts: int, cap: float = None):
    """A.115: cap scales with equity (30 at $100k, 300 at $1M). `cap` may be
    pinned explicitly for boundary tests; default derives from the SAME
    decision-time equity the sizing uses, never a stale default."""
    if cap is None:
        cap = net_delta_cap(state["equity"])
    p = projected_net_delta(state, spread_delta, contracts)
    # epsilon: 0.10*3*100 = 30.000000000000004 in IEEE754 — a boundary must
    # not flip on float dust (exactly-at-cap passes by design)
    ok = abs(p) <= cap + 1e-6
    return ok, f"projected net delta {p:+.1f} vs cap +/-{cap:g}"


# --- gap 2: selection ---------------------------------------------------------

W_IV, W_LIQ, W_CLEAR, GROUP_PENALTY = 0.5, 0.3, 0.2, 0.25


def _minmax(xs):
    lo, hi = min(xs), max(xs)
    span = hi - lo
    return [1.0 if span == 0 else (x - lo) / span for x in xs]


def score_candidates(candidates, state):
    """candidates: [{name, atm_iv, rel_spread, earnings_clear_days}, ...]
    (rel_spread = quoted spread / credit — lower is better).
    Returns [(name, score, reason)] sorted best-first, deterministic.
    """
    if not candidates:
        return []
    ivs = _minmax([c["atm_iv"] for c in candidates])
    liqs = _minmax([-c["rel_spread"] for c in candidates])   # higher=better
    clears = _minmax([min(c["earnings_clear_days"], 21) for c in candidates])
    out = []
    for c, iv_n, liq_n, cl_n in zip(candidates, ivs, liqs, clears):
        occ = sum(1 for h in state["positions_by_name"]
                  if group_of(h) == group_of(c["name"]))
        score = (W_IV * iv_n + W_LIQ * liq_n + W_CLEAR * cl_n
                 - GROUP_PENALTY * occ)
        out.append((c["name"], round(score, 6),
                    f"iv={c['atm_iv']:.3f} rel_spread={c['rel_spread']:.3f} "
                    f"clear={c['earnings_clear_days']}d group_occ={occ}"))
    out.sort(key=lambda t: (-t[1], t[0]))   # score desc, then A-Z tie-break
    return out


def select_from(candidates, state, slots: int):
    """Pick which `slots` qualifying names to enter, respecting group caps.
    Returns [(name, score, reason)] of length <= slots."""
    ranked = score_candidates(candidates, state)
    picked, group_count = [], {}
    for name, score, reason in ranked:
        g = group_of(name)
        if group_count.get(g, 0) >= MAX_PER_GROUP:
            continue
        picked.append((name, score, reason))
        group_count[g] = group_count.get(g, 0) + 1
        if len(picked) == slots:
            break
    return picked
