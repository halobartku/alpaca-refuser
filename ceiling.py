import sys
sys.path.insert(0,".")
from refuser.bs import bs_greeks
def G(S,K,T,r,s): return bs_greeks(S,K,T,r,s,"P")
S0,r,ATM=552.30,0.045,0.18
T1=30/365.0
SK=1.0
def iv(S,K,atm):
    o=max(0.0,(1.0-K/S)*100.0); return max(0.05,atm+SK*o/100.0)
def px(S,K,T,atm): return G(S,K,T,r,iv(S,K,atm))[0]
def dl(S,K,T,atm): return abs(G(S,K,T,r,iv(S,K,atm))[1])
def sfd(S,T,atm,td):
    best,bd,K=None,9,S
    while K>S*0.60:
        d=dl(S,K,T,atm)
        if abs(d-td)<bd: bd,best=abs(d-td),K
        K-=0.5
    return best

print("SUFIT ZYSKU przy naszych wlasnych limitach ryzyka, konto $100k")
print("%6s %8s %9s %9s %9s %11s %12s"%("delta","szer.","kredyt","ryzyko","kr/ryz","maks/tydz","% konta"))
HEAT = 0.04   # nasz limit: 4% konta w ryzyku jednoczesnie
for d_t in (0.15,0.20,0.25):
    for w in (5.0,10.0,25.0):
        Ks=sfd(S0,T1,ATM,d_t); Kl=Ks-w
        cr=px(S0,Ks,T1,ATM)-px(S0,Kl,T1,ATM)
        risk=(w-cr)*100
        if risk<=0: continue
        ratio=cr*100/risk
        # ile ryzyka miesci sie w limicie 4%
        total_risk=100_000.0*HEAT
        max_credit=total_risk*ratio
        print("%6.2f %8.0f %9.2f %9.0f %8.1f%% %+10.0f %+11.3f%%"
              %(d_t,w,cr,risk,ratio*100,max_credit,max_credit/1000.0))
print()
print("Uwaga: 'maks/tydz' zaklada 100% zatrzymanego kredytu na CALYM dopuszczalnym ryzyku,")
print("czyli scenariusz doskonaly, nieosiagalny. Nasza regula wyjscia bierze 50% kredytu.")
print("Realistyczny sufit = polowa powyzszego, przy zalozeniu ZERO strat w tygodniu.")
