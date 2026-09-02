# Gate funnel — aggregate

- chain: **204 records, head `c43f3f9174bceebf…`** (verified on load)
- entries evaluated: **204** — ACCEPT **0**, REFUSE **204**

| gate | pass | fail | pass rate |
|---|---:|---:|---:|
| `width_credit` | 0 | 204 | 0% |
| `liquidity` | 15 | 189 | 7% |
| `iv` | 134 | 70 | 66% |
| `net_delta` | 194 | 10 | 95% |
| `underlying` | 197 | 7 | 97% |
| `short_delta` | 204 | 0 | 100% |
| `portfolio` | 204 | 0 | 100% |
| `dte` | 204 | 0 | 100% |
| `calendar` | 204 | 0 | 100% |

## Near-misses — blocked by exactly one market gate (9)

- **QQQ** seq 72 — only `width_credit`: width=5.00 credit=0.42 risk=4.58
- **QQQ** seq 101 — only `width_credit`: width=5.00 credit=0.55 risk=4.45
- **QQQ** seq 111 — only `width_credit`: width=5.00 credit=0.64 risk=4.36
- **QQQ** seq 121 — only `width_credit`: width=5.00 credit=0.70 risk=4.30
- **QQQ** seq 131 — only `width_credit`: width=5.00 credit=0.81 risk=4.19
- **QQQ** seq 133 — only `width_credit`: width=5.00 credit=0.82 risk=4.18
- **IWM** seq 152 — only `width_credit`: width=5.00 credit=0.58 risk=4.42
- **IWM** seq 160 — only `width_credit`: width=5.00 credit=0.64 risk=4.36
- **AAPL** seq 175 — only `width_credit`: width=5.00 credit=0.60 risk=4.39

## Credit headroom

- best credit seen: **1.00** (MSFT, seq 182) — gate needs ≥ 1.00; short
- candidates with credit ≥ 1.00: **1 / 204** — every one was refused on another gate

_Full per-candidate anatomy: refuser.digest.render on the same journal (appendix)._
