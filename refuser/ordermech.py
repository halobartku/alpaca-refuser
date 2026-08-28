"""Answers design gap 3 (order mechanics on stale data) from NEXT-TASKS §8.

Free-tier option quotes are 15-minute-old indicative derivatives, NOT OPRA.
Sending orders priced off them blindly = celebrating fantasy fills. Policy:

1. INTEGRITY: reprice the spread with Black-Scholes off the LIVE underlying
   (`mark`); if the stale quote mid has diverged from `mark` by more than
   QUOTE_TOL, the quote is unusable -> REFUSE (fail-closed).
2. LIMIT: place the credit limit at min(stale_mid, mark) - CUSHION, rounded
   DOWN to the penny — we never ask more credit than live fair value implies,
   and the rounding direction is always the conservative one for a credit.
3. EDGE FLOOR: if that limit falls below EDGE_FLOOR_FRAC * mark, the remaining
   edge is too thin to pay the spread -> REFUSE rather than chase.
4. WALK: unfilled after a wait interval -> step the limit DOWN one penny at a
   time (accepting less credit), never below the edge floor, never more than
   MAX_WALKS re-pegs. At MAX_WALKS: cancel, log, move on. No market orders,
   ever — a market order on indicative quotes is an unpriceable trade.

Slippage is MEASURED, not assumed: quoted vs limit vs filled, per spread and
per leg, logged for the execution-quality slide nobody else will have.
"""
import math

from refuser import gates

QUOTE_TOL = 0.15        # max |stale_mid - mark| / mark before quote unusable
CUSHION = 0.05          # $ per spread below reference for the initial limit
EDGE_FLOOR_FRAC = 0.90  # refuse if limit < 90% of live-repriced mark
MAX_WALKS = 5           # max re-pegs before cancel


def _penny_down(x: float) -> float:
    """Floor to the cent, immune to IEEE754 dust: int(1.15*100) is 114
    because 1.15*100 = 114.99999999999999. The 1e-7 nudge is 5 orders of
    magnitude below a real sub-penny remainder, so it can only repair dust,
    never cross a true cent boundary."""
    return math.floor(x * 100 + 1e-7) / 100.0


def quote_integrity(mark: float, stale_mid: float, tol: float = QUOTE_TOL):
    div = abs(stale_mid - mark) / mark if mark > 0 else float("inf")
    ok = div <= tol
    return ok, f"|{stale_mid:.2f}-{mark:.2f}|/{mark:.2f} = {div:.1%} vs {tol:.0%}"


def initial_limit(mark: float, stale_mid: float,
                  cushion: float = CUSHION, floor_frac: float = EDGE_FLOOR_FRAC):
    """(ok, limit_or_None, reason). Credit limit for SELL_TO_OPEN the spread."""
    ok_q, why_q = quote_integrity(mark, stale_mid)
    if not ok_q:
        return False, None, f"stale quote diverged from live mark: {why_q}"
    ref = min(mark, stale_mid)
    limit = _penny_down(ref - cushion)
    floor = floor_frac * mark
    if limit < floor:
        return False, None, (f"limit {limit:.2f} < edge floor {floor:.2f} "
                             f"({floor_frac:.0%} of mark {mark:.2f}) -> thin edge")
    if limit < 1.00:
        return False, None, f"limit {limit:.2f} < $1.00 minimum credit"
    return True, limit, f"limit={limit:.2f} (ref {ref:.2f} - {cushion:.2f})"


def walk_limit(current: float, mark: float, walks_done: int,
               step: float = 0.01, floor_frac: float = EDGE_FLOOR_FRAC):
    """One re-peg toward fill: accept one penny LESS credit. Never below the
    edge floor; at MAX_WALKS the answer is CANCEL.
    Returns ('walk', new_limit, reason) | ('cancel', None, reason).
    """
    if walks_done >= MAX_WALKS:
        return "cancel", None, f"{walks_done} walks >= {MAX_WALKS} -> cancel"
    new = _penny_down(current - step)
    floor = floor_frac * mark
    # epsilon: 0.90*1.10 = 0.9900000000000001 — a walk TO the floor is legal,
    # only a walk BELOW it cancels
    if new < floor - 1e-9:
        return "cancel", None, f"next walk {new:.2f} < edge floor {floor:.2f}"
    return "walk", new, f"re-peg {current:.2f} -> {new:.2f} (walk {walks_done + 1})"


def measure_slippage(quoted_mid: float, limit: float, filled: float,
                     legs: int = 2):
    """Execution quality vs OUR OWN marks. For a credit spread, slippage =
    (reference - filled) — how much less credit we actually captured.
    Positive = we gave up edge. Returns per-spread and per-leg $.
    """
    per_spread = round(quoted_mid - filled, 4)
    return {
        "vs_quoted": per_spread,
        "vs_limit": round(limit - filled, 4),
        "per_leg": round(per_spread / legs, 4),
        "captured_frac": round(filled / quoted_mid, 4) if quoted_mid > 0 else None,
    }


def order_plan(mark: float, stale_mid: float, contracts: int):
    """Full SELL_TO_OPEN plan for a put credit spread, or refusal.
    GTC exit companion is built by exits.open_position_plan at fill time.
    """
    ok, limit, why = initial_limit(mark, stale_mid)
    if not ok:
        return {"decision": "REFUSE", "reason": why}
    return {
        "decision": "SUBMIT",
        "order_type": "limit",
        "tif": "day",
        "side": "sell_to_open",
        "limit_credit": limit,
        "contracts": contracts,
        "walk_policy": f"re-peg -0.01 x{MAX_WALKS} max, floor {EDGE_FLOOR_FRAC:.0%} of mark",
        "reason": why,
    }
