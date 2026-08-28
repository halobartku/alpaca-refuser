"""Black-Scholes repricer + greeks, dependency-free.

Why this exists (hackathon differentiator): free-tier option data is 15-min stale,
but the UNDERLYING is live on IEX and IV moves slower than price. We reprice
options ourselves off the live underlying + delayed IV surface, then measure
fill quality against our own marks instead of trusting indicative quotes.

Correctness gate: validated against independently published textbook values
(Hull, Options Futures and Other Derivatives standard example) in test_offline.py.
"""
from math import erf, exp, log, sqrt

SQRT2 = sqrt(2.0)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / SQRT2))


def _norm_pdf(x: float) -> float:
    return exp(-0.5 * x * x) / sqrt(2.0 * 3.141592653589793)


def bs_greeks(S: float, K: float, T: float, r: float, sigma: float, kind: str):
    """Price and greeks for a European option. T in years, kind 'C'|'P'.

    Returns (price, delta, gamma, theta_per_year, vega_per_1.0_vol).
    Raises ValueError on non-positive S/K/T/sigma.
    """
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        raise ValueError("S, K, T, sigma must be positive")
    d1 = (log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrt(T))
    d2 = d1 - sigma * sqrt(T)
    disc = exp(-r * T)
    gamma = _norm_pdf(d1) / (S * sigma * sqrt(T))
    vega = S * disc * _norm_pdf(d1)  # per 1.0 change in sigma
    if kind == "C":
        price = S * _norm_cdf(d1) - K * disc * _norm_cdf(d2)
        delta = _norm_cdf(d1)
        theta = (-S * _norm_pdf(d1) * sigma / (2 * sqrt(T))
                 - r * K * disc * _norm_cdf(d2))
    elif kind == "P":
        price = K * disc * _norm_cdf(-d2) - S * _norm_cdf(-d1)
        delta = _norm_cdf(d1) - 1.0
        theta = (-S * _norm_pdf(d1) * sigma / (2 * sqrt(T))
                 + r * K * disc * _norm_cdf(-d2))
    else:
        raise ValueError("kind must be 'C' or 'P'")
    return price, delta, gamma, theta, vega


def put_spread_mark(S: float, k_short: float, k_long: float, T: float,
                    r: float, sigma: float):
    """Value of a put CREDIT spread we are SHORT: sell k_short put, buy k_long
    put (k_long < k_short). Mark = price(short put) - price(long put); positive
    means the spread is worth that much to close.

    Uses one flat sigma for both legs (free tier gives snapshot IV per contract;
    flat is the conservative repricing choice and we disclose it).
    """
    if not k_long < k_short:
        raise ValueError("put spread requires k_long < k_short")
    p_short = bs_greeks(S, k_short, T, r, sigma, "P")[0]
    p_long = bs_greeks(S, k_long, T, r, sigma, "P")[0]
    return p_short - p_long


def spread_greeks(S, k_short, k_long, T, r, sigma):
    """(net_delta, net_theta_per_day) of the short put spread position."""
    _, d_s, _, th_s, _ = bs_greeks(S, k_short, T, r, sigma, "P")
    _, d_l, _, th_l, _ = bs_greeks(S, k_long, T, r, sigma, "P")
    # short the short-strike put, long the long-strike put
    return (d_l - d_s), (th_l - th_s) / 365.0


def size_contracts(equity: float, risk_per_trade: float, width: float,
                   credit: float) -> int:
    """Contracts such that qty * (width - credit) * 100 <= equity * risk_per_trade.
    Floor at 0 — an unsizable trade is a refusal, not a rounding-up."""
    per_contract_risk = (width - credit) * 100.0
    if per_contract_risk <= 0:
        return 0
    import math
    return math.floor(equity * risk_per_trade / per_contract_risk)
