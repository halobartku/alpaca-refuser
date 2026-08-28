# refuser

> Defined-risk options income where the differentiator is what it **refuses**.
> VRP is the motor; the gates are the transmission.

An autonomous agent that sells put credit spreads on 8 liquid US names —
and refuses most of what it looks at. Every entry passes a fail-closed gate
stack before an order exists; anything ambiguous is a refusal, never a
guess. Built for the Alpaca "Options Alpha Agents" hackathon, Sept 2026.

## The thesis in three sentences

1. Short put spreads harvest the volatility risk premium with defined,
   booked risk: max loss is width minus credit, known at fill.
2. The edge is not the entry — it is the stack of gates that refuses
   entries when liquidity, calendar, IV regime, or portfolio construction
   says no. Refusal is the P&L engine: at 0.5x take-profit and 3.0x
   stop-loss the breakeven win rate is exactly 6/7 = **85.7%**, so every
   trade you don't take is worth as much as one you win.
3. Every decision is written to a hash-chained append-only log — data
   snapshot, every gate evaluation, order ticket, fill, post-mortem — so
   any judge can replay the week with one command.

## One-command test suite

```
python3 run_tests.py
```

91 checks across the core engine and the full offline trading path
(through a fixture-driven broker adapter — zero network, zero credentials):

- Black-Scholes repricer validated against Hull's canonical example and
  put-call parity across a 144-point grid (max error 1.4e-14).
- 8-entry gate stack, fail-closed: all gates run, all failures reported.
- Exit engine: 6 rules in priority order, first-hit-fires.
- Hash-chained decision log: single-byte tamper flips raise on reload.
- The both-equities sizing test: the same signal on $100k and $1M
  accounts produces exactly 10x contracts and identical percentage risk —
  sizing is read from the account endpoint at decision time, never
  defaulted (the guard that prevents tester-calibrated runs leaking into
  the judged account).
- Design finding, documented not patched: at $1M and 0.75% risk/trade,
  sizing demands 20 contracts on a $5-wide spread, which the absolute
  net-delta cap (±30 shares) refuses. Conservative by construction.

## Repository layout

```
refuser/           core engine (no I/O except the decision log)
  bs.py            Black-Scholes prices/greeks, dependency-free
  gates.py         fail-closed entry gates + sizing
  exits.py         exit engine (50% target, delta stop, 21-DTE, 3x loss,
                   Friday flatten, event flatten)
  portfolio.py     correlation groups + deterministic candidate selection
  ordermech.py     quote integrity, limit construction, penny walk policy
  universe.py      fixed 8-name universe + earnings/event calendar
  log.py           hash-chained append-only decision log
  reconcile.py     broker state overrides memory after restarts
  broker.py        THE seam: BaseBroker interface + FixtureBroker (offline)
  live.py          AlpacaBroker (live REST client) — swap-in, one line
fixtures/          model-derived fixtures + full-path integration test
run_tests.py       runs everything, one command, zero network
```

## Design rules the code enforces

- **Fail-closed everywhere.** Unknown earnings date → refuse. Snapshot
  missing → refuse. Account number mismatch → refuse. A wrong number is
  never better than no trade.
- **Equity read at decision time.** Sizing percentages are computed from
  the account endpoint on every decision, never cached, never defaulted.
- **One seam for the broker.** All Alpaca calls go through `BaseBroker`.
  Tests run against `FixtureBroker`; going live is swapping one
  constructor. Live-API assumptions are flagged in `refuser/live.py` so
  first contact with the real API surfaces wrong assumptions fast.
- **No rolling, no adjustments.** Week 1 is proof of discipline.
- **The book is fixed:** short put spreads, 21–35 DTE, 0.15–0.25 short
  delta, 8 names. No convexity sleeve — that is an explicit open decision,
  deliberately not built.

## License

MIT — see [LICENSE](LICENSE).
