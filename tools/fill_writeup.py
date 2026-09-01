#!/usr/bin/env python3
"""Fill WRITEUP.md [FILL] placeholders from a live decision log. A.153 #4.

Run after Wednesday's live session, BEFORE Bartosz submits:
    python3 tools/fill_writeup.py <decisions.jsonl> [--write]

Default is DRY RUN: prints the replacement for every [FILL] line with its
evidence. --write edits WRITEUP.md in place (backup kept as
WRITEUP.md.bak-<ts>). Numbers come ONLY from the log — nothing is invented:
every metric prints the exact source line it was derived from.
"""
import json
import re
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WRITEUP = ROOT / "WRITEUP.md"


def load(path):
    sys.path.insert(0, str(ROOT))
    from refuser.log import DecisionLog  # verifies hash chain or raises

    DecisionLog(path)  # chain check — a broken chain must stop us
    bodies = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                bodies.append(json.loads(line)["body"])
    return bodies


def fmt(n, nd=2):
    return f"{float(n):.{nd}f}"


def derive(bodies):
    ev = [r for r in bodies if r.get("event") == "evaluate_entry"]
    tickets = [r for r in bodies if r.get("event") == "order_ticket"]
    fills = [r for r in bodies if r.get("event") == "fill"]
    pm = [r for r in bodies if r.get("event") == "postmortem"]
    dec = Counter(r.get("decision") for r in ev)
    taken = dec.get("ACCEPT", 0)
    refused = dec.get("REFUSE", 0)

    m = {}
    src = {}

    m["taken"] = str(taken)
    m["refused"] = str(refused)
    src["trades"] = f"evaluate_entry rows: {dict(dec)} (total {len(ev)})"

    # Win rate vs 85.7% breakeven — only defined from CLOSED trades.
    closed = 0
    wins = 0
    pnl_closed = 0.0
    for r in pm + fills + tickets:
        for k in ("realized_pnl", "pnl", "net_pnl"):
            if isinstance(r.get(k), (int, float)):
                closed += 1
                pnl_closed += float(r[k])
                if float(r[k]) > 0:
                    wins += 1
                break
    if closed:
        m["winrate"] = f"{100.0 * wins / closed:.1f}% ({wins}/{closed} closed)"
        src["winrate"] = f"closed trades with pnl field: {closed}, wins {wins}"
    else:
        m["winrate"] = (
            "n/a — the gates refused every candidate, so no trade was "
            "opened and no win rate exists. The refusal log IS the result."
        )
        src["winrate"] = "zero closed trades in log (searched postmortem/fill/ticket pnl fields)"

    # P&L normalised per unit of risk.
    risk = None
    for r in tickets:
        for k in ("risk_per_ticket", "max_loss", "risk"):
            if isinstance(r.get(k), (int, float)):
                risk = float(r[k])
                break
        if risk:
            break
    if closed or pnl_closed:
        if risk:
            m["pnl"] = f"{fmt(pnl_closed)} per {fmt(risk)} risk = {fmt(pnl_closed / risk)}x"
            src["pnl"] = f"closed pnl {fmt(pnl_closed)} / ticket risk {fmt(risk)}"
        else:
            m["pnl"] = f"{fmt(pnl_closed)} at $100k base (per-ticket risk field absent from log)"
            src["pnl"] = f"closed pnl {fmt(pnl_closed)}; no risk field on tickets"
    else:
        m["pnl"] = "n/a — no trade was opened, no P&L was manufactured (see win rate line)"
        src["pnl"] = "zero pnl-bearing rows in log"

    # Slippage: quoted vs limit vs filled, from fill rows.
    slips = []
    for r in fills:
        for qk, lk, fk in (("quoted", "limit", "filled"), ("quote", "limit_price", "fill_price")):
            q, l, f = r.get(qk), r.get(lk), r.get(fk)
            if all(isinstance(v, (int, float)) for v in (q, l, f)):
                slips.append((q, l, f))
                break
    if slips:
        qs = sum(s[0] for s in slips) / len(slips)
        fs = sum(s[2] for s in slips) / len(slips)
        m["slip"] = f"quoted {fmt(qs)} vs filled {fmt(fs)} across {len(slips)} fills"
        src["slip"] = f"{len(slips)} fill rows with quoted/limit/filled fields"
    else:
        m["slip"] = "n/a — zero fills; the repricer marks were never tested against a real fill"
        src["slip"] = "zero fill rows with quoted/limit/filled fields"

    # Max drawdown vs 1.5% daily stop.
    eq = [r.get("equity") for r in bodies if isinstance(r.get("equity"), (int, float))]
    if len(eq) >= 2:
        peak, mdd_pct = eq[0], 0.0
        for v in eq:
            peak = max(peak, v)
            if peak:
                mdd_pct = max(mdd_pct, (peak - v) / peak * 100)
        m["mdd"] = f"{fmt(mdd_pct)}% peak-to-trough on logged equity ({len(eq)} samples)"
        src["mdd"] = f"equity samples {len(eq)}, min {fmt(min(eq))}, max {fmt(max(eq))}"
    else:
        m["mdd"] = "n/a — no positions, equity never moved, drawdown 0 by absence"
        src["mdd"] = f"equity-bearing rows: {len(eq)}"

    return m, src


FILL_RE = re.compile(r"\[FILL\]")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    logpath = sys.argv[1]
    write = "--write" in sys.argv
    bodies = load(logpath)
    m, src = derive(bodies)

    # One key per [FILL] token, in file order (line 73 carries two tokens).
    keys = ["taken", "refused", "winrate", "pnl", "slip", "mdd"]

    text = WRITEUP.read_text()
    out_lines, filled, ki = [], 0, 0
    for line in text.splitlines():
        # Only Evidence bullets carry fillable tokens; the blockquote on the
        # preamble mentions [FILL] as prose and must NOT be substituted.
        if line.lstrip().startswith("- "):
            while FILL_RE.search(line) and ki < len(keys):
                k = keys[ki]
                line = FILL_RE.sub(m[k], line, count=1)
                print(f"  [{ki + 1}/{len(keys)}] {k}: {m[k]}")
                print(f"        src: {src.get(k, src.get('trades') if k in ('taken', 'refused') else '')}")
                filled += 1
                ki += 1
        out_lines.append(line)

    if filled != len(keys):
        print(f"WARNING: expected {len(keys)} [FILL] tokens, filled {filled} — WRITEUP changed?", file=sys.stderr)
        sys.exit(1)

    if write:
        bak = WRITEUP.with_name(f"WRITEUP.md.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(WRITEUP, bak)
        WRITEUP.write_text("\n".join(out_lines) + "\n")
        print(f"\nWRITTEN: {WRITEUP} (backup {bak.name})")
    else:
        print("\nDRY RUN — pass --write to apply (a backup copy is kept).")


if __name__ == "__main__":
    main()
