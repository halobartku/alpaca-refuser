"""PLAYBOOK §4 — NFP Friday straddle gate, measured not lore.

Measured 2026-08-29 (A.120, n=13 Friday 08:30 ET NFP releases Jan-2025→Aug-2026,
IEX 1-min bars, nfp_raw.json): median Thu-close→10:55 ET |move| = 0.97%,
p25 0.49, p75 1.30. At SPY≈770 the median straddle breakeven ≈ $7.50.

GATE (pinned in PLAYBOOK §4): buy the 1-DTE ATM SPY straddle ONLY if the
Thu-close straddle mid ≤ 0.9 × median realized move (0.9 × 0.97% = 0.875% of
spot), size ≤ 2% of account. A 1-DTE ATM straddle normally prices 0.8–1.0% of
spot, so this gate is DESIGNED to refuse most weeks — that is the discipline,
not a bug.

Fail-closed: no live spot or no live quote ⇒ REFUSE. The decision is taken
Thursday 09-03 close with live numbers; this module only does the arithmetic.
"""
from datetime import datetime

# 0.9 x median realized Thu-close->10:55 move (0.97%), PLAYBOOK §4
GATE_FRAC = 0.00875
MAX_SIZE_FRAC = 0.02          # hard size cap, % of decision-time equity


def straddle_gate(spot: float, straddle_mid: float,
                  now: datetime | None = None) -> dict:
    """ACCEPT only when the straddle is cheap vs the median NFP move.

    Inputs are LIVE Thursday-close values (spot from IEX quote, straddle mid
    from the snapshot pair). Anything missing/stale-shaped ⇒ REFUSE.
    """
    def refuse(why):
        return {"decision": "REFUSE", "reason": why,
                "gate_frac": GATE_FRAC, "size_cap_frac": MAX_SIZE_FRAC}

    if spot is None or spot <= 0:
        return refuse(f"no live spot ({spot!r}) — refuse")
    if straddle_mid is None or straddle_mid <= 0:
        return refuse(f"no live straddle mid ({straddle_mid!r}) — refuse")

    cutoff = GATE_FRAC * spot
    priced_frac = straddle_mid / spot
    base = {
        "spot": spot,
        "straddle_mid": straddle_mid,
        "cutoff": round(cutoff, 2),
        "priced_frac": round(priced_frac, 5),
        "gate_frac": GATE_FRAC,
        "size_cap_frac": MAX_SIZE_FRAC,
    }
    if straddle_mid > cutoff:
        return {"decision": "REFUSE",
                "reason": (f"straddle {straddle_mid:.2f} = {priced_frac:.3%} "
                           f"of spot > gate {GATE_FRAC:.3%} "
                           f"(cutoff ${cutoff:.2f}) — too expensive"),
                **base}
    return {"decision": "ACCEPT",
            "reason": (f"straddle {straddle_mid:.2f} = {priced_frac:.3%} "
                       f"of spot <= gate {GATE_FRAC:.3%} "
                       f"(cutoff ${cutoff:.2f}) — cheap vs median NFP move"),
            "size_frac": MAX_SIZE_FRAC,
            **base}
