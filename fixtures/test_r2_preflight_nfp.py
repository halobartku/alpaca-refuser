"""Offline tests for the three PLAYBOOK-critical additions (2026-08-29):

  1. preflight  — §6 Monday checklist incl. the §8.2 suspend_trade trap
  2. liquidate  — R2 Friday-10:55 engine (inventory, tickets, walks, verify)
  3. nfp_gate   — §4 straddle gate arithmetic vs the MEASURED numbers

Every expectation here is derived from the PLAYBOOK / live smoke shapes,
NOT from the implementation under test (correctness gate).
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from refuser import liquidate, nfp_gate, preflight
from refuser.broker import BrokerError, FixtureBroker

TESTER = "FX-DEV-1M"


def mk_fixtures(**files):
    d = tempfile.mkdtemp()
    import json
    for name, obj in files.items():
        with open(os.path.join(d, name), "w") as f:
            json.dump(obj, f)
    return d


ACCT = {"account_number": TESTER, "equity": 1_000_000.0, "status": "ACTIVE",
        "trading_blocked": False, "options_trading_level": 3,
        "currency": "USD"}


# --- §8.2 suspend_trade trap + preflight ----------------------------------

class TestPreflight(unittest.TestCase):
    def _broker(self, configs=None, acct=None):
        files = {"account.json": acct or ACCT}
        if configs is not None:
            files["configurations.json"] = configs
        return FixtureBroker(mk_fixtures(**files), TESTER)

    def test_healthy_account_passes(self):
        rep = preflight.preflight(self._broker(), TESTER)
        self.assertTrue(rep["ok"], rep)
        names = [c["check"] for c in rep["checks"]]
        self.assertIn("suspend_trade", names)
        self.assertIn("options_level", names)

    def test_suspend_trade_blocks(self):
        b = self._broker({"suspend_trade": True})
        rep = preflight.preflight(b, TESTER)
        self.assertFalse(rep["ok"])
        self.assertFalse(rep["fixed"])

    def test_suspend_trade_fixed_only_with_fix_true(self):
        b = self._broker({"suspend_trade": True})
        rep = preflight.preflight(b, TESTER, fix=True)
        self.assertTrue(rep["ok"], rep)
        self.assertIn("suspend_trade", rep["fixed"])
        self.assertIs(b._suspend_patched_to, False)   # cleared, never set

    def test_wrong_account_refuses(self):
        b = self._broker()
        with self.assertRaises(Exception):
            preflight.preflight(b, "FX-JUDGE-100K")

    def test_low_options_level_refuses(self):
        acct = dict(ACCT, options_trading_level=1)
        rep = preflight.preflight(self._broker(acct=acct), TESTER)
        self.assertFalse(rep["ok"])


# --- R2 liquidation --------------------------------------------------------

class TestLegInventory(unittest.TestCase):
    def test_live_shape(self):
        # exact per-leg shape from the 2026-08-28 smoke (positions_after_fill)
        positions = [
            {"symbol": "SPY260918P00737000", "asset_class": "us_option",
             "qty": "1", "side": "long"},
            {"symbol": "SPY260918P00750000", "asset_class": "us_option",
             "qty": "-1", "side": "short"},
            {"symbol": "SPY", "asset_class": "us_equity", "qty": "10",
             "side": "long"},
        ]
        inv = liquidate.leg_inventory(positions)
        self.assertEqual(inv, {"SPY260918P00737000": 1,
                               "SPY260918P00750000": -1})

    def test_unparsable_qty_refuses(self):
        with self.assertRaises(BrokerError):
            liquidate.leg_inventory(
                [{"symbol": "X", "asset_class": "us_option", "qty": "abc"}])

    def test_missing_symbol_refuses(self):
        with self.assertRaises(BrokerError):
            liquidate.leg_inventory(
                [{"asset_class": "us_option", "qty": "1"}])


class TestCloseTicket(unittest.TestCase):
    def test_short_leg_buys_back_through_ask(self):
        t = liquidate.close_ticket("SPY260918P00750000", -1, 2.90)
        self.assertEqual(t["legs"][0]["side"], "buy")
        self.assertEqual(t["legs"][0]["position_intent"], "buy_to_close")
        self.assertEqual(t["order_class"], "simple")
        self.assertEqual(t["qty"], "1")
        self.assertEqual(float(t["limit_price"]), 2.95)  # mid + 0.05

    def test_long_leg_sells_through_bid(self):
        t = liquidate.close_ticket("SPY260918P00737000", 2, 1.70)
        self.assertEqual(t["legs"][0]["side"], "sell")
        self.assertEqual(t["legs"][0]["position_intent"], "sell_to_close")
        self.assertEqual(float(t["limit_price"]), 1.65)  # mid - 0.05

    def test_zero_qty_refuses(self):
        with self.assertRaises(BrokerError):
            liquidate.close_ticket("X", 0, 1.0)

    def test_spread_ticket_matches_live_smoke_shape(self):
        t = liquidate.spread_close_ticket("SPY260918P00750000",
                                          "SPY260918P00737000", 1, 1.18)
        self.assertEqual(t["order_class"], "mleg")
        self.assertEqual(t["limit_price"], "1.23")     # debit + aggression
        legs = {l["symbol"]: l for l in t["legs"]}
        self.assertEqual(legs["SPY260918P00750000"]["position_intent"],
                         "buy_to_close")
        self.assertEqual(legs["SPY260918P00737000"]["position_intent"],
                         "sell_to_close")
        self.assertEqual(t["qty"], "1")


class TestLiquidateAll(unittest.TestCase):
    def test_live_snapshot_shape_latestQuote(self):
        # EXACT payload from the live data API 2026-08-29 (feed=indicative):
        # top-level bidPrice/askPrice are NULL; quotes are latestQuote.bp/ap.
        live_snap = {"bidPrice": None, "askPrice": None, "bidAskSpread": None,
                     "latestQuote": {"ap": 3.03, "as": 80, "ax": "W",
                                     "bp": 3.01, "bs": 43, "bx": "H",
                                     "c": "A",
                                     "t": "2026-08-28T19:59:59.344Z"},
                     "impliedVolatility": 0.1413}
        ref = liquidate._walkable_ref(live_snap)
        self.assertAlmostEqual(ref, (3.01 + 3.03) / 2.0)
        # and the ticket off it is marketable through the ask
        t = liquidate.close_ticket("SPY260918P00750000", -1, ref)
        self.assertEqual(float(t["limit_price"]), 3.07)  # 3.02 + 0.05

    def _run(self, positions, snaps, next_status="filled"):
        files = {"account.json": ACCT, "positions.json": positions,
                 "open_orders.json": [
                     {"id": "orphan-1", "status": "open"}]}
        b = FixtureBroker(mk_fixtures(**files), TESTER)
        b._next_close_status = next_status

        def snapshot_fn(syms):
            if isinstance(syms, str):
                syms = [syms]
            return {s: snaps[s] for s in syms}

        calls = {"n": 0}

        def sleep(x):
            calls["n"] += 1

        return b, liquidate.liquidate_all(b, positions, snapshot_fn,
                                          sleep=sleep, max_walks=3), calls

    def test_full_close_cancels_orphans_then_fills(self):
        positions = [
            {"symbol": "SPY260918P00750000", "asset_class": "us_option",
             "qty": "-1", "side": "short"},
            {"symbol": "SPY260918P00737000", "asset_class": "us_option",
             "qty": "1", "side": "long"},
        ]
        snaps = {"SPY260918P00750000": {"bid": 2.88, "ask": 2.92},
                 "SPY260918P00737000": {"bid": 1.68, "ask": 1.72}}
        b, rep, _ = self._run(positions, snaps)
        self.assertEqual(rep["cancelled"], ["orphan-1"])
        self.assertEqual(len(rep["closed"]), 2)
        self.assertEqual(rep["failed"], [])
        # buy-back of the short at through-the-ask limit
        buys = [o for o in b.placed_orders
                if o["legs"][0]["position_intent"] == "buy_to_close"]
        self.assertEqual(float(buys[0]["limit_price"]), 2.95)

    def test_unfilled_leg_raises_r2_failure(self):
        positions = [
            {"symbol": "SPY260918P00750000", "asset_class": "us_option",
             "qty": "-1", "side": "short"},
        ]
        snaps = {"SPY260918P00750000": {"bid": 2.88, "ask": 2.92}}
        with self.assertRaises(BrokerError) as cm:
            self._run(positions, snaps, next_status="new")
        self.assertIn("R2 FAILURE", str(cm.exception))

    def test_walk_escalates_debit_through_market(self):
        # never fills; assert the last walked limit is above the first
        positions = [
            {"symbol": "SPY260918P00750000", "asset_class": "us_option",
             "qty": "-1", "side": "short"},
        ]
        snaps = {"SPY260918P00750000": {"bid": 2.88, "ask": 2.92}}
        files = {"account.json": ACCT, "positions.json": positions,
                 "open_orders.json": []}
        b = FixtureBroker(mk_fixtures(**files), TESTER)
        b._next_close_status = "new"

        def snapshot_fn(syms):
            return {"SPY260918P00750000": {"bid": 2.88, "ask": 2.92}}

        try:
            liquidate.liquidate_all(b, positions, snapshot_fn,
                                    sleep=lambda x: None, max_walks=3)
        except BrokerError:
            pass
        limits = [float(o["limit_price"]) for o in b.placed_orders]
        self.assertGreater(len(limits), 1)
        self.assertGreater(limits[-1], limits[0])   # paid up, not down

    def test_verify_flat(self):
        ok, res = liquidate.verify_flat([])
        self.assertTrue(ok)
        ok, res = liquidate.verify_flat(
            [{"symbol": "X", "asset_class": "us_option", "qty": "1"}])
        self.assertFalse(ok)
        self.assertEqual(res, ["X"])


# --- §4 NFP gate ------------------------------------------------------------

class TestNFGGate(unittest.TestCase):
    def test_accept_only_below_cutoff(self):
        # PLAYBOOK §4 worked examples: cutoff $6.74 @ 770 spot, $6.12 @ 700
        r = nfp_gate.straddle_gate(770.0, 6.50)
        self.assertEqual(r["decision"], "ACCEPT")
        self.assertEqual(r["cutoff"], 6.74)
        r2 = nfp_gate.straddle_gate(700.0, 6.20)
        self.assertEqual(r2["decision"], "REFUSE")   # 6.20 > 6.12
        r3 = nfp_gate.straddle_gate(700.0, 6.05)
        self.assertEqual(r3["decision"], "ACCEPT")

    def test_median_priced_straddle_refuses(self):
        # typical 1-DTE ATM ~0.9% of spot vs 0.875% gate -> REFUSE by design
        r = nfp_gate.straddle_gate(770.0, 7.00)
        self.assertEqual(r["decision"], "REFUSE")
        self.assertIn("too expensive", r["reason"])

    def test_missing_inputs_refuse(self):
        for spot, mid in ((None, 5.0), (770.0, None), (0.0, 5.0), (770.0, 0.0)):
            r = nfp_gate.straddle_gate(spot, mid)
            self.assertEqual(r["decision"], "REFUSE", (spot, mid))

    def test_size_cap(self):
        r = nfp_gate.straddle_gate(770.0, 6.00)
        self.assertEqual(r["size_frac"], 0.02)
        self.assertEqual(nfp_gate.MAX_SIZE_FRAC, 0.02)


if __name__ == "__main__":
    unittest.main(verbosity=1)
