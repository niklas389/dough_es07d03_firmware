#!/usr/bin/env bash
# poke.sh - read/write one allowlisted chip register on a diag-poke build.
#
#   ./poke.sh read  0x44A           print the byte (BLOCKED if not allowlisted)
#   ./poke.sh write 0x44A 0x46      write a byte (only allowlisted registers)
#   SPECCTL=./specctl MON=1 ./poke.sh read 0x2E902F4B
#
# Writes are volatile: a power cycle (mains off >= 10 s) restores everything.
set -euo pipefail
SPECCTL=${SPECCTL:-specctl}
MON=${MON:-0}

[ $# -ge 2 ] || { sed -n '2,8p' "$0"; exit 2; }
op=$1; addr=$(( $2 ))
hi=$(( (addr >> 16) & 0xFFFF )); lo=$(( addr & 0xFFFF ))

vcp_set() { "$SPECCTL" set "$1" "$2" -d "$MON" --fast >/dev/null 2>&1 || true; }
vcp_get() { "$SPECCTL" get "$1" -d "$MON" --fast 2>/dev/null | sed -n 's/.*= \([0-9]*\) .*/\1/p'; }

# DDC/CI occasionally answers with a stale or missing reply: retry the address setup.
ok=0
for try in 1 2 3 4; do
    vcp_set 0xEA "$hi"
    vcp_set 0xEB "$lo"
    gh=$(vcp_get 0xEA); gl=$(vcp_get 0xEB)
    if [ "$gh" = "$hi" ] && [ "$gl" = "$lo" ]; then ok=1; break; fi
    sleep 0.3
done
[ $ok = 1 ] || { echo "address not accepted after 4 tries (read back hi=${gh:-none} lo=${gl:-none}; is diag-poke in this build?)" >&2; exit 1; }

case $op in
    read)
        v=""
        for try in 1 2 3; do v=$(vcp_get 0xEC); [ -n "$v" ] && break; sleep 0.3; done
        [ -n "$v" ] || { echo "no reply" >&2; exit 1; }
        if [ "$v" -gt 255 ]; then echo "$(printf '0x%08X' "$addr"): BLOCKED (not readable)"
        else printf '0x%08X = 0x%02X\n' "$addr" "$v"; fi ;;
    write)
        [ $# -ge 3 ] || { echo "write needs a value" >&2; exit 2; }
        val=$(( $3 ))
        vcp_set 0xEC "$val"
        v=$(vcp_get 0xEC)
        if [ "$v" = "$val" ]; then printf '0x%08X <- 0x%02X OK\n' "$addr" "$val"
        else printf '0x%08X <- 0x%02X NOT APPLIED (now %s; blocked or masked by hardware)\n' "$addr" "$val" "$v"; fi ;;
    *) echo "unknown op $op" >&2; exit 2 ;;
esac
