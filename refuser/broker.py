"""AlpacaBroker — the ONE seam every live Alpaca call goes through (A.111 #1).

Design contract (testable offline via FixtureBroker):
  get_account()            -> {account_number, equity, status, trading_blocked,
                               options_trading_level, currency}
  get_option_chain(name, lo, hi, dte_lo, dte_hi) -> [contract dicts]
  get_option_snapshot(sym) -> {bid, ask, mid, ...}
  get_underlying_quote(sym)-> {last, ...}   (live IEX mark for repricing)
  get_positions()          -> [position dicts]
  get_open_orders()        -> [order dicts]
  place_option_order(plan) -> order dict (must round-trip through order_plan())
  cancel_order(id)         -> True/False

Live assumptions (flagged per A.111: anything learnable only from the live API
is listed here so a wrong assumption is found fast):
  A1. alpaca-py OptionContractsRequest returns contracts with
      bid/ask/open_interest/strike_price fields populated on the free tier.
  A2. Option snapshots come from the separate Data API (`/v1beta1/options/
      snapshots/...`), NOT TradingClient.get_option_contracts — assumed
      15-min delayed indicative quotes (research brief), which is exactly why
      ordermech reprices off the live underlying before trusting any mid.
  A3. Multi-leg option orders submit via TradingClient.submit_order with
      OptionLegRequest legs (symbol, ratio_qty, side, position_intent) and
      order_class=multileg, time_in_force=day. Verified against the installed
      alpaca-py surface 2026-08-28; live smoke test still pending keys-in-SDK
      (A.112 confirms keys live, SDK smoke is Monday's first task).
  A4. get_account().account_number exists on the paper endpoint (A.112
      verified the raw /v2/account shape).

Hard rules from A.112/A.113 encoded here (not in config, HERE):
  - equity is read at decision time; never defaulted, never cached.
  - assert_account(expected) REFUSES the trade if account_number mismatches.
  - There are TWO paper accounts: a $1M development tester and a $100k
    judged submission account. Any run must name which one it is on; real
    account ids live in the private env file, never in code (A.112).
"""
import json
import os


class AccountMismatch(RuntimeError):
    """Keys resolved to a different account than the run expects. Refuse."""


class BrokerError(RuntimeError):
    """Any adapter-level failure. Fail-closed: callers refuse to trade."""


def _die_unsupported(method_name):
    raise BrokerError(
        f"{method_name} unavailable — broker adapter misconfigured")


class BaseBroker:
    """Minimal interface. FixtureBroker (offline) and AlpacaBroker (live)
    both satisfy it; the trading path is written against THIS, never against
    alpaca-py directly."""

    def get_account(self) -> dict:        _die_unsupported("get_account")
    def get_option_chain(self, name, strike_lo, strike_hi,
                         dte_lo, dte_hi, today=None) -> list:
        _die_unsupported("get_option_chain")
    def get_option_snapshot(self, symbol) -> dict:
        _die_unsupported("get_option_snapshot")
    def get_underlying_quote(self, symbol) -> dict:
        _die_unsupported("get_underlying_quote")
    def get_positions(self) -> list:      _die_unsupported("get_positions")
    def get_open_orders(self) -> list:    _die_unsupported("get_open_orders")

    def place_option_order(self, order_plan: dict) -> dict:
        _die_unsupported("place_option_order")

    def cancel_order(self, order_id) -> bool:
        _die_unsupported("cancel_order")

    # -- the guard every order path must pass through --------------------

    def assert_account(self, expected_number: str) -> dict:
        """Read /v2/account NOW, compare account_number, refuse on mismatch.
        Returns the account dict (so equity is read at decision time in the
        same call). Raises AccountMismatch / BrokerError -> fail-closed."""
        acct = self.get_account()
        got = acct.get("account_number")
        if got != expected_number:
            raise AccountMismatch(
                f"keys resolve to {got!r} but this run expects "
                f"{expected_number!r} — refusing (A.112 #2)")
        return acct


def equity_now(broker: BaseBroker, expected_number: str) -> dict:
    """Decision-time equity read with account assertion. No fallback, no
    cache: if this raises, the caller refuses to trade (fail-closed)."""
    return broker.assert_account(expected_number)


TESTER_ACCOUNT = "FX-DEV-1M"            # fixture: $1,000,000 development role
SUBMISSION_ACCOUNT = "FX-JUDGE-100K"    # fixture: $100,000 judged role
ACCOUNTS = {
    TESTER_ACCOUNT: {"equity": 1_000_000.0, "role": "development"},
    SUBMISSION_ACCOUNT: {"equity": 100_000.0, "role": "submission"},
}
# LIVE runs: the expected account number is injected via the environment
# (ALPACA_EXPECTED_ACCOUNT) from the private env file — real account ids are
# configuration, not code, and never appear in this repository (A.112).
import os as _os
LIVE_EXPECTED_ACCOUNT = _os.environ.get("ALPACA_EXPECTED_ACCOUNT")


class FixtureBroker(BaseBroker):
    """Offline fake driven by JSON fixtures. Same interface, zero network.

    Fixture files (dir): account.json, chain_{NAME}.json (optional),
    snapshot_{SYMBOL}.json, underlying_{SYMBOL}.json, positions.json,
    open_orders.json. Missing file -> BrokerError (fail-closed, same as
    live being down) EXCEPT account.json which a test can seed per-case.
    """

    def __init__(self, fixture_dir: str, account_number: str):
        self.dir = fixture_dir
        self.account_number = account_number
        self.placed_orders = []      # records every ticket, for assertions
        self.cancelled = []
        self._suspend_patched_to = None

    def _load(self, fname):
        path = os.path.join(self.dir, fname)
        if not os.path.exists(path):
            raise BrokerError(f"fixture missing: {fname} (fail-closed)")
        with open(path) as f:
            return json.load(f)

    def get_account(self) -> dict:
        acct = self._load("account.json")
        acct["account_number"] = self.account_number
        return acct

    def get_option_chain(self, name, strike_lo, strike_hi,
                         dte_lo, dte_hi, today=None):
        chain = self._load(f"chain_{name}.json")
        out = []
        for c in chain:
            dte = None
            if today is not None and c.get("expiration_date"):
                y, m, d = (int(x) for x in c["expiration_date"].split("-"))
                from datetime import date
                dte = (date(y, m, d) - today).days
            if dte is not None and not (dte_lo <= dte <= dte_hi):
                continue
            if not (strike_lo <= float(c["strike_price"]) <= strike_hi):
                continue
            out.append(c)
        return out

    def get_option_snapshot(self, symbol):
        return self._load(f"snapshot_{symbol}.json")

    def get_underlying_quote(self, symbol):
        return self._load(f"underlying_{symbol}.json")

    def get_positions(self):
        return self._load("positions.json")

    # -- configurations seam (§8.2 suspend_trade trap) --------------------

    def get_configurations(self) -> dict:
        path = os.path.join(self.dir, "configurations.json")
        if not os.path.exists(path):
            # default healthy shape (live tester GET 2026-08-29)
            return {"suspend_trade": False, "no_shorting": False,
                    "fractional_trading": True, "max_margin_multiplier": "4",
                    "closing_transactions_only": False}
        with open(path) as f:
            return json.load(f)

    def set_suspend_trade(self, value: bool) -> dict:
        self._suspend_patched_to = bool(value)   # assertable in tests
        return {"suspend_trade": bool(value)}

    def place_closing_order(self, ticket: dict):
        # Accept BOTH live shapes: a simple order carries symbol/side at the top
        # level, an mleg order carries legs[]. Demanding legs[] here is what let
        # the 422 of 2026-09-04 14:30Z pass every fixture: the fake enforced our
        # shape, not Alpaca's.
        if not ticket.get("legs") and not (ticket.get("symbol") and ticket.get("side")):
            raise BrokerError("closing ticket has neither legs nor symbol+side")
        rec = {k: v for k, v in ticket.items() if not k.startswith("_")}
        rec["status"] = getattr(self, "_next_close_status", "filled")
        rec["id"] = f"fxc-{len(self.placed_orders) + 1:04d}"
        self.placed_orders.append(rec)
        return rec

    def get_open_orders(self):
        return self._load("open_orders.json")

    def place_option_order(self, order_plan):
        if order_plan.get("decision") != "SUBMIT":
            raise BrokerError("place_option_order requires a SUBMIT plan")
        rec = dict(order_plan)
        rec["status"] = "accepted"
        rec["order_id"] = f"fx-{len(self.placed_orders) + 1:04d}"
        self.placed_orders.append(rec)
        return rec

    def cancel_order(self, order_id):
        self.cancelled.append(order_id)
        return True
