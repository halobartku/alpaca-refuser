import sys, json, urllib.request, math
sys.path.insert(0,".")
from refuser.bs import bs_greeks
def px(S,K,T,r,s,k): return bs_greeks(S,K,T,r,s,k)[0]
def dl(S,K,T,r,s,k): return abs(bs_greeks(S,K,T,r,s,k)[1])
r=0.045
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
    return [(b["t"][:10],b["c"]) for b in bars]

spy=hist("SPY"); c=[x[1] for x in spy]; dates=[x[0] for x in spy]
N=len(c)
# krocząca zrealizowana zmiennosc 20d, roczna
def rvol(i,w=20):
    if i<w: return 0.18
    lr=[math.log(c[j]/c[j-1]) for j in range(i-w+1,i+1)]
    m=sum(lr)/len(lr)
    return math.sqrt(sum((x-m)**2 for x in lr)/len(lr))*math.sqrt(252)

VRP=1.15    # IV = zrealizowana x 1.15, konserwatywnie
HOLD=5      # trzymamy 5 sesji, potem roll
T1=30/365.0; T2=T1-HOLD/365.0

def backtest(delta_t, width, risk_pct, iv_floor=0.0, label=""):
    eq=100_000.0; peak=eq; maxdd=0.0; wins=0; trades=0; curve=[]
    i=25
    while i+HOLD < N:
        rv=rvol(i); iv=rv*VRP
        if iv < iv_floor:            # bramka IV: nie handluj gdy premia za tania
            i+=HOLD; curve.append(eq); continue
        S0=c[i]
        Ks=None; bd=9; Kx=S0
        for _ in range(400):
            d=dl(S0,Kx,T1,r,iv,"P")
            if abs(d-delta_t)<bd: bd,Ks=abs(d-delta_t),Kx
            Kx-=0.5
        Kl=Ks-width
        cred=px(S0,Ks,T1,r,iv,"P")-px(S0,Kl,T1,r,iv,"P")
        risk=(width-cred)*100
        if risk<=0: i+=HOLD; continue
        n=int((eq*risk_pct)//risk)
        if n<1: i+=HOLD; curve.append(eq); continue
        S1=c[i+HOLD]; rv1=rvol(i+HOLD); iv1=max(0.06,rv1*VRP)
        mark=px(S1,Ks,T2,r,iv1,"P")-px(S1,Kl,T2,r,iv1,"P")
        pnl=(cred-mark)*100*n
        # regula wyjscia 50% kredytu: ograniczamy zysk
        pnl=min(pnl,cred*0.5*100*n)
        eq+=pnl; trades+=1; wins+= (1 if pnl>0 else 0)
        peak=max(peak,eq); maxdd=max(maxdd,(peak-eq)/peak)
        curve.append(eq); i+=HOLD
    yrs=(N/252.0)
    cagr=(eq/100_000.0)**(1/yrs)-1 if eq>0 else -1
    print("%-42s CAGR %+7.2f%% | koncowy $%9.0f | maxDD %5.1f%% | trafien %5.1f%% | transakcji %4d"
          %(label,cagr*100,eq,maxdd*100,100.0*wins/max(1,trades),trades))
    return cagr,maxdd

print("BACKTEST 2018-2026 (%.1f lat), SPY, sprzedaz put spreadow, roll co 5 sesji"%(N/252.0))
print("IV zalozona = krocząca zrealizowana 20d x 1.15 (konserwatywnie)\n")
for d_t in (0.15,0.20,0.30):
    for w in (5.0,10.0,25.0):
        backtest(d_t,w,0.0075,0.0,"delta %.2f, szer %2.0f, ryzyko 0.75%%"%(d_t,w))
print()
for rp in (0.02,0.04):
    backtest(0.20,10.0,rp,0.0,"delta 0.20, szer 10, ryzyko %.0f%%"%(rp*100))
print()
for fl in (0.15,0.20,0.25):
    backtest(0.20,10.0,0.02,fl,"delta 0.20, szer 10, ryzyko 2%%, bramka IV>=%.0f%%"%(fl*100))
