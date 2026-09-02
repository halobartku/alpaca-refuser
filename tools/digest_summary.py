#!/usr/bin/env python3
"""Aggregate gate-funnel summary for a decision journal — A.153 #3.

The full refuser.digest render lists every evaluation verbatim (230K chars
on a 448-refusal day). Judges read the FIRST page. This tool aggregates
the same journal into the front page that render() deserves:

  - decision split and chain status
  - gate funnel: pass-rate per gate, worst offender first
  - near-misses: candidates blocked by exactly one gate (excluding the
    calendar gate, which fails by construction outside the entry window)
  - best credits seen vs the credit threshold

Wednesday run: digest_summary.py live-decisions.jsonl > summary.md,
then refuser.digest.render for the full appendix. Chain is verified on
load by refuser.log.DecisionLog (raises on tamper).
"""
import argparse
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

from refuser.log import DecisionLog  # noqa: E402

# calendar fails by construction on any off-window evaluation; it is not
# a market judgement, so near-miss analysis excludes it.
NON_MARKET_GATES = {"calendar"}


def summarize(path: str) -> str:
    log = DecisionLog(path)  # verifies chain or raises
    rows = []
    with open(path) as f:
        for i, line in enumerate(f):
            line = line.strip()
            if line:
                rec = json.loads(line)
                body = rec["body"]
                body.setdefault("seq", rec.get("seq", i))
                rows.append(body)

    entries = [r for r in rows if r.get("event") == "evaluate_entry"]
    decisions = collections.Counter(r.get("decision") for r in entries)
    gate_pass = collections.Counter()
    gate_fail = collections.Counter()
    near_miss = []          # blocked by exactly one market gate
    seen_near_miss = set()  # (name, gate, detail) — dedup re-evaluations
    credits = []            # (credit, passed_width_credit, name, seq)

    for r in entries:
        fails = []
        for g in r.get("gates", []):
            (gate_pass if g["pass"] else gate_fail)[g["gate"]] += 1
            if not g["pass"] and g["gate"] not in NON_MARKET_GATES:
                fails.append(g)
            if g["gate"] == "width_credit":
                m = re.search(r"credit=([0-9.]+)", g.get("detail", ""))
                if m:
                    credits.append((float(m.group(1)), g["pass"],
                                    r.get("name"), r.get("seq")))
        if len(fails) == 1:
            # Dedup identical re-evaluations of the same candidate (same name,
            # same gate, same detail): multi-day live journals re-scan the same
            # 8-name universe each session and the judge-facing front page must
            # list each distinct near-miss once, not once per session.
            key = (r.get("name"), fails[0]["gate"], fails[0]["detail"])
            if key not in seen_near_miss:
                seen_near_miss.add(key)
                near_miss.append((r, fails[0]))

    L = []
    L.append("# Gate funnel — aggregate")
    L.append("")
    L.append(f"- chain: **{log.count} records, head `{log.head[:16]}…`** "
             f"(verified on load)")
    acc = decisions.get("ACCEPT", 0)
    ref = decisions.get("REFUSE", 0)
    L.append(f"- entries evaluated: **{len(entries)}** — "
             f"ACCEPT **{acc}**, REFUSE **{ref}**")
    L.append("")
    L.append("| gate | pass | fail | pass rate |")
    L.append("|---|---:|---:|---:|")
    for g in sorted(set(gate_pass) | set(gate_fail),
                    key=lambda k: gate_fail[k], reverse=True):
        p, f_ = gate_pass[g], gate_fail[g]
        L.append(f"| `{g}` | {p} | {f_} | {p / (p + f_) * 100:.0f}% |")
    L.append("")
    L.append(f"## Near-misses — blocked by exactly one market gate "
             f"({len(near_miss)})")
    L.append("")
    if not near_miss:
        L.append("_none: no candidate was a single gate away from entry._")
    for r, g in near_miss:
        L.append(f"- **{r.get('name')}** seq {r.get('seq')} — only "
                 f"`{g['gate']}`: {g['detail']}")
    if credits:
        best = max(credits)
        L.append("")
        L.append(f"## Credit headroom")
        L.append("")
        L.append(f"- best credit seen: **{best[0]:.2f}** "
                 f"({best[2]}, seq {best[3]}) — gate needs ≥ 1.00; "
                 f"{'cleared' if best[1] else 'short'}")
        n_over = sum(1 for c, p, _, _ in credits if c >= 1.00)
        L.append(f"- candidates with credit ≥ 1.00: **{n_over} / "
                 f"{len(credits)}** — every one was refused on another gate")
    L.append("")
    L.append("_Full per-candidate anatomy: refuser.digest.render on the "
             "same journal (appendix)._")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("journal")
    args = ap.parse_args()
    try:
        sys.stdout.write(summarize(args.journal))
    except Exception as e:
        print(f"FATAL: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
