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
        g = pos.get("gtc_exit", {})
        L.append(f"- 🔓 FILL {pos.get('contracts')}x "
                 f"**{pos.get('name')}** credit "
                 f"${_r0(pos.get('entry_credit', 0))} — GTC exit resting "
                 f"at ${g.get('limit')} (placed at fill)")
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
    L.append("_AI-authored trading agent; disclosure and method in "
             "WRITEUP.md. P&L on the tester account understates per-risk "
             "capacity — read every number per unit of risk (A.113)._")
    return "\n".join(L)

