#!/usr/bin/env python3
"""Correctness gate for the hosted demo (docs/demo.js) — the standing rule
from the sol-audit post-mortem: nothing ships because it RUNS; it ships when
one query with a knowable-correct answer, computed INDEPENDENTLY of the
thing under test, comes back right.

The independent oracle here is the Python gate stack itself — already
validated against Hull's canonical option-pricing example and put-call
parity (max err 1.4e-14, SUBMISSION_RECEIPT.md items 1-2) — plus, for the
hash chain, an independent stdlib re-implementation of the canonical-JSON
+ sha256 recipe (NOT refuser/log.py's own loader).

Battery:
  A. evaluate_intent parity, 24 adversarial cases: decision, contracts, and
     every gate's pass flag AND detail string must match byte-for-byte.
  B. Chain build + verify: JS builds a 3-record chain; Python's independent
     verifier accepts it. Then a single character of one body is flipped and
     BOTH verifiers must flag the break.
  C. Cross-verification of a chain built by Python refuser.log.DecisionLog.

Usage: python3 tools/parity_test.py   (from repo root; needs node on PATH)
"""
import json
import subprocess
import sys
import tempfile
import hashlib
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from refuser import gates as pygates  # noqa: E402

NODE = ["node", os.path.join(ROOT, "docs", "demo.js")]

# --- A. evaluate_intent parity cases ----------------------------------------
# (label, intent, state, market). Dates Mon 2026-08-31 (entry day) unless a
# case exists to break the calendar gate on purpose.
BASE_INTENT = {
    "name": "SPY", "expiry": "2026-09-25", "k_short": 400, "k_long": 395,
    "width": 5.0, "credit": 1.20,
    "ask_short": 1.30, "bid_short": 1.20, "ask_long": 0.55, "bid_long": 0.47,
    "oi_short": 12000, "oi_long": 9000, "short_delta": 0.20,
    "spread_delta": 0.10,
}
BASE_STATE = {
    "equity": 100000.0, "open_positions": 0, "positions_by_name": [],
    "risk_at_open": 0.0, "daily_stop_hit": False, "net_delta": 0.0,
    "now": "2026-08-31T11:30:00", "today": "2026-08-31",
}
BASE_MARKET = {"underlying_last": 405.0, "atm_iv": 0.22,
               "spy_atm_iv": 0.16, "spy_iv_5d_avg": 0.15}

def case(label, *, intent=None, state=None, market=None):
    i = dict(BASE_INTENT); s = dict(BASE_STATE); m = dict(BASE_MARKET)
    if intent: i.update(intent)
    if state: s.update(state)
    if market: m.update(market)
    return (label, i, s, m)

CASES = [
    case("baseline-accept"),
    case("dte-too-short", intent={"expiry": "2026-09-10"}),
    case("dte-too-long", intent={"expiry": "2026-11-20"}),
    case("dte-21-boundary", intent={"expiry": "2026-09-21"}),
    case("delta-too-deep", intent={"short_delta": 0.45}),
    case("delta-too-shallow", intent={"short_delta": 0.08}),
    case("delta-boundary-0.25", intent={"short_delta": 0.25}),
    case("width-too-wide", intent={"width": 6.0, "credit": 1.20}),
    case("credit-thin", intent={"credit": 0.80}),
    case("credit-20pct-boundary", intent={"width": 5.0, "credit": 1.00}),
    case("risk-over-4.50", intent={"width": 5.0, "credit": 0.40}),
    case("wide-leg-spread", intent={"ask_long": 0.85, "bid_long": 0.30}),
    case("oi-too-low", intent={"oi_long": 900}),
    case("underlying-cheap", market={"underlying_last": 31.0}),
    case("not-in-universe", intent={"name": "GME"}),
    case("nfp-blackout", state={"now": "2026-09-04T09:00:00", "today": "2026-09-04"}),
    case("wrong-day-tuesday", state={"now": "2026-09-01T11:30:00", "today": "2026-09-01"}),
    case("before-window", state={"now": "2026-08-31T09:30:00"}),
    case("after-window", state={"now": "2026-08-31T15:30:00"}),
    case("window-edge-1500", state={"now": "2026-08-31T15:00:00"}),
    case("iv-floor-fail", market={"atm_iv": 0.17}),
    case("spy-regime-fail", market={"spy_atm_iv": 0.14}),
    case("daily-stop", state={"daily_stop_hit": True}),
    case("slots-full", state={"open_positions": 6}),
    case("same-name-held", state={"positions_by_name": ["SPY"]}),
    case("heat-over", state={"risk_at_open": 8500.0}),
    case("group-cap", state={"positions_by_name": ["QQQ", "IWM"]}),
    case("net-delta-cap", state={"net_delta": 22.0}),
    case("net-delta-cap-exact", state={"net_delta": 20.0}),
    case("sizing-zero", state={"equity": 300.0}),
    case("sizing-1M-tester", state={"equity": 1000000.0}),
]


def run_js_eval(intent, state, market):
    payload = json.dumps({"intent": intent, "state": state, "market": market})
    p = subprocess.run(NODE + ["eval"], input=payload, capture_output=True,
                       text=True, timeout=30)
    if p.returncode != 0:
        raise RuntimeError(f"node eval failed: {p.stderr[:400]}")
    return json.loads(p.stdout)


def norm_py(res):
    return {"decision": res["decision"], "contracts": res["contracts"],
            "gates": [{"gate": r["gate"], "pass": r["pass"],
                       "detail": r["detail"]} for r in res["gates"]]}


def to_py(intent, state):
    """Python evaluate_intent wants date/datetime objects; JS wants ISO
    strings. Convert a copy for the Python oracle."""
    from datetime import date, datetime
    i = dict(intent); s = dict(state)
    i["expiry"] = date.fromisoformat(i["expiry"])
    s["today"] = date.fromisoformat(s["today"])
    s["now"] = datetime.fromisoformat(s["now"])
    return i, s


def section_a():
    fails = 0
    for label, intent, state, market in CASES:
        pi, ps = to_py(intent, state)
        py = norm_py(pygates.evaluate_intent(pi, ps, market))
        js = run_js_eval(intent, state, market)
        if py == js:
            continue
        fails += 1
        print(f"  MISMATCH [{label}]")
        if py["decision"] != js["decision"]:
            print(f"    decision: py={py['decision']} js={js['decision']}")
        if py["contracts"] != js["contracts"]:
            print(f"    contracts: py={py['contracts']} js={js['contracts']}")
        pg = {g["gate"]: g for g in py["gates"]}
        jg = {g["gate"]: g for g in js["gates"]}
        for k in sorted(set(pg) | set(jg)):
            if pg.get(k) != jg.get(k):
                print(f"    gate {k}: py={pg.get(k)} js={jg.get(k)}")
    print(f"A. evaluate_intent parity: {len(CASES) - fails}/{len(CASES)} cases "
          f"byte-identical (decision+contracts+all gate details)")
    return fails


# --- B/C. chain cross-verification -------------------------------------------
def canonical_json(v):
    """Independent re-implementation of json.dumps(v, sort_keys=True) with
    default separators — written from the JSON spec, not imported from
    refuser.log, so a shared bug cannot hide."""
    if v is True: return "true"
    if v is False: return "false"
    if v is None: return "null"
    if isinstance(v, (int, float)):
        return repr(v)                 # json.dumps uses float.__repr__; ints str()
        # NOTE: test bodies must avoid x.0-valued floats (repr differs JS/Py)
    if isinstance(v, str): return json.dumps(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(canonical_json(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(
            json.dumps(k) + ": " + canonical_json(x)
            for k, x in sorted(v.items())) + "}"
    raise TypeError(type(v))


def py_verify_chain_text(text):
    """Independent Python verifier (same recipe, written here)."""
    head, n = "GENESIS", 0
    for line in text.splitlines():
        if not line.strip(): continue
        rec = json.loads(line)
        if rec["prev"] != head: return False, n
        h = hashlib.sha256((head + canonical_json(rec["body"])).encode()).hexdigest()
        if rec["hash"] != h: return False, n
        head, n = rec["hash"], n + 1
    return True, n


def build_js_chain():
    """JS builds a 3-record chain by calling demo.js sha step by step."""
    bodies = [
        {"event": "intent_evaluated", "name": "SPY", "decision": "REFUSE",
         "gates": ["dte", "short_delta"]},
        {"event": "intent_evaluated", "name": "QQQ", "decision": "ACCEPT",
         "contracts": 1, "credit": 1.2},
        {"event": "exit_fired", "rule": "GTC_50pct", "ticket": "BUY 1 SPW X395 0925P"},
    ]
    head, recs = "GENESIS", []
    for b in bodies:
        h = subprocess.run(NODE + ["sha"], input=head + canonical_json(b),
                           capture_output=True, text=True, timeout=30)
        if h.returncode != 0:
            raise RuntimeError("node sha failed: " + h.stderr[:200])
        rec = {"seq": len(recs), "ts": 1770000000.0 + len(recs),
               "prev": head, "body": b, "hash": h.stdout.strip()}
        recs.append(rec); head = rec["hash"]
    return "".join(json.dumps(r) + "\n" for r in recs)


def run_js_verify(text):
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        f.write(text); path = f.name
    try:
        p = subprocess.run(NODE + ["verify", path], capture_output=True,
                           text=True, timeout=30)
        return p.returncode, json.loads(p.stdout or "{}")
    finally:
        os.unlink(path)


def section_b():
    fails = 0
    text = build_js_chain()
    ok_py, n_py = py_verify_chain_text(text)
    rc, out_js = run_js_verify(text)
    if not (ok_py and rc == 0 and out_js.get("ok") and out_js.get("records") == 3):
        print(f"  B1 FAIL: py_ok={ok_py} js={out_js}"); fails += 1
    # tamper: flip one character deep inside the second body
    lines = text.splitlines()
    rec = json.loads(lines[1]); rec["body"]["credit"] = 1.25
    lines[1] = json.dumps(rec)
    tampered = "\n".join(lines) + "\n"
    ok_py2, _ = py_verify_chain_text(tampered)
    rc2, out_js2 = run_js_verify(tampered)
    if ok_py2 or rc2 == 0 or out_js2.get("ok"):
        print(f"  B2 FAIL (tamper not caught): py={ok_py2} js={out_js2}"); fails += 1
    print(f"B. chain build(JS)+verify: intact accepted by BOTH verifiers; "
          f"1-char tamper caught by BOTH (py line {py_verify_chain_text(tampered)[1]}, "
          f"js: {out_js2.get('error', '')[:60]})")
    return fails


def section_c():
    from refuser.log import DecisionLog
    fails = 0
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "d.jsonl")
        log = DecisionLog(path)
        log.append({"event": "intent_evaluated", "name": "SPY",
                    "decision": "REFUSE", "blocked_by": ["liquidity"]})
        log.append({"event": "order_filled", "qty": 1, "credit": 1.18})
        text = open(path).read()
        rc, out = run_js_verify(text)
        if not (rc == 0 and out.get("ok") and out.get("records") == 2):
            print(f"  C FAIL: js verifier rejected a Python-built chain: {out}")
            fails += 1
    print("C. cross-verify: JS verifier accepts a chain written by Python "
          "refuser.log.DecisionLog (2 records)")
    return fails


if __name__ == "__main__":
    print("parity_test.py — hosted-demo correctness gate (oracle: Python "
          "stack + independent canonical-JSON verifier)")
    total = section_a() + section_b() + section_c()
    print()
    if total:
        print(f"PARITY FAIL — {total} section(s) with mismatches")
        sys.exit(1)
    print("PARITY OK — demo.js is behaviorally identical to the Python "
          "gate stack on every case, and both chain verifiers cross-verify.")
