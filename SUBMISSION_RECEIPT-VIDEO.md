# SUBMISSION_RECEIPT — video (MP4) + slides (PDF), 2026-08-30

Deliverable: `build/slides-final.mp4` (gitignored binary; on-disk artifact for upload).

| Check | Result | Evidence |
|---|---|---|
| Runtime < 5:00 cap | PASS | ffprobe duration **193.34s (3:13)** |
| Container/playback | PASS | h264 1280x720 + AAC 44.1kHz, 4.7 MB, faststart |
| Scene 0 cold open = slide 01 | PASS | frame@12s vs slide_01.png MAD 3.56 |
| Scene 1 engine = slide 05 | PASS | frame@38s MAD 4.38 |
| Scene 2 demo terminal = real gate output | PASS | frame@66s vs demo.png MAD 4.63 (demo.txt = production AuditTrail+gates on FixtureBroker, 4 eval / 1 accept / 3 refused, chain verify OK records=5) |
| Scene 3 gates = slide 06 / 07 | PASS | MAD 11.65 / 9.13 |
| Scene 4 10x trap = slide 10 | PASS | MAD 10.12 |
| Scene 5 close = slide 12 | PASS | MAD 4.23 |
| Audio is real speech, not silence | PASS | volumedetect mean -21.9 dB, max -4.5 dB |
| No [LIVE] fabrication | PASS | every [LIVE] sentence cut per VIDEO-SCRIPT rule; honest pre-week cut, AI-use disclosed in closing line |
| Slides PDF | PASS | build/slides-final.pdf 12pp, 0 `[LIVE]` markers left, FX-JUDGE-100K substitution in place (also independently verified via pypdf by Claude 2026-08-30) |
| Pipeline committed & pushed | PASS | commit 21b052d on halobartku/alpaca-refuser main (verified via GitHub API) |

Verdict: **both previously-missing submission assets (MP4, PDF) now exist and pass QA.**

Known limitation (by design): numbers shown are the demo-cycle fixture values, not the
judged week — Alpaca keys still return 401. After keys land and the judged week closes,
the [LIVE] variant rebuilds with: `tools/build_video.sh` (frames+PDF) → `tools/narrate.py`
(audio) → `tools/assemble.py` (MP4).

Orphan check: no chromium/ffmpeg/edge-tts processes left running after build.
