"""AlpacaBroker — live implementation of the BaseBroker seam.

Raw REST (requests), not alpaca-py method calls: A.112 verified /v2/account
works this way, and it removes SDK-version roulette. Paper endpoints only.

This module NEVER runs in the offline suite (no network in tests). It is
imported by live runner only. All failure paths raise BrokerError so the
caller refuses to trade — there is no code path here that returns a stale
or default equity.

Live-API assumptions (A.111 rule: list what only the live API can confirm):
  L1. POST /v2/orders with class=multileg + legs[] is accepted for options
      level 3 accounts (spreads approved per A.112). Unverified until the
      Monday smoke test — the FIRST live action is a 1-contract spread on
      the tester, watched, then cancelled.
  L2. Option chain endpoint: GET /v2/options/contracts (Trading API host).
  L3. Snapshots: GET data host /v1beta1/options/snapshots (indicative,
      15-min delayed on free tier — ordermech reprices off live underlying).
  L4. Latest underlying quote: GET data host /v2/stocks/{sym}/quotes/latest
      with feed=iex (free live feed).
"""
import json

import requests

from refuser.broker import BaseBroker, BrokerError


def occ_symbol(root: str, expiry, strike: float, kind: str = "P") -> str:
    """OCC option symbol: SPY260918P00400000. expiry = date or 'YYYY-MM-DD'."""
    s = str(expiry)
    y, m, d = s.split("-")
    return f"{root.upper()}{y[2:]}{m}{d}{kind.upper()}{int(round(strike * 1000)):08d}"


class AlpacaBroker(BaseBroker):
    TRADING = "https://paper-api.alpaca.markets"
    DATA = "https://data.alpaca.markets"
    TIMEOUT = 10

    def __init__(self, key_id: str, secret_key: str):
        self.key = key_id
        self.secret = secret_key

    def _h(self):
        return {"APCA-API-KEY-ID": self.key,
                "APCA-API-SECRET-KEY": self.secret}

    def _get(self, url, params=None):
        r = requests.get(url, headers=self._h(), params=params,
                         timeout=self.TIMEOUT)
        if r.status_code != 200:
            raise BrokerError(f"GET {url} -> {r.status_code}: {r.text[:200]}")
        return r.json()

    # -- seam methods -----------------------------------------------------

    def get_account(self) -> dict:
        acct = self._get(f"{self.TRADING}/v2/account")
        out = {
            "account_number": acct.get("account_number"),
            "equity": float(acct.get("equity") or 0.0),
            "status": acct.get("status"),
            "trading_blocked": acct.get("trading_blocked"),
            "options_trading_level": acct.get("options_trading_level"),
            "currency": acct.get("currency"),
        }
        if out["account_number"] is None:
            raise BrokerError("account payload missing account_number")
        if out["trading_blocked"]:
            raise BrokerError("trading_blocked=True — refuse")
        if out["status"] != "ACTIVE":
            raise BrokerError(f"account status {out['status']} != ACTIVE")
        if out["equity"] <= 0:
            raise BrokerError(f"equity {out['equity']} not positive — refuse")
        return out

    def get_option_chain(self, name, strike_lo, strike_hi,
                         dte_lo, dte_hi, today=None):
        """Active put contracts in [strike_lo, hi] whose expiration is
        dte_lo..dte_hi days from today. Paginates via next_page_token."""
        from datetime import date, timedelta
        today = today or date.today()
        lo = (today + timedelta(days=dte_lo)).isoformat()
        hi = (today + timedelta(days=dte_hi)).isoformat()
        out, token = [], None
        while True:
            params = {
                "underlying_symbols": name, "status": "active",
                "type": "put", "style": "american",
                "expiration_date_gte": lo, "expiration_date_lte": hi,
                "strike_price_gte": strike_lo, "strike_price_lte": strike_hi,
                "limit": 1000,
            }
            if token:
                params["page_token"] = token
            page = self._get(f"{self.TRADING}/v2/options/contracts", params)
            out.extend(page.get("option_contracts", []))
            token = page.get("next_page_token")
            if not token:
                return out

    def get_option_snapshot(self, symbols):
        """Unwraps the {snapshots:{...}, next_page_token} envelope and
        paginates. LIVE-FIX 2026-08-28 smoke test: the envelope shape was
        assumption L3 and the flat-dict reading returned nothing pre-open."""
        if isinstance(symbols, str):
            symbols = [symbols]
        out, token = {}, None
        while True:
            params = {"symbols": ",".join(symbols), "feed": "indicative"}
            if token:
                params["page_token"] = token
            page = self._get(f"{self.DATA}/v1beta1/options/snapshots", params)
            out.update(page.get("snapshots") or {})
            token = page.get("next_page_token")
            if not token:
                break
        if not out:
            raise BrokerError(f"empty snapshot for {','.join(symbols)[:80]}")
        return out

    def get_underlying_quote(self, symbol):
        q = self._get(
            f"{self.DATA}/v2/stocks/{symbol}/quotes/latest",
            {"feed": "iex"})
        quote = (q or {}).get("quote") or {}
        last = quote.get("bp") and quote.get("ap") and (
            (quote["bp"] + quote["ap"]) / 2.0)
        if last is None:
            raise BrokerError(f"no IEX quote for {symbol} — refuse")
        return {"last": last, "bid": quote.get("bp"), "ask": quote.get("ap")}

    def get_positions(self):
        return self._get(f"{self.TRADING}/v2/positions")

    def get_configurations(self) -> dict:
        """§8.2 trap surface: suspend_trade & friends. GET only."""
        return self._get(f"{self.TRADING}/v2/account/configurations")

    def set_suspend_trade(self, value: bool) -> dict:
        """PATCH /v2/account/configurations {suspend_trade: bool}. Only ever
        called with False by preflight (clearing a block, never adding one).
        Shape live-verified on the tester 2026-08-29 (GET; PATCH mirrors the
        documented config object)."""
        r = requests.patch(
            f"{self.TRADING}/v2/account/configurations",
            headers=self._h(), data=json.dumps({"suspend_trade": bool(value)}),
            timeout=self.TIMEOUT)
        if r.status_code != 200:
            raise BrokerError(
                f"PATCH configurations -> {r.status_code}: {r.text[:200]}")
        return r.json()

    def place_closing_order(self, ticket: dict) -> dict:
        """R2 liquidation ticket (single-leg or mleg close). Same mleg
        conventions as place_option_order; strip the _meta audit key before
        sending. Debit limit is POSITIVE (we pay), credit close negative —
        the ticket's limit_price string is passed through as-shaped."""
        payload = {k: v for k, v in ticket.items() if not k.startswith("_")}
        r = requests.post(f"{self.TRADING}/v2/orders", headers=self._h(),
                          data=json.dumps(payload), timeout=self.TIMEOUT)
        if r.status_code not in (200, 201):
            raise BrokerError(
                f"closing order rejected {r.status_code}: {r.text[:300]}")
        return r.json()

    def get_open_orders(self):
        return self._get(f"{self.TRADING}/v2/orders",
                         {"status": "open", "limit": 500})

    def place_option_order(self, plan: dict) -> dict:
        """plan comes from ordermech.order_plan + symbols. Multileg credit
        spread: sell short-strike put, buy long-strike put, 1:1.

        PAYLOAD VERIFIED LIVE 2026-08-28 13:50 UTC on the tester (order
        ceae4490, filled 0.4s). Schema notes the docs half-state:
          - order_class='mleg' (NOT 'class'), type='limit' (NOT 'order_type')
          - qty and ratio_qty as STRINGS
          - limit_price NEGATIVE = credit, positive = debit (mleg convention)
          - legs carry side (buy/sell) AND position_intent (sell_to_open etc.)
        """
        if plan.get("decision") != "SUBMIT":
            raise BrokerError("place_option_order requires a SUBMIT plan")
        for k in ("symbols_short", "symbols_long", "limit_credit",
                  "contracts"):
            if k not in plan:
                raise BrokerError(f"order plan missing {k!r}")
        payload = {
            "type": "limit",
            "time_in_force": "day",
            "order_class": "mleg",
            "qty": str(plan["contracts"]),
            "limit_price": f"-{plan['limit_credit']:.2f}",
            "legs": [
                {"symbol": plan["symbols_short"], "ratio_qty": "1",
                 "side": "sell", "position_intent": "sell_to_open"},
                {"symbol": plan["symbols_long"], "ratio_qty": "1",
                 "side": "buy", "position_intent": "buy_to_open"},
            ],
        }
        r = requests.post(f"{self.TRADING}/v2/orders", headers=self._h(),
                          data=json.dumps(payload), timeout=self.TIMEOUT)
        if r.status_code not in (200, 201):
            raise BrokerError(
                f"order rejected {r.status_code}: {r.text[:300]}")
        return r.json()

    def cancel_order(self, order_id) -> bool:
        r = requests.delete(f"{self.TRADING}/v2/orders/{order_id}",
                            headers=self._h(), timeout=self.TIMEOUT)
        # 200/204 ok; 422 'order already filled/cancelled' -> False, not raise
        return r.status_code in (200, 204)
