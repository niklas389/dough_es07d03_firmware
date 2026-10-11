#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 niklas389 and contributors
"""Source of patches/panel-prepower.json (v2). Run in an unpacked work dir (RT=runtime_0x200000.bin).

Power the panel up during start-up, with the backlight off, so that when a
valid input arrives only the backlight step of the panel-on sequence is left.
v2: the 550 ms wait of the panel-on sequence no longer blocks the start-up.

Vendor panel-on sub_245919: T12 check (panel-t12), output mode 2, VLCD on,
25 ms, eDP on, 10 ms, HPD poll + link training, 550 ms busy-wait, pnl = 1,
output mode 0, re-detect check, backlight on.

v1 (patches/panel-prepower-v1.json) ran this at boot up to "output mode 0" and
blocked the start for ~0.75 s, which delayed the main loop and with it the
input front-end set-up. The LG 28MQ780 firmware (same SDK) runs the same steps
as a non-blocking state machine in its main loop, with the 550 ms as a timer.

v2, same order of panel operations as the vendor sequence:
- Boot (0x2620CC, before the main loop, if the power flag is set and the panel
  is off): PREQ = 1, run sub_245919. At the 550 ms wait (0x24597D) with PREQ
  set: start a 550 ms countdown (unused slot 8 of the 1 ms ISR timer table:
  flag 0x455179, counter 0x45518A), PST = 1, return. pnl stays 0, output mode
  stays 2, as during the vendor wait.
- Main loop (hook on the port-task call 0x262114): when PST = 1 and the
  countdown has run out: pnl = 1, output mode 0 (sub_23CCD5(0)), PST = 2.
- Panel-on call while PST = 1 (signal accepted within the 550 ms): waits for the
  rest of the countdown (1 ms steps, at most 600), then as above, then the
  backlight step. So training -> backlight stays >= 550 ms (panel T8 >= 350 ms).
- Panel-on call with pnl = 1 and PST = 2: PST = 0, continue at the vendor
  re-detect check + backlight-on (0x245991), as v1.
- Panel-off sub_245860: also runs when PST = 1 (panel powered, pnl still 0);
  clears pnl, PST and the countdown.

State: PST at 0x203FF0 (v1's PRE byte), PREQ at 0x203FF1 (zero linker padding,
reloaded with the image at every boot). Requires standby-lhs (as v1).
"""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeon'))
import aeondis as A, aeonasm as S

d = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
def cur(a, n): return d[a - 0x200000:a - 0x200000 + n]

CAVE = 0x203A00                     # part 1 (up to 0x203B00, eeprom-fast-read starts there)
CAVE2 = 0x203B08                    # part 2 (after eeprom-fast-read)
PST, PREQ = 0x3FF0, 0x3FF1          # offsets from 0x200000
TFLAG, TCNT = 0x5179, 0x518A        # ISR timer slot 8 (0x455171 + 8, 0x45517A + 2 * 8), offsets from 0x450000
WAIT_MS = 550                       # vendor value (0x24597D ori r3,r0,0x226)
PANEL_ON = 0x245919
SUB_23CCD5, SUB_241505, PORT_TASK = 0x23CCD5, 0x241505, 0x22F2C7
R0, R1, R3, R6, R7, R9, R10 = 0, 1, 3, 6, 7, 9, 10

mh = lambda r, v: ('bg.movhi', {'D': r, 'U': v})
lbz = lambda rd, off, ra: ('bg.lbz', {'?': rd, 'A': ra, '!': off})
sb = lambda off, ra, rb: ('bg.sb', {'Y': off, 'A': ra, 'B': rb})
beqi = lambda r, i, lab: ('bg.beqi', {'A': r, 'I': i, ';': lab})
bnei = lambda r, i, lab: ('bg.bnei', {'A': r, 'I': i, ';': lab})
j = lambda t: ('bg.j', {'/': t})
jal = lambda t: ('bg.jal', {'/': t})
movi = lambda r, i: ('bt.movi', {'D': r, 'I': i})
push = lambda n: ('bt.addi', {'D': R1, 'I': -n})
pop = lambda n: ('bt.addi', {'D': R1, 'I': n})
sw = lambda off, rb: ('bn.sw', {':': off, 'A': R1, 'B': rb})
lw = lambda rd, off: ('bn.lwz', {'D': rd, 'A': R1, ':': off})

prog = [
 'on_entry:',                     # sub_245919 @0x245925 (r9 saved, r10 = 0x450000)
 mh(R7, 0x20), lbz(R6, PST, R7), bnei(R6, 1, 'e_pnl'),
 jal('pfin'),                     # countdown running: finish it (pnl = 1, mode 0, PST = 2)
 'e_pnl:',
 lbz(R6, 0x51a8, R10), bnei(R6, 0, 'e_on'),
 j(0x245936),                     # pnl == 0: full power-up as stock
 'e_on:',
 mh(R7, 0x20), lbz(R6, PST, R7), beqi(R6, 2, 'e_fin'),
 j(0x24592C),                     # pnl == 1, not prepared: stock early return
 'e_fin:',
 sb(PST, R7, R0),
 j(0x245991),                     # prepared: re-detect check + backlight on

 'w550:',                         # sub_245919 @0x24597D (ori r3,r0,0x226; jal sub_241505)
 mh(R7, 0x20), lbz(R6, PREQ, R7), bnei(R6, 0, 'w_prep'),
 ('bg.ori', {'D': R3, 'A': R0, 't': WAIT_MS}),
 j(0x245981),                     # not preparing: vendor busy-wait
 'w_prep:',
 sb(PREQ, R7, R0), movi(R6, 1), sb(PST, R7, R6),
 mh(R7, 0x45), ('bg.ori', {'D': R6, 'A': R0, 't': WAIT_MS}),
 ('bg.sh', {'X': TCNT, 'A': R7, 'B': R6}),      # counter first, then the flag (ISR)
 movi(R6, 1), sb(TFLAG, R7, R6),
 j(0x2459E4),                     # epilogue: pnl = 0, mode 2, backlight off

 'pfin:',                         # finish a running preparation; uses r3, r6, r7
 mh(R7, 0x20), lbz(R6, PST, R7), beqi(R6, 1, 'f_go'),
 ('bt.jr', {'A': R9}),
 'f_go:',
 push(8), sw(4, R9), sw(0, R10),
 ('bg.ori', {'D': R10, 'A': R0, 't': WAIT_MS + 50}),
 'f_wait:',
 mh(R7, 0x45), lbz(R7, TFLAG, R7), beqi(R7, 0, 'f_done'),
 movi(R3, 1), jal(SUB_241505),
 ('bt.addi', {'D': R10, 'I': -1}), bnei(R10, 0, 'f_wait'),
 'f_done:',
 mh(R7, 0x45), sb(TFLAG, R7, R0),
 movi(R6, 1), sb(0x51a8, R7, R6),                # pnl = 1 (vendor 0x245987)
 mh(R7, 0x20), movi(R6, 2), sb(PST, R7, R6),
 movi(R3, 0), jal(SUB_23CCD5),                   # output mode 0 (vendor 0x24598D)
 lw(R10, 0), lw(R9, 4), pop(8),
 ('bt.jr', {'A': R9}),

 'ploop:',                        # main loop @0x262114, replaces jal sub_22F2C7 (r9 = return)
 mh(R7, 0x20), lbz(R6, PST, R7), bnei(R6, 1, 'l_out'),
 mh(R7, 0x45), lbz(R7, TFLAG, R7), bnei(R7, 0, 'l_out'),
 push(4), sw(0, R9), jal('pfin'), lw(R9, 0), pop(4),
 'l_out:',
 j(PORT_TASK),
]
prog2 = [
 'off_guard:',                    # sub_245860 @0x245869 (r7 = 0x450000): lbz r6,pnl
 lbz(R6, 0x51a8, R7), bnei(R6, 0, 'g_out'),
 mh(R6, 0x20), lbz(R6, PST, R6),
 ('bn.andi', {'D': R6, 'A': R6, 'N': 1}),        # PST == 1: panel powered, pnl still 0
 'g_out:',
 j(0x24586D),
 'off_hook:',                     # sub_245860 @0x245877 (r7 = 0x450000): pnl = 0
 sb(0x51a8, R7, R0), sb(TFLAG, R7, R0),
 mh(R6, 0x20), sb(PST, R6, R0),
 j(0x24587B),

 'prep:',                         # boot @0x2620CC, replaces jal sub_268C55
 push(4), sw(0, R9),
 mh(R7, 0x3b), ('bg.lwz', {'D': R7, 'A': R7, 'W': 0x5f38}), lbz(R7, 0x48, R7),
 ('bn.andi', {'D': R7, 'A': R7, 'N': 1}), beqi(R7, 0, 'p_skip'),   # power flag off
 mh(R7, 0x45), lbz(R6, 0x51a8, R7), bnei(R6, 0, 'p_skip'),        # panel already on
 mh(R7, 0x20), movi(R6, 1), sb(PREQ, R7, R6),
 jal(PANEL_ON),
 mh(R7, 0x20), sb(PREQ, R7, R0),
 'p_skip:',
 lw(R9, 0), pop(4),
 j(0x268C55),
]
code, L = S.assemble(prog, CAVE)
code2, L2 = S.assemble(prog2, CAVE2)
assert not set(L) & set(L2)
for base, c, labs in ((CAVE, code, L), (CAVE2, code2, L2)):
    print('cave %#x: %d bytes' % (base, len(c)))
    for a, b, x in A.disasm(c, base, base + len(c), base):
        lab = [k for k, v in labs.items() if v == a]
        print(('%-10s' % (lab[0] + ':' if lab else '')) + '%08x: %-12s %-9s %s' % (a, b.hex(' '), x['mnem'], x['ops']))
assert CAVE + len(code) <= 0x203B00, hex(CAVE + len(code))
assert CAVE2 + len(code2) <= 0x203C00, hex(CAVE2 + len(code2))
assert cur(CAVE, len(code)) == b'\0' * len(code) and cur(CAVE2, len(code2)) == b'\0' * len(code2)
assert cur(0x200000 + PST, 2) == b'\0\0'
assert cur(0x24597D, 8).hex() == 'c8600226e7ff7708', cur(0x24597D, 8).hex()   # ori r3,r0,0x226; jal sub_241505
L.update(L2)

hooks = [
 (0x245925, 'bg.j', 'on_entry', 'f0ca51a8', 'sub_245919 entry: lbz r6,pnl -> preparation check'),
 (0x24597D, 'bg.j', 'w550', 'c8600226', 'sub_245919 550 ms wait: countdown instead of busy-wait when preparing'),
 (0x245869, 'bg.j', 'off_guard', 'f0c751a8', 'sub_245860 guard: also run while a preparation is in progress'),
 (0x245877, 'bg.j', 'off_hook', 'f80751a8', 'sub_245860: clear preparation state with pnl'),
 (0x262114, 'bg.jal', 'ploop', 'e7f9a366', 'main loop: finish preparation after 550 ms, then sub_22F2C7'),
 (0x2620CC, 'bg.jal', 'prep', 'e400d712', 'boot: prepare panel, then sub_268C55'),
]
edits = [{'addr': '0x%06X' % CAVE, 'old': '00' * len(code), 'new': code.hex(),
          'asm': 'panel-prepower v2 code part 1 in linker padding (0x203A00); PST/PREQ at 0x203FF0/0x203FF1; ISR timer slot 8'},
         {'addr': '0x%06X' % CAVE2, 'old': '00' * len(code2), 'new': code2.hex(),
          'asm': 'panel-prepower v2 code part 2 (panel-off hooks, boot hook) in linker padding (0x203B08)'}]
for a, op, lab, old, c in hooks:
    ob = cur(a, 4)
    assert ob.hex() == old, (hex(a), ob.hex())
    nb = S.encode(op, {'/': L[lab]}, a)
    x, y = A.decode(ob, 0, a), A.decode(nb, 0, a)
    print('%x  %s %-24s -> %s %s   ; %s' % (a, ob.hex(), x['mnem'] + ' ' + x['ops'], nb.hex(), y['mnem'] + ' ' + y['ops'], c))
    edits.append({'addr': '0x%06X' % a, 'old': ob.hex(), 'new': nb.hex(),
                  'asm': '%s %s -> %s %s (%s)' % (x['mnem'], x['ops'], y['mnem'], y['ops'], c)})

patch = {
 'name': 'panel-prepower',
 'summary': 'Power the panel up (backlight off) during start-up; the 550 ms panel wait runs as a timer in the main loop instead of blocking the start',
 'status': 'hardware-tested 2026-10-07 (v2): deep-standby wake 6.7-6.9 s (3 runs, with port-accept), power-key start 6.6 s, mains ~11.9 s; power-off right after a start and No signal -> deep standby -> wake OK',
 'requires': ['standby-lhs'],
 'edits': edits,
 'notes': ("Boot (0x2620CC): vendor panel-on up to the link training, then a 550 ms countdown (1 ms ISR timer slot 8, "
           "0x455179/0x45518A) instead of the busy-wait; the main loop then sets pnl = 1 and output mode 0 (vendor order). "
           "A panel-on before the countdown ends waits for the rest, so training -> backlight stays >= 550 ms. "
           "Panel-off also runs during the countdown. Same idea as the LG 28MQ780 panel state machine. "
           "Generated by tools/patches_src_panel_prepower.py."),
}
out = os.environ.get('OUT', 'panel-prepower.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
