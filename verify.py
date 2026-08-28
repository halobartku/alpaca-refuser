#!/usr/bin/env python3
"""One-command verification of the decision log's hash chain.

Promised in refuser/log.py since the first commit, shipped now. Judges (or
anyone) can confirm the audit trail is tamper-evident:

    python3 verify.py [decisions.jsonl]

Exit 0 + "CHAIN OK" = every line's prev/hash links verify against the
previous line and the recorded body. Any mutation of a historical line
(a rewritten gate result, an edited fill price) breaks the chain at that
line and this says exactly where.
"""
import json
import os
import sys

from refuser.log import DecisionLog


def main(argv):
    path = argv[1] if len(argv) > 1 else "decisions.jsonl"
    if not os.path.exists(path):
        print(f"CHAIN OK (empty) — no decision log yet at {path}")
        return 0
    try:
        log = DecisionLog(path)
    except (RuntimeError, json.JSONDecodeError) as e:
        print(f"CHAIN BROKEN — {e}")
        return 1
    print(f"CHAIN OK — {log.count} records, head {log.head[:16]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
