import sys
sys.path.insert(0,".")
from refuser.bs import bs_greeks
def G(S,K,T,r,s): return bs_greeks(S,K,T,r,s,"P")
S0,r = 552.30,0.045
ATM=0.18; EQ,RISK,NPOS=100_000.0,0.0075,4
T1,HOLD=30/365.0,5/365.0; T2=T1-HOLD
SKEW_PTS_PER_PCT = 1.0     # 1 pkt IV na 1% OTM: ATM 18% -> 8% OTM ~26%. Zgodne z typowym skew SPX.

def iv(S,K,atm):
    otm_pct = max(0.0,(1.0 - K/S)*100.0)
    return max(0.05, atm + SKEW_PTS_PER_PCT*otm_pct/100.0)
def px(S,K,T,atm): return G(S,K,T,r,iv(S,K,atm))[0]
def dl(S,K,T,atm): return abs(G(S,K,T,r,iv(S,K,atm))[1])
def sfd(S,T,atm,td):
    best,bd,K=None,9,S
    while K>S*0.60:
        d=dl(S,K,T,atm)
        if abs(d-td)<bd: bd,best=abs(d-td),K
        K-=0.5
    return best

print("=== KALIBRACJA SKEW (kontrola zdrowego rozsadku) ===")
for k in (552.3,530,510,495,480):
    print("  K=%.0f (%.1f%% OTM) IV=%.1f%% cena $%.2f delta %.3f"%(k,(k/S0-1)*100,iv(S0,k,ATM)*100,px(S0,k,T1,ATM),dl(S0,k,T1,ATM)))

IVS={0.0:1.00,-0.03:1.45,-0.05:1.90,-0.07:2.40,-0.10:3.20}
PR ={0.0:0.9310,-0.03:0.0491,-0.05:0.0146,-0.07:0.0040,-0.10:0.0013}
Ks=sfd(S0,T1,ATM,0.20); Kl=Ks-5.0
cr=px(S0,Ks,T1,ATM)-px(S0,Kl,T1,ATM)
rp=(5.0-cr)*100; n=max(1,int((EQ*RISK)//rp))
Kw=sfd(S0,T1,ATM,0.05); wp=px(S0,Kw,T1,ATM)
print("\n=== BOOK ===")
print("short K=%.1f (delta %.3f, IV %.1f%%) long %.1f | kredyt $%.2f | %d kontr x %d = maks $%.0f/tydz (%.2f%%)"
      %(Ks,dl(S0,Ks,T1,ATM),iv(S0,Ks,ATM)*100,Kl,cr,n,NPOS,cr*100*n*NPOS,cr*100*n*NPOS/EQ*100))
print("=== SLEEVE: skrzydlo K=%.1f (%.1f%% OTM) IV=%.1f%% cena $%.2f = $%.0f/szt"
      %(Kw,(Kw/S0-1)*100,iv(S0,Kw,ATM)*100,wp,wp*100))

for BP in (0.0025,0.005,0.010):
    bud=EQ*BP; nw=max(1,int(bud//(wp*100)))
    print("\n##### SLEEVE %.2f%% = $%.0f -> %d szt (koszt $%.0f = %.2f%% konta) #####"%(BP*100,bud,nw,nw*wp*100,nw*wp*100/EQ*100))
    print("%7s %7s %10s %10s %10s %9s"%("ruch","praw.","book","sleeve","razem","razem %"))
    e0=e1=0.0
    for mv,p in PR.items():
        S1=S0*(1+mv); a1=ATM*IVS[mv]
        pb=(cr-(px(S1,Ks,T2,a1)-px(S1,Kl,T2,a1)))*100*n*NPOS
        ps=(px(S1,Kw,T2,a1)-wp)*100*nw
        e0+=p*pb; e1+=p*(pb+ps)
        print("%6.0f%% %6.2f%% %+9.0f %+9.0f %+9.0f %+8.2f%%"%(mv*100,p*100,pb,ps,pb+ps,(pb+ps)/EQ*100))
    print("  EV bez=%+.0f (%+.3f%%)   ze=%+.0f (%+.3f%%)   ROZNICA=%+.0f"%(e0,e0/EQ*100,e1,e1/EQ*100,e1-e0))
    print("  P(tydzien na minusie): bez=%.1f%%  ze=%.1f%%"
          %(sum(p for mv,p in PR.items() if (cr-(px(S0*(1+mv),Ks,T2,ATM*IVS[mv])-px(S0*(1+mv),Kl,T2,ATM*IVS[mv])))*100*n*NPOS<0)*100,
            sum(p for mv,p in PR.items() if ((cr-(px(S0*(1+mv),Ks,T2,ATM*IVS[mv])-px(S0*(1+mv),Kl,T2,ATM*IVS[mv])))*100*n*NPOS+(px(S0*(1+mv),Kw,T2,ATM*IVS[mv])-wp)*100*nw)<0)*100))
