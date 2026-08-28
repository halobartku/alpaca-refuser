import sys, json, urllib.request, math
sys.path.insert(0,".")
from refuser.bs import bs_greeks
def px(S,K,T,r,s,k): return bs_greeks(S,K,T,r,s,k)[0]
def dl(S,K,T,r,s,k): return abs(bs_greeks(S,K,T,r,s,k)[1])
r=0.045; T1=30/365.0; T2=T1-5/365.0
IVS={"SPY":0.18,"QQQ":0.20,"NVDA":0.45,"TSLA":0.55,"AMD":0.45,"META":0.35,
     "AAPL":0.28,"AVGO":0.40,"MSTR":0.75,"COIN":0.70,"PLTR":0.60,"SMCI":0.70}
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

print("KONTROLA: ile z wyniku to DRYF, a ile wartosc opcji")
print("%-6s %9s %9s %11s | %11s %11s"%("sym","dryf 5d","zreal.vol","IV zalozona","call z dryfem","call BEZ dryfu"))
for s,iv0 in IVS.items():
    try: c=hist(s)
    except Exception: continue
    if len(c)<300: continue
    S0=c[-1]
    rets=[(c[i+5]/c[i]-1.0) for i in range(len(c)-5)]
    n=len(rets); mu=sum(rets)/n
    # zrealizowana zmiennosc roczna z 5-dniowych zwrotow
    var=sum((x-mu)**2 for x in rets)/n
    rv=math.sqrt(var)*math.sqrt(252.0/5.0)
    Kc=sfd(S0,T1,iv0,0.20,"C"); c0=px(S0,Kc,T1,r,iv0,"C")
    if c0<=0.01: continue
    def run(adj):
        out=[]
        for rt in rets:
            x=rt-adj
            S1=S0*(1+x); iv1=max(0.10,min(3.0,iv0*(1.0-0.30*x*3)))
            out.append((px(S1,Kc,T2,r,iv1,"C")-c0)/c0)
        return sum(out)/len(out)
    print("%-6s %+8.2f%% %8.0f%% %10.0f%% | %+10.1f%% %+11.1f%%"
          %(s,mu*100,rv*100,iv0*100,run(0.0)*100,run(mu)*100))
print()
print("dryf 5d = sredni 5-sesyjny zwrot w probie. Jesli 'bez dryfu' jest ujemne,")
print("caly zysk z long calla pochodzil z historycznego trendu, nie z wyceny opcji.")
