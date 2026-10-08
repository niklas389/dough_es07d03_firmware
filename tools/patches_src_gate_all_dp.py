#!/usr/bin/env python3
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

Patch: sub_2612F9's entry jumps to a new gate in the linker padding (gate2 at
0x2038AC, the per-connector query gq at 0x203B78);
its callers (power-save entry 0x2613A0, link-held standby re-query 0x261DFD,
diag-log's G hook) are unchanged. Conflicts with gate-raw-id (same function).
"""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeon'))
import aeondis as A, aeonasm as S

d = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
def cur(a, n): return d[a - 0x200000:a - 0x200000 + n]

GATE = 0x2612F9                      # sub_2612F9: r3 = 1 refuse, 0 allow
MBOX = 0x238FA5                      # mailbox_query(r3 cmd, r4 sub, r5, r6 len, r7 data, r8 reply) -> r3 1 ok / 0 failed
CAVE = 0x2038AC                      # gate2: linker padding after standby-lhs (0x203800-0x2038A9), before panel-t12 (0x203900)
CAVE_Q = 0x203B78                    # gq: linker padding after panel-prepower (0x203B08-0x203B75), before popup-flat (0x203C00)
R0, R1, R3, R4, R5, R6, R7, R8, R9, R10, R11 = 0, 1, 3, 4, 5, 6, 7, 8, 9, 10, 11

assert cur(GATE, 5).hex() == '9c340d2108'                           # addi r1,r1,-0xc ; sw 8(r1),r9
assert A.decode(d, 0x2612FE - 0x200000, 0x2612FE)['ops'] == 'r7,0x48'
assert A.decode(d, 0x261302 - 0x200000, 0x261302)['ops'] == 'r5,-0x50b(r7)'   # current port 0x47FAF5
assert A.decode(d, 0x261344 - 0x200000, 0x261344)['ops'] == 'r3,r0,0x60'
assert A.decode(d, 0x261354 - 0x200000, 0x261354)['target'] == MBOX
assert cur(0x3B4281, 2).hex() == '0708'                              # front-end ids of ports 0 (USB-C), 1 (DP)
assert cur(MBOX, 3).hex() == '1c21d4'

mh = lambda r, v: ('bg.movhi', {'D': r, 'U': v})
prog = [
 'gate2:',                                                # r3 = 1 refuse standby, 0 allow
 ('bn.addi', {'D': R1, 'A': R1, 'O': -12}),
 ('bn.sw', {':': 8, 'A': R1, 'B': R9}), ('bn.sw', {':': 4, 'A': R1, 'B': R10}), ('bn.sw', {':': 0, 'A': R1, 'B': R11}),
 mh(R7, 0x48), ('bg.lbz', {'?': R10, 'A': R7, '!': -0x50B}),          # r10 = current port
 mh(R7, 0x3B), ('bg.lwz', {'D': R7, 'A': R7, 'W': 0x5F38}),
 ('bn.lbz', {'?': R7, 'A': R7, 'z': 0x4F}),                           # settings +0x4F: 0 = automatic input
 ('bt.movi', {'D': R11, 'I': 0}),
 ('bg.bnei', {'A': R7, 'I': 0, ';': 'g_one'}),
 ('bt.movi', {'D': R10, 'I': 0}), ('bg.jal', {'/': 'gq'}), ('bn.or', {'D': R11, 'A': R11, 'B': R3}),   # USB-C
 ('bt.movi', {'D': R10, 'I': 1}), ('bg.jal', {'/': 'gq'}), ('bn.or', {'D': R11, 'A': R11, 'B': R3}),   # DP
 ('bg.j', {'/': 'g_out'}),
 'g_one:',
 ('bg.jal', {'/': 'gq'}), ('bn.or', {'D': R11, 'A': R11, 'B': R3}),
 'g_out:',
 ('bn.or', {'D': R3, 'A': R11, 'B': R0}),
 ('bn.lwz', {'D': R11, 'A': R1, ':': 0}), ('bn.lwz', {'D': R10, 'A': R1, ':': 4}), ('bn.lwz', {'D': R9, 'A': R1, ':': 8}),
 ('bn.addi', {'D': R1, 'A': R1, 'O': 12}), ('bt.jr', {'A': R9}),

]
prog_q = [
 'gq:',                                                   # r10 = port -> r3 = 1: DP-class and a source is active (or no answer)
 ('bn.addi', {'D': R1, 'A': R1, 'O': -8}), ('bn.sw', {':': 4, 'A': R1, 'B': R9}),
 ('bg.ori', {'D': R7, 'A': R0, 't': 0xB0}), ('bn.mul', {'D': R7, 'A': R10, 'B': R7}),
 mh(R6, 0x3B), ('bg.addi', {'D': R6, 'A': R6, 'Y': 0x4950}), ('bn.add', {'D': R7, 'A': R7, 'B': R6}),
 ('bn.lwz', {'D': R6, 'A': R7, ':': 4}),                             # port type
 mh(R5, 0x2), ('bn.and', {'D': R5, 'A': R6, 'B': R5}), ('bg.beqi', {'A': R5, 'I': 0, ';': 'gq_no'}),   # front-end port
 ('bn.andi', {'D': R5, 'A': R6, 'N': 0x20}), ('bg.beqi', {'A': R5, 'I': 0, ';': 'gq_no'}),             # DP class
 mh(R7, 0x3B), ('bg.addi', {'D': R7, 'A': R7, 'Y': 0x4281}), ('bn.add', {'D': R7, 'A': R7, 'B': R10}),
 ('bn.lbz', {'?': R7, 'A': R7, 'z': 0}),                             # front-end id
 ('bn.sb', {'z': 0, 'A': R1, 'B': R7}), ('bn.sb', {'z': 1, 'A': R1, 'B': R0}),
 ('bg.ori', {'D': R3, 'A': R0, 't': 0x60}), ('bg.ori', {'D': R4, 'A': R0, 't': 0xFF}),
 ('bt.movi', {'D': R5, 'I': 0xB}), ('bt.movi', {'D': R6, 'I': 1}),
 ('bn.addi', {'D': R7, 'A': R1, 'O': 0}), ('bn.addi', {'D': R8, 'A': R1, 'O': 1}),
 ('bg.jal', {'/': MBOX}),
 ('bg.beqi', {'A': R3, 'I': 0, ';': 'gq_yes'}),                     # no answer: refuse
 ('bn.lbz', {'?': R7, 'A': R1, 'z': 1}),
 ('bg.beqi', {'A': R7, 'I': 0, ';': 'gq_yes'}),                     # 0 = source active
 'gq_no:',
 ('bt.movi', {'D': R3, 'I': 0}), ('bg.j', {'/': 'gq_out'}),
 'gq_yes:',
 ('bt.movi', {'D': R3, 'I': 1}),
 'gq_out:',
 ('bn.lwz', {'D': R9, 'A': R1, ':': 4}), ('bn.addi', {'D': R1, 'A': R1, 'O': 8}), ('bt.jr', {'A': R9}),
]
code_q, LQ = S.assemble(prog_q, CAVE_Q)
assert CAVE_Q + len(code_q) <= 0x203C00, hex(CAVE_Q + len(code_q))
assert cur(CAVE_Q, len(code_q)) == b'\0' * len(code_q)
prog = [(('bg.jal', {'/': LQ['gq']}) if it == ('bg.jal', {'/': 'gq'}) else it) for it in prog]
code, L = S.assemble(prog, CAVE)
assert CAVE + len(code) <= 0x203900, hex(CAVE + len(code))
assert cur(CAVE, len(code)) == b'\0' * len(code)
for c, base, labs in ((code, CAVE, L), (code_q, CAVE_Q, LQ)):
    for a, b, x in A.disasm(c, base, base + len(c), base):
        lab = [k for k, v in labs.items() if v == a]
        print(('%-8s' % (lab[0] + ':' if lab else '')) + '%08x: %-12s %-9s %s' % (a, b.hex(' '), x['mnem'], x['ops']))
hook = S.encode('bg.j', {'/': CAVE}, GATE)
print('%06x: %s -> %s  (gate2 %#x-%#x, gq %#x-%#x)' % (GATE, cur(GATE, 4).hex(), hook.hex(), CAVE, CAVE + len(code), CAVE_Q, CAVE_Q + len(code_q)))

patch = {
 'name': 'gate-all-dp',
 'summary': ('Standby gate v2: with automatic input, standby is refused while a source is active on any DP-class '
             'connector (DP or USB-C), not only the current one; fixed input: the selected one; no answer from the '
             'front-end: refused. Each connector is asked by its own id (replaces gate-raw-id)'),
 'status': ('hardware-tested 2026-10-08: automatic input, both outputs off -> deep standby, no wake for minutes; '
            'after a key wake the dock held the DP link (DP: source active) -> link-held standby, deep standby as soon '
            'as the dock released the link'),
 'conflicts': ['gate-raw-id'],
 'edits': [
  {'addr': '0x%06X' % CAVE, 'old': '00' * len(code), 'new': code.hex(),
   'asm': 'gate2 (linker padding 0x2038AC): automatic input -> ask ports 0 and 1, else the current port'},
  {'addr': '0x%06X' % CAVE_Q, 'old': '00' * len(code_q), 'new': code_q.hex(),
   'asm': 'gq (linker padding 0x203B78): 0x60/0xB for one DP-class connector by front-end id'},
  {'addr': '0x%06X' % GATE, 'old': cur(GATE, 4).hex(), 'new': hook.hex(),
   'asm': 'sub_2612F9 entry -> j gate2'},
 ],
 'notes': 'See the docstring of tools/patches_src_gate_all_dp.py. Generated by tools/patches_src_gate_all_dp.py.',
}
out = os.environ.get('OUT', 'gate-all-dp.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
