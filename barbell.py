import sys, json, urllib.request, math, random
sys.path.insert(0,".")
from refuser.bs import bs_greeks
def px(S,K,T,r,s,k): return bs_greeks(S,K,T,r,s,k)[0]
def dl(S,K,T,r,s,k): return abs(bs_greeks(S,K,T,r,s,k)[1])
r=0.045; T1=30/365.0; T2=T1-5/365.0; EQ=100_000.0
K="/workspace/forge/keys/alpaca.env"
env={}
for l in open(K):
    if "=" in l: a,b=l.strip().split("=",1); env[a]=b
H={"APCA-API-KEY-ID":env["APCA_API_KEY_ID"],"APCA-API-SECRET-KEY":env["APCA_API_SECRET_KEY"]}
def hist(s):
    bars,tok=[],None
    u=("https://data.alpaca.markets/v2/stocks/%s/bars?timeframe=1Day"
       "&start=2018-01-01T00:00:00Z&end=2026-08-27T00:00:00Z&limit=10000&feed=iex")%s
    while True:
        rq=urllib.request.Request(u+(("&page_token="+tok) if tok else ""),headers=H)
        d=json.load(urllib.request.urlopen(rq,timeout=60)); bars+=d.get("bars") or []
        tok=d.get("next_page_token")
        if not tok: break
    return [b["c"] for b in bars]
def sfd(S,T,s,td,kind):
    best,bd=None,9; Kx=S; step=0.5 if kind=="C" else -0.5
    for _ in range(700):
        d=dl(S,Kx,T,r,s,kind)
        if abs(d-td)<bd: bd,best=abs(d-td),Kx
        Kx+=step
    return best

# --- CORE: short put spread na SPY, uczciwa IV
spy=hist("SPY"); S0=spy[-1]
sr=[(spy[i+5]/spy[i]-1.0) for i in range(len(spy)-5)]
mu_s=sum(sr)/len(sr)
rv_s=math.sqrt(sum((x-mu_s)**2 for x in sr)/len(sr))*math.sqrt(252.0/5)
iv_s=rv_s*1.15
Kps=sfd(S0,T1,iv_s,0.20,"P"); Kpl=Kps-5.0
cred=px(S0,Kps,T1,r,iv_s,"P")-px(S0,Kpl,T1,r,iv_s,"P")
risk=(5.0-cred)*100; ncore=max(1,int((EQ*0.0075)//risk)); NPOS=4
print("CORE: SPY spread %.1f/%.1f IV %.0f%% kredyt $%.2f, %d x %d poz."%(Kps,Kpl,iv_s*100,cred,ncore,NPOS))

# --- SATELLITE: long calle na koszyku zmiennych nazw, uczciwa IV, dryf usuniety
SAT=["NVDA","AMD","META","PLTR","COIN"]
sat={}
for s in SAT:
    c=hist(s); Sx=c[-1]
    rs=[(c[i+5]/c[i]-1.0) for i in range(len(c)-5)]
    m=sum(rs)/len(rs); rv=math.sqrt(sum((x-m)**2 for x in rs)/len(rs))*math.sqrt(252.0/5)
    iv=rv*1.08
    Kc=sfd(Sx,T1,iv,0.20,"C"); c0=px(Sx,Kc,T1,r,iv,"C")
    sat[s]=(Sx,Kc,c0,iv,[x-m for x in rs])
    print("  SAT %-5s IV %3.0f%% call K=%.1f cena $%.2f"%(s,iv*100,Kc,c0))

NS=len(sr)-1
def portfolio(alloc_pct, trials=4000):
    res=[]
    for _ in range(trials):
        i=random.randrange(min(NS,min(len(v[4]) for v in sat.values())))
        # core
        x=sr[i]-mu_s
        S1=S0*(1+x); iv1=max(0.08,iv_s*(1.0+1.5*max(0,-x)*10-0.5*max(0,x)*10))
        pb=(cred-(px(S1,Kps,T2,r,iv1,"P")-px(S1,Kpl,T2,r,iv1,"P")))*100*ncore*NPOS
        # satellite: rowny podzial budzetu na 5 nazw, ten sam indeks czasu
        budget=EQ*alloc_pct; per=budget/len(sat)
        ps=0.0
        for s,(Sx,Kc,c0,iv,drs) in sat.items():
            nq=int(per//(c0*100))
            if nq<1: continue
            y=drs[i]
            S2=Sx*(1+y); iv2=max(0.10,min(3.5,iv*(1.0-0.30*y*3)))
            ps+=(px(S2,Kc,T2,r,iv2,"C")-c0)*100*nq
        res.append((pb+ps)/EQ)
    res.sort(); n=len(res)
    q=lambda p: res[min(n-1,int(p*n))]
    return (sum(res)/n, q(0.50), q(0.95), q(0.99),
            100.0*sum(1 for x in res if x>0)/n,
            100.0*sum(1 for x in res if x>0.05)/n,
            100.0*sum(1 for x in res if x>0.10)/n,
            100.0*sum(1 for x in res if x<-0.05)/n)

random.seed(7)
print("\n=== BARBELL: ile konta w satelicie (long calle) ===")
print("%7s %8s %8s %8s %8s %8s %9s %9s %9s"%("alok.","srednia","mediana","p95","p99","P(>0)","P(>+5%)","P(>+10%)","P(<-5%)"))
for a in (0.0,0.005,0.01,0.02,0.03,0.05,0.08):
    m,med,p95,p99,pos,p5,p10,dn=portfolio(a)
    print("%6.1f%% %+7.2f%% %+7.2f%% %+7.2f%% %+7.2f%% %7.1f%% %8.2f%% %8.2f%% %8.2f%%"
          %(a*100,m*100,med*100,p95*100,p99*100,pos,p5,p10,dn))
