# The Refuser - slide deck for the required PDF

Written 2026-08-30 by Claude. **Twelve slides.** Every `[LIVE]` is read off the judged
account at build time, never typed from memory. If a `[LIVE]` number is unavailable,
delete the line rather than approximating it.

Build: write these as HTML and print to PDF, reusing the hosted demo's stylesheet so
the deck and the demo look like one artefact. Do not introduce a template.

---

## 1. Title
**The Refuser**
An options agent that is judged on what it did not do
Account `[LIVE PA3YVMJ3YVDZ]` · Alpaca Options Alpha Agents · September 2026
Repo (MIT): github.com/halobartku/alpaca-refuser · Demo: halobartku.github.io/alpaca-refuser

## 2. The concession, first
- A defined-risk short-premium book at 4% portfolio heat has a **ceiling near 0.5% a week**.
- At our 50%-of-credit exit, realistically **about 0.29%**.
- **So this does not win a raw P&L leaderboard. Stated up front, not discovered later.**
- What it competes on: reasoning, risk management, and an audit trail nobody else has.

Speaker note: this slide buys credibility for the other eleven.

## 3. What it trades
- Put credit spreads, **21-35 DTE**, short-leg delta **0.15-0.25**, **$1-5 wide**
- Fixed **8-name** liquid universe, **0.75% of equity** per ticket
- Unattended loop: reconcile - scan - gate - size - order - exit
- **No LLM at the wheel.** Deterministic arithmetic decides; the model may only veto.

## 4. The economic engine
- Motor: the **variance risk premium** (Carr and Wu, 2009), not pattern-reading
- Candlesticks were tested and dropped: Marshall, Young and Rose (2007) find no value
  across a majority of DJIA stocks; Park and Irwin find the positive results concentrate
  in pre-2000 FX and futures
- The four signals that earn their place: **IV level and rank, delta as a probability
  proxy, DTE and theta geometry, the earnings calendar**

## 5. Why refusal IS the edge
- Target 0.5x credit, stop 3.0x credit gives a breakeven win rate of **6/7 = 85.7%**
- At that breakeven, the mechanical rules have near-zero naive expected value
- **The gates do not decorate the edge, they stop us destroying one we already have**
- Fail-closed is absolute: unknown earnings date, missing snapshot, account mismatch,
  broker error - each produces **no order at all**

## 6. The gate stack
Eight gates, all must pass:
duration · short-leg delta · width and credit · liquidity · underlying price ·
calendar and earnings · IV regime · portfolio shape

`[LIVE]` This week: **N evaluated, M taken, K refused**, every refusal with a written reason.

## 7. The portfolio gate, and the failure it prevents
- SPY, QQQ and IWM held together are **one bet, not three**
- Cap: **2 per correlated beta-group**, plus a portfolio net-delta cap as a fraction of equity
- The mechanism we defend against is not a blow-up. It is **clustered stops on one
  volatility event, then the refusal layer locking out re-entry**, leaving a negative
  account with no premium left to grind back inside a one-week window.

## 8. The 10x equity trap
- Rules require development on any account and judging on a **fresh $100,000** account
- Ours differ by **10x**. Every risk rule is a percentage of equity.
- A constant calibrated on the dev account makes every judged position **10x too large**
- Defence: equity read from `/v2/account` **at decision time**, never cached, never
  defaulted; **account number asserted before any order**; a test proves the same signal
  gives contract counts exactly 10x apart at identical percentage risk

## 9. Execution on stale data
- Free-tier option quotes are **15 minutes stale**. No free real-time options feed exists
  anywhere, because every vendor pays exchange fees.
- The underlying is live and **IV moves slower than price**, so every spread is repriced
  off the live underlying and the delayed surface
- A quote diverging from our mark beyond tolerance is a **refusal before an order exists**
- `[LIVE]` Measured slippage against our own marks: **X cents per leg**

## 10. Evidence you can check yourself
- **Hash-chained append-only log**: per decision - snapshot, signal, every gate evaluation
  with reasons, order ticket, fill
- The chain can be **verified in the browser** on the hosted demo
- **Offline test suite: ALL GREEN**, including a parity battery proving the browser port
  is byte-identical to the Python core
- Public **MIT** repo, no credentials, no account ids in the tree

## 11. What the week actually did
- `[LIVE]` Equity curve, start to finish
- `[LIVE]` Trades taken, refusals, win rate, P&L **per unit of risk**
- **Liquidated 10:55 ET Friday** so judged P&L equals realized P&L: submissions close
  mid-session at 11:00 ET, and the last 3.5 hours of Friday are unjudged, so removing
  that variance was free

## 12. The honest close
- A field this size contains many accounts up 15% on one lucky bet
- It contains approximately none that can **account for themselves**
- Every position sized from live equity, every refusal written down with a reason,
  every decision hash-chained so the record cannot be edited after the fact
- **AI use disclosed throughout.**

---

## Build checklist
- [ ] Fill every `[LIVE]` from the judged account after Friday's liquidation
- [ ] Delete, do not approximate, any `[LIVE]` that cannot be produced
- [ ] Confirm no account number, key or token appears in any exported image
- [ ] Print to PDF, check it opens on a phone, keep it under 5 MB
