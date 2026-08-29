"""Audit producers — the ONLY layer allowed to write the decision log.

A.111 #4: the evidence harness. Every runtime step that matters to a judge
flows through here, each returning the record it appended (hash-chained,
tamper-evident — see refuser/log.py). The composition contract is the one
pinned in fixtures/test_broker_path.py:

    an order reaches the broker ONLY if gates ACCEPT *and* ordermech SUBMITS.

This module never imports a concrete broker; it takes the BaseBroker seam,
so the same producers run offline (FixtureBroker) and live (AlpacaBroker).
"""
import time as _time

from refuser import exits, gates, liquidate, ordermech
from refuser.log import DecisionLog


class AuditTrail:
    """One decision log per run. Producers below are methods so the chain
    ordering (session -> evaluations -> tickets -> fills -> exits) is
    enforced by construction, not by caller discipline."""

    def __init__(self, broker, log: DecisionLog):
        self.broker = broker
        self.log = log

    # -- session lifecycle ------------------------------------------------

    def session_open(self, expected_account: str, role: str) -> dict:
        """First record of every run: decision-time account assertion.
        If equity_now raises (AccountMismatch/BrokerError) the session
        refuses to start — fail-closed, and the failure itself is logged."""
        try:
            from refuser.broker import equity_now
            acct = equity_now(self.broker, expected_account)
        except Exception as e:                      # fail-closed, recorded
            rec = self.log.append({
                "event": "session_open",
                "ok": False,
                "account_number": expected_account,
                "role": role,
                "error": f"{type(e).__name__}: {e}",
            })
            raise
        return self.log.append({
            "event": "session_open",
            "ok": True,
            "account_number": acct["account_number"],
            "role": role,
            "equity": acct["equity"],
            "status": acct.get("status"),
            "trading_blocked": acct.get("trading_blocked"),
        })

    # -- entry path ---------------------------------------------------------

    def evaluate_entry(self, intent: dict, state: dict, market: dict) -> dict:
        """Gate evaluation record. The full refusal anatomy (every gate,
        pass or fail) is the artifact — judges see why, not just that."""
        ev = gates.evaluate_intent(intent, state, market)
        self.log.append({
            "event": "evaluate_entry",
            "decision": ev["decision"],
            "name": intent.get("name"),
            "contracts": ev["contracts"],
            "gates": ev["gates"],
        })
        return ev

    def submit_entry(self, ev: dict, mark: float, stale_mid: float,
                     sym_short: str, sym_long: str) -> dict:
        """Order ticket record — the guarded composition. Places ONLY when
        gates ACCEPT and ordermech SUBMITS; every other branch is a logged
        refusal with the broker untouched."""
        if ev["decision"] != "ACCEPT" or ev["contracts"] < 1:
            return self.log.append({
                "event": "order_ticket", "decision": "REFUSE",
                "reason": f"gates said {ev['decision']}",
            })
        plan = ordermech.order_plan(mark, stale_mid, ev["contracts"])
        if plan.get("decision") != "SUBMIT":
            return self.log.append({
                "event": "order_ticket", "decision": "REFUSE",
                "reason": plan.get("reason"),
            })
        plan["symbols_short"] = sym_short
        plan["symbols_long"] = sym_long
        receipt = self.broker.place_option_order(plan)
        slip = ordermech.measure_slippage(
            stale_mid, plan["limit_credit"],
            float(receipt.get("filled_avg_price", plan["limit_credit"])))
        return self.log.append({
            "event": "order_ticket", "decision": "SUBMIT",
            "plan": {k: v for k, v in plan.items()},
            "receipt": {k: receipt.get(k) for k in
                        ("order_id", "status", "filled_qty",
                         "filled_avg_price")},
            "slippage": slip,
        })

    def fill(self, position_plan: dict, order_id: str) -> dict:
        """Position-opened record (the plan; proves nothing was PLACED)."""
        return self.log.append({
            "event": "fill",
            "order_id": order_id,
            "position": position_plan,
        })

    def place_gtc_exit(self, position_plan: dict, sym_short: str,
                       sym_long: str) -> dict:
        """Rule 1 (exits.py): a position is NEVER alive without its resting
        exit. Actually PLACES the GTC buy-to-close companion at the broker AT
        FILL TIME and logs the receipt (2026-08-29 correctness fix: the digest
        used to render 'GTC exit resting at $X' from the plan alone — a claim
        no code path backed. A fill record alone now renders nothing).

        Fail-closed: if the broker rejects the GTC ticket the error is logged
        and re-raised — the runtime must close the fresh position immediately
        rather than keep it naked. The digest renders GTC exits ONLY from
        these records.
        """
        g = position_plan["gtc_exit"]
        ticket = {
            "type": "limit",
            "time_in_force": "gtc",
            "order_class": "mleg",
            "qty": str(position_plan["contracts"]),
            "limit_price": f"{g['limit']:.2f}",
            "legs": [
                {"symbol": sym_short, "ratio_qty": "1", "side": "buy",
                 "position_intent": "buy_to_close"},
                {"symbol": sym_long, "ratio_qty": "1", "side": "sell",
                 "position_intent": "sell_to_close"},
            ],
            "_meta": {"kind": "gtc-exit-companion", "placed_at": "fill"},
        }
        try:
            receipt = self.broker.place_closing_order(ticket)
        except Exception as e:
            self.log.append({
                "event": "gtc_exit", "ok": False,
                "name": position_plan.get("name"),
                "error": f"{type(e).__name__}: {e}",
            })
            raise
        return self.log.append({
            "event": "gtc_exit", "ok": True,
            "name": position_plan.get("name"),
            "contracts": position_plan["contracts"],
            "limit": g["limit"],
            "receipt": {k: receipt.get(k) for k in ("id", "status")},
        })

    # -- exit path ----------------------------------------------------------

    def scan_exits(self, positions: list, now) -> dict:
        """Evaluate every open position against all 6 exit rules; log the
        scan (including holds) so the digest can show exits NOT taken."""
        fired = []
        for pos in positions:
            decision = exits.check_position(pos, {}, now)
            if decision is not None:
                fired.append(decision)
        return self.log.append({
            "event": "exit_scan",
            "checked": len(positions),
            "fired": fired,
        })

    # -- close ----------------------------------------------------------

    def postmortem(self, summary: dict) -> dict:
        """End-of-run record: realized/unrealized, per-risk framing."""
        return self.log.append({"event": "postmortem", **summary})

    # -- R2 liquidation (PLAYBOOK §2: judged P&L = realized P&L) ---------

    def r2_liquidate(self, positions: list, snapshot_fn, sleep=_time.sleep,
                     max_walks: int = liquidate.MAX_WALKS_R2) -> dict:
        """Hash-chained R2 record (2026-08-29 correctness fix: liquidate_all
        was audit-silent — the week's terminal judged event, the 10:55 ET
        flatten that pins judged P&L = realized P&L, would have left ZERO
        chain evidence). The engine's fail-closed BrokerError is logged then
        re-raised so a broken liquidation is on the record too."""
        t0 = _time.time()
        try:
            report = liquidate.liquidate_all(
                self.broker, positions, snapshot_fn,
                sleep=sleep, max_walks=max_walks)
        except Exception as e:
            self.log.append({
                "event": "r2_liquidation", "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "elapsed_s": round(_time.time() - t0, 1)})
            raise
        return self.log.append({
            "event": "r2_liquidation", "ok": True,
            "cancelled": report["cancelled"],
            "closed": report["closed"],
            "failed": report["failed"],
            "elapsed_s": round(_time.time() - t0, 1)})

    def r2_verify(self, positions_after: list) -> dict:
        """10:55–11:00 ET verification: every option position row must be
        gone. The residual list IS the record — a non-empty residual logs
        ok=False but does not raise (the R2 engine already raised); the
        digest shows it red."""
        ok, residual = liquidate.verify_flat(positions_after)
        return self.log.append({
            "event": "r2_verify_flat", "ok": ok, "residual": residual})
