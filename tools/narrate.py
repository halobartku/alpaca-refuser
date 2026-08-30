#!/usr/bin/env python3
"""Generate per-scene narration MP3s via edge-tts, then assemble the MP4 with ffmpeg.

Scene map (honest pre-week cut; every [LIVE] sentence from VIDEO-SCRIPT.md is
cut per its own rule, not approximated):
  0  cold open (slide 01)
  1  what it trades + engine (slide 02 -> 05)
  2  DEMO: real terminal refusal (demo.png)
  3  gate stack + portfolio (slide 06 -> 07)
  4  trap + execution (slide 10)
  5  close (slide 12)
"""
import subprocess, os, sys

VOICE = "en-US-AndrewMultilingualNeural"

SCENES = [
    ("s0", """A defined-risk short-premium book, sized at four percent portfolio heat, has a hard ceiling of about half a percent a week. That is arithmetic, not modesty. So this agent will not win a raw profit and loss leaderboard, and I am not going to pretend otherwise. What it does instead is the thing none of the others can: it shows you every trade it refused, and why."""),

    ("s1", """The Refuser sells put credit spreads, twenty-one to thirty-five days out, on a fixed eight-name universe, sized at three quarters of one percent of equity per ticket. There is no language model at the wheel. The decision core is deterministic arithmetic, a Black-Scholes repricer validated against Hull's canonical example and put-call parity. The volatility risk premium is the motor. The gate stack is the transmission."""),

    ("s2", """Here is a live cycle on the shipped decision code. It reconciles against the broker first, because after any restart the agent must ask what it holds and never trust its own memory. Then it scans. Four candidates, eight gates each. Three are refused. Refused, the earnings date inside the expiry window could not be confirmed. Refused, the quoted spread blew past the liquidity gate. Refused, the candidate arrived inside the NFP blackout window. Every one of those refusals carries a written reason, and every one is appended to a hash-chained log."""),

    ("s3", """Eight gates. Every entry passes all of them, or no order exists. Duration, delta, structure, liquidity, underlying, calendar, volatility regime, and portfolio shape. That last one matters more than it looks. Holding SPY, QQQ and IWM at once is not three positions, it is one bet. The failure mode we defend against is not a blow-up. It is clustered stops on a single volatility event, leaving a negative account with no premium left to grind back inside one week."""),

    ("s4", """The rules require development on any account and judging on a fresh hundred thousand dollar account. Ours differ by ten times, so a constant calibrated on the development account would make every judged position ten times too large. Equity is read from the account endpoint at decision time, never cached and never defaulted. The account number is asserted before any order exists, and a test proves the same signal produces contract counts exactly ten times apart at identical percentage risk."""),

    ("s5", """I said at the start this would not win on profit and loss, and it will not. What it can do is account for itself. Every position sized from live equity, every refusal written down with a reason, every decision hash-chained so the record cannot be edited after the fact. A field this large will contain many accounts up fifteen percent on one lucky bet, and approximately none that can explain themselves. That is the entry. The repository, the write-up and this video are disclosed as AI-assisted."""),
]

os.makedirs("build/audio", exist_ok=True)
for tag, text in SCENES:
    out = f"build/audio/{tag}.mp3"
    subprocess.run(["edge-tts", "--voice", VOICE, "--text", text,
                    "--write-media", out], check=True)
    d = subprocess.check_output(["ffprobe", "-v", "error",
                                 "-show_entries", "format=duration",
                                 "-of", "csv=p=0", out]).decode().strip()
    print(f"{tag} {d}s")

# scene -> slide image mapping + display slides
slidemap = {
    "s0": "01", "s1": "05", "s3": "06",
    "s4": "10", "s5": "12",
}
print("AUDIO_DONE")