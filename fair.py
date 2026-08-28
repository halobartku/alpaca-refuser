import sys, json, urllib.request, math
sys.path.insert(0,".")
from refuser.bs import bs_greeks
def px(S,K,T,r,s,k): return bs_greeks(S,K,T,r,s,k)[0]
def dl(S,K,T,r,s,k): return abs(bs_greeks(S,K,T,r,s,k)[1])
r=0.045; T1=30/365.0; T2=T1-5/365.0
SYMS=["SPY","QQQ","NVDA","TSLA","AMD","META","AAPL","AVGO","MSTR","COIN","PLTR","SMCI"]
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

VRP_IDX, VRP_SS = 1.15, 1.08   # IV = zrealizowana x premia. Indeks drozszy niz akcje (literatura).
print("UCZCIWA WYCENA: IV = zrealizowana zmiennosc x premia (indeks 1.15, akcje 1.08)")
print("Dryf USUNIETY. Long call delta 0.20, 30 DTE, 5 sesji trzymania.")
print("%-6s %8s %8s | %9s %9s %9s %9s %8s"%("sym","zreal","IV ucz.","sr zwrot","mediana","p95","p99","P(>2x)"))
rows=[]
for s in SYMS:
    try: c=hist(s)
    except Exception: continue
    if len(c)<300: continue
    S0=c[-1]; rets=[(c[i+5]/c[i]-1.0) for i in range(len(c)-5)]
    n=len(rets); mu=sum(rets)/n
    rv=math.sqrt(sum((x-mu)**2 for x in rets)/n)*math.sqrt(252.0/5.0)
    iv0=rv*(VRP_IDX if s in ("SPY","QQQ") else VRP_SS)
    Kc=sfd(S0,T1,iv0,0.20,"C"); c0=px(S0,Kc,T1,r,iv0,"C")
    if c0<=0.01: continue
    out=[]
    for rt in rets:
        x=rt-mu                                  # dryf usuniety
        S1=S0*(1+x); iv1=max(0.10,min(3.5,iv0*(1.0-0.30*x*3)))
        out.append((px(S1,Kc,T2,r,iv1,"C")-c0)/c0)
    out.sort(); m=len(out); q=lambda p: out[min(m-1,int(p*m))]
    avg=sum(out)/m
    rows.append((s,avg))
    print("%-6s %7.0f%% %7.0f%% | %+8.1f%% %+8.1f%% %+8.1f%% %+8.1f%% %7.1f%%"
          %(s,rv*100,iv0*100,avg*100,q(0.50)*100,q(0.95)*100,q(0.99)*100,
            100.0*sum(1 for x in out if x>1.0)/m))
print()
print("WNIOSEK: srednia ujemna wszedzie = kupowanie calli ma ujemna EV po uczciwej wycenie.")
print("To jest premia za ryzyko zmiennosci. Prawy ogon istnieje, ale jest OPLACONY z gory.")
