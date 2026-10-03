#!/usr/bin/env python3
"""Source of patches/panel-prepower.json. Run in an unpacked work dir (RT=runtime_0x200000.bin).

Power the panel up during start-up, with the backlight off, so that when a
valid input arrives only the backlight step of the panel-on sequence is left.

- Boot (0x2620CC, before the main loop; the same point where the stock logo
  powered the panel): if the power flag is set and the panel is off, set PREQ
  and run the vendor panel-on sub_245919 (T12 check, VLCD, eDP, link training,
  550 ms). With PREQ set, sub_245919 stops after the link step: PRE=1, no
  re-detect check, no backlight.
- Later panel-on calls (mode set, key, state entries): with pnl=1 and PRE=1,
  sub_245919 clears PRE and continues at its re-detect check + backlight-on
  (0x245991), exactly the tail of the stock sequence.
- Panel-off sub_245860 clears PRE together with pnl.

PRE/PREQ live at 0x203FF0/0x203FF1 in the zero linker padding (reloaded with
the image at every boot, unreferenced). Requires standby-lhs: the stock
pre-standby routine sub_24578B cuts VLCD without clearing pnl.
"""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeon'))
import aeondis as A, aeonasm as S

d = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
def cur(a, n): return d[a - 0x200000:a - 0x200000 + n]

CAVE = 0x203A00
PRE, PREQ = 0x3FF0, 0x3FF1          # offsets from 0x200000
PANEL_ON, PANEL_OFF = 0x245919, 0x245860
R0, R1, R6, R7, R9, R10 = 0, 1, 6, 7, 9, 10

mh = lambda r, v: ('bg.movhi', {'D': r, 'U': v})
lbz = lambda rd, off, ra: ('bg.lbz', {'?': rd, 'A': ra, '!': off})
sb = lambda off, ra, rb: ('bg.sb', {'Y': off, 'A': ra, 'B': rb})
beqi = lambda r, lab: ('bg.beqi', {'A': r, 'I': 0, ';': lab})
bnei = lambda r, lab: ('bg.bnei', {'A': r, 'I': 0, ';': lab})
j = lambda t: ('bg.j', {'/': t})

prog = [
 'on_entry:',                     # sub_245919 @0x245925 (r10 = 0x450000)
 lbz(R6, 0x51a8, R10), bnei(R6, 'e_on'),
 j(0x245936),                     # pnl == 0: full power-up as stock
 'e_on:',
 mh(R7, 0x20), lbz(R6, PRE, R7), bnei(R6, 'e_fin'),
 j(0x24592C),                     # pnl == 1, not prepared: stock early return
 'e_fin:',
 sb(PRE, R7, R0),
 j(0x245991),                     # prepared: re-detect check + backlight on
 'on_tail:',                      # sub_245919 @0x245991, after pnl=1 and sub_23CCD5(0)
 mh(R7, 0x20), lbz(R6, PREQ, R7), bnei(R6, 't_prep'),
 mh(R6, 0x48),                    # replaced instruction
 j(0x245995),
 't_prep:',
 sb(PREQ, R7, R0), ('bt.movi', {'D': R6, 'I': 1}), sb(PRE, R7, R6),
 j(0x2459E4),                     # epilogue: panel powered, backlight stays off
 'off_hook:',                     # sub_245860 @0x245877 (r7 = 0x450000)
 sb(0x51a8, R7, R0), mh(R6, 0x20), sb(PRE, R6, R0),
 j(0x24587B),
 'prep:',                         # boot @0x2620CC, replaces jal sub_268C55
 ('bt.addi', {'D': R1, 'I': -4}), ('bn.sw', {':': 0, 'A': R1, 'B': R9}),
 mh(R7, 0x3b), ('bg.lwz', {'D': R7, 'A': R7, 'W': 0x5f38}), lbz(R7, 0x48, R7),
 ('bn.andi', {'D': R7, 'A': R7, 'N': 1}), beqi(R7, 'p_skip'),      # power flag off
 mh(R7, 0x45), lbz(R6, 0x51a8, R7), bnei(R6, 'p_skip'),           # panel already on
 mh(R7, 0x20), ('bt.movi', {'D': R6, 'I': 1}), sb(PREQ, R7, R6),
 ('bg.jal', {'/': PANEL_ON}),
 mh(R7, 0x20), sb(PREQ, R7, R0),
 'p_skip:',
 ('bn.lwz', {'D': R9, 'A': R1, ':': 0}), ('bt.addi', {'D': R1, 'I': 4}),
 j(0x268C55),
]
code, L = S.assemble(prog, CAVE)
print('cave bytes', len(code))
for a, b, x in A.disasm(code, CAVE, CAVE + len(code), CAVE):
    lab = [k for k, v in L.items() if v == a]
    print(('%-10s' % (lab[0] + ':' if lab else '')) + '%08x: %-12s %-9s %s' % (a, b.hex(' '), x['mnem'], x['ops']))
assert CAVE + len(code) <= 0x203F00
assert cur(CAVE, len(code)) == b'\0' * len(code)
assert cur(0x200000 + PRE, 2) == b'\0\0'

hooks = [
 (0x245925, 'bg.j', 'on_entry', 'f0ca51a8', 'sub_245919 entry: lbz r6,pnl -> prepared-panel check'),
 (0x245991, 'bg.j', 'on_tail', 'c0c00901', 'sub_245919 tail: stop before re-detect/backlight when preparing'),
 (0x245877, 'bg.j', 'off_hook', 'f80751a8', 'sub_245860: clear PRE with pnl'),
 (0x2620CC, 'bg.jal', 'prep', 'e400d712', 'boot: prepare panel, then sub_268C55'),
]
edits = [{'addr': '0x%06X' % CAVE, 'old': '00' * len(code), 'new': code.hex(),
          'asm': 'panel-prepower code in linker padding (0x203A00); flags PRE/PREQ at 0x203FF0/0x203FF1'}]
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
 'summary': 'Power the panel up (backlight off) during start-up so only the backlight step remains when the input is ready',
 'status': 'experimental, hardware test pending',
 'requires': ['standby-lhs'],
 'edits': edits,
 'notes': ("At boot (0x2620CC, where the stock logo powered the panel) the vendor panel-on runs with the backlight held off; "
           "the later panel-on from mode setup only does the re-detect check and backlight-on. Panel-off clears the state. "
           "The vendor already keeps the panel powered across mode changes (No signal -> picture), so the panel sees the same transition as stock. "
           "Boot is blocked for the panel sequence (~0.6-0.8 s) as with the stock logo. "
           "Generated by tools/patches_src_panel_prepower.py."),
}
out = os.environ.get('OUT', 'panel-prepower.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
