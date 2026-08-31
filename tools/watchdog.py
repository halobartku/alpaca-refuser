#!/usr/bin/env python3
"""Ground-truth check of the Alpaca paper account — A.153 watchdog.

Reads keys from /workspace/forge/keys/alpaca.env, hits the live paper API,
prints a one-line status + any positions + any open orders. Exit codes:
  0 = account healthy, no positions, no open orders
  1 = API error (auth/network)
  2 = POSITION EXISTS (check GTC exit beside it!)
  3 = open orders exist without positions
"""
import json
import os
import urllib.request

BASE = "https://paper-api.alpaca.markets"


def load_env(path="/workspace/forge/keys/alpaca.env"):
    env = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def api(path, hdrs):
    req = urllib.request.Request(BASE + path, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:200]}
    except Exception as e:  # noqa: BLE001
        return 0, {"error": f"{type(e).__name__}: {e}"}


def main():
    env = load_env()
    hdrs = {
        "APCA-API-KEY-ID": env["APCA_API_KEY_ID"],
        "APCA-API-SECRET-KEY": env["APCA_API_SECRET_KEY"],
    }
    code, acct = api("/v2/account", hdrs)
    if code != 200:
        print(f"ALPACA P0: account API HTTP {code} {acct.get('error', '')}")
        return 1
    print(f"account: {acct.get('status')} | equity {acct.get('equity')} "
          f"| blocked {acct.get('trading_blocked')} "
          f"| user-suspend {acct.get('trade_suspended_by_user')} "
          f"| opts L{acct.get('options_trading_level')} "
          f"| cash {acct.get('cash')}")

    code, positions = api("/v2/positions", hdrs)
    code2, orders = api("/v2/orders?status=open&limit=50", hdrs)
    pos = positions if isinstance(positions, list) else []
    opn = orders if isinstance(orders, list) else []
    print(f"positions: {len(pos)} | open orders: {len(opn)}")

    # broker-side history: catches orders even if the session log is lost
    code3, acts = api("/v2/account/activities?activity_types=FILL,TRANS"
                      "&days=7", hdrs)
    if code3 == 200 and isinstance(acts, list):
        fills = [a for a in acts if a.get("activity_type") == "FILL"]
        print(f"order fills in last 7d: {len(fills)} "
              f"(total activities {len(acts)})")
        for a in acts[:5]:
            print(f"  ACT {a.get('activity_type')} {a.get('symbol')} "
                  f"{a.get('side')} qty {a.get('qty')} "
                  f"@{a.get('price')} {a.get('transaction_time', '')}")
    else:
        print(f"activities: HTTP {code3} (non-fatal)")
    for p in pos:
        print(f"  POS {p.get('symbol')} qty {p.get('qty')} "
              f"side {p.get('side')} avg {p.get('avg_entry_price')} "
              f"upl {p.get('unrealized_pl')}")
    for o in opn:
        print(f"  ORDER {o.get('id')} {o.get('symbol')} {o.get('type')} "
              f"{o.get('side')} qty {o.get('qty')} status {o.get('status')} "
              f"tif {o.get('time_in_force')}")
    if pos:
        print("ALPACA: POSITION EXISTS — verify its GTC exit is in the open "
              "orders above; position without GTC = P0")
        return 2
    if opn:
        return 3
    print("ALPACA: clean — no positions, no open orders")
    return 0


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    raise SystemExit(main())
