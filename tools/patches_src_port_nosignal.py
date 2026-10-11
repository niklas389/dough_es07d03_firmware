#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 niklas389 and contributors
"""Source of patches/port-nosignal.json (v4). Run in an unpacked work dir (RT=runtime_0x200000.bin).

Shorter "no signal" decision for all input ports: DP / USB-C (NOSIG_DP,
default 125 passes = 2.5 s, vendor 8 s) and HDMI (NOSIG, default 125 = 2.5 s,
vendor 10 s). Faster automatic input switching and a faster way to "No
signal" and standby. Requires nosignal-once (v4).

v4 (2026-10-08): the "No signal" loop that limited v1-v3 (repeat after every
+0x1A passes restarting the countdown) was not caused by the port threshold
itself but by the input path's detection rounds re-entering "No signal";
nosignal-once (v2, hardware-tested) stops that re-entry, so short thresholds
no longer keep the monitor out of standby (docs/firmware-map.md sections 33,
34). Lower bound now 50 passes (1 s): ports whose receiver reports nothing at
all give up after 50 passes anyway (sub_23B068), only ports with some activity
wait the full threshold. Measured times from port enable to a signal: DP
after a wake 0.6 s, DP after a switch with switch-no-unplug 0.2 s, a laptop on
USB-C that had just re-enabled its output 2.1 s; 2.5 s covers these. A source
slower than the threshold costs, with automatic input, one more scan round;
with a fixed input a brief "No signal" message before the picture.

Vendor (sub_260E0E -> sub_23E5C5, port +0x1A; see port-accept for +0x18):
the port monitor sub_23B068 (every 20 ms per port) declares a port without
signal after +0x1A passes (port state 2, flags +0x1C |= 6). sub_260E0E loops
over the 6 ports (port index in r3 at every sub_23E5C5 call) and chooses the
values by port type:
- type 0x20 (port 0 = front-end id 7 = USB-C, port 1 = id 8 = DP; measured
  2026-10-07 from the PM51 wake port: USB-C wake -> 0, DP wake -> 1):
  400 passes = 8 s (200 when settings +0x48 bit 2 or flg bit 0 is set);
- type bit 3/4/0x400 (ports 2-5, HDMI class): 500 passes = 10 s (200 with
  the flag);
- types bit 0 and bit 1/2 (20 / 60 passes) do not occur in the port table.
LG 28MQ780 (same SDK) uses 100 passes (2 s) for both classes.

History:
- v1 set all four values to NOSIG (200 = 4 s). With a USB-C source behind a
  dock the monitor then woke, showed "No signal" and went back to standby,
  twice in a row (2026-10-07).
- v2 kept port 0 (USB-C) at 8 s and set port 1 (DP) to NOSIG through a stub
  on the type-0x20 sub_23E5C5 call. With the input fixed to DP, "No signal"
  then flickered about 4-5 s after it appeared (about when port 0 gave up)
  and the monitor never reached standby; with automatic input it did reach
  standby. Assumed first: ports 0 and 1 are judged together. Traced
  afterwards: they are separate receivers and a detached port is not
  monitored, so that assumption is not supported; the cause is open
  (docs/firmware-map.md, "Ports, receivers and input paths").
- v3 (this): only the HDMI-class ports 2-5 get NOSIG; ports 0 and 1 keep the
  vendor values (400 / 200), i.e. DP and USB-C behave as stock.
- Cause of the v1/v2 loop (diag-log-ring, 2026-10-07, input fixed to DP,
  output disabled): "No signal" (state-4 entry, caller 0x2575C6) repeated
  every 4.07 s with no port state change in between. The port in state 2
  repeats its no-signal decision every +0x1A passes (its counter restarts),
  every repeat re-enters state 4, and the state-4 entry restarts the
  countdown whose pre-standby comes 5 s after the entry (vendor and
  standby-timeout). With 200 passes (4.07 s) the repeat always comes first.
  The vendor's 400 / 500 passes (8 / 10 s) are longer than 5 s.
  v3's first default (200 for ports 2-5) would have looped the same way on
  a fixed HDMI input; default now 300 passes (6 s), checked >= 275.
The flag case (200 passes when settings +0x48 bit 2 or flg bit 0) stays
vendor; the cmov source for ports 2-5 is left at 200 for that case.
"""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeon'))
import aeondis as A, aeonasm as S

d = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
def cur(a, n): return d[a - 0x200000:a - 0x200000 + n]

NOSIG = int(os.environ.get('NOSIG', '125'))        # HDMI class (ports 2-5)
NOSIG_DP = int(os.environ.get('NOSIG_DP', '125'))  # type 0x20 (port 0 USB-C, port 1 DP)
# Without nosignal-once a value below ~275 loops on "No signal" (see the history above); v4
# requires nosignal-once, so the lower bound is the receiver's own 1 s give-up.
assert 50 <= NOSIG <= 500 and 50 <= NOSIG_DP <= 400

SITES = [  # addr, stock bytes, register, vendor value, new value, what
 (0x260E73, 'c8a001f4', 5, 500, NOSIG, 'type bit3/4/0x400 (HDMI), normal case'),
 (0x260EDA, 'c8a00190', 5, 400, NOSIG_DP, 'type 0x20 (USB-C, DP), normal case'),
]
edits = []
for a, old, reg, val, NEW, what in SITES:
    ob = cur(a, len(old) // 2)
    assert ob.hex() == old, (hex(a), ob.hex())
    x = A.decode(ob, 0, a)
    assert x['mnem'] == 'b.ori' and x['ops'] == 'r%d,r0,%#x' % (reg, val), x
    nb = S.encode('bg.ori', {'D': reg, 'A': 0, 't': NEW}, a)
    assert len(nb) == len(ob) and A.decode(nb, 0, a)['ops'] == 'r%d,r0,%#x' % (reg, NEW)
    print('%06x: %s -> %s  %s %d -> %d passes' % (a, ob.hex(), nb.hex(), what, val, NEW))
    if nb != ob:
        edits.append({'addr': '0x%06X' % a, 'old': ob.hex(), 'new': nb.hex(),
                      'asm': 'sub_260E0E ori r%d,r0,%#x -> ori r%d,r0,%#x (port +0x1A no-signal threshold, %s)' % (reg, val, reg, NEW, what)})

# flag-case values (200 passes when settings +0x48 bit 2 or flg bit 0) stay vendor
assert cur(0x260ED1, 3).hex() == '50a0c8' and cur(0x260E70, 3).hex() == '50e0c8'

patch = {
 'name': 'port-nosignal',
 'summary': ('v4: declare an input "no signal" after %.1f s (DP / USB-C, vendor 8 s) and %.1f s (HDMI, vendor 10 s): '
             'faster automatic switching and a faster way to standby; requires nosignal-once') % (NOSIG_DP * 0.02, NOSIG * 0.02),
 'status': 'untested (v4; v3 HDMI-only 6 s in daily use)',
 'requires': ['nosignal-once'],
 'conflicts': ['port-nosignal-v1', 'port-nosignal-v2'],
 'edits': edits,
 'notes': ("Port +0x1A thresholds set by sub_260E0E (vendor: 400 passes for type 0x20 = ports 0 USB-C and 1 DP, 500 for "
           "types bit3/4/0x400 = ports 2-5, 200 in the flag case). v4: type 0x20 -> %d, ports 2-5 -> %d (normal case); the "
           "flag case stays 200. LG 28MQ780 uses 100. Accept thresholds (+0x18, see port-accept) unchanged. "
           "Generated by tools/patches_src_port_nosignal.py (NOSIG_DP=n, NOSIG=n, 50-400/500)." % (NOSIG_DP, NOSIG)),
}
out = os.environ.get('OUT', 'port-nosignal.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
