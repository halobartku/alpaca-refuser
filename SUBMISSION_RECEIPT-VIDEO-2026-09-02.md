# SUBMISSION_RECEIPT — video (MP4) + slides (PDF), rebuilt 2026-09-02

Rebuild trigger: Alpaca keys verified ACTIVE (PA3Y…YVDZ, $100k, L3) — the
"keys 401" limitation of the 2026-08-30 build no longer applied, so the
fictional `FX-JUDGE-100K` substitution was replaced with the real judged
account number, read from the live API at build time.

Deliverables: `build/slides-final.mp4` + `build/slides-final.pdf` (build/ is
gitignored; the full account id never enters the git tree — tracked files carry
only the partial `PA3Y…YVDZ`, slide 12 claim intact. Found via cowork review
2026-09-03; previously this receipt itself quoted the full id, contradicting
its own claim).

| Check | Result | Evidence |
|---|---|---|
| Keys live (independent, A.152) | PASS | GET /v2/account → PA3Y…YVDZ ACTIVE, equity 100000, 0 positions/orders/fills (pre-14:10Z Wednesday session — expected) |
| Real account on slide 1 | PASS | slides-final.html line 66 + pypdf page-1 extract contains PA3Y…YVDZ; 0 `[LIVE]`/`[FILL]` markers, 12 pages |
| Build reads account from API, not memory | PASS | tools/build_video.sh fetches /v2/account, asserts status==ACTIVE, aborts otherwise (commit fe99f49, pushed) |
| Runtime < 5:00 | PASS | ffprobe 193.34s (3:13) |
| Container | PASS | h264 1280x720 + AAC, 4.67 MB |
| Scene frames = slides | PASS | 6/6 MAD 6.91–9.63 (12s↔slide_01, 38s↔slide_05, 66s↔demo terminal, 100s↔slide_06, 150s↔slide_10, 185s↔slide_12) |
| Audio real speech | PASS | volumedetect mean −22.0 dB, max −3.0 dB |
| Frame bug fixed in rebuild | NOTE | `--screenshot url#fragment` yields identical frames (never worked); rebuilt via split_slides.py per-slide pages, md5s distinct |
| Orphan processes | PASS | no chromium/ffmpeg left running |
| Git tree clean | PASS | scratch root slides.pdf/refusal_demo.mp4/record_refusal.sh deleted (untracked); only tools/build_video.sh committed |

Honest limits, unchanged by design: N/M/K scene-2 numbers are the fixture demo
cycle (4 eval / 1 taken / 3 refused) — the judged week's live numbers belong to
the post-week rebuild if the contest window allows. Judged week runs 09-02…09-04;
Wednesday one-shot session 14:10Z host-side (A.153/A.157).
