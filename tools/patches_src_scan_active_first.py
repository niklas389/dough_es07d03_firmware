#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 niklas389 and contributors
"""Source of patches/scan-active-first.json. Run in an unpacked work dir (RT=runtime_0x200000.bin).

Automatic input: the scan asks the front-end which DP-class connectors (DP,
USB-C) have an active source and uses the answer to choose the next input.

Stock scan step (docs/firmware-map.md section 24): when the current input
has no signal, sub_25FE39 calls sub_2653EA(port) (0x2601EB), a fixed
rotation 0 -> 1 -> 2 -> 3 -> 0 (USB-C, DP, HDMI 1, HDMI 2; ports 4/5 -> 2)
that marks the next port's status +0x20 |= 0x0C ("no signal" until it
reports one), and switches path 0 to it. Every input in between is visited:
DP-class inputs for the full no-signal time (2.5 s with port-nosignal v4),
HDMI inputs ~1 s each with a 600 ms hot-plug pulse. Measured 2026-10-08
(automatic input, DP output disabled, laptop active on USB-C): USB-C picture
after ~6.8 s, of which ~2.1 s are the two HDMI visits.

The front-end link query 0x60 sub 0xFF r5 0xB (front-end id; answer 0 =
source active, 1 = no source; section 29) works per connector, also for the
connector that is not selected. Untested for HDMI ids, so HDMI inputs are
treated as stock.

Patch (scan step 0x2601EB 'jal sub_2653EA' -> 'jal as_next'), v2 (2026-10-10):
The stock scan steps once per no-signal decision; its decision counter
0x453BF2 is cleared only when a port finds a signal, and "No signal" comes on
the 9th decision (two full rounds over the four inputs, section 59). v2 keeps
a set of the inputs visited since that counter started (RAM 0x2024EA; reset
when the counter is 1, i.e. at the first decision of a search) and, at each
step, looks at the next three inputs in rotation order:
- visited in this search: not a candidate;
- DP-class (DP, USB-C): the front-end link query; "no source" is not a
  candidate, "source active" is preferred, another answer is a candidate;
- HDMI: the vendor's cable detect sub_23EDA4 (SAR ADC levels, section 59); no
  cable is not a candidate.
It takes the first input with an active source, else the first other
candidate in rotation order. With no candidate left it does not step: it
continues in the scan handler's "No signal" branch (0x2600C1), as the stock
handler does after its last round. So the search ends after one visit of each
input that can have a source; with only the lost input cabled, "No signal"
comes at its first decision (2.5 s, as with a fixed input).
A query without an answer (mailbox failure) ends the step with the stock
sub_2653EA, as v1. The key-selection mode (0x4551AC bit 5) goes to
sub_2653EA unchanged; the other scan call (0x2602FE, that mode) is not
touched. v1's "one jump per search" guard (RAM 0x2024E8/E9, accept counter
of picture-watchdog) is replaced by the visited set: two connectors that
both hold a link without video are each visited once.

Risk: an HDMI input whose cable detect reads "no cable" while a source is
connected is never visited by the automatic scan (the vendor already gives
such an input only 1 s). tools/cabledump.sh (diag-poke) shows the ADC levels.

Limitation: in DisplayPort Mode "1.4 without DSC" the scan's attach sends no
'HPD high' (0x20 sub 14) to the new connector (stock, section 32); if the old
connector's source still holds its link, the front-end may keep showing it.

Code in the image head zero area 0x201A00 (after picture-watchdog, before
diag-fe at 0x201C00); RAM 0x2024EA = inputs visited in the current search
(bit per port, readable with diag-poke).
"""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeon'))
import aeondis as A, aeonasm as S

d = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
def cur(a, n): return d[a - 0x200000:a - 0x200000 + n]

SITE, NEXT = 0x2601EB, 0x2653EA                # scan step: jal sub_2653EA (r3 = current port -> next port)
MBOX = 0x238FA5                                # mailbox_query(r3 cmd, r4 sub, r5, r6 len, r7 data, r8 reply) -> r3 1 ok
CAVE = 0x201A00
VIS = 0x2024EA                                 # inputs visited in this search (0x2024E8 is cleared by gate-all-dp)
CNT = 0x453BF2                                 # scan decision counter (0 after a signal was found)
CABLE = 0x23EDA4                               # vendor cable detect (port) -> 1 cable present
NOSIG = 0x2600C1                               # scan handler: "No signal" branch (r10 = port)
R0, R1, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12 = 0, 1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12

assert A.decode(d, SITE - 0x200000, SITE)['target'] == NEXT
assert cur(SITE - 2, 2).hex() == '886a' and cur(SITE + 4, 2).hex() == '8943'       # mov r3,r10 ; jal ; mov r10,r3
assert A.decode(d, 0x2602FE - 0x200000, 0x2602FE)['target'] == NEXT                # the key-mode call (not touched)
assert cur(NEXT, 0x21).hex() == ('9c3c0d2100c0e008a1e8e751ad54e72020e0ce98a3206830206db05c600948a20b'
                                  ), cur(NEXT, 0x21).hex()                          # flag test, rotation 0-1-2-3-0, 4/5 -> 2
assert cur(NEXT + 0x21, 0x0A).hex() == '50e0b040e53bc0c00761', cur(NEXT + 0x21, 0x0A).hex()   # status |= 0x0C follows
assert cur(0x3B4281, 4).hex() == '07080b0c'                                       # front-end ids of ports 0-3
assert cur(MBOX, 3).hex() == '1c21d4'
assert cur(CAVE, 0x200) == b'\0' * 0x200 and cur(VIS, 1) == b'\0'
assert A.decode(d, NOSIG - 0x200000, NOSIG)['ops'] == 'r11,0x45' and A.decode(d, NOSIG + 4 - 0x200000, NOSIG + 4)['ops'] == 'r7,0x3c70(r11)'
assert A.decode(d, 0x2600DF - 0x200000, 0x2600DF)['ops'] == 'r7,0x3c70(r11)'      # bit 16 test, then sub_23E5FB, 0x25FF46
assert A.decode(d, 0x23B35C - 0x200000, 0x23B35C)['ops'] == '0x3bf2(r7),r0'        # counter cleared when a signal is found
assert A.decode(d, CABLE - 0x200000, CABLE)['ops'] == 'r1,r1,-0x4' and A.decode(d, CABLE + 2 - 0x200000, CABLE + 2)['ops'] == '0x0(r1),r9'

mh = lambda r, v: ('bg.movhi', {'D': r, 'U': v})
mov = lambda rd, rs: ('bn.or', {'D': rd, 'A': rs, 'B': R0})
movi = lambda r, i: ('bt.movi', {'D': r, 'I': i})
prog = [
 # ---- as_next(r3 = current port) -> r3 = next port (marked "no signal" as sub_2653EA does),
 #      or no candidate left: continue in the scan handler's "No signal" branch ----
 'as_next:',
 mh(R7, 0x45), ('bg.lhz', {'D': R7, 'A': R7, 'X': 0x51AC}), ('bn.andi', {'D': R7, 'A': R7, 'N': 0x20}),
 ('bg.beqi', {'A': R7, 'I': 0, ';': 'as_go'}),
 ('bg.j', {'/': NEXT}),                                    # key-selection mode: stock
 'as_go:',                                                 # frame: regs, res[3] at +20, port[3] at +24
 ('bn.addi', {'D': R1, 'A': R1, 'O': -28}),
 ('bn.sw', {':': 16, 'A': R1, 'B': R9}), ('bn.sw', {':': 12, 'A': R1, 'B': R10}),
 ('bn.sw', {':': 8, 'A': R1, 'B': R11}), ('bn.sw', {':': 4, 'A': R1, 'B': R12}),
 mov(R12, R3), mov(R10, R3), movi(R11, 0),
 mh(R7, 0x45), ('bg.lbz', {'?': R6, 'A': R7, '!': CNT & 0xFFFF}),
 mh(R5, 0x20), ('bg.bnei', {'A': R6, 'I': 1, ';': 'as_v'}),
 ('bg.sb', {'Y': VIS & 0xFFFF, 'A': R5, 'B': R0}),         # first decision of a search: nothing visited yet
 'as_v:',
 ('bg.lbz', {'?': R6, 'A': R5, '!': VIS & 0xFFFF}), movi(R7, 1), ('bn.sll', {'D': R7, 'A': R7, 'B': R12}),
 ('bn.or', {'D': R6, 'A': R6, 'B': R7}), ('bg.sb', {'Y': VIS & 0xFFFF, 'A': R5, 'B': R6}),   # current input visited
 'as_q:',                                                  # classify the next three inputs in rotation order
 ('bg.jal', {'/': 'as_rot'}),
 ('bn.add', {'D': R7, 'A': R1, 'B': R11}), ('bn.sb', {'z': 24, 'A': R7, 'B': R10}),
 mh(R5, 0x20), ('bg.lbz', {'?': R6, 'A': R5, '!': VIS & 0xFFFF}), ('bn.srl', {'D': R6, 'A': R6, 'B': R10}),
 ('bn.andi', {'D': R6, 'A': R6, 'N': 1}), movi(R3, 4),
 ('bg.bnei', {'A': R6, 'I': 0, ';': 'as_st'}),            # 4: visited
 mov(R3, R10), ('bg.jal', {'/': 'asq'}),
 ('bg.beqi', {'A': R3, 'I': 3, ';': 'as_fail'}),           # front-end did not answer: stock rotation
 ('bg.bnei', {'A': R3, 'I': 2, ';': 'as_st'}),             # 0 source active / 1 no source (DP class)
 mov(R3, R10), ('bg.jal', {'/': CABLE}),                   # not DP class: cable detect
 movi(R6, 2), ('bg.bnei', {'A': R3, 'I': 0, ';': 'as_c'}),
 movi(R6, 1),                                              # no cable: as "no source"
 'as_c:', mov(R3, R6),
 'as_st:',
 ('bn.add', {'D': R7, 'A': R1, 'B': R11}), ('bn.sb', {'z': 20, 'A': R7, 'B': R3}),
 ('bn.addi', {'D': R11, 'A': R11, 'O': 1}),
 ('bg.bnei', {'A': R11, 'I': 3, ';': 'as_q'}),
 movi(R11, 0),
 'as_a:',                                                  # 1. first input with an active source
 ('bn.add', {'D': R7, 'A': R1, 'B': R11}), ('bn.lbz', {'?': R6, 'A': R7, 'z': 20}),
 ('bg.beqi', {'A': R6, 'I': 0, ';': 'as_take'}),
 ('bn.addi', {'D': R11, 'A': R11, 'O': 1}),
 ('bg.bnei', {'A': R11, 'I': 3, ';': 'as_a'}),
 movi(R11, 0),
 'as_b:',                                                  # 2. first other candidate in rotation order
 ('bn.add', {'D': R7, 'A': R1, 'B': R11}), ('bn.lbz', {'?': R6, 'A': R7, 'z': 20}),
 ('bg.beqi', {'A': R6, 'I': 2, ';': 'as_take'}),
 ('bn.addi', {'D': R11, 'A': R11, 'O': 1}),
 ('bg.bnei', {'A': R11, 'I': 3, ';': 'as_b'}),
 # 3. no candidate: "No signal" now (r10 = the current port, as the handler expects)
 mov(R10, R12),
 ('bn.lwz', {'D': R12, 'A': R1, ':': 4}), ('bn.lwz', {'D': R11, 'A': R1, ':': 8}),
 ('bn.lwz', {'D': R9, 'A': R1, ':': 16}), ('bn.addi', {'D': R1, 'A': R1, 'O': 28}),
 ('bg.j', {'/': NOSIG}),
 'as_take:',
 ('bn.add', {'D': R7, 'A': R1, 'B': R11}), ('bn.lbz', {'?': R10, 'A': R7, 'z': 24}),
 # status +0x20 |= 0x0C ("no signal" until the port reports one), as sub_2653EA does
 ('bg.ori', {'D': R7, 'A': R0, 't': 0xB0}), ('bn.mul', {'D': R7, 'A': R10, 'B': R7}),
 mh(R6, 0x3B), ('bg.addi', {'D': R6, 'A': R6, 'Y': 0x4950}), ('bn.add', {'D': R7, 'A': R7, 'B': R6}),
 ('bn.lbz', {'?': R6, 'A': R7, 'z': 0x20}), ('bg.ori', {'D': R6, 'A': R6, 't': 0x0C}),
 ('bn.sb', {'z': 0x20, 'A': R7, 'B': R6}),
 mov(R3, R10),
 ('bn.lwz', {'D': R12, 'A': R1, ':': 4}), ('bn.lwz', {'D': R11, 'A': R1, ':': 8}),
 ('bn.lwz', {'D': R10, 'A': R1, ':': 12}), ('bn.lwz', {'D': R9, 'A': R1, ':': 16}),
 ('bn.addi', {'D': R1, 'A': R1, 'O': 28}), ('bt.jr', {'A': R9}),
 'as_fail:',
 mov(R3, R12),
 ('bn.lwz', {'D': R12, 'A': R1, ':': 4}), ('bn.lwz', {'D': R11, 'A': R1, ':': 8}),
 ('bn.lwz', {'D': R10, 'A': R1, ':': 12}), ('bn.lwz', {'D': R9, 'A': R1, ':': 16}),
 ('bn.addi', {'D': R1, 'A': R1, 'O': 28}),
 ('bg.j', {'/': NEXT}),

 # ---- as_rot: r10 = next port in the vendor rotation (0-1-2-3-0, 4/5 -> 2) ----
 'as_rot:',
 ('bg.beqi', {'A': R10, 'I': 3, ';': 'as_r0'}),
 ('bg.bgtui', {'A': R10, 'I': 3, ';': 'as_r2'}),
 ('bn.addi', {'D': R10, 'A': R10, 'O': 1}), ('bt.jr', {'A': R9}),
 'as_r0:', movi(R10, 0), ('bt.jr', {'A': R9}),
 'as_r2:', movi(R10, 2), ('bt.jr', {'A': R9}),

 # ---- asq(r3 = port) -> r3: 0 source active, 1 no source, 2 other answer / not a DP-class front-end port,
 #      3 no answer (mailbox failure) ----
 'asq:',
 ('bn.addi', {'D': R1, 'A': R1, 'O': -8}), ('bn.sw', {':': 4, 'A': R1, 'B': R9}),
 ('bg.ori', {'D': R7, 'A': R0, 't': 0xB0}), ('bn.mul', {'D': R7, 'A': R3, 'B': R7}),
 mh(R6, 0x3B), ('bg.addi', {'D': R6, 'A': R6, 'Y': 0x4950}), ('bn.add', {'D': R7, 'A': R7, 'B': R6}),
 ('bn.lwz', {'D': R6, 'A': R7, ':': 4}),                   # port type
 mh(R5, 0x2), ('bn.and', {'D': R5, 'A': R6, 'B': R5}), ('bg.beqi', {'A': R5, 'I': 0, ';': 'asq_u'}),   # front-end port
 ('bn.andi', {'D': R5, 'A': R6, 'N': 0x20}), ('bg.beqi', {'A': R5, 'I': 0, ';': 'asq_u'}),             # DP class
 mh(R7, 0x3B), ('bg.addi', {'D': R7, 'A': R7, 'Y': 0x4281}), ('bn.add', {'D': R7, 'A': R7, 'B': R3}),
 ('bn.lbz', {'?': R7, 'A': R7, 'z': 0}),                   # front-end id
 ('bg.beqi', {'A': R7, 'I': 0, ';': 'asq_u'}),
 ('bn.sb', {'z': 0, 'A': R1, 'B': R7}), movi(R7, 2), ('bn.sb', {'z': 1, 'A': R1, 'B': R7}),
 ('bg.ori', {'D': R3, 'A': R0, 't': 0x60}), ('bg.ori', {'D': R4, 'A': R0, 't': 0xFF}),
 movi(R5, 0xB), movi(R6, 1),
 ('bn.addi', {'D': R7, 'A': R1, 'O': 0}), ('bn.addi', {'D': R8, 'A': R1, 'O': 1}),
 ('bg.jal', {'/': MBOX}),
 ('bg.beqi', {'A': R3, 'I': 0, ';': 'asq_f'}),             # no answer
 ('bn.lbz', {'?': R3, 'A': R1, 'z': 1}),
 ('bg.bleui', {'A': R3, 'I': 1, ';': 'asq_x'}),
 'asq_u:', movi(R3, 2), ('bg.j', {'/': 'asq_x'}),
 'asq_f:', movi(R3, 3),
 'asq_x:',
 ('bn.lwz', {'D': R9, 'A': R1, ':': 4}), ('bn.addi', {'D': R1, 'A': R1, 'O': 8}), ('bt.jr', {'A': R9}),

]
code, L = S.assemble(prog, CAVE)
assert CAVE + len(code) <= 0x201C00, hex(CAVE + len(code))
for a, b, x in A.disasm(code, CAVE, CAVE + len(code), CAVE):
    lab = [k for k, v in L.items() if v == a]
    print(('%-9s' % (lab[0] + ':' if lab else '')) + '%08x: %-12s %-9s %s' % (a, b.hex(' '), x['mnem'], x['ops']))
h1 = S.encode('bg.jal', {'/': L['as_next']}, SITE)
print('%06x: %s -> %s' % (SITE, cur(SITE, 4).hex(), h1.hex()))

patch = {
 'name': 'scan-active-first',
 'summary': ('Automatic input: each input that can have a source is visited once per search (DP / USB-C by the '
             "front-end's link status, an active source first; HDMI only with a cable), then \"No signal\" at once "
             'instead of two full rounds over all four inputs'),
 'status': 'v2 untested (v1 untested)',
 'requires': ['fe-failsafe'],
 'edits': [
  {'addr': '0x%06X' % CAVE, 'old': '00' * len(code), 'new': code.hex(),
   'asm': 'as_next / as_rot / asq (image head zero area 0x201A00); RAM 0x2024EA inputs visited in this search'},
  {'addr': '0x%06X' % SITE, 'old': cur(SITE, 4).hex(), 'new': h1.hex(),
   'asm': 'sub_25FE39 scan step: jal sub_2653EA -> jal as_next'},
 ],
 'notes': 'See the docstring of tools/patches_src_scan_active_first.py. Generated by tools/patches_src_scan_active_first.py.',
}
out = os.environ.get('OUT', 'scan-active-first.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
