#!/usr/bin/env bash
# fequery.sh - ask the input front-end for the link status of connectors (needs diag-poke + diag-fe).
#
#   ./fequery.sh            query USB-C (8), DP (7), HDMI 1 (1), HDMI 2 (3), then raw ids r7 (USB-C), r8 (DP)
#   ./fequery.sh 7 1        query the given connector codes only
#   ./fequery.sh r7 r8      raw mode (diag-fe v2): link query 0x60/0xB for front-end id 7 / 8 directly
#                           (no 0x30/7 mapping; asks a connector that is not the selected input)
#   SPECCTL=./specctl MON=1 ./fequery.sh
#
# Per code: VCP 0xED = code runs the vendor queries 0x30/7 (front-end index) and 0x60/0xB
# (0 = source active, 1 = no source; docs/firmware-map.md section 29); the answers are read back from RAM 0x2024F0..F6 with poke.sh. The two
# durations need a diag-log variant in the build (0 otherwise): 2-6 ms per transaction after a
# mains start and after a deep-standby wake (measured 2026-10-07).
set -euo pipefail
SPECCTL=${SPECCTL:-specctl}
MON=${MON:-0}
HERE=$(cd "$(dirname "$0")" && pwd)
command -v "$SPECCTL" >/dev/null 2>&1 || { echo "specctl not found as '$SPECCTL': set SPECCTL=/path/to/specctl" >&2; exit 1; }
export SPECCTL
codes=("$@"); [ ${#codes[@]} -gt 0 ] || codes=(8 7 1 3 r7 r8)
name() { case $1 in 8) echo USB-C;; 7) echo DP;; 1) echo HDMI1;; 3) echo HDMI2;;
          r7) echo "USB-C raw";; r8) echo "DP raw";; r11) echo "HDMI1 raw";; r12) echo "HDMI2 raw";; *) echo "code $1";; esac; }
# r<id>: raw mode, VCP value 0x100 | id
val() { case $1 in r*) echo $(( 0x100 | ${1#r} ));; *) echo "$1";; esac; }
rd1() { SPECCTL="$SPECCTL" MON="$MON" "$HERE/poke.sh" read "$1" 2>/dev/null | sed -n 's/.*= 0x\([0-9A-F]*\).*/\1/p' || true; }
rd() { local v; v=$(rd1 "$1"); [ -n "$v" ] || v=$(rd1 "$1"); echo "$v"; }   # one retry; empty = DDC/CI read error
ms() { local v; v=$(rd "$1"); [ -n "$v" ] && echo $(( 16#$v )) || echo '?'; }
sh_() { local v; v=$(rd "$1"); echo "${v:-??}"; }
for c in "${codes[@]}"; do
    # DDC/CI drops a SET now and then: send it again (up to 3 times) while the run counter is unchanged
    before=$(rd 0x2024F4 || true); after=$before
    for try in 1 2 3; do
        "$SPECCTL" set 0xED "$(val "$c")" -d "$MON" --fast >/dev/null 2>&1 || true
        sleep 0.5
        after=$(rd 0x2024F4 || true)
        [ -n "$before" ] && [ -n "$after" ] && [ "$before" != "$after" ] && break
    done
    if [ -z "$before" ] || [ -z "$after" ]; then echo "$(name "$c"): run counter not readable (DDC/CI error; repeat)"; continue; fi
    if [ "$before" = "$after" ]; then echo "$(name "$c"): query did not run after 3 tries (counter unchanged; is diag-fe in this build?)"; continue; fi
    [ "$try" = 1 ] || echo "($(name "$c"): SET needed $try tries)"
    idx=$(sh_ 0x2024F0); lk=$(sh_ 0x2024F1)
    case "$idx:$lk" in 00:*) what="no index";; *:00) what="source active";; *:01) what="no source";; *) what="?";; esac
    printf '%-9s code %-3s  index 0x%s  link 0x%s = %-13s completed %s  (echo 0x%s)  took %s + %s ms\n' \
        "$(name "$c")" "$c" "$idx" "$lk" "$what" "$(sh_ 0x2024F2)" "$(sh_ 0x2024F3)" \
        "$(ms 0x2024F5)" "$(ms 0x2024F6)"
done
