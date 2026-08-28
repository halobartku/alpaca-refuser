# The Refuser — one-page write-up (skeleton v1, numbers filled as they land)

> Status: pre-kickoff skeleton. Structure and logic are final; every
> `[FILL]` gets its live number during the competition week. Nothing here
> will be rewritten after the fact — the hash-chained log is the source.

## 1. What the agent is

An autonomous options agent that sells put credit spreads (21–35 DTE,
0.15–0.25 short delta, $1–5 wide) on a fixed 8-name liquid universe,
sized at 0.75% of equity per ticket. It runs unattended: reconcile →
scan → gate → size → order → exit, every cycle logged.

The differentiator is **what it refuses**. The volatility risk premium is
the motor; the gate stack is the transmission. At 0.5x take-profit and
3.0x stop-loss the breakeven win rate is 6/7 = **85.7%** — so refusal
discipline is not risk decoration, it is the edge.

## 2. AI logic (decision-making)

- **Not an LLM at the wheel.** The decision core is deterministic,
  explainable arithmetic: a Black-Scholes repricer (validated against
  Hull's canonical example and put-call parity, max error 1.4e-14) marks
  every spread off the LIVE underlying, because free-tier option quotes
  are 15-minute-old indicative derivatives. Trusting them blindly is how
  you celebrate fantasy fills; we reprice instead.
- **Signal.** Sell premium when IV is rich: per-name ATM IV ≥ 18% AND SPY
  ATM IV above its 5-day average (regime filter). IVR proxy bias is
  one-directional — a stale proxy can only make us too cautious, never
  reckless; entry quality is protected by the floor and the repricing.
- **Selection.** Deterministic, non-fitted composite when more names
  qualify than slots: IV level (0.5), liquidity/relative spread (0.3),
  earnings clearance (0.2), minus a group-occupancy penalty. No optimized
  weights — data-snooping is the death sentence. Same input, same output,
  always.
- **Adaptation surface.** The agent adapts position-to-position (which
  strikes, which names, how many contracts given current equity and heat),
  never parameter-to-parameter. Week 1 runs frozen parameters.

## 3. Risk gates (every entry passes ALL, or no order exists)

| # | Gate | Rule | Refuses when |
|---|------|------|--------------|
| 1 | DTE | 21–35 days | outside the band |
| 2 | Short-leg delta | 0.15–0.25 | too close / too far OTM |
| 3 | Width & credit | $1–5 wide, credit ≥ max($1, 20% of width), risk ≤ $4.50 | thin or sloppy structures |
| 4 | Liquidity | both leg spreads ≤ 35% of credit, OI ≥ 1000 both legs | untradeable |
| 5 | Underlying | last ≥ $40 | sub-penny-tick landmines |
| 6 | Calendar | Mon/Wed 10:05–15:00 ET, no earnings within DTE+3 (unknown date = refuse), NFP blackout | bad timing, unknown data |
| 7 | IV regime | ATM IV ≥ 18%, SPY IV > 5d avg | no premium worth harvesting |
| 8 | Portfolio | ≤ 6 slots, 1/name, heat ≤ 9%, ≤ 2 per correlated beta-group, net delta ≤ ±30 shares | concentration, one-beta book |

**Fail-closed is absolute:** unknown earnings date, missing snapshot,
account mismatch, broker error — every one is a refusal. A wrong number
is never better than no trade.

**Sizing integrity:** equity is read from the account endpoint at
decision time — never cached, never defaulted — and the account number is
asserted before any order (dev and judged accounts differ 10x; the suite
proves the same signal sizes to exactly 10x contracts with identical
percentage risk).

**Exits (first-hit-fires, all closing orders, no rolling):** 50% GTC
profit target placed at fill · short-delta ≥ 0.40 stop · 21-DTE time exit
· 3x-credit loss stop · Friday 15:55 flatten · event flatten.

## 4. Evidence

Hash-chained append-only log (`refuser/log.py`): per decision — data
snapshot, signal, every gate evaluation with reasons, order ticket, fill,
post-mortem. Tamper-evident; `verify.py` replay for judges.

- Trades taken / refused: `[FILL]` / `[FILL]`
- Win rate vs 85.7% breakeven: `[FILL]`
- P&L normalised per unit of risk: `[FILL]` (raw $ at $100k base)
- Slippage captured vs own marks: `[FILL]` (quoted vs limit vs filled)
- Max drawdown vs 1.5% daily stop: `[FILL]`

## 5. Known limitations (stated, not hidden)

- Free-tier quotes are 15-min delayed indicative derivatives → we reprice
  off the live underlying and disclose the flat-sigma assumption.
- Absolute net-delta cap (±30 shares) binds at high equity: on a $1M
  account, 0.75% sizing (≥15 contracts, $5-wide) is refused by design.
  Conservative by construction; the judged $100k account is unaffected.
- Earnings dates are a hand-maintained map (free tier has no calendar
  API); unknown date = refuse, re-verified Sundays.
- No convexity sleeve. Week 1 is the discipline proof; whether theta
  bleed in quiet weeks justifies a tail hedge is an explicit open
  decision, deliberately not built.
