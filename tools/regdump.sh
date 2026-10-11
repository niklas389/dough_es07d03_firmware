#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 niklas389 and contributors
# regdump.sh - read register ranges on a diag-poke build, one "addr value" line each.
#
#   MON=1 SPECCTL=./specctl tools/regdump.sh 0x400-0x45F 0x2E902F40-0x2E902F5F > a.txt
#   ... change state ...
#   MON=1 SPECCTL=./specctl tools/regdump.sh 0x400-0x45F 0x2E902F40-0x2E902F5F > b.txt
#   diff a.txt b.txt
#
# Read-only. Sets the address high half once per range and only the low half per
# register (about 3 DDC transfers per register instead of 5 with poke.sh).
# Unreadable addresses print BLOCKED, failed reads ERR, reads that stayed unstable
# after three tries UNSTABLE (diag-poke compares three reads per request).
set -u
SPECCTL=${SPECCTL:-specctl}
MON=${MON:-0}
[ $# -ge 1 ] || { sed -n '4,14p' "$0"; exit 2; }

vset() { "$SPECCTL" set "$1" "$2" -d "$MON" --fast >/dev/null 2>&1 || true; }
vget() { "$SPECCTL" get "$1" -d "$MON" --fast 2>/dev/null | sed -n 's/.*= \([0-9]*\) .*/\1/p' || true; }

for r in "$@"; do
    a=$(( ${r%-*} )); b=$(( ${r#*-} ))
    hi=-1
    for (( x = a; x <= b; x++ )); do
        h=$(( (x >> 16) & 0xFFFF )); l=$(( x & 0xFFFF ))
        if [ $h -ne $hi ]; then
            for t in 1 2 3 4; do vset 0xEA $h; [ "$(vget 0xEA)" = "$h" ] && break; done
            hi=$h
        fi
        v=""
        for t in 1 2 3; do
            vset 0xEB $l
            [ "$(vget 0xEB)" = "$l" ] || continue
            v=$(vget 0xEC); [ -n "$v" ] && [ "$v" != 65534 ] && break
        done
        if [ -z "$v" ]; then printf '0x%08X ERR\n' "$x"
        elif [ "$v" = 65534 ]; then printf '0x%08X UNSTABLE\n' "$x"
        elif [ "$v" -gt 255 ]; then printf '0x%08X BLOCKED\n' "$x"
        else printf '0x%08X 0x%02X\n' "$x" "$v"; fi
    done
done
