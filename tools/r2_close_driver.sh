#!/bin/bash
# R2 Friday liquidation wrapper — scheduled 2026-09-03 by sprint cron (Jarvis).
# Fires tools/r2_liquidate_driver.py --live at 14:30:00Z Friday 09-04
# (10:30 ET close-start; engine walks legs, hard-flat by 10:55 ET).
# One retry at 14:45Z only if the first attempt produced no R2 journal
# record today. Verifies the hash chain after. Dead by ~15:05Z.
set -u
cd /workspace/forge/alpaca-refuser
LOG=build/r2-driver.log
JOURNAL=live-decisions.jsonl

echo "$(date -u +%FT%TZ) wrapper up, pid $$" >> "$LOG"
target=$(date -u -d "2026-09-04 14:30:00" +%s)
now=$(date -u +%s)
wait=$((target - now))
if [ "$wait" -gt 0 ]; then
  echo "$(date -u +%FT%TZ) sleeping ${wait}s until 14:30:00Z Fri 09-04" >> "$LOG"
  sleep "$wait"
fi

run_and_check() {
  # success = driver exit 0. rc==2 means R2_FAILURE/NOT_FLAT (legs may remain)
  # and a crash means rc!=0 — BOTH retry: liquidate_all is idempotent
  # (re-fetches positions, cancels orphans first). Journal growth alone is
  # NOT success: the ABORT path (not armed / out of window) also appends.
  echo "$(date -u +%FT%TZ) attempt: python3 tools/r2_liquidate_driver.py --live" >> "$LOG"
  python3 tools/r2_liquidate_driver.py --live >> "$LOG" 2>&1
  rc=$?
  echo "$(date -u +%FT%TZ) rc=$rc" >> "$LOG"
  python3 verify.py "$JOURNAL" >> "$LOG" 2>&1
  [ "$rc" -eq 0 ]
}

if run_and_check; then
  echo "$(date -u +%FT%TZ) R2 done first attempt" >> "$LOG"
  exit 0
fi
echo "$(date -u +%FT%TZ) no journal progress; retrying at 14:45Z" >> "$LOG"
target=$(date -u -d "2026-09-04 14:45:00" +%s)
now=$(date -u +%s)
wait=$((target - now))
if [ "$wait" -gt 0 ]; then
  sleep "$wait"
fi
if run_and_check; then
  echo "$(date -u +%FT%TZ) R2 done on retry" >> "$LOG"
  exit 0
fi
echo "$(date -u +%FT%TZ) R2 FAILED BOTH ATTEMPTS — sprint session must act" >> "$LOG"
exit 1
