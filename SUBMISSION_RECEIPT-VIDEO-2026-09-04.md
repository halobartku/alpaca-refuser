# SUBMISSION_RECEIPT — video (MP4) + slides (PDF), FINAL CUT 2026-09-04 (~00:55Z)

Rebuild trigger: PLAYBOOK.md DECISION POINT option A — post-week rebuild with
real judged-week numbers. The 09-02 build deliberately shipped placeholders
("filled at build time; removed if not available") on slides 5/9/11; the judged
week is now complete (204/0 income + seq 205 event trade), so the final cut
replaces every placeholder with chain-derivable numbers.

Deliverables: `build/slides-final.mp4` (3:58, 5.97 MB) + `build/slides-final.pdf`
(12 pages). build/ is gitignored; account id never enters the git tree.

## Data sources (nothing typed from memory)

| Number | Source |
|---|---|
| Account PA3Y...YVDZ, ACTIVE, equity 99,934.74 | GET /v2/account at build 00:40Z, script asserts status==ACTIVE |
| 204 entry REFUSE / 0 taken | counted live from live-decisions.jsonl (event=evaluate_entry) |
| seq 205 ACCEPT, 5 ct, fill $3.93, $1,965 = 1.97% | journal seq 205 (order HTTP 200 id=f4f6c9ef) + fill verified vs order API 20:40Z 09-03 (A.163); position re-verified live at build (5× SPY 09-04 773 C + P) |
| 206 evaluated / 204 refused (slide 5) | 204 entry evals + 2 nfp_gate evals = 206 candidates through gates |

## Checks

| Check | Result | Evidence |
|---|---|---|
| All [LIVE] placeholders replaced | PASS | build_final_cut.py asserts leftover==0; pypdf text: '[LIVE' count 0 |
| Real numbers present in PDF | PASS | pypdf: '204'×2, '3.93', 'seq 205', '0.504', '1.97%', equity line "$100,000.00 → $99,934.74" on p11 |
| Slides fit A4 landscape | PASS | tools/check_slides.js: ALL 12 SLIDES FIT (incl. longer slide 11) |
| Runtime < 5:00 | PASS | ffprobe 237.81s (3:58) |
| Container | PASS | h264 1280x720 + AAC, 5.97 MB |
| Scene frames = intended slides | PASS | content-region MAD 4.3–10.5 across 8 scenes incl. NEW slide_11 week scene (195s MAD 8.26); earlier naive-crop FAIL was a comparison bug (pad bars), re-verified with correct 131px-crop geometry |
| Audio real speech | PASS | volumedetect mean −22.0 dB, max −2.8 dB |
| Frame determinism | PASS | re-render of slide_07 and slide_11 = md5-identical to shipped frames (0.0 MAD) |
| Narration/deck consistency | PASS | "Eight gates"→"Nine gates" fixed in narrate.py (s2, s3 + net-delta named); PDF 'Eight gates' count 0, 'Nine gates' 1 |
| New week scene | PASS | s5 (43.2s, slide_11) before close s5b (32.1s, slide_12); all 8 frame md5s distinct |
| Orphan processes | PASS | no chromium/edge-tts/ffmpeg left running |
| Git tree clean of account id | PASS | only tools/*.py committed; build/ gitignored |

## Honesty notes

- Slide 9 slippage line now states: no income fills occurred, so no slippage
  exists to report — consistent with WRITEUP.md §4.
- Slide 11 equity is marked at final build (99,934.74) with the straddle still
  open; liquidation 14:55 ET makes judged P&L = realised P&L (see WRITEUP).
- Video narration s5 says "zero point five percent vs zero point nine percent
  gate" — rounded from 0.504% / 0.875%; exact figures in WRITEUP and PDF.
