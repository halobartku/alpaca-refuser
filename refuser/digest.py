"""Daily evidence digest — A.111 #4.

Renders the hash-chained decision log into the one-page daily artifact a
judge (or we) read first: chain status, account/equity, every entry
evaluated with its full gate anatomy, every ticket with measured
slippage, fills, exit scans, and the post-mortem — with the per-unit-of-
risk framing A.113 mandates (tester numbers are 10x and must never be
read as capacity).

Built BEFORE there is data to render (A.111: the digest must exist
before the data, not after), and tested against a synthetic log produced
by audit.py itself — so the renderer is pinned to real record shapes,
not invented ones.
"""
import json

from refuser.log import DecisionLog


def _r0(x):
    return round(float(x), 2) if isinstance(x, (int, float)) else x


def render(path: str) -> str:
    """One-page markdown digest of a decision log. Tamper-evidence is
    re-verified on load (DecisionLog raises on a broken chain)."""
    log = DecisionLog(path)          # verifies the chain or raises
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line)["body"])

    ev_entries = [r for r in rows if r.get("event") == "evaluate_entry"]
    tickets = [r for r in rows if r.get("event") == "order_ticket"]
    fills = [r for r in rows if r.get("event") == "fill"]
    scans = [r for r in rows if r.get("event") == "exit_scan"]
    sessions = [r for r in rows if r.get("event") == "session_open"]
    posts = [r for r in rows if r.get("event") == "postmortem"]
    gtcs = [r for r in rows if r.get("event") == "gtc_exit"]
    r2s = [r for r in rows if r.get("event") == "r2_liquidation"]
    verifies = [r for r in rows if r.get("event") == "r2_verify_flat"]

    L = []
    L.append("# Daily evidence digest")
    L.append("")
    L.append(f"- chain: **{log.count} records, head `{log.head[:16]}…`** "
             f"(verified by refuser.log on load; `python3 verify.py` "
             f"re-checks independently)")
    s = sessions[-1] if sessions else {}
    if s:
        L.append(f"- session: account `{s.get('account_number')}` role "
                 f"**{s.get('role')}** equity **${s.get('equity'):,.0f}**"
                 + (" ⚠️ trading_blocked" if s.get("trading_blocked") else ""))
    for p in posts:
        extra = {k: v for k, v in p.items() if k != "event"}
        L.append(f"- post-mortem: `{json.dumps(extra, default=str)}`")
    L.append("")

    # -- entries ----------------------------------------------------------
    L.append(f"## Entries evaluated ({len(ev_entries)})")
    L.append("")
    if not ev_entries:
        L.append("_none today_")
    for r in ev_entries:
        icon = "✅" if r["decision"] == "ACCEPT" else "🚫"
        fails = [g["detail"] for g in r.get("gates", [])
                 if not g["pass"]]
        L.append(f"- {icon} **{r.get('name')}** — {r['decision']} "
                 f"({r.get('contracts', 0)} contracts)")
        for g in r.get("gates", []):
            mark = "pass" if g["pass"] else "**FAIL**"
            L.append(f"  - `{g['gate']}` {mark} — {g['detail']}")
        if not fails:
            L.append("  - _all gates passed_")
    L.append("")

    # -- tickets ----------------------------------------------------------
    L.append(f"## Order tickets ({len(tickets)})")
    L.append("")
    if not tickets:
        L.append("_none today_")
    for r in tickets:
        if r.get("decision") != "SUBMIT":
            L.append(f"- 🚫 REFUSE — {r.get('reason')}")
            continue
        plan, slip = r.get("plan", {}), r.get("slippage", {})
        rcpt = r.get("receipt", {})
        L.append(f"- 📨 SUBMIT **{plan.get('contracts')}x** "
                 f"credit limit **${plan.get('limit_credit')}** "
                 f"→ `{rcpt.get('status')}` ({rcpt.get('order_id')})")
        if slip:
            L.append(f"  - slippage: quoted−filled "
                     f"**${slip.get('vs_quoted')}**/spread "
                     f"(${slip.get('per_leg')}/leg, "
                     f"captured {slip.get('captured_frac')})")
    L.append("")

    # -- fills & exits ------------------------------------------------------
    L.append(f"## Fills ({len(fills)}) · exit scans ({len(scans)})")
    L.append("")
    if not fills and not scans:
        L.append("_no positions today_")
    for r in fills:
        pos = r.get("position", {})
        # GTC exits render ONLY from placed gtc_exit records — the fill plan
        # alone proves nothing was placed (2026-08-29 correctness fix).
        gtc = next((g for g in gtcs
                    if g.get("name") == pos.get("name")), None)
        if gtc and gtc.get("ok"):
            L.append(f"- 🔓 FILL {pos.get('contracts')}x "
                     f"**{pos.get('name')}** credit "
                     f"${_r0(pos.get('entry_credit', 0))} — GTC exit "
                     f"**placed** at ${gtc.get('limit')} "
                     f"({(gtc.get('receipt') or {}).get('id')})")
        else:
            L.append(f"- 🔓 FILL {pos.get('contracts')}x "
                     f"**{pos.get('name')}** credit "
                     f"${_r0(pos.get('entry_credit', 0))} — "
                     f"⚠️ **no GTC exit placement on record** "
                     f"(position must not stay open)")
    for r in scans:
        fired = r.get("fired", [])
        if not fired:
            L.append(f"- ⏸️ exit scan: {r.get('checked')} held, 0 fired")
            continue
        for d in fired:
            L.append(f"- 🔁 EXIT **{d.get('rule')}** {d.get('contracts')}x "
                     f"{d.get('name')} → {d.get('action')} "
                     f"@ ${d.get('limit')} — {d.get('note')}")
    L.append("")

    # -- R2 liquidation (PLAYBOOK §2: judged P&L = realized P&L) -----------
    if r2s:
        L.append(f"## R2 liquidation ({len(r2s)})")
        L.append("")
        for r in r2s:
            if not r.get("ok"):
                L.append(f"- 🚫 **R2 FAILURE** — {r.get('error')}")
                continue
            closed = ", ".join(
                f"{c.get('symbol')}×{c.get('qty')} "
                f"({c.get('status')})" for c in r.get("closed", []))
            L.append(f"- 🧹 R2 flatten: {len(r.get('cancelled', []))} orders "
                     f"cancelled, closed: {closed or 'nothing to liquidate'}"
                     + (f", **{len(r.get('failed', []))} FAILED**"
                        if r.get("failed") else ""))
        for r in verifies:
            if r.get("ok"):
                L.append(f"- ✅ verify-flat 10:55–11:00 ET: "
                         f"residual {r.get('residual') or '[]'} — "
                         f"**judged P&L = realized P&L**")
            else:
                L.append(f"- 🚫 verify-flat: residual positions "
                         f"{r.get('residual')} — judged P&L ≠ realized")
        L.append("")
    L.append("_AI-authored trading agent; disclosure and method in "
             "WRITEUP.md. P&L on the tester account understates per-risk "
             "capacity — read every number per unit of risk (A.113)._")
    return "\n".join(L)

