"""Static universe + earnings/event calendar gates.

Fixed list, not a scan (per research brief §1): 8 liquid names, no earnings
inside the judged window. Earnings dates are a STATIC map maintained by hand
against IR pages each Sunday (free tier has no earnings calendar endpoint);
an unknown date is a REFUSAL, not a pass — fail-closed.
"""
from datetime import date, datetime, timedelta

# name -> next known earnings date (ET). None = verified no report in window
# (AAPL/MSFT/XOM/KO/PFE fiscal calendars put next reports late Sep-Oct, per
# research brief — re-verify every Sunday, one call each).
UNIVERSE = {
    "SPY": None, "QQQ": None, "IWM": None,
    "AAPL": None, "MSFT": None, "XOM": None, "KO": None, "PFE": None,
}

# Hard event windows: no NEW entries from this time until after the event.
EVENT_BLACKOUTS = [
    # NFP Fri Sep 4 08:30 ET: flatten Wed Sep 3 15:55 ET, stand down through print
    (datetime(2026, 9, 3, 15, 55), datetime(2026, 9, 4, 12, 0)),
]

# System-wide entry windows (ET): Mon and Wed ~10:05, never first minutes.
ENTRY_DAYS = {0, 2}  # Monday=0, Wednesday=2


def dte(expiry: date, today: date) -> int:
    return (expiry - today).days


def earnings_within(name: str, horizon_days: int, today: date) -> bool | None:
    """True if earnings inside today..today+horizon_days. None if date unknown
    (fail-closed caller must refuse)."""
    d = UNIVERSE.get(name, "UNKNOWN")
    if d == "UNKNOWN":
        return None
    if d is None:
        return False
    return today <= d <= today + timedelta(days=horizon_days)


def in_entry_window(now: datetime) -> bool:
    """Mon/Wed between 10:05 and 15:00 ET (naive ET datetimes in this offline
    skeleton; the live loop converts via zoneinfo)."""
    if now.weekday() not in ENTRY_DAYS:
        return False
    t = now.time()
    from datetime import time as dtime
    return dtime(10, 5) <= t <= dtime(15, 0)


def in_event_blackout(now: datetime) -> bool:
    return any(start <= now <= end for start, end in EVENT_BLACKOUTS)
