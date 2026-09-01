#!/bin/bash
# build_video.sh — produce the submission MP4 (honest pre-week cut).
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=build
mkdir -p "$OUT/frames" "$OUT/audio"
CHROM="chromium --headless=new --no-sandbox --disable-gpu --hide-scrollbars"
VOICE="en-US-AndrewMultilingualNeural"

# ---- 1. honest slide variant ----
python3 - "$OUT/slides-final.html" <<'PY'
import sys
html = open("slides.html").read()
subs = [
    ("[LIVE ACCOUNT]",
     "Judged account FX-JUDGE-100K (week opens 2026-09-01; live number filled at build)"),
    ("This week: <span class=\"live\">[LIVE N]</span> evaluated,\n    "
     "<span class=\"live\">[LIVE M]</span> taken, <span class=\"live\">[LIVE K]</span> refused",
     "Demo cycle (shipped gate path, fixture market): 4 evaluated, 1 taken, 3 refused"),
    ("<span class=\"live\">[LIVE X cents per leg]</span>",
     "measured at build against final marks; cut if unavailable"),
    ("<span class=\"live\">[LIVE equity curve, start to finish]</span>",
     "filled from the judged account at build time; removed if not available"),
    ("<span class=\"live\">[LIVE trades taken / refusals / win rate / P&amp;L per unit of risk]</span>",
     "filled from the judged account at build time; removed if not available"),
]
for a, b in subs:
    assert a in html, f"missing: {a[:40]}"
    html = html.replace(a, b)
open(sys.argv[1], "w").write(html)
print("slides-final.html written")
PY

# ---- 2. render demo terminal ---- 
python3 tools/demo_cycle.py > "$OUT/demo.txt" 2>&1
python3 - "$OUT/demo.txt" <<'PY'
import sys, html as H
demo = open(sys.argv[1]).read()
open("/tmp/demo_screen.html","w").write(
 f"""<!doctype html><html><head><meta charset=utf-8><style>
 body{{margin:0;background:#0b0e14;color:#dbe4f0;
 font:15px/1.32 ui-monospace,Menlo,Consolas,monospace}}
 pre{{padding:20px 26px;white-space:pre;margin:0}}</style></head>
 <body><pre>{H.escape(demo)}</pre></body></html>""")
PY
$CHROM --force-device-scale-factor=1 --window-size=1200,820 \
  --screenshot="$OUT/frames/demo.png" "file:///tmp/demo_screen.html" >/dev/null 2>&1 || true
echo "demo.png rendered"

# ---- 3. render each slide ----
for i in 1 2 5 6 7 10 12; do
  # each .slide is its own page; print-specific: show slide i then screenshot
  $CHROM --force-device-scale-factor=1 --window-size=1122,793 \
    --screenshot="$OUT/frames/slide_$i.png" \
    "file://$PWD/$OUT/slides-final.html#$i" >/dev/null 2>&1 || true
done
ls -la "$OUT/frames/" | grep slide_ | head

# ---- 4. PDF from print ----
$CHROM --headless=new --no-sandbox --disable-gpu \
  --print-to-pdf="$OUT/slides-final.pdf" \
  --print-to-pdf-no-header \
  "file://$PWD/$OUT/slides-final.html" >/dev/null 2>&1 || true
ls -la "$OUT/slides-final.pdf"

echo "BUILD_STAGE=rendered done"