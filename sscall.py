import sys, json
sys.path.insert(0,".")
from refuser.bs import bs_greeks
def px(S,K,T,r,s,k): return bs_greeks(S,K,T,r,s,k)[0]
def dl(S,K,T,r,s,k): return abs(bs_greeks(S,K,T,r,s,k)[1])
r=0.045; T1=30/365.0; T2=T1-5/365.0

# realistyczne IV ATM (typowe poziomy dla tych nazw poza earnings)
IVS={"SPY":0.18,"QQQ":0.20,"NVDA":0.45,"TSLA":0.55,"AMD":0.45,"META":0.35,
     "AAPL":0.28,"AVGO":0.40,"MSTR":0.75,"COIN":0.70,"PLTR":0.60,"SMCI":0.70}

import urllib.request
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
    for _ in range(600):
        d=dl(S,Kx,T,r,s,kind)
        if abs(d-td)<bd: bd,best=abs(d-td),Kx
        Kx+=step
    return best

print("LONG CALL delta 0.20, 30 DTE, trzymany 5 sesji. Zwrot NA ZAINWESTOWANY DOLAR.")
print("%-6s %5s %8s %8s %8s %8s %9s %9s"%("sym","IV","sr zwr","med","p95","p99","P(>0)","P(>2x)"))
for s,iv0 in IVS.items():
    try: c=hist(s)
    except Exception as e: print("%-6s blad"%s); continue
    if len(c)<300: continue
    S0=c[-1]
    Kc=sfd(S0,T1,iv0,0.20,"C"); c0=px(S0,Kc,T1,r,iv0,"C")
    if c0<=0.01: continue
    rets=[(c[i+5]/c[i]-1.0) for i in range(len(c)-5)]
    pnl=[]
    for rt in rets:
        S1=S0*(1+rt)
        iv1=iv0*(1.0-0.30*rt*3)          # IV spada gdy rosnie (skos), rosnie przy spadku
        iv1=max(0.10,min(3.0,iv1))
        pnl.append((px(S1,Kc,T2,r,iv1,"C")-c0)/c0)
    pnl.sort(); n=len(pnl); q=lambda p: pnl[min(n-1,int(p*n))]
    print("%-6s %4.0f%% %+7.1f%% %+7.1f%% %+7.1f%% %+7.1f%% %8.1f%% %8.1f%%"
          %(s,iv0*100,sum(pnl)/n*100,q(0.50)*100,q(0.95)*100,q(0.99)*100,
            100.0*sum(1 for x in pnl if x>0)/n, 100.0*sum(1 for x in pnl if x>1.0)/n))
