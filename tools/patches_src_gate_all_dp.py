#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Source of patches/gate-all-dp.json. Run in an unpacked work dir (RT=runtime_0x200000.bin).

Standby gate v2 (replaces gate-raw-id): with automatic input, standby is
refused while a source is active on ANY DP-class connector (DP or USB-C),
not only on the current one; with a fixed input, only the selected connector
counts (as gate-raw-id). Every connector is asked by its own front-end id.

Finding (2026-10-08, automatic input, DP output disabled through the MST
dock, laptop on USB-C): after a wake through USB-C and disabling the laptop's
output again, the monitor looped: deep standby, woken ~12 s later, scan,
"No signal", standby, ... The wake was event 9 from port 1 (DP): the dock
retrained the DP link after the monitor dropped it. The vendor gate
(sub_2612F9) asks only about the current port (here USB-C: no source) and
allowed deep standby, although the PM51 wakes on activity from every
connector in automatic mode. Not going to deep standby while a connector's
source still holds its link (link-held standby instead) is what the gate does
for the current port; this extends it to every connector that can wake the
monitor. With a fixed input, pm51-input-filter ignores wakes from the other
connectors, so only the selected one is asked.

If the front-end does not answer a query (mailbox failure), the gate refuses
standby: the monitor stays in link-held standby, where keys and DDC/CI work,
instead of handing over to the PM51 with a front-end that does not answer
(docs/firmware-map.md section 30).

Patch: sub_2612F9's entry jumps to the new gate; its callers (power-save
entry 0x2613A0, link-held standby re-query 0x261DFD, diag-log's G hook) are
unchanged. Conflicts with gate-raw-id (same function).

v3 (2026-10-08): automatic input, the dock held the DP link -> link-held
standby. A source on the other connector cannot end it: in link-held standby
only the routed input's own video does (standby-lhs, cave_b), and the
front-end routes only the current connector. v3 woke the monitor like a key
on a "no source" -> "source active" change; on hardware the laptop had been
enabled before link-held standby began (no change seen) and the current
input was HDMI 2, so nothing happened for minutes.

v4: the gate keeps each connector's last answer (RAM 0x2024C0 USB-C,
0x2024C1 DP) and, while in link-held standby (rws 0x4551CC) with automatic
input, routes path 0 to a connector with an active link (sub_23F836, as the
scan does; the panel stays off), so that connector's video ends link-held
standby the normal way:
1. a connector that is not the current one and changed to "source active";
2. else, if the current input is HDMI or its connector has no link: the
   first other connector with an active link;
3. else (both links active): the other one every ALT (6) re-queries = 30 s,
   so video on either is found while two links are held (counter 0x2024C2).
Every gate call also clears scan-active-first's jump flag (0x2024E8).
v4 also runs the same check every 5 s of the "No signal" countdown (OSD state
4, pre-standby included; hook 0x261CEB in the 1 s task sub_261C04): the
vendor scan stops after one round, so before the standby decision (30 s
with standby-timeout) a source that appears on another connector was not
found either.
v4.1: the routing also stores the port in settings +0x5B (path 0's current
port, written by the scan at 0x260189 and by sub_2678D9, read by sub_26A809,
the OSD and DDC/CI); v4 left it stale after a routing.
v5 (2026-10-09, Option A of docs/firmware-map.md sections 51-55; build with
HOLD=1, the default; HOLD=0 gives v4.1): when the only reason to refuse is a
DP-class source that holds its link (all queries answered, not the routing
tick), standby is allowed and the request is marked "hold the link": RAM
0x2024C6 = 0x80 | connectors (bit 0 USB-C, bit 1 DP; automatic input: those
that answered "source active", fixed input: the selected one), copied by the
power-save entry into byte +3 of the standby block (0x48A740 + 3, hook at
0x261425, stub 0x202500), which reaches the PM51 as XDATA 0x5E95.
pm51-hold-link then keeps the front-end running (link held) and wakes on
video. A query without an answer still refuses (link-held standby with the
CPU running, as v4; RAM 0x2024C5 = 1 for that call). Requires
pm51-hold-link: without it the PM51 sends the front-end to its standby mode
as before, and the dock's retraining wakes the monitor again.
Code in the image head zero area: gate 0x2016D0, link-held part 0x201900,
tick 0x201350, query 0x201280, v5 hold part 0x202520, block stub 0x202500.
"""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeon'))
import aeondis as A, aeonasm as S

d = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
def cur(a, n): return d[a - 0x200000:a - 0x200000 + n]

GATE = 0x2612F9                      # sub_2612F9: r3 = 1 refuse, 0 allow
MBOX = 0x238FA5                      # mailbox_query(r3 cmd, r4 sub, r5, r6 len, r7 data, r8 reply) -> r3 1 ok / 0 failed
CAVE, CAVE_END = 0x2016D0, 0x201800  # image head zero area: after diag-log-ring's code (ends 0x2016C8), before picture-watchdog
CAVE_L, CAVE_L_END = 0x201900, 0x201A00  # link-held standby part: after picture-watchdog, before scan-active-first
CAVE_T, CAVE_T_END = 0x201350, 0x201400  # countdown tick: after wake-port-first (0x201300-0x201344), before diag-log
CAVE_Q, CAVE_Q_END = 0x201280, 0x201300  # gq: head zero area after fe-failsafe (0x201220-0x20126D), before wake-port-first
                                     # (v2 used the linker padding 0x2038AC and 0x203B78; both are free again)
SWITCH = 0x23F836                    # sub_23F836(path, port): the scan's input switch
ALT = int(os.environ.get('ALT', '6'))  # both links active in link-held standby: try the other one every ALT re-queries (5 s)
ALTC = 0x2024C2
TICK, ROUTE = 0x2024C3, 0x2024C4     # countdown ticks since the last routing check; 1 while the tick runs the gate
TICK_S = 5                           # routing check every 5 s of the "No signal" countdown
TICK_SITE = 0x261CEB                 # sub_261C04: lbz r7,0x51a6(r10) before cnt -= 1
PREV = 0x2024C0                      # last answer per connector (0 USB-C, 1 DP): 0 active, 1 none
SCAN_FLAG = 0x2024E8                 # scan-active-first: jumped in this search
HOLD = int(os.environ.get('HOLD', '1'))   # v5: allow standby with the link held (pm51-hold-link)
FAILB, HOLDB = 0x2024C5, 0x2024C6    # this call had a query without answer; hold byte for the standby block
CAVE_H, CAVE_B = 0x202520, 0x202500  # head zero area 0x202087-0x2037FF (diag-log data ends 0x202414)
BLK_SITE, BLK_CONT = 0x261425, 0x261429   # power-save entry: lbz r6,0xbf(r5) after the block's +3 = 0
R0, R1, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13 = 0, 1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13

assert cur(GATE, 5).hex() == '9c340d2108'                           # addi r1,r1,-0xc ; sw 8(r1),r9
assert A.decode(d, 0x2612FE - 0x200000, 0x2612FE)['ops'] == 'r7,0x48'
assert A.decode(d, 0x261302 - 0x200000, 0x261302)['ops'] == 'r5,-0x50b(r7)'   # current port 0x47FAF5
assert A.decode(d, 0x261344 - 0x200000, 0x261344)['ops'] == 'r3,r0,0x60'
assert A.decode(d, 0x261354 - 0x200000, 0x261354)['target'] == MBOX
assert cur(0x3B4281, 2).hex() == '0708'                              # front-end ids of ports 0 (USB-C), 1 (DP)
assert cur(MBOX, 3).hex() == '1c21d4'
assert A.decode(d, 0x260181 - 0x200000, 0x260181)['target'] == SWITCH   # the scan's sub_23F836(0, port)
assert 2 <= ALT <= 15
assert cur(TICK_SITE, 4).hex() == 'f0ea51a6' and cur(TICK_SITE + 4, 5).hex() == '9cff5ce700'   # lbz r7,cnt ; addi -1 ; extbz
assert A.decode(d, 0x261DFD - 0x200000, 0x261DFD)['target'] == GATE and cur(0x261F89, 6).hex() == '98e5f8ea51cd'  # re-query; refusal re-arms
assert cur(PREV, 4) == b'\0' * 4
assert cur(FAILB, 2) == b'\0' * 2
assert cur(0x26141B, 10).hex() == 'fce4a74018c70218070 3'.replace(' ', ''), cur(0x26141B, 10).hex()   # r7 = block; +2 = port; +3 = 0
assert cur(BLK_SITE, 4).hex() == 'f0c500bf', cur(BLK_SITE, 4).hex()                   # lbz r6,0xbf(r5)
assert cur(CAVE_B, 0x100) == b'\0' * 0x100

mh = lambda r, v: ('bg.movhi', {'D': r, 'U': v})
lbz = lambda rd, a, ra: ('bg.lbz', {'?': rd, 'A': ra, '!': a & 0xFFFF})
sb = lambda a, ra, rb: ('bg.sb', {'Y': a & 0xFFFF, 'A': ra, 'B': rb})
prog = [
 'gate3:',                                                # r3 = 1 refuse standby, 0 allow
 ('bn.addi', {'D': R1, 'A': R1, 'O': -20}),
 ('bn.sw', {':': 16, 'A': R1, 'B': R9}), ('bn.sw', {':': 12, 'A': R1, 'B': R10}), ('bn.sw', {':': 8, 'A': R1, 'B': R11}),
 ('bn.sw', {':': 4, 'A': R1, 'B': R12}), ('bn.sw', {':': 0, 'A': R1, 'B': R13}),
 mh(R7, 0x20), sb(SCAN_FLAG, R7, R0),                     # scan-active-first: a new search after any standby decision
 sb(FAILB, R7, R0),                                       # v5: no failed query yet in this call
 mh(R7, 0x48), ('bg.lbz', {'?': R10, 'A': R7, '!': -0x50B}),          # r10 = current port (0x47FAF5)
 ('bt.movi', {'D': R11, 'I': 0}), ('bt.movi', {'D': R12, 'I': 0}),    # r11 refuse, r12 = connectors with a new source (bits)
 mh(R7, 0x3B), ('bg.lwz', {'D': R7, 'A': R7, 'W': 0x5F38}),
 ('bn.lbz', {'?': R7, 'A': R7, 'z': 0x4F}),                           # settings +0x4F: 0 = automatic input
 ('bg.beqi', {'A': R7, 'I': 0, ';': 'g_auto'}),
 ('bn.or', {'D': R3, 'A': R10, 'B': R0}), ('bg.jal', {'/': 'gq'}),     # fixed input: the selected connector only
 ('bg.jal', {'/': 'g_ref'}),
 ('bg.j', {'/': 'g_out'}),
 'g_auto:',
 ('bt.movi', {'D': R13, 'I': 0}),
 'g_loop:',                                               # USB-C (0), DP (1)
 ('bn.or', {'D': R3, 'A': R13, 'B': R0}), ('bg.jal', {'/': 'gq'}),
 ('bg.jal', {'/': 'g_ref'}),
 ('bg.bgtui', {'A': R3, 'I': 1, ';': 'g_next'}),          # no answer / not DP-class: keep the last answer
 mh(R7, 0x20), ('bg.addi', {'D': R7, 'A': R7, 'Y': PREV & 0xFFFF}), ('bn.add', {'D': R7, 'A': R7, 'B': R13}),
 ('bn.lbz', {'?': R6, 'A': R7, 'z': 0}), ('bn.sb', {'z': 0, 'A': R7, 'B': R3}),
 ('bg.bnei', {'A': R3, 'I': 0, ';': 'g_next'}),
 ('bg.bnei', {'A': R6, 'I': 1, ';': 'g_next'}),           # "no source" -> "source active"
 ('bt.movi', {'D': R6, 'I': 1}), ('bn.sll', {'D': R6, 'A': R6, 'B': R13}), ('bn.or', {'D': R12, 'A': R12, 'B': R6}),
 'g_next:',
 ('bn.addi', {'D': R13, 'A': R13, 'O': 1}),
 ('bg.bnei', {'A': R13, 'I': 2, ';': 'g_loop'}),
 ('bg.beqi', {'A': R11, 'I': 0, ';': 'g_out'}),
 ('bg.j', {'/': CAVE_L}),                                 # link-held standby part (second block)
 'g_out:',
 *([('bg.jal', {'/': CAVE_H})] if HOLD else []),          # v5: link held only -> allow, mark the request
 ('bn.or', {'D': R3, 'A': R11, 'B': R0}),
 ('bn.lwz', {'D': R13, 'A': R1, ':': 0}), ('bn.lwz', {'D': R12, 'A': R1, ':': 4}), ('bn.lwz', {'D': R11, 'A': R1, ':': 8}),
 ('bn.lwz', {'D': R10, 'A': R1, ':': 12}), ('bn.lwz', {'D': R9, 'A': R1, ':': 16}),
 ('bn.addi', {'D': R1, 'A': R1, 'O': 20}), ('bt.jr', {'A': R9}),
 'g_ref:',                                                # r3 = 0 (active) or 3 (no answer): refuse
 ('bg.beqi', {'A': R3, 'I': 0, ';': 'g_r1'}),
 ('bg.bnei', {'A': R3, 'I': 3, ';': 'g_r0'}),
 mh(R7, 0x20), ('bt.movi', {'D': R6, 'I': 1}), sb(FAILB, R7, R6),   # no answer: never hold
 'g_r1:', ('bt.movi', {'D': R11, 'I': 1}),
 'g_r0:', ('bt.jr', {'A': R9}),
]
prog_l = [
 # ---- link-held standby (rws set, standby refused): route a connector with an active link ----
 'g_lhs:',
 mh(R7, 0x45), lbz(R6, 0x4551CC, R7), ('bg.bnei', {'A': R6, 'I': 0, ';': 'g_l0'}),
 mh(R7, 0x20), lbz(R6, ROUTE, R7), ('bg.beqi', {'A': R6, 'I': 0, ';': 'G_OUT'}),   # "No signal" countdown tick
 'g_l0:',
 mh(R7, 0x20),
 ('bt.movi', {'D': R13, 'I': 0}),                         # 1. a new source on another connector
 'g_e:',
 ('bg.beq', {'A': R13, 'B': R10, ';': 'g_e1'}),
 ('bn.srl', {'D': R6, 'A': R12, 'B': R13}), ('bn.andi', {'D': R6, 'A': R6, 'N': 1}),
 ('bg.bnei', {'A': R6, 'I': 0, ';': 'g_sw'}),
 'g_e1:',
 ('bn.addi', {'D': R13, 'A': R13, 'O': 1}), ('bg.bnei', {'A': R13, 'I': 2, ';': 'g_e'}),
 ('bg.bgtui', {'A': R10, 'I': 1, ';': 'g_any'}),          # 2. current input is not DP-class, or has no link:
 ('bg.addi', {'D': R6, 'A': R7, 'Y': PREV & 0xFFFF}), ('bn.add', {'D': R6, 'A': R6, 'B': R10}),
 ('bn.lbz', {'?': R6, 'A': R6, 'z': 0}),
 ('bg.beqi', {'A': R6, 'I': 0, ';': 'g_alt'}),
 'g_any:',                                                #    the first connector with an active link
 ('bt.movi', {'D': R13, 'I': 0}),
 'g_a:',
 ('bg.beq', {'A': R13, 'B': R10, ';': 'g_a1'}),
 ('bg.addi', {'D': R6, 'A': R7, 'Y': PREV & 0xFFFF}), ('bn.add', {'D': R6, 'A': R6, 'B': R13}),
 ('bn.lbz', {'?': R6, 'A': R6, 'z': 0}),
 ('bg.beqi', {'A': R6, 'I': 0, ';': 'g_sw'}),
 'g_a1:',
 ('bn.addi', {'D': R13, 'A': R13, 'O': 1}), ('bg.bnei', {'A': R13, 'I': 2, ';': 'g_a'}),
 ('bg.j', {'/': 'G_OUT'}),
 'g_alt:',                                                # 3. both links active: try the other one every ALT re-queries
 lbz(R6, ALTC, R7), ('bn.addi', {'D': R6, 'A': R6, 'O': 1}), sb(ALTC, R7, R6),
 ('bg.bleui', {'A': R6, 'I': ALT - 1, ';': 'G_OUT'}),
 sb(ALTC, R7, R0),
 ('bg.xori', {'D': R13, 'A': R10, 'Y': 1}),                # the other connector (current is 0 or 1 here)
 ('bg.addi', {'D': R6, 'A': R7, 'Y': PREV & 0xFFFF}), ('bn.add', {'D': R6, 'A': R6, 'B': R13}),
 ('bn.lbz', {'?': R6, 'A': R6, 'z': 0}),
 ('bg.bnei', {'A': R6, 'I': 0, ';': 'G_OUT'}),
 'g_sw:',                                                 # path 0 -> port r13 (as the scan: "no signal" until it reports one)
 sb(ALTC, R7, R0),
 ('bg.ori', {'D': R7, 'A': R0, 't': 0xB0}), ('bn.mul', {'D': R7, 'A': R13, 'B': R7}),
 mh(R6, 0x3B), ('bg.addi', {'D': R6, 'A': R6, 'Y': 0x4950}), ('bn.add', {'D': R7, 'A': R7, 'B': R6}),
 ('bn.lbz', {'?': R6, 'A': R7, 'z': 0x20}), ('bg.ori', {'D': R6, 'A': R6, 't': 0x0C}), ('bn.sb', {'z': 0x20, 'A': R7, 'B': R6}),
 ('bt.movi', {'D': R3, 'I': 0}), ('bn.or', {'D': R4, 'A': R13, 'B': R0}), ('bg.jal', {'/': SWITCH}),
 mh(R7, 0x3B), ('bg.lwz', {'D': R7, 'A': R7, 'W': 0x5F38}),
 ('bn.sb', {'z': 0x5B, 'A': R7, 'B': R13}),                # settings +0x5B = path 0's port, as the scan (0x260189)
 ('bg.j', {'/': 'G_OUT'}),
]
prog_t = [

 # ---- standby countdown, once per second while it runs (0x261CEB; r10 = 0x45 base, r5-r7 free) ----
 'g_tick:',
 ('bn.addi', {'D': R1, 'A': R1, 'O': -4}), ('bn.sw', {':': 0, 'A': R1, 'B': R9}),
 mh(R7, 0x45), lbz(R6, 0x457854, R7), ('bg.bnei', {'A': R6, 'I': 4, ';': 't_x'}),   # "No signal" / pre-standby only
 mh(R7, 0x20), lbz(R6, TICK, R7), ('bn.addi', {'D': R6, 'A': R6, 'O': 1}), sb(TICK, R7, R6),
 ('bg.bleui', {'A': R6, 'I': TICK_S - 1, ';': 't_x'}),
 sb(TICK, R7, R0), ('bt.movi', {'D': R6, 'I': 1}), sb(ROUTE, R7, R6),
 ('bg.jal', {'/': 'GATE3'}),                              # query both connectors, route if needed (result ignored)
 mh(R7, 0x20), sb(ROUTE, R7, R0),
 't_x:',
 ('bn.lwz', {'D': R9, 'A': R1, ':': 0}), ('bn.addi', {'D': R1, 'A': R1, 'O': 4}),
 lbz(R7, 0x4551A6, R10),                                  # displaced: lbz r7,0x51a6(r10)
 ('bt.jr', {'A': R9}),
]
prog_q = [
 'gq:',                                                   # r3 = port -> 0 source active, 1 no source, 2 not DP-class / other, 3 no answer
 ('bn.addi', {'D': R1, 'A': R1, 'O': -8}), ('bn.sw', {':': 4, 'A': R1, 'B': R9}),
 ('bg.ori', {'D': R7, 'A': R0, 't': 0xB0}), ('bn.mul', {'D': R7, 'A': R3, 'B': R7}),
 mh(R6, 0x3B), ('bg.addi', {'D': R6, 'A': R6, 'Y': 0x4950}), ('bn.add', {'D': R7, 'A': R7, 'B': R6}),
 ('bn.lwz', {'D': R6, 'A': R7, ':': 4}),                             # port type
 mh(R5, 0x2), ('bn.and', {'D': R5, 'A': R6, 'B': R5}), ('bg.beqi', {'A': R5, 'I': 0, ';': 'gq_u'}),   # front-end port
 ('bn.andi', {'D': R5, 'A': R6, 'N': 0x20}), ('bg.beqi', {'A': R5, 'I': 0, ';': 'gq_u'}),             # DP class
 mh(R7, 0x3B), ('bg.addi', {'D': R7, 'A': R7, 'Y': 0x4281}), ('bn.add', {'D': R7, 'A': R7, 'B': R3}),
 ('bn.lbz', {'?': R7, 'A': R7, 'z': 0}),                             # front-end id
 ('bn.sb', {'z': 0, 'A': R1, 'B': R7}), ('bt.movi', {'D': R7, 'I': 2}), ('bn.sb', {'z': 1, 'A': R1, 'B': R7}),
 ('bg.ori', {'D': R3, 'A': R0, 't': 0x60}), ('bg.ori', {'D': R4, 'A': R0, 't': 0xFF}),
 ('bt.movi', {'D': R5, 'I': 0xB}), ('bt.movi', {'D': R6, 'I': 1}),
 ('bn.addi', {'D': R7, 'A': R1, 'O': 0}), ('bn.addi', {'D': R8, 'A': R1, 'O': 1}),
 ('bg.jal', {'/': MBOX}),
 ('bg.beqi', {'A': R3, 'I': 0, ';': 'gq_f'}),
 ('bn.lbz', {'?': R3, 'A': R1, 'z': 1}),
 ('bg.bleui', {'A': R3, 'I': 1, ';': 'gq_x'}),
 'gq_u:', ('bt.movi', {'D': R3, 'I': 2}), ('bg.j', {'/': 'gq_x'}),
 'gq_f:', ('bt.movi', {'D': R3, 'I': 3}),
 'gq_x:',
 ('bn.lwz', {'D': R9, 'A': R1, ':': 4}), ('bn.addi', {'D': R1, 'A': R1, 'O': 8}), ('bt.jr', {'A': R9}),
]
prog_h = [
 # ---- v5: r11 = 1 (refuse) and r10 = current port; leaf, uses r5-r7 ----
 'g_hold:',
 mh(R7, 0x20), sb(HOLDB, R7, R0),
 ('bg.beqi', {'A': R11, 'I': 0, ';': 'h_x'}),
 lbz(R6, FAILB, R7), ('bg.bnei', {'A': R6, 'I': 0, ';': 'h_x'}),    # a query got no answer: refuse (link-held standby)
 lbz(R6, ROUTE, R7), ('bg.bnei', {'A': R6, 'I': 0, ';': 'h_x'}),    # routing tick: result not used
 mh(R5, 0x3B), ('bg.lwz', {'D': R5, 'A': R5, 'W': 0x5F38}), ('bn.lbz', {'?': R5, 'A': R5, 'z': 0x4F}),
 ('bg.beqi', {'A': R5, 'I': 0, ';': 'h_auto'}),
 ('bg.bgtui', {'A': R10, 'I': 1, ';': 'h_x'}),            # fixed input: the selected DP-class connector
 ('bt.movi', {'D': R6, 'I': 1}), ('bn.sll', {'D': R6, 'A': R6, 'B': R10}), ('bg.j', {'/': 'h_set'}),
 'h_auto:',                                               # automatic: every connector that answered "source active"
 ('bt.movi', {'D': R6, 'I': 0}),
 lbz(R5, PREV, R7), ('bg.bnei', {'A': R5, 'I': 0, ';': 'h_a1'}), ('bg.ori', {'D': R6, 'A': R6, 't': 1}),
 'h_a1:',
 lbz(R5, PREV + 1, R7), ('bg.bnei', {'A': R5, 'I': 0, ';': 'h_a2'}), ('bg.ori', {'D': R6, 'A': R6, 't': 2}),
 'h_a2:',
 ('bg.beqi', {'A': R6, 'I': 0, ';': 'h_x'}),
 'h_set:',
 ('bg.ori', {'D': R6, 'A': R6, 't': 0x80}), sb(HOLDB, R7, R6),
 ('bt.movi', {'D': R11, 'I': 0}),                         # allow standby
 'h_x:',
 ('bt.jr', {'A': R9}),
]
code_h, LH = S.assemble(prog_h, CAVE_H)
assert CAVE_H + len(code_h) <= CAVE_B + 0x100, hex(CAVE_H + len(code_h))
prog_b = [
 'g_blk:',                                                # power-save entry, r7 = standby block 0x48A740, r5 = settings
 mh(R6, 0x20), lbz(R6, HOLDB, R6), ('bn.sb', {'z': 3, 'A': R7, 'B': R6}),   # block +3 = hold byte (PM51 XDATA 0x5E95)
 ('bg.lbz', {'?': R6, 'A': R5, '!': 0xBF}),               # replaced: lbz r6,0xbf(r5)
 ('bg.j', {'/': BLK_CONT}),
]
code_b, LB = S.assemble(prog_b, CAVE_B)
assert CAVE_B + len(code_b) <= CAVE_H
code_q, LQ = S.assemble(prog_q, CAVE_Q)
assert CAVE_Q + len(code_q) <= CAVE_Q_END, hex(CAVE_Q + len(code_q))
assert cur(CAVE_Q, len(code_q)) == b'\0' * len(code_q)
prog = [(('bg.jal', {'/': LQ['gq']}) if it == ('bg.jal', {'/': 'gq'}) else it) for it in prog]
code, L = S.assemble(prog, CAVE)
assert CAVE + len(code) <= CAVE_END, hex(CAVE + len(code))
assert cur(CAVE, len(code)) == b'\0' * len(code)
prog_l = [((it[0], {**it[1], **({';': L['g_out']} if it[1].get(';') == 'G_OUT' else {}),
                     **({'/': L['g_out']} if it[1].get('/') == 'G_OUT' else {}),
                     **({'/': L['gate3']} if it[1].get('/') == 'GATE3' else {})}) if isinstance(it, tuple) else it)
          for it in prog_l]
code_l, LL = S.assemble(prog_l, CAVE_L)
prog_t = [((it[0], {**it[1], **({'/': L['gate3']} if it[1].get('/') == 'GATE3' else {})}) if isinstance(it, tuple) else it)
          for it in prog_t]
code_t, LT = S.assemble(prog_t, CAVE_T)
assert CAVE_T + len(code_t) <= CAVE_T_END, hex(CAVE_T + len(code_t))
assert cur(CAVE_T, len(code_t)) == b'\0' * len(code_t)
assert LL['g_lhs'] == CAVE_L and CAVE_L + len(code_l) <= CAVE_L_END, hex(CAVE_L + len(code_l))
assert cur(CAVE_L, len(code_l)) == b'\0' * len(code_l)
for c, base, labs in ((code, CAVE, L), (code_l, CAVE_L, LL), (code_t, CAVE_T, LT), (code_q, CAVE_Q, LQ)) + \
                     (((code_h, CAVE_H, LH), (code_b, CAVE_B, LB)) if HOLD else ()):
    for a, b, x in A.disasm(c, base, base + len(c), base):
        lab = [k for k, v in labs.items() if v == a]
        print(('%-8s' % (lab[0] + ':' if lab else '')) + '%08x: %-12s %-9s %s' % (a, b.hex(' '), x['mnem'], x['ops']))
hook = S.encode('bg.j', {'/': CAVE}, GATE)
print('%06x: %s -> %s  (gate3 %#x-%#x)' % (GATE, cur(GATE, 4).hex(), hook.hex(), CAVE, CAVE + len(code)))

patch = {
 'name': 'gate-all-dp',
 'summary': (('Standby gate v5: a DP-class source that only holds its link no longer keeps the monitor awake: deep '
              'standby with the link kept, video watched by the PM51 (pm51-hold-link). ' if HOLD else '') +
             'Standby gate v4: with automatic input, standby is refused while a source is active on any DP-class '
             'connector (DP or USB-C), not only the current one; fixed input: the selected one; no answer from the '
             'front-end: refused. v4: in link-held standby and every 5 s of "No signal" with automatic input, the input is '
             'routed to a connector with an active link (a new one first, alternating every 30 s if both), so its video '
             'is found'),
 'status': ('v5 (HOLD=1) hardware-tested 2026-10-09 with pm51-hold-link: link held only -> deep standby at ~4 W with the link kept, wake on video (event 9, port 1), key wake, cable pulled -> stock deep standby (section 55). '
            'v4.1 hardware-tested 2026-10-08 (routing: laptop picked up during the countdown; deep standby after). '
            'v2 hardware-tested 2026-10-08: automatic input, both outputs off -> deep standby; the dock held the DP link '
            'after a key wake -> link-held standby. v3 (edge wake) did not help') if HOLD else
           ('v4.1 hardware-tested 2026-10-08 (routing: laptop picked up during the countdown; deep standby after)'),
 'conflicts': ['gate-raw-id'],
 **({'requires': ['pm51-hold-link']} if HOLD else {}),
 'edits': [
  {'addr': '0x%06X' % CAVE, 'old': '00' * len(code), 'new': code.hex(),
   'asm': 'gate3 (image head zero area 0x2016D0): automatic input -> ask ports 0 and 1 (edge wake from link-held standby), else the current port'},
  {'addr': '0x%06X' % CAVE_L, 'old': '00' * len(code_l), 'new': code_l.hex(),
   'asm': 'g_lhs (image head zero area 0x201900): route a connector with an active link (sub_23F836, settings +0x5B)'},
  {'addr': '0x%06X' % CAVE_T, 'old': '00' * len(code_t), 'new': code_t.hex(),
   'asm': 'g_tick (image head zero area 0x201350): routing check every 5 s of the No-signal countdown'},
  {'addr': '0x%06X' % CAVE_Q, 'old': '00' * len(code_q), 'new': code_q.hex(),
   'asm': 'gq (image head zero area 0x201280): 0x60/0xB for one DP-class connector: 0 active, 1 none, 2 not DP-class, 3 no answer'},
  {'addr': '0x%06X' % GATE, 'old': cur(GATE, 4).hex(), 'new': hook.hex(),
   'asm': 'sub_2612F9 entry -> j gate3'},
  {'addr': '0x%06X' % TICK_SITE, 'old': cur(TICK_SITE, 4).hex(), 'new': S.encode('bg.jal', {'/': LT['g_tick']}, TICK_SITE).hex(),
   'asm': 'sub_261C04 standby countdown: lbz r7,0x51a6(r10) -> jal g_tick (routing check every 5 s of "No signal")'},
 ] + ([
  {'addr': '0x%06X' % CAVE_H, 'old': '00' * len(code_h), 'new': code_h.hex(),
   'asm': 'g_hold (head zero area 0x202520): link held only -> allow standby, hold byte 0x2024C6 = 0x80 | connectors'},
  {'addr': '0x%06X' % CAVE_B, 'old': '00' * len(code_b), 'new': code_b.hex(),
   'asm': 'g_blk (head zero area 0x202500): standby block +3 = hold byte'},
  {'addr': '0x%06X' % BLK_SITE, 'old': cur(BLK_SITE, 4).hex(), 'new': S.encode('bg.j', {'/': CAVE_B}, BLK_SITE).hex(),
   'asm': 'sub_26136B power-save entry: lbz r6,0xbf(r5) -> j g_blk'},
 ] if HOLD else []),
 'notes': 'See the docstring of tools/patches_src_gate_all_dp.py. Generated by tools/patches_src_gate_all_dp.py.',
}
out = os.environ.get('OUT', 'gate-all-dp.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
