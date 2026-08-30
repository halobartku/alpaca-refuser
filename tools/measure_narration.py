#!/usr/bin/env python3
"""measure_narration.py — measure TTS duration of each VIDEO-SCRIPT.md VOICE segment.

Synthesizes each VOICE block with edge-tts (the same voice build_video.sh uses)
and reports the wall-clock audio duration per segment + running total. This is
the rehearsal timing test: the script targets 4:30, hard cap 5:00, and the VOICE
is the clock that matters (screens are cut to the narration, not vice versa).
"""
import asyncio
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "VIDEO-SCRIPT.md")
VOICE = "en-US-AndrewMultilingualNeural"


def parse_segments(path):
    """Return [(start_timestamp, [voice_paragraphs...])] from the script."""
    text = open(path).read()
    # Split by the ## TIME headings
    parts = re.split(r"^## (\d+:\d+) - (\d+:\d+)", text, flags=re.M)
    segs = []
    # parts[0] is preamble; then groups of (start, end, body)
    i = 1
    while i + 2 <= len(parts):
        start, end, body = parts[i], parts[i + 1], parts[i + 2]
        # pull VOICE: > quoted lines
        voices = []
        in_voice = False
        cur = []
        for line in body.splitlines():
            if line.startswith("VOICE:"):
                in_voice = True
                continue
            if in_voice and line.startswith(">"):
                cur.append(line[1:].strip())
            elif in_voice and line.strip() == "" and cur:
                voices.append(" ".join(cur))
                cur = []
            elif in_voice and not line.startswith(">") and line.strip():
                # end of voice block (WHY THIS / ON SCREEN etc)
                if cur:
                    voices.append(" ".join(cur))
                    cur = []
                in_voice = False
        if cur:
            voices.append(" ".join(cur))
        segs.append((start, end, voices))
        i += 3
    return segs


def synth_duration(text, voice, outdir):
    """Return float seconds for the given text via edge-tts."""
    txt = text.replace("`", "").replace("[LIVE]", "LIVE")
    txt = re.sub(r"\s+", " ", txt).strip()
    if not txt:
        return 0.0
    mp3 = os.path.join(outdir, "seg.mp3")
    subprocess.run(
        ["edge-tts", "--voice", voice, "--text", txt, "--write-media", mp3],
        check=True, capture_output=True,
    )
    # duration via ffprobe if available, else estimate from mp3 frame count
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", mp3],
            check=True, capture_output=True, text=True,
        )
        return float(out.stdout.strip())
    except FileNotFoundError:
        # crude estimate: 128kbps -> bytes/16000 per sec
        size = os.path.getsize(mp3)
        return size / 16000.0


async def main():
    segs = parse_segments(SCRIPT)
    with tempfile.TemporaryDirectory() as td:
        total = 0.0
        for start, end, voices in segs:
            seg_total = 0.0
            for v in voices:
                seg_total += synth_duration(v, VOICE, td)
            total += seg_total
            print(f"{start:>5} - {end:<5}  voice={seg_total:5.1f}s  "
                  f"({len(voices)} paragraph(s))")
        print("-" * 40)
        print(f"TOTAL NARRATION: {total:.1f}s = {int(total//60)}:{total%60:04.1f}")
        print(f"target 4:30 = 270s, hard cap 5:00 = 300s")
        if total <= 270:
            print("WITHIN TARGET")
        elif total <= 300:
            print("OVER TARGET BUT UNDER HARD CAP")
        else:
            print("OVER HARD CAP — MUST CUT")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))