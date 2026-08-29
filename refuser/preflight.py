"""PLAYBOOK §6 — Monday pre-flight, executable.

Every item in the written checklist that can be checked by API, checked by
API, fail-closed. Anything that cannot be checked here is a REFUSE until a
human/next session verifies it manually.

§8.2 trap (live-verified on the tester 2026-08-28): `suspend_trade: true`
was set on the fresh paper account; every order 403s with "new orders are
rejected by user request" until PATCHed false via /v2/account/configurations.
CHECK ON THE SUBMISSION ACCOUNT MONDAY PRE-OPEN BEFORE THE FIRST REAL ORDER.

This module adds the two seam methods the trap needs:
  get_configurations()   -> dict (suspend_trade, no_shorting, ...)
  ensure_tradable()      -> refuses (or with fix=True PATCHes) bad flags

The PATCH is opt-in: automated runs may only clear flags that block defined-
risk option spreads; it NEVER sets anything to true. Logged in the audit
chain by the caller when run under AuditTrail.
"""
from refuser.broker import BaseBroker, BrokerError

# flags that must be FALSE for our defined-risk option trading
BLOCKING_FLAGS = ("suspend_trade", "trading_blocked_is_set_elsewhere")


def check_configurations(configs: dict) -> tuple[bool, list]:
    """Pure: which configuration flags block our trading?"""
    problems = []
    if not isinstance(configs, dict):
        return False, ["configurations payload not a dict — refuse"]
    if configs.get("suspend_trade"):
        problems.append("suspend_trade=true (§8.2 trap): orders would 403")
    acct_flag_note = configs.get("_account_trading_blocked")
    if acct_flag_note:
        problems.append(str(acct_flag_note))
    return (len(problems) == 0), problems


def preflight(broker: BaseBroker, expected_account: str,
              fix: bool = False) -> dict:
    """PLAYBOOK §6 items 1-4 (the API-checkable ones). Returns a report;
    ok=False ⇒ the session REFUSES to place any order.

    fix=True authorises exactly one PATCH per blocking flag (only ever
    setting it to False). fix=False is read-only.
    """
    out = {"checks": [], "ok": True, "fixed": []}

    def chk(name, ok, detail, fix_action=None):
        rec = {"check": name, "ok": bool(ok), "detail": str(detail)[:300]}
        out["checks"].append(rec)
        if not ok:
            if fix and fix_action is not None:
                try:
                    fix_action()
                    out["fixed"].append(name)
                    rec["fixed"] = True
                except Exception as e:            # fail-closed
                    rec["error"] = f"{type(e).__name__}: {e}"
                    out["ok"] = False
            else:
                out["ok"] = False

    # 1. account assertion (equity read at decision time, no cache)
    acct = broker.assert_account(expected_account)
    chk("account", True,
        f"{acct['account_number']} equity {acct['equity']:.2f} "
        f"status {acct.get('status')}")

    # 2. trading_blocked / status from /v2/account
    chk("account_status", acct.get("status") == "ACTIVE",
        f"status={acct.get('status')}")

    # 3. configurations incl. the §8.2 suspend_trade trap
    try:
        configs = broker.get_configurations()
    except Exception as e:
        chk("configurations", False, f"{type(e).__name__}: {e}")
        return out
    ok_cfg, problems = check_configurations(configs)
    if not ok_cfg and fix and "suspend_trade" in problems[0]:
        chk("suspend_trade", False, "; ".join(problems),
            fix_action=lambda: broker.set_suspend_trade(False))
    else:
        chk("suspend_trade", ok_cfg, "; ".join(problems) if problems
            else f"suspend_trade={configs.get('suspend_trade')}")

    # 4. options level readable and >= 3 (spreads need level 3, A.112)
    lvl = acct.get("options_trading_level")
    try:
        lvl_ok = int(lvl) >= 3
    except (TypeError, ValueError):
        lvl_ok = False
    chk("options_level", lvl_ok, f"options_trading_level={lvl!r} (need >=3)")

    return out
