#!/usr/bin/env bash
# regdump.sh - read register ranges on a diag-poke build, one "addr value" line each.
#
#   MON=1 tools/regdump.sh 0x400-0x45F 0x2E902F40-0x2E902F5F > stuck.txt
#   ... change state ...
#   MON=1 tools/regdump.sh 0x400-0x45F 0x2E902F40-0x2E902F5F > working.txt
#   diff stuck.txt working.txt
#
# Read-only. Unreadable addresses print BLOCKED, failed reads print ERR.
set -u
P=${POKE:-"$(dirname "$0")/poke.sh"}
[ $# -ge 1 ] || { sed -n '2,9p' "$0"; exit 2; }
for r in "$@"; do
    a=$(( ${r%-*} )); b=$(( ${r#*-} ))
    for (( x = a; x <= b; x++ )); do
        v=$("$P" read "$x" 2>/dev/null | sed -n 's/.*= \(0x[0-9A-Fa-f]*\)$/\1/p; s/.*\(BLOCKED\).*/\1/p')
        printf '0x%08X %s\n' "$x" "${v:-ERR}"
    done
done
