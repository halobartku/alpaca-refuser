#!/usr/bin/env python3
"""Split slides-final.html into N single-slide pages + one PDF-per-slide set."""
import re, sys, os

src = open("build/slides-final.html").read()

# extract the <style> block
m = re.search(r"<style>.*?</style>", src, re.S)
style = m.group(0)

# extract each <section class="slide"> ... </section>
sections = re.findall(r"<section class=\"slide\">.*?</section>", src, re.S)
print(f"found {len(sections)} slides")

os.makedirs("build/slides", exist_ok=True)
for i, sec in enumerate(sections, 1):
    page = f"""<!doctype html><html><head><meta charset="utf-8">
{style}
@media print {{ .slide{{margin:0;box-shadow:none}} }}
</head><body style="background:#05070b">{sec}</body></html>"""
    open(f"build/slides/slide_{i:02d}.html", "w").write(page)
print("wrote build/slides/slide_01..%02d.html" % len(sections))