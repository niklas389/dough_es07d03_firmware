#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 niklas389 and contributors
# glowtest.sh - backlight-glow test on a diag-poke build: drive one PM51 standby
# output (0x434 bit 6 or bit 7) low in link-held standby, then restore it.
#
#   MON=1 ./glowtest.sh 6                (same MON / SPECCTL as poke.sh)
#
# Tested 2026-10-04: driving either bit low stops the CPU (a mains power cycle
# restores). Kept for reference; neither is usable in link-held standby.
#
# Run it while the monitor glows (link-held standby: poke.sh read must answer).
# If the monitor stops answering, the CPU lost power: unplug it for >= 10 s.
set -u
P=${POKE:-"$(dirname "$0")/poke.sh"}

rd() { "$P" read "$1" 2>/dev/null | sed -n 's/.*= \(0x[0-9A-Fa-f]*\)$/\1/p'; }
wr() { "$P" write "$1" "$(printf '0x%02X' "$2")"; }
alive() {
    if [ -z "$(rd 0x434)" ]; then
        echo "*** NO ANSWER: the CPU lost power. Note what you saw, then unplug the monitor for >= 10 s."
        exit 1
    fi
    echo "    (monitor still answers)"
}
step() { read -rp ">>> $1 -- note the glow, then press Enter " _; alive; }

case ${1:-} in 6|7) ;; *) echo "usage: $0 6|7  (both are known to stop the CPU)"; exit 2 ;; esac

O434=$(rd 0x434); O436=$(rd 0x436)
if [ -z "$O434" ] || [ -z "$O436" ]; then
    echo "no answer: not in link-held standby (or DDC problem); nothing changed"; exit 1
fi
echo "start: 0x434 = $O434   0x436 = $O436"
echo "       expected: 0x434 bit 7 = 1, bit 6 = 1; 0x436 bit 7 = 1, bit 6 = 0"
step "baseline (nothing changed yet)"

case ${1:-} in
7)
    echo "--- bit 7: output low, then driver on"
    wr 0x434 $(( O434 & 0x7F ))
    wr 0x436 $(( O436 & 0x7F ))
    step "bit 7 driven low"
    echo "--- bit 7: restore (driver off first, then output value)"
    wr 0x436 $(( O436 ))
    wr 0x434 $(( O434 ))
    step "bit 7 restored" ;;
6)
    echo "--- bit 6: output low"
    wr 0x434 $(( O434 & 0xBF ))
    step "bit 6 driven low"
    echo "--- bit 6: restore"
    wr 0x434 $(( O434 ))
    step "bit 6 restored" ;;
*)
    echo "usage: $0 6|7  (both are known to stop the CPU)"; exit 2 ;;
esac

echo "end:   0x434 = $(rd 0x434)   0x436 = $(rd 0x436)   (should equal the start values)"
