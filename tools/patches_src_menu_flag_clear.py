#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Source of patches/menu-flag-clear.json. Run in an unpacked work dir (RT=runtime_0x200000.bin).

Stock bug: the "quick input menu open" flag 0x453C70 bit 16 stays set when the
quick input menu is left by a key, and then blocks "No signal" (and with it the
standby countdown) for the rest of the run.

- key_process sets bit 16 when it opens the quick input menu (OSD state 8 at
  0x257E34, state 0x1A at 0x257E93) while the picture is shown.
- While it is set, the automatic scan's no-signal branch (sub_25FE39,
  0x2600DF) returns without calling sub_26A809, so "No signal" is never
  entered (docs/firmware-map.md section 47).
- It is cleared only at the menu-timer end while the menu is still open
  (sub_258E5D, 0x2590B0: states 8/9/0x1A, which also runs the vendor retry
  selection and sets state 6) and by power_soft_off.
- Leaving the menu by a key (key_process sets state 6, e.g. 0x257682) does not
  clear it.

Observed 2026-10-09 (diag-log-ring): quick input menu at 45.13 s (0x453C72 ->
0x01), closed by a key at 45.64 s (state 6), bit never cleared; the laptop
slept at 1449 s, DP reached its no-signal decision at 1452 s, but no
"No signal" and no standby for the remaining 35 minutes (black screen,
backlight on).

Patch: main loop, every pass (hook on 'jal sub_20BD37' at 0x262128, which takes
no arguments): if the OSD state (0x457854) is 6 (no menu, picture or idle) and
bit 16 is set, clear bit 16. In states 8/9/0x1A (menu open) nothing changes,
so the vendor's menu-timer path and its retry stay as they are. The
read-modify-write of 0x453C70 runs with interrupts masked (SR IEE/TEE), as
diag-poke's reads do, so a bit set by an interrupt in between is not lost.

v2 (2026-10-10): the same task also ends a stuck link-event pause
(docs/firmware-map.md section 59). 0x453C70 bit 13 stops the port monitor
sub_23B068 (no detection, no scan, no "No signal", no standby). The OSD
timer-end handler sets it together with OSD state 0x0D (0x258C80) after a
DP link event during "No signal"; state 0x0D runs a vendor sequence whose
last step (0x265F36), or a timer end still in state 0x0D (0x258C18), clears it
with sub_265EAE and restarts detection. If the state leaves 0x0D first (a key,
or a timer end with the standby gate's bit 3 set, 0x258AD8 -> state 6), nothing
clears it. Patch: bit 13 set while the OSD state is not 0x0D -> sub_265EAE and
the current port's restart bit (+0x1C bit 0), as the vendor does at 0x258C18;
RAM 0x2024EB counts these recoveries (diag-poke). The vendor sets the state
before the flag (0x258C86, 0x258C9D), so the task never sees the flag set
before state 0x0D.

Code in the image head zero area 0x202900 (after diag-osd's code, before its
tables at 0x202A00; v1 was at 0x201E00).
"""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeon'))
import aeondis as A, aeonasm as S

d = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
def cur(a, n): return d[a - 0x200000:a - 0x200000 + n]

SITE, FN = 0x262128, 0x20BD37            # main loop: jal sub_20BD37 (no arguments, result unused)
CAVE, CAVE_END = 0x202900, 0x202A00
CLEAR13 = 0x265EAE                       # vendor: clear bit 13, path re-enable (sub_23EC38)
RECOV = 0x2024EB                         # recoveries (scan-active-first uses 0x2024EA)
R0, R1, R5, R6, R7, R8, R9 = 0, 1, 5, 6, 7, 8, 9

assert A.decode(d, SITE - 0x200000, SITE)['target'] == FN
assert A.decode(d, 0x262124 - 0x200000, 0x262124)['target'] == 0x245EF3         # main loop order
assert cur(FN, 8).hex() == 'c0e008a1f0c740e7'                                     # movhi r7,0x45; lbz r6,0x40e7(r7): no argument use
assert cur(0x257E2B, 12).hex() == 'ecec3c72948144e725ecec3c70'[:24]               # key_process: bit 16 set (state 8)
assert cur(0x2590A1, 16).hex() == 'ecea3c72c09fffc1c884ffff44e724ec'              # menu-timer end: bit 16 cleared
assert cur(CAVE, CAVE_END - CAVE) == bytes(CAVE_END - CAVE) and cur(RECOV, 1) == b'\0'
assert cur(0x258C80, 4).hex() == 'c8e42000' and cur(0x258C84, 2).hex() == '98cd'   # ori r7,r4,0x2000 ; movi r6,0xd
assert A.decode(d, 0x258C18 - 0x200000, 0x258C18)['target'] == CLEAR13
assert A.decode(d, 0x265F36 - 0x200000, 0x265F36)['target'] == CLEAR13
assert cur(CLEAR13 + 0x10, 4).hex() == 'fca0dfff'                                  # addi r5,r0,-0x2001
assert A.decode(d, 0x23B096 - 0x200000, 0x23B096)['ops'] == 'r7,0x45'             # port monitor: bit 13 test follows
ops = [A.decode(d, a - 0x200000, a)['ops'] for a in (0x258C1C, 0x258C20, 0x258C23, 0x258C34, 0x258C37, 0x258C3A)]
assert ops == ['r7,0x48', 'r6,r0,0xb0', 'r7,-0x50b(r7)', 'r23,0x1c(r6)', 'r7,r23,0x1', '0x1c(r6),r7'], ops   # vendor: restart bit of 0x47FAF5's port

mh = lambda rd, v: ('bg.movhi', {'D': rd, 'U': v})
ori = lambda rd, ra, v: ('bg.ori', {'D': rd, 'A': ra, 't': v})
andi = lambda rd, ra, v: ('bg.andi', {'D': rd, 'A': ra, 't': v})
prog = [
 'mf_task:',
 mh(R7, 0x45), ('bg.lbz', {'?': R6, 'A': R7, '!': 0x7854}),          # OSD state
 ('bg.bnei', {'A': R6, 'I': 6, ';': 'mf_b13'}),
 ('bg.lwz', {'D': R6, 'A': R7, 'W': 0x3C70}),
 mh(R5, 0x1), ('bn.and', {'D': R5, 'A': R6, 'B': R5}),
 ('bg.beqi', {'A': R5, 'I': 0, ';': 'mf_b13'}),                       # bit 16 clear: nothing to do
 ori(R5, R0, 0x11), ('bg.mfspr', {'D': R8, 'A': R5, '|': 0}),         # r8 = SR
 ('bt.movi', {'D': R6, 'I': -7}), ('bn.and', {'D': R6, 'A': R8, 'B': R6}),
 ('bg.mtspr', {'A': R5, 'B': R6, '|': 0}),                            # interrupts off
 ('bg.lwz', {'D': R6, 'A': R7, 'W': 0x3C70}),
 mh(R5, 0xFFFE), ori(R5, R5, 0xFFFF), ('bn.and', {'D': R6, 'A': R6, 'B': R5}),
 ('bg.sw', {'W': 0x3C70, 'A': R7, 'B': R6}),                          # bit 16 cleared
 ori(R5, R0, 0x11), ('bg.mtspr', {'A': R5, 'B': R8, '|': 0}),         # SR restored
 'mf_b13:',                                                           # stuck link-event pause (bit 13)
 mh(R7, 0x45), ('bg.lwz', {'D': R6, 'A': R7, 'W': 0x3C70}), andi(R5, R6, 0x2000),
 ('bg.beqi', {'A': R5, 'I': 0, ';': 'mf_x'}),
 ('bg.lbz', {'?': R6, 'A': R7, '!': 0x7854}),
 ('bg.beqi', {'A': R6, 'I': 0x0D, ';': 'mf_x'}),                      # vendor sequence still running
 ('bn.addi', {'D': R1, 'A': R1, 'O': -4}), ('bn.sw', {':': 0, 'A': R1, 'B': R9}),
 ('bg.jal', {'/': CLEAR13}),                                          # clear bit 13, re-enable the path
 mh(R7, 0x48), ('bg.lbz', {'?': R7, 'A': R7, '!': -0x50B}),           # current port (0x47FAF5)
 ori(R6, R0, 0xB0), ('bn.mul', {'D': R6, 'A': R6, 'B': R7}),
 mh(R7, 0x3B), ('bg.addi', {'D': R7, 'A': R7, 'Y': 0x4950}), ('bn.add', {'D': R6, 'A': R6, 'B': R7}),
 ('bg.lbz', {'?': R5, 'A': R6, '!': 0x1C}), ori(R5, R5, 1), ('bg.sb', {'Y': 0x1C, 'A': R6, 'B': R5}),   # restart detection
 mh(R7, RECOV >> 16), ('bg.lbz', {'?': R5, 'A': R7, '!': RECOV & 0xFFFF}),
 ('bn.addi', {'D': R5, 'A': R5, 'O': 1}), ('bg.sb', {'Y': RECOV & 0xFFFF, 'A': R7, 'B': R5}),
 ('bn.lwz', {'D': R9, 'A': R1, ':': 0}), ('bn.addi', {'D': R1, 'A': R1, 'O': 4}),
 'mf_x:',
 ('bg.j', {'/': FN}),
]
code, L = S.assemble(prog, CAVE)
assert CAVE + len(code) <= CAVE_END, hex(CAVE + len(code))
for a, b, x in A.disasm(code, CAVE, CAVE + len(code), CAVE):
    lab = [k for k, v in L.items() if v == a]
    print(('%-9s' % (lab[0] + ':' if lab else '')) + '%08x: %-12s %-9s %s' % (a, b.hex(' '), x['mnem'], x['ops']))
hook = S.encode('bg.jal', {'/': L['mf_task']}, SITE)
edits = [{'addr': '0x%06X' % CAVE, 'old': '00' * len(code), 'new': code.hex(),
          'asm': 'mf_task (image head zero area 0x202900): OSD state 6 and 0x453C70 bit 16 set -> clear bit 16; bit 13 set outside OSD state 0x0D -> sub_265EAE + restart detection; RAM 0x2024EB recoveries'},
         {'addr': '0x%06X' % SITE, 'old': cur(SITE, 4).hex(), 'new': hook.hex(),
          'asm': 'main loop: jal sub_20BD37 -> jal mf_task'}]
patch = {
 'name': 'menu-flag-clear',
 'summary': ('Clears the "quick input menu open" flag (0x453C70 bit 16) once the OSD is back in state 6; stock leaves '
             'it set when the menu is closed by a key, which blocks "No signal" and the standby countdown. v2: also ends '
             'a link-event pause (bit 13) left set outside its OSD state 0x0D, which stops all input detection'),
 'status': 'v2 untested (emulator-checked; v1 untested)',
 'edits': edits,
 'notes': 'See the docstring of tools/patches_src_menu_flag_clear.py. Generated by tools/patches_src_menu_flag_clear.py.',
}
out = os.environ.get('OUT', 'menu-flag-clear.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
