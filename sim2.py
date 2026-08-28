import sys
sys.path.insert(0, ".")
from refuser.bs import bs_greeks, put_spread_mark
# bs_greeks -> (price, delta, gamma, theta, vega)
def px(S,K,T,r,s): return bs_greeks(S,K,T,r,s,"P")[0]
def dl(S,K,T,r,s): return abs(bs_greeks(S,K,T,r,s,"P")[1])

S0, r = 552.30, 0.045
IV0 = 0.18
EQ, RISK_PCT = 100_000.0, 0.0075
T1, HOLD = 30/365.0, 5/365.0
T2 = T1 - HOLD
N_POS = 4

IV_SHOCK = {0.0:1.00, -0.03:1.45, -0.05:1.90, -0.07:2.40, -0.10:3.20}
PROB     = {0.0:0.9310, -0.03:0.0491, -0.05:0.0146, -0.07:0.0040, -0.10:0.0013}

def strike_for_delta(S,T,s,td):
    best,bd=None,9
    K=S
    while K>S*0.60:
        d=dl(S,K,T,r,s)
        if abs(d-td)<bd: bd,best=abs(d-td),K
        K-=0.5
    return best

Ks=strike_for_delta(S0,T1,IV0,0.20); Kl=Ks-5.0
credit=put_spread_mark(S0,Ks,Kl,T1,r,IV0)
risk_per=(5.0-credit)*100
n=max(1,int((EQ*RISK_PCT)//risk_per))
print("=== BOOK (konto $100k) ===")
print("short K=%.1f (%.1f%% OTM, delta %.3f) long K=%.1f | kredyt $%.2f | ryzyko/kontrakt $%.0f | %d kontr. x %d poz."
      % (Ks,(Ks/S0-1)*100,dl(S0,Ks,T1,r,IV0),Kl,credit,risk_per,n,N_POS))
print("maks. zysk booku (100%% kredytu): $%.0f = %.2f%% konta" % (credit*100*n*N_POS, credit*100*n*N_POS/EQ*100))

Kw=strike_for_delta(S0,T1,IV0,0.05)
wpx=px(S0,Kw,T1,r,IV0)
print("\n=== SLEEVE ===")
print("skrzydlo K=%.1f (%.1f%% OTM, delta %.3f) cena $%.2f = $%.0f/kontrakt"
      % (Kw,(Kw/S0-1)*100,dl(S0,Kw,T1,r,IV0),wpx,wpx*100))

for BP in (0.0025,0.005,0.010):
    bud=EQ*BP; nw=max(1,int(bud//(wpx*100)))
    print("\n===== SLEEVE %.2f%% konta = $%.0f -> %d skrzydel (koszt $%.0f) ====="%(BP*100,bud,nw,nw*wpx*100))
    print("%7s %7s | %9s | %9s %9s | %9s"%("ruch","praw.","book","sleeve","razem","razem %"))
    ev0=ev1=0.0
    for mv,p in PROB.items():
        S1=S0*(1+mv); s1=IV0*IV_SHOCK[mv]
        pb=(credit-put_spread_mark(S1,Ks,Kl,T2,r,s1))*100*n*N_POS
        ps=(px(S1,Kw,T2,r,s1)-wpx)*100*nw
        ev0+=p*pb; ev1+=p*(pb+ps)
        print("%6.0f%% %6.2f%% | %+8.0f | %+8.0f | %+8.0f | %+8.2f%%"%(mv*100,p*100,pb,ps,pb+ps,(pb+ps)/EQ*100))
    print("  EV bez=%+.0f (%+.3f%%)  EV ze=%+.0f (%+.3f%%)  ROZNICA EV=%+.0f"%(ev0,ev0/EQ*100,ev1,ev1/EQ*100,ev1-ev0))
