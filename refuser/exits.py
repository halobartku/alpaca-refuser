"""Exit engine — research brief §2, priority order, first rule hit fires.

Six rules in EXACTLY the spec order:
  1. profit_target   GTC buy-to-close at 50% of max credit (placed at fill)
  2. delta_stop      short-leg |delta| >= 0.40 -> the booked risk profile
                     no longer exists
  3. time_exit       21 DTE, no exceptions (no position reaches expiry)
  4. loss_stop       spread mark >= 3.0x entry credit (~65-75% of max loss)
  5. weekend_flatten Fri 15:55 ET everything closes (no weekend gamma)
  6. event_flatten   NFP blackout (universe.in_event_blackout) everything closes

All exits are closing orders on the spread as ONE ticket. NO rolling in week 1.

Parameter self-check (the pitch, verified against arithmetic, not our code):
  target 0.5x credit / stop 3.0x credit  =>  breakeven win rate
  p = stop_loss / (stop_loss + take_profit) = 3.0 / 3.5 = 85.7%
  That number appears in the write-up; this module refuses to load if the
  constants drift away from it (fails loud, not silent).
"""
from datetime import time as dtime
from refuser import universe as U

# --- presented parameters (explicit, not accidents) -------------------------
PROFIT_TAKE_FRACTION = 0.50    # close at 50% of max credit
DELTA_STOP_ABS = 0.40          # short-leg delta migration stop
TIME_EXIT_DTE = 21             # hard time exit
LOSS_STOP_MULT = 3.0           # mark >= 3x credit
WEEKEND_FLATTEN = (4, dtime(15, 55))   # Friday=4, 15:55 ET

# Spec invariant: these imply the 85.7% breakeven win rate we cite everywhere.
_implied_breakeven = LOSS_STOP_MULT / (LOSS_STOP_MULT + PROFIT_TAKE_FRACTION)
assert abs(_implied_breakeven - 6 / 7) < 1e-12, (
    f"exit parameters drifted: implied breakeven {_implied_breakeven:.4f} "
    "!= 6/7 (85.71%) — the pitch and the engine disagree")


def gtc_target_price(entry_credit: float) -> float:
    """Limit for the GTC buy-to-close placed at fill time (rule 1).
    Rounded to the penny (option quotes are in $0.01 ticks)."""
    return round(PROFIT_TAKE_FRACTION * entry_credit, 2)


def _at_or_past_friday_1555(now) -> bool:
    wd, cutoff = WEEKEND_FLATTEN
    return now.weekday() == wd and now.time() >= cutoff


def check_position(pos: dict, market: dict, now) -> dict | None:
    """Return an exit decision dict, or None if the position is held.

    pos:    {name, expiry(date), k_short, k_long, width, entry_credit,
             contracts, short_delta (current, live), spread_mark (current)}
    market: {} (reserved; per-name data lives in pos for one-ticket exits)
    now:    naive ET datetime (same convention as universe.py)
    """
    d = U.dte(pos["expiry"], now.date())
    credit = pos["entry_credit"]
    mark = pos["spread_mark"]
    delta = abs(pos["short_delta"])

    def exit_(rule, note, limit):
        return {
            "rule": rule,
            "action": "BUY_TO_CLOSE",
            "ticket": "single-spread-ticket",
            "name": pos["name"],
            "contracts": pos["contracts"],
            "limit": limit,
            "note": note,
        }

    # 1. profit target (the resting GTC fills; we also fire on mark touch)
    tgt = gtc_target_price(credit)
    if mark <= tgt:
        return exit_("profit_target", f"mark {mark:.2f} <= 50% target {tgt:.2f}",
                     tgt)

    # 2. delta migration stop
    if delta >= DELTA_STOP_ABS:
        return exit_("delta_stop", f"short |delta| {delta:.3f} >= 0.40", mark)

    # 3. time exit
    if d <= TIME_EXIT_DTE:
        return exit_("time_exit", f"{d} DTE <= {TIME_EXIT_DTE} (no expiry risk)",
                     mark)

    # 4. hard loss stop
    if mark >= LOSS_STOP_MULT * credit:
        return exit_("loss_stop",
                     f"mark {mark:.2f} >= 3.0x credit {3.0 * credit:.2f}", mark)

    # 5. weekend flatten
    if _at_or_past_friday_1555(now):
        return exit_("weekend_flatten", "Fri >= 15:55 ET, no weekend gamma",
                     mark)

    # 6. event flatten (NFP stand-down window)
    if U.in_event_blackout(now):
        return exit_("event_flatten", "event blackout window (NFP stand-down)",
                     mark)

    return None  # hold


def open_position_plan(intent_result: dict, contracts: int) -> dict:
    """What the runtime records + places when an entry fills (offline shape).
    The GTC profit-taking order is placed AT FILL TIME (rule 1 requirement),
    so a position is never alive without its resting exit."""
    credit = float(intent_result["intent"]["credit"])
    return {
        "name": intent_result["intent"]["name"],
        "expiry": intent_result["intent"]["expiry"],
        "k_short": intent_result["intent"]["k_short"],
        "k_long": intent_result["intent"]["k_long"],
        "width": float(intent_result["intent"]["width"]),
        "entry_credit": credit,
        "contracts": contracts,
        "gtc_exit": {
            "type": "BUY_TO_CLOSE_GTC",
            "limit": gtc_target_price(credit),
            "placed_at": "fill",
        },
    }


def implied_breakeven_win_rate() -> float:
    """p such that p*take = (1-p)*stop  =>  p = stop/(stop+take).
    Knowable independently of this codebase: 3.0/3.5 = 85.714%."""
    return LOSS_STOP_MULT / (LOSS_STOP_MULT + PROFIT_TAKE_FRACTION)
