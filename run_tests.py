#!/usr/bin/env python3
"""One-command test runner: python3 run_tests.py — zero network, zero creds."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SUITES = ["test_offline.py", os.path.join("fixtures", "test_broker_path.py")]

fails = 0
for suite in SUITES:
    print(f"\n### {suite}")
    r = subprocess.run([sys.executable, os.path.join(HERE, suite)])
    if r.returncode != 0:
        fails += 1
print(f"\n{'ALL GREEN' if fails == 0 else f'{fails} SUITE(S) FAILED'}")
sys.exit(1 if fails else 0)
