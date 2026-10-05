#!/usr/bin/env bash
# lhspower.sh - link-held standby power test on a diag-poke build: drive one of
# the outputs that deep standby switches off (0x44A bits 7, 6, 2, 1) low, let the
# owner note the power meter and the PC side, then restore it.
#
#   MON=1 ./lhspower.sh            (same MON / SPECCTL as poke.sh)
#
# Run it in link-held standby (dark, red LED, ~13 W, poke.sh read answers).
# Keep "sudo dmesg -w" running in another terminal to see DP or USB changes.
# If the monitor stops answering: note what you saw, unplug it for >= 10 s.
set -u
P=${POKE:-"$(dirname "$0")/poke.sh"}

rd() { "$P" read "$1" 2>/dev/null | sed -n 's/.*= \(0x[0-9A-Fa-f]*\)$/\1/p'; }
wr() { "$P" write "$1" "$(printf '0x%02X' "$2")" >/dev/null; }
ask() { read -rp ">>> $1 -- wait ~10 s, note watts, PC display list, USB devices, then press Enter " _; }

O44A=$(rd 0x44A); O44C=$(rd 0x44C)
if [ -z "$O44A" ] || [ -z "$O44C" ]; then
    echo "no answer: not in link-held standby (or DDC problem); nothing changed"; exit 1
fi
echo "start: 0x44A = $O44A   0x44C = $O44C   (0x44C bit = 0 means the pin is driven)"
ask "baseline (nothing changed yet)"

for bit in 7 6 2 1; do
    m=$(( 1 << bit ))
    if (( (O44A & m) == 0 )); then echo "--- bit $bit already low, skipped"; continue; fi
    echo "--- 0x44A bit $bit low"
    wr 0x44A $(( O44A & ~m & 0xFF ))
    v=$(rd 0x44A)
    if [ -z "$v" ]; then
        echo "*** NO ANSWER after bit $bit: note what you saw, then unplug the monitor for >= 10 s"; exit 1
    fi
    ask "0x44A bit $bit low (0x44A now $v)"
    echo "--- 0x44A bit $bit restored"
    wr 0x44A $(( O44A ))
    v=$(rd 0x44A)
    if [ -z "$v" ]; then
        echo "*** NO ANSWER after restoring bit $bit: unplug the monitor for >= 10 s"; exit 1
    fi
    ask "0x44A bit $bit restored (0x44A now $v)"
done
echo "end:   0x44A = $(rd 0x44A)   0x44C = $(rd 0x44C)   (should equal the start values)"
