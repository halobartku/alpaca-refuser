# The Refuser - video script for the required MP4 (under 5 minutes)

Written 2026-08-30 by Claude. Target runtime **4:30**, hard cap 5:00.
Every `[LIVE]` marker is a number that must be read off the judged account at
recording time and never typed from memory. If a `[LIVE]` number cannot be
produced, cut the sentence rather than approximating it.

**Recording is blocked until Alpaca keys for PA3YVMJ3YVDZ work** (they currently
return HTTP 401). Everything else in this script can be rehearsed and the slides
built now.

---

## 0:00 - 0:22  COLD OPEN. Lead with the number that frames everything.

VISUAL: black screen, one line of white text, then the terminal.

VOICE:
> A defined-risk short-premium book, sized at four percent portfolio heat, has a
> hard ceiling of about half a percent a week. That is arithmetic, not modesty.
> So this agent will not win a raw profit-and-loss leaderboard, and I am not going
> to pretend otherwise. What it does instead is the thing none of the others can:
> it shows you every trade it refused, and why.

WHY THIS OPENING: judges see many decks claiming an edge. Opening by conceding the
criterion you cannot win buys credibility for every claim that follows, and it is true.

## 0:22 - 1:00  WHAT IT IS, in one breath.

VISUAL: architecture diagram, 8 modules, arrows: reconcile - scan - gate - size - order - exit.

VOICE:
> The Refuser sells put credit spreads, twenty-one to thirty-five days out,
> short-leg delta between fifteen and twenty-five, on a fixed eight-name universe,
> sized at three quarters of one percent of equity per ticket.
> There is no language model at the wheel. The decision core is deterministic
> arithmetic: a Black-Scholes repricer validated against Hull's canonical example
> and put-call parity, maximum error one-point-four times ten to the minus fourteen.
> The volatility risk premium is the motor. The gate stack is the transmission.

## 1:00 - 2:05  THE DEMO. This is the heart. Show a REFUSAL, not a fill.

VISUAL: live terminal. Run one scan cycle against the judged account.

VOICE:
> Here is a live cycle. It reconciles against the broker first, because after any
> restart the agent must ask Alpaca what it holds and never trust its own memory.
> Then it scans. Watch what happens to this candidate.

ON SCREEN: a candidate failing a gate, with the reason printed.

VOICE:
> Refused. The earnings date inside the expiry window could not be confirmed, and
> an unknown earnings date is a refusal, not a shrug. Fail-closed is absolute here:
> unknown data, missing snapshot, account mismatch, broker error - every one of
> those produces no order at all. A wrong number is never better than no trade.

> `[LIVE]` So far this week the agent has evaluated N candidates, taken M, and
> refused K, and every one of those K carries a written reason.

WHY THIS SCENE: criterion one is P&L and we lose it. Criteria two through five are
reasoning, risk management and engineering, and a refusal with a reason demonstrates
all three in twenty seconds.

## 2:05 - 2:50  THE GATE STACK and the audit trail.

VISUAL: the eight-row gate table, then a scroll of the hash-chained log.

VOICE:
> Eight gates. Every entry passes all of them or no order exists. Duration,
> delta, structure, liquidity, underlying price, calendar, volatility regime,
> and portfolio shape.
> That last one matters more than it looks. Holding SPY, QQQ and IWM at once is
> not three positions, it is one bet. So there is a cap of two per correlated
> beta-group and a portfolio net-delta cap expressed as a fraction of equity.
> The failure mode we are defending against is not a blow-up. It is clustered
> stops on a single volatility event, followed by a refusal layer that locks out
> re-entry, leaving a negative account with no premium left to grind back inside
> a one-week window.
> Every decision, every gate evaluation, every fill is appended to a hash-chained
> log. You can verify the chain yourself in the browser, on the hosted demo.

## 2:50 - 3:30  THE TRAP WE BUILT AGAINST. Judges remember specifics.

VISUAL: side-by-side, two account numbers, two equity figures, two contract counts.

VOICE:
> The rules require development on any account and judging on a fresh hundred
> thousand dollar account. Ours differ by ten times. Every risk rule here is a
> percentage of equity, so a constant calibrated on the development account would
> make every position ten times too large on the judged one, and the first bad day
> would be unrecoverable.
> So equity is read from the account endpoint at decision time, never cached and
> never defaulted, the account number is asserted before any order exists, and
> there is a test proving the same signal produces contract counts exactly ten
> times apart at identical percentage risk.

## 3:30 - 4:05  EXECUTION QUALITY. The constraint turned into the differentiator.

VISUAL: live underlying tick next to a fifteen-minute-old option quote, then our mark.

VOICE:
> Free-tier option data is fifteen minutes stale. There is no free real-time
> options feed anywhere, because every vendor pays exchange fees. Most entries
> will send market orders against stale quotes and celebrate fantasy fills.
> We reprice instead: the underlying is live, implied volatility moves slower
> than price, so every spread is marked off the live underlying and the delayed
> surface. If a quote diverges from our own mark beyond tolerance, that is a
> refusal before an order exists, not a bad fill afterwards.
> `[LIVE]` Measured slippage against our own marks this week: X cents per leg.

## 4:05 - 4:30  CLOSE. Honest, and therefore memorable.

VISUAL: the account equity curve, whatever it actually is, plus the refusal counter.

VOICE:
> `[LIVE]` The judged account finished the week at X percent.
> I said at the start this would not win on profit and loss, and it did not.
> What it can do is account for itself: every position sized from live equity,
> every refusal written down with a reason, every decision hash-chained so the
> record cannot be edited after the fact.
> A field this large will contain many accounts up fifteen percent on one lucky
> bet, and approximately none that can explain themselves. That is the entry.

---

## Production notes

- **Screen recording, no talking head.** Terminal plus browser. Faster to produce,
  and it keeps attention on the artefact.
- **Record after Friday's 10:55 ET liquidation**, so the closing equity number is
  final and judged P&L equals realized P&L.
- **Do not speed up the terminal.** A judge watching a real refusal happen at real
  speed is the whole point.
- **Disclose AI use** in the description, as we do everywhere.
- **Cut to 4:30.** Five minutes is the cap, not the target; the last thirty seconds
  of a capped video are the ones that get skipped.
