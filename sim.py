import sys
sys.path.insert(0, ".")
from refuser.bs import bs_greeks, put_spread_mark

# ZALOZENIA, jawne
S0, r = 552.30, 0.045
IV0 = 0.18                # ATM IV spokojny rezim
EQ  = 100_000.0           # konto oceniane
RISK_PCT = 0.0075         # 0.75% na pozycje
DTE_ENTRY, HOLD = 30/365.0, 5/365.0
N_POS = 4                 # 4 rownolegle spready

# skok IV wg wielkosci spadku, kalibracja z historii VIX (podane jako zalozenie)
IV_SHOCK = {0.0: 1.00, -0.03: 1.45, -0.05: 1.90, -0.07: 2.40, -0.10: 3.20}
PROB     = {0.0: 0.931, -0.03: 0.0491, -0.05: 0.0146, -0.07: 0.0040, -0.10: 0.0013}

def leg(S, K, T, sig, kind="P"):
    return bs_greeks(S, K, T, r, sig, kind)

# --- BOOK: short put spread, short leg ~0.20 delta, 5 szeroki
def find_strike(S, T, sig, target_delta):
    best, bd = None, 9
    K = S
    while K > S*0.70:
        g = leg(S, K, T, sig)
        d = abs(g["delta"] if isinstance(g, dict) else g[0])
        if abs(d-target_delta) < bd: bd, best = abs(d-target_delta), K
        K -= 0.5
    return best

Ks = find_strike(S0, DTE_ENTRY, IV0, 0.20)
Kl = Ks - 5.0
credit0 = put_spread_mark(S0, Ks, Kl, DTE_ENTRY, r, IV0)
risk_per = (5.0 - credit0) * 100
n_contracts = int((EQ*RISK_PCT) // risk_per)
print("=== BOOK ===")
print("short K=%.1f long K=%.1f  kredyt=%.3f  ryzyko/kontrakt=$%.0f  kontraktow=%d x %d pozycji"
      % (Ks, Kl, credit0, risk_per, n_contracts, N_POS))

# --- SLEEVE: dlugie OTM puty ~0.05 delta, 30 DTE
Kw = find_strike(S0, DTE_ENTRY, IV0, 0.05)
gw = leg(S0, Kw, DTE_ENTRY, IV0)
w_price = gw["price"] if isinstance(gw, dict) else gw[-1]
print("=== SLEEVE ===")
print("skrzydlo K=%.1f (%.1f%% OTM)  cena=%.3f  = $%.0f/kontrakt"
      % (Kw, (Kw/S0-1)*100, w_price, w_price*100))

for BUDGET_PCT in (0.002, 0.005, 0.010):
    budget = EQ*BUDGET_PCT
    n_w = max(1, int(budget // (w_price*100)))
    print("\n########## SLEEVE = %.1f%% konta = $%.0f -> %d skrzydel ##########"
          % (BUDGET_PCT*100, budget, n_w))
    T2 = DTE_ENTRY - HOLD
    ev_no, ev_sl = 0.0, 0.0
    print("%8s %6s | %10s %10s | %10s %10s" % ("ruch","praw.","book","book %","z sleeve","z sleeve %"))
    for mv, p in PROB.items():
        S1 = S0*(1+mv); sig1 = IV0*IV_SHOCK[mv]
        m1 = put_spread_mark(S1, Ks, Kl, T2, r, sig1)
        pnl_book = (credit0 - m1)*100*n_contracts*N_POS
        g1 = leg(S1, Kw, T2, sig1)
        w1 = g1["price"] if isinstance(g1, dict) else g1[-1]
        pnl_sleeve = (w1 - w_price)*100*n_w
        tot = pnl_book + pnl_sleeve
        ev_no += p*pnl_book; ev_sl += p*tot
        print("%7.0f%% %5.2f%% | %+9.0f %+9.2f%% | %+9.0f %+9.2f%%"
              % (mv*100, p*100, pnl_book, pnl_book/EQ*100, tot, tot/EQ*100))
    print("  EV bez sleeve: %+8.0f (%+.3f%%)   EV ze sleeve: %+8.0f (%+.3f%%)   koszt EV: %+.0f"
          % (ev_no, ev_no/EQ*100, ev_sl, ev_sl/EQ*100, ev_sl-ev_no))
