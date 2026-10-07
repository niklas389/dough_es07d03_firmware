#!/usr/bin/env bash
# fequery.sh - ask the input front-end for the link status of connectors (needs diag-poke + diag-fe).
#
#   ./fequery.sh            query USB-C (8), DP (7), HDMI 1 (1), HDMI 2 (3)
#   ./fequery.sh 7 1        query the given connector codes only
#   SPECCTL=./specctl MON=1 ./fequery.sh
#
# Per code: VCP 0xED = code runs the vendor queries 0x30/7 (front-end index) and 0x60/0xB
# (link status); the answers are read back from RAM 0x2024F0..F6 with poke.sh. The two
# durations need a diag-log variant in the build (0 otherwise): 2-6 ms per transaction after a
# mains start and after a deep-standby wake (measured 2026-10-07).
set -euo pipefail
SPECCTL=${SPECCTL:-specctl}
MON=${MON:-0}
HERE=$(cd "$(dirname "$0")" && pwd)
codes=("$@"); [ ${#codes[@]} -gt 0 ] || codes=(8 7 1 3)
name() { case $1 in 8) echo USB-C;; 7) echo DP;; 1) echo HDMI1;; 3) echo HDMI2;; *) echo "code $1";; esac; }
rd() { SPECCTL="$SPECCTL" MON="$MON" "$HERE/poke.sh" read "$1" | sed -n 's/.*= 0x\([0-9A-F]*\).*/\1/p'; }
for c in "${codes[@]}"; do
    # DDC/CI drops a SET now and then: send it again (up to 3 times) while the run counter is unchanged
    before=$(rd 0x2024F4 || true); after=$before
    for try in 1 2 3; do
        "$SPECCTL" set 0xED "$c" -d "$MON" --fast >/dev/null 2>&1 || true
        sleep 0.5
        after=$(rd 0x2024F4 || true)
        [ -n "$before" ] && [ -n "$after" ] && [ "$before" != "$after" ] && break
    done
    if [ -z "$before" ] || [ -z "$after" ]; then echo "$(name "$c"): run counter not readable (DDC/CI error; repeat)"; continue; fi
    if [ "$before" = "$after" ]; then echo "$(name "$c"): query did not run after 3 tries (counter unchanged; is diag-fe in this build?)"; continue; fi
    [ "$try" = 1 ] || echo "($(name "$c"): SET needed $try tries)"
    printf '%-6s code %-2s  index 0x%s  link 0x%s  completed %s  (echo 0x%s)  took %d + %d ms\n' \
        "$(name "$c")" "$c" "$(rd 0x2024F0)" "$(rd 0x2024F1)" "$(rd 0x2024F2)" "$(rd 0x2024F3)" \
        "0x$(rd 0x2024F5)" "0x$(rd 0x2024F6)"
done
