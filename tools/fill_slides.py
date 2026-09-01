#!/usr/bin/env python3
"""fill_slides.py – inject live data into slides.html

Usage: python3 tools/fill_slides.py <decision_log.json>

The script reads a JSON file containing live decision results (e.g. the account ID
and any runtime numbers) and replaces placeholders in `slides.html`:
    [LIVE ACCOUNT]   → actual account identifier
    [LIVE METRIC …] → metric values

It updates the file in‑place and exits with code 0 on success.
"""
import sys, json, re, pathlib

def main():
    if len(sys.argv) != 2:
        print("Usage: fill_slides.py <decision_log.json>")
        sys.exit(1)
    log_path = pathlib.Path(sys.argv[1])
    data = json.loads(log_path.read_text())
    slide_path = pathlib.Path("slides.html")
    text = slide_path.read_text()
    # Simple placeholder replacement: keys in data map to [LIVE KEY]
    for key, val in data.items():
        placeholder = f"[LIVE {key.upper()}]"
        text = re.sub(re.escape(placeholder), str(val), text)
    slide_path.write_text(text)
    print("filled slides.html")

if __name__ == "__main__":
    main()
