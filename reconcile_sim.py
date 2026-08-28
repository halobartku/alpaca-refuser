"""Full-week distribution reconciliation — MY corrected numbers (Bartosz's ask #3).

Corrected inputs (gap memo + A.116/A.117):
- carry ceiling 0.15-0.25%/week at sane heat, on carry capital (80-85% of acct)
- 4.7 judged sessions (not 5.5)
- catalyst ladder: DELL 4% + AVGO 8% + NTAP 2% + HPE 2% (=16% at "15-20%" alloc),
  defined-risk debit spreads, sequential draws, Dubins-Savage escalation
  (behind after Wed close -> remaining budget in bolder, higher-multiple strikes)

Per-ticket distribution (my honest read of the flashalpha conditional:
small implied move -> larger print; we still pay for gamma):
  big win   p=0.22  -> +2.3x allocation (spread goes ITM)
  partial   p=0.23  -> +0.5x
  scratch   p=0.15  -> -0.1x (IV crush eats an incomplete move)
  loss      p=0.40  -> -1.0x (debit dies)
EV = +0.21x per unit, fat right tail. Escalated (trailing) tickets:
  p_win 0.16 -> +4.5x, partial 0.14 -> +0.8x, scratch 0.15 -> -0.1x, loss 0.55 -> -1.0x
  (EV -0.06x: escalation buys P(target), not EV — that is the point.)

Carry on its capital: 88% of weeks N(+0.22%, 0.10%); 12% "bad week" N(-1.5%, 0.6%)
  -> weekly median ~+0.19%, p5 ~ -0.9%, matching the 0.15-0.25 ceiling at sane heat.
"""
import random

CARRY_GOOD = (0.88, 0.0022, 0.0010)
CARRY_BAD = (0.12, -0.0150, 0.0060)
TKT = [(0.22, 2.3), (0.23, 0.50), (0.15, -0.10), (0.40, -1.00)]
TKT_ESC = [(0.16, 4.50), (0.14, 0.80), (0.15, -0.10), (0.55, -1.00)]


def draw(dist):
    u, acc = random.random(), 0.0
    for p, v in dist:
        acc += p
        if u < acc:
            return v
    return dist[-1][1]


def week(alloc):
    """Returns total week P&L as fraction of starting account."""
    # --- carry on 100-alloc% of capital (risk budget, not notional)
    p, m, s = CARRY_GOOD if random.random() < CARRY_GOOD[0] else CARRY_BAD
    carry = random.gauss(m, s) * (1.0 - alloc)
    # --- catalyst ladder: fractions of TOTAL account summing to alloc
    w = [0.25, 0.50, 0.125, 0.125]           # DELL, AVGO, NTAP, HPE shares of budget
    tickets = [alloc * x for x in w]
    pnl = 0.0
    fired = 0
    for i, size in enumerate(tickets):
        # escalation checkpoint: after ticket 2 (Wed close) if cum pnl < -1%
        dist = TKT_ESC if (fired >= 2 and pnl < -0.01) else TKT
        pnl += size * draw(dist)
        fired += 1
    return carry + pnl


def run(alloc, n=200000, seed=7):
    random.seed(seed)
    rs = sorted(week(alloc) for _ in range(n))
    q = lambda p: rs[int(p * n)]
    return {
        "alloc": alloc,
        "median": q(0.50), "mean": sum(rs) / n,
        "p5": q(0.05), "p95": q(0.95),
        "P_ge_10.6": sum(1 for x in rs if x >= 0.106) / n,
        "P_ge_7.8": sum(1 for x in rs if x >= 0.078) / n,
        "P_le_-10": sum(1 for x in rs if x <= -0.10) / n,
        "P_le_-15": sum(1 for x in rs if x <= -0.15) / n,
    }


if __name__ == "__main__":
    print(f"{'alloc':>5} {'median':>8} {'mean':>8} {'p5':>7} {'p95':>7} "
          f"{'P>=10.6%':>9} {'P<=-10%':>8} {'P<=-15%':>8}")
    for a in (0.10, 0.15, 0.16, 0.20, 0.25, 0.30):
        r = run(a)
        print(f"{a*100:4.0f}% {r['median']*100:+7.2f}% {r['mean']*100:+7.2f}% "
              f"{r['p5']*100:+6.1f}% {r['p95']*100:+6.1f}% "
              f"{r['P_ge_10.6']*100:8.2f}% {r['P_le_-10']*100:7.2f}% "
              f"{r['P_le_-15']*100:7.2f}%")
