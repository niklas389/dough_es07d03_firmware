#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 niklas389 and contributors
"""Source of patches/dpmode-same.json. Run in an unpacked work dir (RT=runtime_0x200000.bin).

Selecting the DisplayPort Mode that is already set does nothing.

The OSD action for "DisplayPort Mode" (0x268C20) stores the menu value
(0x457857) into settings +0xCB and always calls sub_268BB0, which applies
the mode to DP and USB-C with sub_26535A: 650 ms hot-plug pulse (the source
sees an unplug), port configuration, 0x60 sub 2 (DSC), then 0x60 sub 0 (link
rate) (docs/firmware-map.md sections 27, 29). Owner's test 2026-10-08:
re-selecting 1.4 while 1.4 was set blanked both monitors behind the dock;
this monitor then stayed on "No signal" and went to standby.

Second problem (stock, log 2026-10-08 with the input fixed to DP): the apply
leaves the input disabled. sub_26535A(port, dsc) sends the HPD pulse, then
0x20 sub 0 with enable = 0 for the port, 0x60 sub 2 (id, dsc), and calls
sub_264633(dsc). Only sub_264633 requests the port configuration update that
enables the port again (path 0's port entry in 0x3B4288: +0 = 1, +0x11 = 0,
+1 = 2; 0x264683), and only when the DSC value differs from its cached one
(or settings +0x59 != 0). Re-selecting 1.4, or changing between "1.4
without DSC" and 1.2 (DSC off both), therefore left DP disabled in the
front-end: "No signal", link-held standby (the dock kept the link), no
picture until another input selection or a restart.

Patch: the store (0x268C35, 'sb 0xcb(r6),r7') jumps to a stub:
- value unchanged: no store, no apply;
- changed: store, sub_268BB0, then the same update request for path 0's
  port as sub_264633 makes, so the input is enabled again (with
  switch-no-unplug: HPD high, 0x60 sub 2, enable).
The rest of the action (0x4551BB bit 0, return 1) runs as stock. Start-up
(sub_268BB0 after a mains start) is not touched: the start-up selection
attaches the input afterwards anyway.

Code in the linker padding 0x2038B0 (free since gate-all-dp v4 moved out).
"""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeon'))
import aeondis as A, aeonasm as S

d = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
def cur(a, n): return d[a - 0x200000:a - 0x200000 + n]

SITE, APPLY, CONT = 0x268C35, 0x268BB0, 0x268C3D
CAVE = 0x2038B0
R5, R6, R7 = 5, 6, 7

assert cur(0x268C25, 0x14).hex() == 'c0e00761ecc75f3ac0e008a1f0e77857f8e600cb', cur(0x268C25, 0x14).hex()
assert A.decode(d, 0x268C39 - 0x200000, 0x268C39)['target'] == APPLY
assert cur(CAVE, 0x50) == b'\0' * 0x50
assert cur(0x264683, 0x25).hex() == ('50e018c0c00901f0c621d440e733c0c00761fcc642888ce698c118c70018071198c218c701'), \
    cur(0x264683, 0x25).hex()                              # sub_264633's update request for path 0's port

prog = [
 'dps:',                                                   # r6 = settings, r7 = new value
 ('bg.lbz', {'?': R5, 'A': R6, '!': 0xCB}),                # current +0xCB
 ('bg.beq', {'A': R5, 'B': R7, ';': 'dps_x'}),             # unchanged: no store, no apply
 ('bg.sb', {'Y': 0xCB, 'A': R6, 'B': R7}),
 ('bg.jal', {'/': APPLY}),
 # request the port configuration update (enable) of path 0's port, as sub_264633 does on a DSC change (0x264683)
 ('bg.movhi', {'D': R6, 'U': 0x48}), ('bg.lbz', {'?': R6, 'A': R6, '!': 0x21D4}),
 ('bg.ori', {'D': R7, 'A': 0, 't': 0x18}), ('bn.mul', {'D': R7, 'A': R7, 'B': R6}),
 ('bg.movhi', {'D': R6, 'U': 0x3B}), ('bg.addi', {'D': R6, 'A': R6, 'Y': 0x4288}), ('bn.add', {'D': R7, 'A': R7, 'B': R6}),
 ('bt.movi', {'D': R6, 'I': 1}), ('bn.sb', {'z': 0, 'A': R7, 'B': R6}),
 ('bn.sb', {'z': 0x11, 'A': R7, 'B': 0}),
 ('bt.movi', {'D': R6, 'I': 2}), ('bn.sb', {'z': 1, 'A': R7, 'B': R6}),
 'dps_x:',
 ('bg.j', {'/': CONT}),
]
code, L = S.assemble(prog, CAVE)
assert CAVE + len(code) <= 0x203900, hex(CAVE + len(code))
for a, b, x in A.disasm(code, CAVE, CAVE + len(code), CAVE):
    lab = [k for k, v in L.items() if v == a]
    print(('%-7s' % (lab[0] + ':' if lab else '')) + '%08x: %-12s %-9s %s' % (a, b.hex(' '), x['mnem'], x['ops']))
hook = S.encode('bg.j', {'/': CAVE}, SITE)
print('%06x: %s -> %s' % (SITE, cur(SITE, 4).hex(), hook.hex()))

patch = {
 'name': 'dpmode-same',
 'summary': ('DisplayPort Mode: selecting the mode that is already set does nothing (stock: re-applies it with a 650 ms '
             'hot-plug pulse, which blanks every monitor behind a dock, and leaves the input disabled); a real change is '
             'applied and the input enabled again (stock left it disabled when the DSC setting did not change, e.g. '
             '"1.4 without DSC" <-> 1.2)'),
 'status': ('hardware-tested 2026-10-08: same mode -> nothing; 1.4 -> 1.4 without DSC -> 1.2 -> 1.4 with the PC at 4K 60 Hz: picture after every change (at 4K 144 Hz, 1.2 has no picture: the mode does not fit HBR2 without DSC)'),
 'edits': [
  {'addr': '0x%06X' % CAVE, 'old': '00' * len(code), 'new': code.hex(),
   'asm': 'dps (linker padding 0x2038B0): +0xCB unchanged -> skip; else store, sub_268BB0, port update request for path 0'},
  {'addr': '0x%06X' % SITE, 'old': cur(SITE, 4).hex(), 'new': hook.hex(),
   'asm': 'OSD action 0x268C20: sb 0xcb(r6),r7 -> j dps'},
 ],
 'notes': 'See the docstring of tools/patches_src_dpmode_same.py. Generated by tools/patches_src_dpmode_same.py.',
}
out = os.environ.get('OUT', 'dpmode-same.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
