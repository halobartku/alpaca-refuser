import sys, json, urllib.request, math, random
sys.path.insert(0,".")
from refuser.bs import bs_greeks
def px(S,K,T,r,s,k): return bs_greeks(S,K,T,r,s,k)[0]
def dl(S,K,T,r,s,k): return abs(bs_greeks(S,K,T,r,s,k)[1])
r=0.045; random.seed(5)

# --- ile trzeba zeby wygrac: rozklad wynikow 107 zgloszen ---
# zalozenie: wiekszosc to boty LLM na megacapach, waski rozklad; mniejszosc gra agresywnie
def field(n=107):
    out=[]
    for i in range(n):
        u=random.random()
        if u<0.55:   out.append(random.gauss(0.000,0.010))   # pasywni/zepsuci: ~0%
        elif u<0.85: out.append(random.gauss(0.005,0.025))   # carry/premium sellers
        elif u<0.97: out.append(random.gauss(0.010,0.080))   # kierunkowi
        else:        out.append(random.gauss(0.020,0.250))   # hazardzisci
    return sorted(out,reverse=True)

TR=4000
th=[]
for _ in range(TR):
    f=field()
    th.append((f[0],f[2]))   # 1. miejsce i 3. miejsce
th.sort()
w1=sorted(x[0] for x in th); w3=sorted(x[1] for x in th)
def q(a,p): return a[int(p*len(a))]
print("=== ILE TRZEBA (model pola 107 zgloszen, %d symulacji) ==="%TR)
print("  proba 3. miejsca:  mediana %+.1f%%   p25 %+.1f%%   p75 %+.1f%%"%(q(w3,0.5)*100,q(w3,0.25)*100,q(w3,0.75)*100))
print("  proba 1. miejsca:  mediana %+.1f%%   p25 %+.1f%%   p75 %+.1f%%"%(q(w1,0.5)*100,q(w1,0.25)*100,q(w1,0.75)*100))
T3=q(w3,0.5); T1=q(w1,0.5)
print("  => celujemy w >= %+.1f%% (podium) i >= %+.1f%% (wygrana)"%(T3*100,T1*100))

# --- konstrukcje: ile konta w zaklad kierunkowy na earnings ---
# debit call spread na AVGO: implied move 6.5%. Kupujemy spread 0/+7% za ~35% szerokosci.
# wyplata: pelna szerokosc jesli ruch >= +7%, czesciowa miedzy, zero jesli <= 0.
IMPL=0.065
def avgo_move():
    # rozklad ruchu na earnings: gruby, lekko dodatnio skosny (dane flashalpha)
    u=random.random()
    base=random.gauss(0.01, IMPL*1.15)
    if u<0.12: base*= 2.2          # ogon: ruch znacznie wiekszy niz wyceniony
    return base

def payoff_debit(move, w_lo=0.0, w_hi=0.07, cost_frac=0.35):
    # zwrot na zainwestowany dolar
    if move<=w_lo: return -1.0
    if move>=w_hi: return (1.0-cost_frac)/cost_frac
    frac=(move-w_lo)/(w_hi-w_lo)
    return (frac-cost_frac)/cost_frac

def run(alloc, carry_wk=0.0025, trials=20000):
    res=[]
    for _ in range(trials):
        carry=random.gauss(carry_wk,0.004)*(1-alloc)
        m=avgo_move()
        res.append(carry + alloc*payoff_debit(m))
    res.sort(); n=len(res); Q=lambda p: res[int(p*n)]
    return (sum(res)/n, Q(0.50), Q(0.95),
            100.0*sum(1 for x in res if x>0)/n,
            100.0*sum(1 for x in res if x>=T3)/n,
            100.0*sum(1 for x in res if x>=T1)/n,
            100.0*sum(1 for x in res if x<=-0.05)/n)

print("\n=== ALOKACJA W ZAKLAD KIERUNKOWY (AVGO debit spread) ===")
print("%7s %9s %9s %9s %8s %10s %10s %9s"%("alok.","srednia","mediana","p95","P(>0)","P(podium)","P(wygrana)","P(<-5%)"))
for a in (0.0,0.02,0.05,0.10,0.15,0.25,0.40):
    m,med,p95,pos,pp,pw,dn=run(a)
    print("%6.0f%% %+8.2f%% %+8.2f%% %+8.2f%% %7.1f%% %9.2f%% %9.2f%% %8.1f%%"
          %(a*100,m*100,med*100,p95*100,pos,pp,pw,dn))
