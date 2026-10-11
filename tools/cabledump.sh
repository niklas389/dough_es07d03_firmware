#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 niklas389 and contributors
# cabledump.sh - read the SAR ADC levels of the vendor cable detect (sub_23EDA4,
# docs/firmware-map.md section 59) on a diag-poke build and decode them as the
# firmware does. Read-only.
#
#   MON=1 SPECCTL=./specctl tools/cabledump.sh
#
# Run it with different cables plugged in (USB-C, DP, HDMI 1, HDMI 2) and check
# that every plugged connector shows "cable": scan-active-first v2 skips HDMI
# inputs that show "no cable" in the automatic scan.
set -u
here=$(dirname "$0")
raw=$("$here/regdump.sh" 0x3A30-0x3A31 0x3A34-0x3A35)
echo "$raw"
python3 - "$raw" <<'EOF'
import sys
v = {}
for line in sys.argv[1].splitlines():
    a, x = line.split()
    v[int(a, 16)] = int(x, 16) if x.startswith('0x') else None
def ch(lo):                                   # sub_23DCE4: 16-bit register >> 2, low 8 bits
    a, b = v.get(lo), v.get(lo + 1)
    return None if a is None or b is None else ((b << 8 | a) >> 2) & 0xFF
near = lambda x, c, t: x is not None and abs(x - c) <= t
c8, c6 = ch(0x3A34), ch(0x3A30)
print('ADC channel 8 (USB-C / DP):   %s' % ('--' if c8 is None else '0x%02X' % c8))
print('ADC channel 6 (HDMI 1 / 2):   %s' % ('--' if c6 is None else '0x%02X' % c6))
cable = {
    'USB-C ': near(c8, 0x6F, 7) or near(c8, 0x25, 4),
    'DP    ': near(c8, 0x36, 7) or near(c8, 0x25, 4),
    'HDMI 1': near(c6, 0x44, 7) or near(c6, 0x28, 7),
    'HDMI 2': near(c6, 0x98, 7) or near(c6, 0x28, 7),
}
for k, x in cable.items():
    print('%s  %s' % (k, 'cable' if x else 'no cable'))
EOF
