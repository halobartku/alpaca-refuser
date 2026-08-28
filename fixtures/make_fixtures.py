"""Offline fixtures for FixtureBroker, derived FROM the BS model.

Scenario: Wednesday 2026-09-02 11:30 ET (inside Mon/Wed entry window, before
the Sep 3 NFP blackout), SPY @ 552.30, expiry 2026-09-25 (23 DTE),
short 517.5P / long 512.5P, sigma 0.40 (elevated-vol regime — VRP entries
happen when IV is rich; that is also the only regime where a $5-wide spread
prices so that $100k and $1M size to an EXACT 10x contract ratio:
credit ~1.252 -> per-contract risk $374.80 -> floor(750/374.8)=2 and
floor(7500/374.8)=20).

Snapshot quotes are model prices with small realistic staleness (+0.5% /
-0.5%) so quote integrity passes BY CONSTRUCTION. The generator self-checks
every gate-relevant band and refuses to emit fixtures that would not behave
as intended — hand-tuned numbers drifting from the model was the bug class
that killed v1 of this fixture.

Only account.json differs between the two accounts (A.112/A.113): same
market, different equity.

DESIGN FINDING encoded here (do not silently patch): at $1M equity, 0.75%
sizing demands >=15 contracts on any $5-wide spread (credit>0 => per-contract
risk <$500 => 7500/PCR > 15), while MAX_NET_DELTA_ABS=30 shares allows at
most ~10 (per-contract spread delta ~2.9 shares in the 0.15-0.25 delta band).
So on the TESTER the net-delta gate always refuses full-size index entries —
conservative by construction. The submission account ($100k, 2 contracts,
~5.7 shares) is unaffected. Tester P&L therefore UNDERSTATES per-risk
capacity; present results normalised per unit of risk (A.113).
"""
import json
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from refuser import bs  # noqa: E402

ACCOUNTS = {
    "FX-DEV-1M": 1_000_000.0,      # development tester role
    "FX-JUDGE-100K": 100_000.0,    # submission (judged) role
}

S = 552.30
R = 0.04
SIGMA = 0.40
K_SHORT, K_LONG = 517.5, 512.5
EXPIRY = "2026-09-25"
TODAY = date(2026, 9, 2)
DTE = (date(2026, 9, 25) - TODAY).days          # 23
T = DTE / 365.0
STALE_DRIFT = 0.005        # +0.5% short leg / -0.5% long leg

SYM_SHORT = "SPY260925P05175000"
SYM_LONG = "SPY260925P05125000"


def scenario():
    """Model-consistent scenario dict; self-checked against gate bands."""
    p_s, d_s, *_ = bs.bs_greeks(S, K_SHORT, T, R, SIGMA, "P")
    p_l, d_l, *_ = bs.bs_greeks(S, K_LONG, T, R, SIGMA, "P")
    mark = p_s - p_l
    stale_mid = p_s * (1 + STALE_DRIFT) - p_l * (1 - STALE_DRIFT)
    div = abs(stale_mid - mark) / mark
    # self-checks: refuse to emit fixtures that miss their intent
    assert 21 <= DTE <= 35, DTE
    assert 0.15 <= abs(d_s) <= 0.25, f"short delta {d_s:.3f} out of band"
    assert mark >= 1.00 and mark >= 0.20 * 5.0, f"credit {mark:.2f}"
    assert (5.0 - mark) <= 4.50
    assert div <= 0.10, f"staleness divergence {div:.1%} too wide"
    n_100k = int(100_000 * 0.0075 // ((5.0 - mark) * 100))
    n_1m = int(1_000_000 * 0.0075 // ((5.0 - mark) * 100))
    assert n_1m == 10 * n_100k, f"10x property broken: {n_1m} vs {n_100k}"
    return {"p_short": p_s, "p_long": p_l, "d_short": d_s, "d_long": d_l,
            "mark": mark, "stale_mid": stale_mid,
            "spread_delta": d_l - d_s, "n_100k": n_100k, "n_1m": n_1m}


def _snap(price, drift):
    mid = price * (1.0 + drift)
    half = 0.05
    return {"bid": round(mid - half, 2), "ask": round(mid + half, 2),
            "mid": round(mid, 2), "iv": SIGMA}


def write_fixture_broker(dirpath, account_number):
    os.makedirs(dirpath, exist_ok=True)
    sc = scenario()
    equity = ACCOUNTS[account_number]

    def w(name, obj):
        with open(os.path.join(dirpath, name), "w") as f:
            json.dump(obj, f, indent=1)

    w("account.json", {
        "account_number": account_number,
        "equity": equity,
        "status": "ACTIVE",
        "trading_blocked": False,
        "options_trading_level": 3,
        "currency": "USD",
    })

    def contract(sym, strike, expiry, oi, price):
        sn = _snap(price, 0.0)
        return {"symbol": sym, "strike_price": str(strike),
                "expiration_date": expiry, "type": "put",
                "open_interest": oi, "bid": sn["bid"], "ask": sn["ask"],
                "underlying_symbol": "SPY"}

    w("chain_SPY.json", [
        contract(SYM_SHORT, K_SHORT, EXPIRY, 8400, sc["p_short"]),
        contract(SYM_LONG, K_LONG, EXPIRY, 5100, sc["p_long"]),
        # decoys outside the strike window / DTE window
        contract("SPY260925P04900000", 490.0, EXPIRY, 900, 0.35),
        contract("SPY261106P05175000", K_SHORT, "2026-11-06", 300, 3.9),
        contract("SPY260911P05175000", K_SHORT, "2026-09-11", 900, 0.5),
    ])
    # stale snapshots: short leg slightly rich, long leg slightly cheap
    w(f"snapshot_{SYM_SHORT}.json", _snap(sc["p_short"], +STALE_DRIFT))
    w(f"snapshot_{SYM_LONG}.json", _snap(sc["p_long"], -STALE_DRIFT))
    w("underlying_SPY.json", {"last": S, "bid": S - 0.02, "ask": S + 0.02})
    w("positions.json", [])
    w("open_orders.json", [])
    return sc


if __name__ == "__main__":
    sc = scenario()
    print(f"scenario: mark={sc['mark']:.3f} d_short={sc['d_short']:.3f} "
          f"spread_delta={sc['spread_delta']:+.4f} "
          f"n_100k={sc['n_100k']} n_1m={sc['n_1m']}")
    for acct in ACCOUNTS:
        write_fixture_broker(os.path.join(HERE, "acct_" + acct), acct)
    print("fixtures written for", list(ACCOUNTS))
