import sys, json, math
sys.path.insert(0,".")
from refuser.bs import bs_greeks
def G(S,K,T,r,s,kind): return bs_greeks(S,K,T,r,s,kind)

bars=json.load(open("/root/spy.json")); c=[b["c"] for b in bars]
rets=[(c[i+5]/c[i]-1.0) for i in range(len(c)-5)]
N=len(rets)

r=0.045; ATM0=0.18; EQ=100_000.0
T1=30/365.0; T2=T1-5/365.0
SKEW=1.0   # pkt IV na 1% OTM (put), calle taniej: polowa nachylenia
def iv(S,K,atm,kind):
    m=(1.0-K/S)*100.0
    if kind=="P": return max(0.05, atm + SKEW*max(0.0,m)/100.0)
    else:         return max(0.05, atm + 0.35*SKEW*max(0.0,-m)/100.0)  # call skew plaszsze
def px(S,K,T,atm,kind): return G(S,K,T,r,iv(S,K,atm,kind),kind)[0]
def dl(S,K,T,atm,kind): return abs(G(S,K,T,r,iv(S,K,atm,kind),kind)[1])
def sfd(S,T,atm,td,kind):
    best,bd=None,9
    K=S; step=-0.5 if kind=="P" else 0.5
    for _ in range(400):
        d=dl(S,K,T,atm,kind)
        if abs(d-td)<bd: bd,best=abs(d-td),K
        K+=step
    return best
def atm_after(ret):
    if ret<0: return ATM0*(1.0+1.5*(-ret)*10)      # -3% -> x1.45
    return max(0.08, ATM0*(1.0-0.5*ret*10))         # +3% -> x0.85

S0=552.30
Kps=sfd(S0,T1,ATM0,0.20,"P"); Kpl=Kps-5.0
credit=px(S0,Kps,T1,ATM0,"P")-px(S0,Kpl,T1,ATM0,"P")
risk=(5.0-credit)*100
NPOS=4; n=max(1,int((EQ*0.0075)//risk))
Kc=sfd(S0,T1,ATM0,0.20,"C")          # call delta 0.20
cpx=px(S0,Kc,T1,ATM0,"C")
Kc5=sfd(S0,T1,ATM0,0.08,"C")         # dalszy call
cpx5=px(S0,Kc5,T1,ATM0,"C")
print("BASE short put spread %.1f/%.1f kredyt $%.2f, %d kontr x %d"%(Kps,Kpl,credit,n,NPOS))
print("CALL d0.20 K=%.1f (%.1f%% OTM) $%.2f | CALL d0.08 K=%.1f (%.1f%% OTM) $%.2f"
      %(Kc,(Kc/S0-1)*100,cpx,Kc5,(Kc5/S0-1)*100,cpx5))

def sim(nc20,nc08,label):
    out=[]
    for ret in rets:
        S1=S0*(1+ret); a1=atm_after(ret)
        pb=(credit-(px(S1,Kps,T2,a1,"P")-px(S1,Kpl,T2,a1,"P")))*100*n*NPOS
        pc=((px(S1,Kc,T2,a1,"C")-cpx)*100*nc20 if nc20 else 0.0)
        pc+=((px(S1,Kc5,T2,a1,"C")-cpx5)*100*nc08 if nc08 else 0.0)
        out.append(pb+pc)
    out.sort()
    def q(p): return out[min(N-1,int(p*N))]
    mean=sum(out)/N
    pos=100.0*sum(1 for x in out if x>0)/N
    cost = (nc20*cpx+nc08*cpx5)*100
    print("%-34s koszt$%5.0f | sr %+7.0f (%+.3f%%) | med %+6.0f | p05 %+7.0f | p95 %+7.0f | p99 %+8.0f | dod %5.1f%% | P(>+2%%) %4.2f%%"
          %(label,cost,mean,mean/EQ*100,q(0.50),q(0.05),q(0.95),q(0.99),pos,
            100.0*sum(1 for x in out if x>0.02*EQ)/N))
    return out

print("\n=== ROZKLADY na %d rzeczywistych sciezkach 5-sesyjnych ==="%N)
sim(0,0,"A. sam short put spread")
sim(1,0,"B. + 1 call d0.20")
sim(2,0,"C. + 2 calle d0.20")
sim(0,3,"D. + 3 calle d0.08 (tansze)")
sim(0,6,"E. + 6 calli d0.08")
sim(1,3,"F. barbell 1x d0.20 + 3x d0.08")
