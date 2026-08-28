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
    return [b["c"] for b in bars]
c=hist("SPY"); N=len(c)
def rvol(i,w=20):
    if i<w: return 0.18
    lr=[math.log(c[j]/c[j-1]) for j in range(i-w+1,i+1)]
    m=sum(lr)/len(lr)
    return math.sqrt(sum((x-m)**2 for x in lr)/len(lr))*math.sqrt(252)
HOLD=5; T1=30/365.0; T2=T1-HOLD/365.0

def bt(mode,delta_t,width,notional_pct,vrp,iv_floor,label):
    eq=100_000.0; peak=eq; mdd=0.0; i=25; tr=0; wins=0
    while i+HOLD<N:
        rv=rvol(i); iv=rv*vrp
        if iv<iv_floor: i+=HOLD; continue
        S0=c[i]
        Ks=None; bd=9; Kx=S0
        for _ in range(400):
            d=dl(S0,Kx,T1,r,iv,"P")
            if abs(d-delta_t)<bd: bd,Ks=abs(d-delta_t),Kx
            Kx-=0.5
        S1=c[i+HOLD]; iv1=max(0.06,rvol(i+HOLD)*vrp)
        if mode=="csp":
            # cash-secured: kapital pod zabezpieczenie = Ks*100 na kontrakt
            n=int((eq*notional_pct)//(Ks*100))
            if n<1: i+=HOLD; continue
            cr=px(S0,Ks,T1,r,iv,"P"); mk=px(S1,Ks,T2,r,iv1,"P")
            pnl=(cr-mk)*100*n
        else:
            Kl=Ks-width
            cr=px(S0,Ks,T1,r,iv,"P")-px(S0,Kl,T1,r,iv,"P")
            risk=(width-cr)*100
            if risk<=0: i+=HOLD; continue
            n=int((eq*notional_pct)//risk)
            if n<1: i+=HOLD; continue
            mk=px(S1,Ks,T2,r,iv1,"P")-px(S1,Kl,T2,r,iv1,"P")
            pnl=(cr-mk)*100*n
        eq+=pnl; tr+=1; wins+=(1 if pnl>0 else 0)
        peak=max(peak,eq); mdd=max(mdd,(peak-eq)/peak)
        i+=HOLD
    yrs=N/252.0
    cagr=(eq/100_000.0)**(1/yrs)-1 if eq>0 else -1
    print("%-46s CAGR %+7.2f%% | $%9.0f | maxDD %5.1f%% | traf %5.1f%% | n=%d"
          %(label,cagr*100,eq,mdd*100,100.0*wins/max(1,tr),tr))

print("PORToWNANIE: co faktycznie zbiera premie za ryzyko zmiennosci (2018-2026)\n")
print("--- A. nasz obecny ksztalt: waski spread, male ryzyko ---")
bt("spread",0.20,5.0,0.0075,1.15,0.0,"spread d0.20 szer5, ryzyko 0.75%")
print("\n--- B. cash-secured put (bez dlugiej nogi), jak indeks CBOE PUT ---")
for np_ in (0.25,0.50,1.00):
    bt("csp",0.20,0,np_,1.15,0.0,"CSP d0.20, %3.0f%% kapitalu pod zabezpieczenie"%(np_*100))
for np_ in (0.50,1.00):
    bt("csp",0.30,0,np_,1.15,0.0,"CSP d0.30, %3.0f%% kapitalu"%(np_*100))
print("\n--- C. wrazliwosc na zalozona premie VRP ---")
for v in (1.05,1.15,1.25,1.35):
    bt("csp",0.30,0,1.00,v,0.0,"CSP d0.30, 100%% kapitalu, VRP x%.2f"%v)
print("\n--- D. z bramka IV ---")
for fl in (0.15,0.20):
    bt("csp",0.30,0,1.00,1.15,fl,"CSP d0.30, 100%%, bramka IV>=%.0f%%"%(fl*100))
