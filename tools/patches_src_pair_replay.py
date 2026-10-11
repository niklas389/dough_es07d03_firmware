#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 niklas389 and contributors
"""Source of patches/pair-replay.json. Run in an unpacked work dir (RT=runtime_0x200000.bin).

Half-width DP picture (docs/firmware-map.md sections 50, 57, 58).

At 3840x2160 144 Hz the front-end sends the picture as two 1920x2160 halves,
one on each of its two links to the scaler (the scaler ports of USB-C and DP),
and the scaler's path 0 joins them. The pairing comes only from the front-end:
its routing report (message type 8; front-end 0x8631D on a change of its
active receiver, 0x862A4 on a change of an output path's input mask) is read
with the scaler's mailbox traffic (sub_238F40 -> sub_238EB4 -> dispatcher
sub_238E50, type 8 -> sub_238CDE). sub_238CDE sets path 0 +0x94 = 1 (pair) and
maps the reported links to scaler ports (sub_23E7BE(3, ...)), then redoes the
layout; with byte 0 = 0 it sets +0x94 = 0.

The layout set-up sub_25F0D3 resets all input paths (sub_23E4CE clears +0x94)
and is run at every start (sub_261FDE: front-end set-up sub_261FA8, then
sub_25FD58 at 0x2620AA) and on layout changes. The front-end sends the report
only on a change, so a report that arrived before the reset (during the
front-end set-up's mailbox traffic, i.e. when the source's stream is already
there at the start: first start after a flash with the PC sending, wake with
the link held) is lost: path 0 shows the DP-link half alone, 1920 wide.

Patch:
- 0x238E95 'jal sub_238CDE' (type 8, r3 = payload) -> rp_save: keep payload
  bytes 0-2 at RAM 0x2024A0-A2, valid flag 0x2024A3 = 1, replay flag
  0x2024A5 = 0; then the vendor handler.
- Main loop (0x262124 'jal sub_245EF3', no arguments) -> rp_task: if the
  layout is single-window (settings +0x59 = 0), the saved report says "pair"
  (byte 0 != 0), path 0 +0x94 is 0 and no replay since path 0 was last paired:
  replay flag = 1, count 0x2024A4 += 1, sub_238CDE(saved copy) - the same
  call the vendor makes when the report arrives. The replay flag is cleared
  (re-armed) whenever path 0 is seen paired, so each later reset is covered,
  while a replay that does not pair the path is not repeated. A new report
  (also "no pair") replaces the copy.
No hot-plug, no front-end command. Code at 0x201E60 (head zero area, after
menu-flag-clear). RAM 0x2024A0-A5 readable with diag-poke.
"""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeon'))
import aeondis as A, aeonasm as S

d = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
def cur(a, n): return d[a - 0x200000:a - 0x200000 + n]

SAVE_SITE, HANDLER = 0x238E95, 0x238CDE
LOOP_SITE, LOOP_FN = 0x262124, 0x245EF3
CAVE = 0x201E60
RAM = 0x2024A0                          # +0..2 payload, +3 valid, +4 replay count, +5 replayed
PATH0_PAIR = 0x4821AC + 0x94
R0, R1, R3, R4, R5, R6, R7, R9 = 0, 1, 3, 4, 5, 6, 7, 9

assert A.decode(d, SAVE_SITE - 0x200000, SAVE_SITE)['target'] == HANDLER and cur(SAVE_SITE - 2, 2).hex() == '8866'   # mov r3,r6
assert A.decode(d, LOOP_SITE - 0x200000, LOOP_SITE)['target'] == LOOP_FN
assert cur(LOOP_FN, 9).hex() == '9c3c0d2100c0e008a1'                    # no argument use at entry
assert cur(0x238D45, 9).hex() == '98609881e400ac0298'[:18]               # sub_238CDE: sub_23E34A(0, 1) (pair)
assert cur(0x23E34A, 3).hex() == '50e0a8' and cur(0x23E35A, 4).hex() == 'f8830094'   # path +0x94 setter
assert cur(0x25F1A9, 4).hex() == '9860e7fb'                              # layout case 0 starts with path resets
assert cur(CAVE, 0xA0) == b'\0' * 0xA0 and cur(RAM, 8) == b'\0' * 8

mh = lambda rd, v: ('bg.movhi', {'D': rd, 'U': v})
lbz = lambda rd, a, ra: ('bg.lbz', {'?': rd, 'A': ra, '!': a & 0xFFFF})
sb = lambda a, ra, rb: ('bg.sb', {'Y': a & 0xFFFF, 'A': ra, 'B': rb})
nlbz = lambda rd, off, ra: ('bn.lbz', {'?': rd, 'A': ra, 'z': off})
movi = lambda r, i: ('bt.movi', {'D': r, 'I': i})
prog = [
 # ---- type 8 routing report (r3 = payload) ----
 'rp_save:',
 mh(R7, 0x20),
 nlbz(R6, 0, R3), sb(RAM + 0, R7, R6),
 nlbz(R6, 1, R3), sb(RAM + 1, R7, R6),
 nlbz(R6, 2, R3), sb(RAM + 2, R7, R6),
 movi(R6, 1), sb(RAM + 3, R7, R6), sb(RAM + 5, R7, R0),
 ('bg.j', {'/': HANDLER}),

 # ---- main loop, every pass ----
 'rp_task:',
 mh(R7, 0x20),
 lbz(R6, RAM + 3, R7), ('bg.beqi', {'A': R6, 'I': 0, ';': 'rp_x'}),     # no report yet
 lbz(R6, RAM + 0, R7), ('bg.beqi', {'A': R6, 'I': 0, ';': 'rp_x'}),     # last report: no pair
 mh(R5, 0x48), lbz(R6, PATH0_PAIR, R5),
 ('bg.bnei', {'A': R6, 'I': 0, ';': 'rp_arm'}),                         # path 0 paired: re-arm, nothing to do
 lbz(R6, RAM + 5, R7), ('bg.bnei', {'A': R6, 'I': 0, ';': 'rp_x'}),     # replayed since it was last paired
 mh(R5, 0x3B), ('bg.lwz', {'D': R5, 'A': R5, 'W': 0x5F38}),
 nlbz(R6, 0x59, R5), ('bg.bnei', {'A': R6, 'I': 0, ';': 'rp_x'}),      # not single-window
 movi(R6, 1), sb(RAM + 5, R7, R6),
 lbz(R6, RAM + 4, R7), ('bn.addi', {'D': R6, 'A': R6, 'O': 1}), sb(RAM + 4, R7, R6),
 ('bn.addi', {'D': R1, 'A': R1, 'O': -4}), ('bn.sw', {':': 0, 'A': R1, 'B': R9}),
 mh(R3, 0x20), ('bg.ori', {'D': R3, 'A': R3, 't': RAM & 0xFFFF}),
 ('bg.jal', {'/': HANDLER}),                                            # as on arrival of the report
 ('bn.lwz', {'D': R9, 'A': R1, ':': 0}), ('bn.addi', {'D': R1, 'A': R1, 'O': 4}),
 ('bg.j', {'/': 'rp_x'}),
 'rp_arm:',
 sb(RAM + 5, R7, R0),
 'rp_x:',
 ('bg.j', {'/': LOOP_FN}),
]
code, L = S.assemble(prog, CAVE)
assert CAVE + len(code) <= 0x201F00, hex(CAVE + len(code))
for a, b, x in A.disasm(code, CAVE, CAVE + len(code), CAVE):
    lab = [k for k, v in L.items() if v == a]
    print(('%-9s' % (lab[0] + ':' if lab else '')) + '%08x: %-12s %-9s %s' % (a, b.hex(' '), x['mnem'], x['ops']))
edits = [{'addr': '0x%06X' % CAVE, 'old': '00' * len(code), 'new': code.hex(),
          'asm': 'rp_save / rp_task (image head zero area 0x201E60); RAM 0x2024A0-A5'}]
for a, lab, txt in ((SAVE_SITE, 'rp_save', 'front-end message type 8: jal sub_238CDE -> jal rp_save'),
                    (LOOP_SITE, 'rp_task', 'main loop: jal sub_245EF3 -> jal rp_task')):
    edits.append({'addr': '0x%06X' % a, 'old': cur(a, 4).hex(), 'new': S.encode('bg.jal', {'/': L[lab]}, a).hex(), 'asm': txt})
patch = {
 'name': 'pair-replay',
 'summary': ('Half-width 4K 144 Hz picture: keeps the front-end\'s last routing report and, when a layout reset '
             '(start, layout change) has cleared path 0\'s two-link pairing that this report set, applies it again '
             'through the vendor handler (once per reset); RAM 0x2024A0-A5'),
 'status': 'untested',
 'edits': edits,
 'notes': 'See the docstring of tools/patches_src_pair_replay.py. Generated by tools/patches_src_pair_replay.py.',
}
out = os.environ.get('OUT', 'pair-replay.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
