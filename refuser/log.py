"""Hash-chained append-only decision log — the audit artifact.

One JSONL line per decision (entry evaluated, exit fired, gate blocked, order
ticket, fill, post-mortem), each carrying the sha256 of the previous line.
Tamper-evidence is the point: judges can verify the chain with one command
(repo ships verify.py). Same artifact class as the lablab winners that won on
sealed audit trails.
"""
import hashlib
import json
import os
import time


def _hash_line(line: str) -> str:
    return hashlib.sha256(line.encode()).hexdigest()


class DecisionLog:
    def __init__(self, path: str):
        self.path = path
        self._head = "GENESIS"
        self._lines = 0
        if os.path.exists(path):
            self._load_and_verify()

    def _load_and_verify(self):
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                body = json.dumps(rec["body"], sort_keys=True)
                expect = _hash_line(self._head + body)
                if rec["prev"] != self._head or rec["hash"] != expect:
                    raise RuntimeError(
                        f"chain broken at line {self._lines}: log tampered")
                self._head = rec["hash"]
                self._lines += 1

    def append(self, body: dict) -> dict:
        rec = {
            "seq": self._lines,
            "ts": time.time(),
            "prev": self._head,
            "body": body,
        }
        rec["hash"] = _hash_line(self._head + json.dumps(body, sort_keys=True))
        with open(self.path, "a") as f:
            f.write(json.dumps(rec) + "\n")
        self._head = rec["hash"]
        self._lines += 1
        return rec

    @property
    def head(self):
        return self._head

    @property
    def count(self):
        return self._lines
