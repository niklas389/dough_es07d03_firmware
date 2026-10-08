#!/usr/bin/env python3
"""Source of patches/fe-failsafe.json. Run in an unpacked work dir (RT=runtime_0x200000.bin).

Front-end failsafe: after a mailbox transaction to the front-end (through the
PM51) has timed out, the following transactions wait at most SHORT ms per
phase instead of 10 s, until one completes again.

mailbox_query (0x238FA5, docs/firmware-map.md sections 22, 27) waits in up to
three phases, each with the shared 1 ms down-counter 0x4551C8 loaded with
10000 (0x238FD9 PM51 idle, 0x239091 request data taken, 0x23914B answer;
the third only when an answer is expected). A phase that runs out leaves the
counter at 0: phases 1 and 3 then return 0 (failed); phase 2 of a posted
command returns 1 anyway. With a front-end (or PM51 path) that does not
answer, every command blocks the main loop for 10-30 s, so keys, the OSD and
DDC/CI stop responding, and the link-held standby's gate query every 5 s
(gate-all-dp: refused on failure) keeps it that way (incident 2026-10-08,
section 39).

Patch (image head zero area, code 0x201220, state at RAM 0x2024E0, readable
with diag-poke):
- The three 'addi rX,r0,10000' loads become 'jal fs_t'; fs_t returns the
  budget in r6 and r7 (both free at all three sites): 10000, or SHORT while
  the failsafe flag 0x2024E0 is set.
- The function's last two instructions (0x239023 'addi r1,r1,0x2c; jr r9',
  reached only by falling through the epilogue; diag-log-ring's hook at
  0x239002 is not touched) become 'j fs_x'. fs_x checks the counter: 0 = a
  phase ran out -> flag = 1 and the failure count 0x2024E1 + 1 (stops at
  255); otherwise flag = 0. Return value r3 unchanged.

Normal operation is unchanged until a transaction has run out its full 10 s.
Every later transaction is a probe: the first one that completes within the
short budget restores the 10 s waits. Each start (mains, wake) begins with
the flag clear (the head is copied from flash at every start).
Risk while the flag is set: a command that the PM51 would have taken after
more than SHORT ms (e.g. while it is still retrying an earlier one, up to 5
tries) is dropped instead of sent late.
"""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeon'))
import aeondis as A, aeonasm as S

d = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
def cur(a, n): return d[a - 0x200000:a - 0x200000 + n]

SHORT = int(os.environ.get('SHORT', '500'))          # ms per phase while the flag is set
assert 100 <= SHORT <= 2000
LOADS = {0x238FD9: 'fce02710', 0x239091: 'fcc02710', 0x23914B: 'fce02710'}   # addi r7/r6/r7,r0,10000
EXIT = 0x239023                                      # addi r1,r1,0x2c ; jr r9
CAVE = 0x201220                                      # head zero area 0x201214-0x2012FF (wake-port-first at 0x201300)
FLAG, CNT = 0x2024E0, 0x2024E1                       # head zero area; diag-log-ring data ends 0x202410, diag-fe 0x2024F0
R0, R1, R3, R5, R6, R7, R9 = 0, 1, 3, 5, 6, 7, 9

assert cur(0x238FA5, 3).hex() == '1c21d4'                                 # mailbox_query prologue
for a, h in LOADS.items():
    assert cur(a, 4).hex() == h, (hex(a), cur(a, 4).hex())
    nxt = A.decode(d, a + 4 - 0x200000, a + 4)
    assert 'sh' in nxt['mnem'] or nxt['ops'] == 'r7,0x45', (hex(a), nxt)   # the counter store follows
assert cur(0x239020, 9).hex() == '0d212a1c212c852988', cur(0x239020, 9).hex()  # lwz r9 ; addi r1 ; jr r9 ; (next func)
assert cur(0x240CA9, 4).hex() == 'e8e651c9'                               # 1 ms ISR counts 0x4551C8 down to 0
assert cur(CAVE - 0x0C, 0x0C + 0xE0) == b'\0' * (0x0C + 0xE0)
assert cur(FLAG, 0x10) == b'\0' * 0x10

mh = lambda r, v: ('bg.movhi', {'D': r, 'U': v})
prog = [
 'fs_t:',                                                  # -> r6 = r7 = wait budget of this phase (ms)
 mh(R7, 0x20), ('bg.lbz', {'?': R7, 'A': R7, '!': FLAG & 0xFFFF}),
 ('bg.ori', {'D': R6, 'A': R0, 't': 10000}),
 ('bg.beqi', {'A': R7, 'I': 0, ';': 'fs_t1'}),
 ('bg.ori', {'D': R6, 'A': R0, 't': SHORT}),
 'fs_t1:',
 ('bn.or', {'D': R7, 'A': R6, 'B': R0}),
 ('bt.jr', {'A': R9}),

 'fs_x:',                                                  # mailbox_query exit (r9 restored, r3 = result)
 ('bn.addi', {'D': R1, 'A': R1, 'O': 0x2C}),
 mh(R7, 0x45), ('bg.lhz', {'D': R6, 'A': R7, 'X': 0x51C8}),   # remaining budget, 0 = a phase ran out
 mh(R7, 0x20),
 ('bg.beqi', {'A': R6, 'I': 0, ';': 'fs_bad'}),
 ('bg.sb', {'Y': FLAG & 0xFFFF, 'A': R7, 'B': R0}),        # completed: normal waits
 ('bt.jr', {'A': R9}),
 'fs_bad:',
 ('bt.movi', {'D': R6, 'I': 1}), ('bg.sb', {'Y': FLAG & 0xFFFF, 'A': R7, 'B': R6}),
 ('bg.lbz', {'?': R6, 'A': R7, '!': CNT & 0xFFFF}),
 ('bg.ori', {'D': R5, 'A': R0, 't': 255}), ('bg.beq', {'A': R6, 'B': R5, ';': 'fs_r'}),   # count stops at 255
 ('bn.addi', {'D': R6, 'A': R6, 'O': 1}), ('bg.sb', {'Y': CNT & 0xFFFF, 'A': R7, 'B': R6}),
 'fs_r:',
 ('bt.jr', {'A': R9}),
]
code, L = S.assemble(prog, CAVE)
assert CAVE + len(code) <= 0x201300, hex(CAVE + len(code))
for a, b, x in A.disasm(code, CAVE, CAVE + len(code), CAVE):
    lab = [k for k, v in L.items() if v == a]
    print(('%-8s' % (lab[0] + ':' if lab else '')) + '%08x: %-12s %-9s %s' % (a, b.hex(' '), x['mnem'], x['ops']))

edits = [{'addr': '0x%06X' % CAVE, 'old': '00' * len(code), 'new': code.hex(),
          'asm': 'fs_t / fs_x (image head zero area 0x201220): wait budget per phase; flag 0x2024E0 and count 0x2024E1'}]
for a in LOADS:
    b = S.encode('bg.jal', {'/': L['fs_t']}, a)
    print('%06x: %s -> %s' % (a, cur(a, 4).hex(), b.hex()))
    edits.append({'addr': '0x%06X' % a, 'old': cur(a, 4).hex(), 'new': b.hex(),
                  'asm': 'mailbox_query: addi r%d,r0,10000 -> jal fs_t' % (6 if a == 0x239091 else 7)})
b = S.encode('bg.j', {'/': L['fs_x']}, EXIT)
print('%06x: %s -> %s' % (EXIT, cur(EXIT, 4).hex(), b.hex()))
edits.append({'addr': '0x%06X' % EXIT, 'old': cur(EXIT, 4).hex(), 'new': b.hex(),
              'asm': 'mailbox_query end: addi r1,r1,0x2c; jr r9 -> j fs_x'})

patch = {
 'name': 'fe-failsafe',
 'summary': ('After a front-end mailbox transaction has timed out (10 s), the next ones wait at most %d ms per phase '
             'until one completes again: keys and OSD keep working while the front-end does not answer; '
             'RAM 0x2024E0 = 1 while active, 0x2024E1 = number of timed-out transactions' % SHORT),
 'status': 'untested',
 'edits': edits,
 'notes': 'See the docstring of tools/patches_src_fe_failsafe.py. Generated by tools/patches_src_fe_failsafe.py.',
}
out = os.environ.get('OUT', 'fe-failsafe.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
