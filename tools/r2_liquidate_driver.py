#!/usr/bin/env python3
"""PLAYBOOK R2 — Friday 10:55 ET liquidation, driven on a schedule.

Why this file exists: liquidate.py is the ENGINE but nothing invoked it on
a clock — the same "tripwire without a schedule" failure class that burned
the registry rederivation checker for six days (notepad, 2026-08-30).
The Friday sprint session lands 14:30Z which happens to equal the 10:30 ET
close-start, but that coupling was luck, not design. This driver makes R2
fire on a wall clock like the NFP driver does, with the same interlock
discipline.

Modes:
  --live            Cancel orphans, close EVERY open option leg with
                    marketable-through limits (walk up, max 10 re-pegs),
                    then verify flat. Journal every step to the hash chain.
  --fixture POSITIONS_JSON   Offline: run liquidate_all against a
                    FixtureBroker-style fake with canned snapshots; no
                    network, no journal write. Exit 0 = all legs closed.

Interlocks before ANY live order (all must hold, else fail-closed abort):
  1. tools/R2_ARMED exists (operator opt-in, created explicitly).
  2. broker.get_account().account_number matches PA3Y…YVDZ (partial id —
     the git tree carries no full account id, commit 6ffd642).
  3. Wall-clock inside Friday 14:25-15:59 UTC (10:25-11:59 ET) — R2 never
     fires on any other day/hour, even if invoked by accident.
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from refuser.live import AlpacaBroker
from refuser.log import DecisionLog
from refuser.liquidate import liquidate_all, verify_flat
from refuser.broker import BrokerError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOURNAL = os.path.join(ROOT, "live-decisions.jsonl")
ARM_FILE = os.path.join(ROOT, "tools", "R2_ARMED")
# Partial id only — the tree must carry no full account id (commit 6ffd642,
# slide-83 claim). Prefix+suffix match is a strong-enough account assert.
EXPECTED_ACCOUNT_PREFIX = "PA3Y"
EXPECTED_ACCOUNT_SUFFIX = "YVDZ"
WEEKDAY = 4                     # Friday
WINDOW = (14 * 60 + 25, 15 * 60 + 59)   # UTC minutes: 10:25-11:59 ET


def _load_env():
    env = {}
    with open(os.path.join(ROOT, "keys", "alpaca.env")) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def _arm_ok():
    return os.path.exists(ARM_FILE)


def _in_window(now):
    if now.weekday() != WEEKDAY:
        return False, f"not Friday (weekday={now.weekday()})"
    m = now.hour * 60 + now.minute
    if not (WINDOW[0] <= m <= WINDOW[1]):
        return False, f"outside 14:25-15:59 UTC window (now {now:%H:%M}Z)"
    return True, "in window"


# -- offline fixture mode ------------------------------------------------

class _FakeBroker:
    """Just the surface liquidate_all touches, with deterministic fills."""

    def __init__(self, orders=("orphan-1",)):
        self._orders = list(orders)
        self.placed = []

    def get_open_orders(self):
        return [{"id": o} for o in self._orders]

    def cancel_order(self, oid):
        return True

    def place_closing_order(self, ticket):
        self.placed.append(ticket)
        return {"id": f"fix-{len(self.placed)}", "status": "filled"}


def _fixture_mode(path):
    with open(path) as f:
        positions = json.load(f)
    fake = _FakeBroker()

    def snap_fn(syms):
        return {s: {"latestQuote": {"bp": 2.00, "ap": 2.10}} for s in syms}

    report = liquidate_all(fake, positions, snap_fn, sleep=lambda s: None)
    flat, residual = verify_flat(positions)
    print(json.dumps({
        "cancelled": report["cancelled"],
        "closed": report["closed"],
        "failed": report["failed"],
        "note": report.get("note"),
        "verify_flat_on_input_positions": flat,
        "residual": residual,
        "orders_placed": len(fake.placed),
    }, indent=2))
    ok = (not report["failed"]) and len(report["closed"]) > 0
    print("FIXTURE RESULT:", "PASS — every leg closed" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--fixture" in argv:
        return _fixture_mode(argv[argv.index("--fixture") + 1])

    now = datetime.now(timezone.utc)
    log = DecisionLog(JOURNAL)

    def journal(body):
        body["event"] = "r2_liquidation"
        body["utc"] = now.isoformat()
        return log.append(body)

    ok, why = _in_window(now)
    if not (_arm_ok() and ok):
        rec = journal({"decision": "ABORT",
                       "reason": f"interlock failed: armed={_arm_ok()}, {why}",
                       "positions_touched": 0})
        print(json.dumps(rec["body"], indent=2))
        print("ABORTED (fail-closed) — no orders placed.")
        return 0

    env = _load_env()
    broker = AlpacaBroker(env["APCA_API_KEY_ID"], env["APCA_API_SECRET_KEY"])

    acct = broker.get_account()
    num = acct["account_number"]
    assert num.startswith(EXPECTED_ACCOUNT_PREFIX) and \
        num.endswith(EXPECTED_ACCOUNT_SUFFIX), f"unexpected account {num[:4]}…{num[-4:]}"
    journal({"decision": "R2_START", "equity": acct.get("equity"),
             "account": f"{num[:4]}…{num[-4:]}"})

    positions = broker.get_positions()
    before = [p.get("symbol") for p in positions
              if p.get("asset_class") == "us_option"]
    journal({"decision": "R2_INVENTORY", "option_legs": before})

    def snap_fn(syms):
        return broker.get_option_snapshot(syms)

    try:
        report = liquidate_all(broker, positions, snap_fn)
    except BrokerError as e:
        rec = journal({"decision": "R2_FAILURE", "reason": str(e)})
        print(json.dumps(rec["body"], indent=2))
        print("R2 FAILED — legs may remain open. Sprint session must act.")
        return 2

    # verify flat on FRESH positions, not the stale snapshot
    fresh = broker.get_positions()
    flat, residual = verify_flat(fresh)
    rec = journal({"decision": "FLAT" if flat else "NOT_FLAT",
                   "cancelled": report["cancelled"],
                   "closed": report["closed"],
                   "residual": residual})
    print(json.dumps(rec["body"], indent=2))
    if not flat:
        print("NOT FLAT — residual legs:", residual)
        return 2
    print("R2 COMPLETE — account flat, judged P&L = realized P&L.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
