import sys
sys.path.insert(0, ".")
from refuser.bs import bs_greeks

def g(S,K,T,r,s): return bs_greeks(S,K,T,r,s,"P")
S0, r = 552.30, 0.045
ATM_IV = 0.18
EQ, RISK_PCT, N_POS = 100_000.0, 0.0075, 4
T1, HOLD = 30/365.0, 5/365.0; T2 = T1-HOLD

# SKEW: IV rosnie im dalej OTM. SPX ~2.5 pkt IV na 1% moneyness w tym zakresie.
SKEW = 0.025
def iv_of(S,K,atm):
    m = (K/S - 1.0)          # ujemne dla OTM puta
    return max(0.05, atm + SKEW*(-m)*100*0.01*2.5)

def px(S,K,T,atm): return g(S,K,T,r,iv_of(S,K,atm))[0]
def dl(S,K,T,atm): return abs(g(S,K,T,r,iv_of(S,K,atm))[1])
def strike_for_delta(S,T,atm,td):
    best,bd,K=None,9,S
    while K>S*0.60:
        d=dl(S,K,T,atm)
        if abs(d-td)<bd: bd,best=abs(d-td),K
        K-=0.5
    return best

IV_SHOCK={0.0:1.00,-0.03:1.45,-0.05:1.90,-0.07:2.40,-0.10:3.20}
PROB    ={0.0:0.9310,-0.03:0.0491,-0.05:0.0146,-0.07:0.0040,-0.10:0.0013}

Ks=strike_for_delta(S0,T1,ATM_IV,0.20); Kl=Ks-5.0
credit=px(S0,Ks,T1,ATM_IV)-px(S0,Kl,T1,ATM_IV)
risk_per=(5.0-credit)*100; n=max(1,int((EQ*RISK_PCT)//risk_per))
Kw=strike_for_delta(S0,T1,ATM_IV,0.05); wpx=px(S0,Kw,T1,ATM_IV)
print("SKEW WLACZONY (2.5 pkt IV na 1%% moneyness)")
print("short K=%.1f IV=%.1f%% | long K=%.1f | kredyt $%.2f | %d kontr x %d poz"%(Ks,iv_of(S0,Ks,ATM_IV)*100,Kl,credit,n,N_POS))
print("skrzydlo K=%.1f (%.1f%% OTM) IV=%.1f%% cena $%.2f  <-- ze skew, bylo $0.60 bez"%(Kw,(Kw/S0-1)*100,iv_of(S0,Kw,ATM_IV)*100,wpx))
print("maks zysk booku/tydz: $%.0f (%.2f%%)"%(credit*100*n*N_POS,credit*100*n*N_POS/EQ*100))

for BP in (0.0025,0.005,0.010):
    bud=EQ*BP; nw=max(1,int(bud//(wpx*100)))
    print("\n===== SLEEVE %.2f%% = $%.0f -> %d skrzydel (koszt $%.0f) ====="%(BP*100,bud,nw,nw*wpx*100))
    print("%7s %7s | %9s %9s %9s %9s"%("ruch","praw.","book","sleeve","razem","razem %"))
    ev0=ev1=0.0
    for mv,p in PROB.items():
        S1=S0*(1+mv); atm1=ATM_IV*IV_SHOCK[mv]
        pb=(credit-(px(S1,Ks,T2,atm1)-px(S1,Kl,T2,atm1)))*100*n*N_POS
        ps=(px(S1,Kw,T2,atm1)-wpx)*100*nw
        ev0+=p*pb; ev1+=p*(pb+ps)
        print("%6.0f%% %6.2f%% | %+8.0f %+8.0f %+8.0f %+8.2f%%"%(mv*100,p*100,pb,ps,pb+ps,(pb+ps)/EQ*100))
    print("  EV bez=%+.0f (%+.3f%%)  ze=%+.0f (%+.3f%%)  ROZNICA=%+.0f"%(ev0,ev0/EQ*100,ev1,ev1/EQ*100,ev1-ev0))
