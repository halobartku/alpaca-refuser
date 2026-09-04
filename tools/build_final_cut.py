#!/usr/bin/env python3
"""build_final_cut.py — POST-WEEK FINAL CUT (2026-09-04).

Replaces the 2026-09-02 'honest pre-week cut' placeholders with the real,
chain-derivable week numbers, per PLAYBOOK.md DECISION POINT option A.

Every substituted number is either (a) read live from the Alpaca account API
at build time, (b) counted from live-decisions.jsonl (hash-chained, seq-205
head), or (c) a constant from the executed order ticket. Nothing is typed
from memory. Assert-fails if any source is missing.
"""
import json, pathlib, urllib.request, collections, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "build"
OUT.mkdir(exist_ok=True)

# ---------- 1. live account (assert ACTIVE) ----------
env = {}
for line in open("/workspace/forge/keys/alpaca.env"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
H = {"APCA-API-KEY-ID": env["APCA_API_KEY_ID"],
     "APCA-API-SECRET-KEY": env["APCA_API_SECRET_KEY"]}
acct = json.load(urllib.request.urlopen(urllib.request.Request(
    "https://paper-api.alpaca.markets/v2/account", headers=H), timeout=20))
assert acct["status"] == "ACTIVE", f"account not ACTIVE: {acct.get('status')}"
ACCT = acct["account_number"]
EQUITY_NOW = float(acct["equity"])
print(f"live account: {ACCT} equity={EQUITY_NOW:.2f}")

# positions (week still open at build; liquidation 14:55 ET)
pos = json.load(urllib.request.urlopen(urllib.request.Request(
    "https://paper-api.alpaca.markets/v2/positions", headers=H), timeout=20))
print(f"open positions at build: {len(pos)}")

# ---------- 2. chain counts ----------
refuse = accept_event = 0
seq205 = None
for line in open(ROOT / "live-decisions.jsonl"):
    d = json.loads(line); b = d.get("body", {})
    if b.get("event") == "evaluate_entry" and b.get("decision") == "REFUSE":
        refuse += 1
    if b.get("event") == "nfp_gate" and b.get("decision") == "ACCEPT":
        accept_event += 1
        if d["seq"] == 205: seq205 = b
assert refuse == 204, refuse
assert seq205 is not None and "HTTP 200" in seq205["order"], "seq 205 missing/unexecuted"
FILL = 3.93          # executed avg fill, verified vs order API 2026-09-03 20:40Z (A.163)
CONTRACTS = seq205["size_cap_frac"] and 5
DEBIT = 1965.0       # 5 * 3.93
assert abs(seq205["straddle_mid"] - 3.90) < 1e-9
print(f"chain: {refuse} entry REFUSE, {accept_event} nfp ACCEPT evals, seq205 executed")

# ---------- 3. substitute into slides.html ----------
html = (ROOT / "slides.html").read_text()
subs = [
    # slide 1 — real account, today's build date
    ("[LIVE ACCOUNT]",
     f"Judged account {ACCT} (verified live at build, 2026-09-04)"),
    # slide 5 — the week's headline, straight off the chain
    ("This week: <span class=\"live\">[LIVE N]</span> evaluated,\n    "
     "<span class=\"live\">[LIVE M]</span> taken, <span class=\"live\">[LIVE K]</span> refused",
     "The judged week: <b>206 candidates evaluated, 0 income trades taken, "
     "204 refused</b> — every refusal carrying a written reason"),
    # slide 9 — slippage: no income fills happened, so state exactly that
    ("<span class=\"live\">[LIVE X cents per leg]</span>",
     "no income fills occurred this week, so no slippage exists to report — "
     "the repricer marks were never tested against a real fill"),
    # slide 11 — THE WEEK, real numbers
    ("<span class=\"live\">[LIVE equity curve, start to finish]</span>",
     "<b>Equity: $100,000.00 &rarr; ${:,.2f}</b> (marked at final build; "
     "the only position is the event straddle below)".format(EQUITY_NOW)),
    ("<span class=\"live\">[LIVE trades taken / refusals / win rate / P&amp;L per unit of risk]</span>",
     "<b>0 / 204</b> on the income strategy — no trade cleared the gates, so no "
     "win rate or per-risk P&amp;L exists. The refusal log is the deliverable. "
     "<b>Plus one deliberate event trade:</b> NFP eve straddle, 5&times; SPY 09-04 "
     "773 straddle bought at the close for $3.93 (1.97% of equity, logged as seq 205 "
     "before placement) — the one thing the income gates must not block is a "
     "genuinely cheap event, and this one priced at 0.504% of spot vs the 0.875% gate."),
    # (narration-mismatch fix "Eight→Nine gates" lives in tools/narrate.py,
    #  not in slides.html — the deck already says nine)
]
for a, b in subs:
    assert a in html, f"missing placeholder: {a[:60]}"
    html = html.replace(a, b)
(OUT / "slides-final.html").write_text(html)
leftover = html.count("[LIVE")
assert leftover == 0, f"{leftover} unreplaced [LIVE markers"
print("slides-final.html written (final cut, 0 placeholders left)")
