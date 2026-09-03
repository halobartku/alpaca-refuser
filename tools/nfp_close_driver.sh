#!/bin/bash
# NFP Thursday-close driver wrapper — started 2026-09-03 ~12:50Z by sprint cron.
# Fires tools/nfp_decide.py at 19:50:00Z; one retry at 19:55Z only if the
# first attempt left no decision file. Verifies the hash chain after.
set -u
cd /workspace/forge/alpaca-refuser
LOG=build/nfp-driver.log
STAMP=build/nfp-decision.json

echo "$(date -u +%FT%TZ) wrapper up, pid $$" >> "$LOG"
target=$(date -u -d "2026-09-03 19:50:00" +%s)
now=$(date -u +%s)
wait=$((target - now))
if [ "$wait" -gt 0 ]; then
  echo "$(date -u +%FT%TZ) sleeping ${wait}s until 19:50:00Z" >> "$LOG"
  sleep "$wait"
fi

run_and_check() {
  # success = the decision stamp was rewritten by THIS attempt.
  # (mtime check — the stamp schema carries no date string, so the old
  #  grep-for-today test could never match and forced a guaranteed second
  #  nfp_decide.py run at 19:55Z => double mleg order on ACCEPT. Fixed
  #  2026-09-03 ~13:20Z by 18:30Z sprint task t_dea88b8e.)
  local before after
  before=$(stat -c %Y "$STAMP" 2>/dev/null || echo 0)
  echo "$(date -u +%FT%TZ) attempt: python3 tools/nfp_decide.py" >> "$LOG"
  python3 tools/nfp_decide.py >> "$LOG" 2>&1
  echo "$(date -u +%FT%TZ) rc=$?" >> "$LOG"
  python3 verify.py live-decisions.jsonl >> "$LOG" 2>&1
  after=$(stat -c %Y "$STAMP" 2>/dev/null || echo 0)
  [ "$after" -gt "$before" ]
}

if ! run_and_check; then
  echo "$(date -u +%FT%TZ) first attempt failed — retry 19:55Z" >> "$LOG"
  target2=$(date -u -d "2026-09-03 19:55:00" +%s)
  now=$(date -u +%s)
  [ $((target2 - now)) -gt 0 ] && sleep $((target2 - now))
  run_and_check || echo "$(date -u +%FT%TZ) BOTH ATTEMPTS FAILED — decision NOT recorded" >> "$LOG"
fi
echo "$(date -u +%FT%TZ) wrapper done" >> "$LOG"
