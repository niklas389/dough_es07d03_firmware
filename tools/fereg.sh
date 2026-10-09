#!/usr/bin/env bash
# fereg.sh - read registers of the input front-end (MSB3300) through its debug read command
# (needs diag-poke + diag-fe v3; docs/firmware-map.md section 53).
#
#   ./fereg.sh 0x113068 16                 16 bytes from front-end register 0x113068
#   ./fereg.sh 0x113068 16 0x001200 32     several ranges
#   ./fereg.sh preset dp > dp_video.txt    the DP receiver set (see below); diff two runs
#   SPECCTL=./specctl MON=1 ./fereg.sh ...
#
# Output: one "0xADDR 0xVV" line per byte (ERR = not read); diff two runs taken in different
# states (picture / link held without video / link released).
# Only reads are sent, and only inside the DP receiver ranges 0x001100-0x0016FF and
# 0x110000-0x113FFF (other addresses are skipped by the firmware and print SKIP).
# Each byte is one front-end transaction (~5 ms); the main loop is busy during a block.
#
# Presets (receiver 0 = USB-C, receiver 1 = DP; register blocks from the front-end firmware):
#   dp    DP receiver: DPCD banks 0x1200-0x12FF and 0x1500-0x15FF, link block 0x110D20-0x110D3F,
#         0x110F40-0x110F4F, stream timing (MSA) of decoders 0-3 at 0x113068/0x113168/0x113268/0x113368
#   usbc  the same for receiver 0 (0x1100.., 0x1400.., 0x110320.., 0x110540..) plus the MSA blocks
#   msa   only the four MSA blocks (16 bytes each: htotal, vtotal, width, height, hstart, vstart,
#         hsync, vsync; 16-bit little-endian, 15 bits used; section 54)
set -u
SPECCTL=${SPECCTL:-specctl}
MON=${MON:-0}
HERE=$(cd "$(dirname "$0")" && pwd)
TRIES=${TRIES:-4}
command -v "$SPECCTL" >/dev/null 2>&1 || { echo "specctl not found as '$SPECCTL': set SPECCTL=/path/to/specctl" >&2; exit 1; }
[ $# -ge 1 ] || { sed -n '2,24p' "$0"; exit 2; }

vset() { "$SPECCTL" set "$1" "$2" -d "$MON" --fast >/dev/null 2>&1 || true; }
vget() { "$SPECCTL" get "$1" -d "$MON" --fast 2>/dev/null | sed -n 's/.*= \([0-9]*\) .*/\1/p' || true; }
setaddr() {   # $1 = 32-bit address -> diag-poke address variable (VCP 0xEA/0xEB), verified
    local hi=$(( ($1 >> 16) & 0xFFFF )) lo=$(( $1 & 0xFFFF )) t
    for t in $(seq 1 "$TRIES"); do
        vset 0xEA "$hi"; vset 0xEB "$lo"
        [ "$(vget 0xEA)" = "$hi" ] && [ "$(vget 0xEB)" = "$lo" ] && return 0
        sleep 0.3
    done
    return 1
}
ram() {       # $1 = RAM address in 0x2024xx -> decimal byte or empty
    local t v
    setaddr "$1" || return 0
    for t in 1 2 3; do v=$(vget 0xEC); [ -n "$v" ] && [ "$v" -le 255 ] && { echo "$v"; return 0; }; done
}

block() {     # $1 = front-end address, $2 = count (1-32)
    local a=$(( $1 )) n=$(( $2 )) before after t i v ok
    [ "$n" -ge 1 ] && [ "$n" -le 32 ] || { echo "count must be 1-32" >&2; return 1; }
    before=$(ram 0x2024F4); after=$before
    for t in 1 2 3; do
        setaddr "$a" || { echo "address not accepted (is diag-poke in this build?)" >&2; return 1; }
        vset 0xED $(( 0x300 | n ))
        sleep 0.4
        after=$(ram 0x2024F4)
        [ -n "$before" ] && [ -n "$after" ] && [ "$before" != "$after" ] && break
    done
    if [ -z "$before" ] || [ -z "$after" ] || [ "$before" = "$after" ]; then
        echo "# block $(printf '0x%06X' "$a")+$n: did not run (DDC/CI error, or diag-fe v3 missing)" >&2
        for (( i = 0; i < n; i++ )); do printf '0x%06X ERR\n' $(( a + i )); done
        return 0
    fi
    ok=$(ram 0x2024F2)
    echo "# block $(printf '0x%06X' "$a")+$n: ${ok:-?} of $n reads completed" >&2
    setaddr 0x202480 || true                    # buffer page: from here only the low half changes
    for (( i = 0; i < n; i++ )); do
        x=$(( a + i ))
        if ! { (( (x >> 8) >= 0x11 && (x >> 8) <= 0x16 )) || (( (x >> 14) == 0x44 )); }; then
            printf '0x%06X SKIP\n' "$x"; continue
        fi
        v=$(buf "$i")
        if [ -n "$v" ]; then printf '0x%06X 0x%02X\n' "$x" "$v"; else printf '0x%06X ERR\n' "$x"; fi
    done
}
buf() {       # $1 = index -> decimal byte of the buffer 0x202480+i (address high half already 0x0020)
    local lo=$(( 0x2480 + $1 )) t v
    for t in 1 2 3; do
        vset 0xEB "$lo"
        [ "$(vget 0xEB)" = "$lo" ] || continue
        v=$(vget 0xEC); [ -n "$v" ] && [ "$v" -le 255 ] && { echo "$v"; return 0; }
    done
}

ranges=()
case $1 in
    preset)
        case ${2:-} in
            dp)   ranges=(0x001200 32 0x001220 32 0x001240 32 0x001260 32 0x001280 32 0x0012A0 32 0x0012C0 32 0x0012E0 32
                          0x001500 32 0x001520 32 0x001540 32 0x001560 32 0x001580 32 0x0015A0 32 0x0015C0 32 0x0015E0 32
                          0x110D20 32 0x110F40 16) ;;
            usbc) ranges=(0x001100 32 0x001120 32 0x001140 32 0x001160 32 0x001180 32 0x0011A0 32 0x0011C0 32 0x0011E0 32
                          0x001400 32 0x001420 32 0x001440 32 0x001460 32 0x001480 32 0x0014A0 32 0x0014C0 32 0x0014E0 32
                          0x110320 32 0x110540 16) ;;
            msa)  ranges=() ;;
            *) echo "presets: dp, usbc, msa" >&2; exit 2 ;;
        esac
        ranges+=(0x113068 16 0x113168 16 0x113268 16 0x113368 16) ;;
    *)  ranges=("$@") ;;
esac
(( ${#ranges[@]} % 2 == 0 )) || { echo "give address/count pairs" >&2; exit 2; }
echo "# fereg $(date '+%F %T')"
for (( k = 0; k < ${#ranges[@]}; k += 2 )); do block "${ranges[k]}" "${ranges[k+1]}"; done
