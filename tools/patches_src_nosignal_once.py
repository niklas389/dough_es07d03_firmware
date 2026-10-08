#!/usr/bin/env python3
"""Source of patches/nosignal-once.json. Run in an unpacked work dir (RT=runtime_0x200000.bin).

v3: "No signal" is not entered again while it is already the OSD state AND its
standby countdown is still running (or standby is already requested / the
monitor is in link-held standby), so the countdown is not restarted by the
input path's repeated detection rounds. When the countdown was cleared in the
meantime, "No signal" is entered again as stock, which reloads it.

v3 finding (diag-log-ring, 2026-10-08, automatic input): every detection
restart of a port (sub_23B068 -> sub_23E64A(port, 1) at 0x23B367, tail call
sub_23AB33) clears the power-save request bit (0x4551AC bit 1) and the
countdown cnt (0x4551A6 = 0, 0x23AB91). Stock relies on the next "no signal"
decision re-entering state 4 to load it again. v2 skipped that re-entry
whenever the OSD state was already 4, so after a restart during "No signal"
(an attach by the scan, or gate-all-dp's routing) the countdown stayed 0:
black screen with the panel on, no standby, no 5 s routing check, for as long
as nothing else happened (owner's runs: 625 s, 354 s and more).

Finding (diag-log-ring, 2026-10-08, automatic input, DP disabled, USB-C
unplugged): "No signal" (OSD state-4 entry, caller 0x2575C6) every 8.04-8.05 s
for minutes, no port state change, no standby gate query; LED red
(pre-standby). The OSD state stayed 4 throughout (no change of 0x457854 after
the first entry).

v1 (port monitor, 0x23B2E9) had no effect: after its first no-signal decision
the port monitor sub_23B068 returns early anyway (port flags +0x1C bit 1,
0x23B266), so the decision is not repeated there (docs/firmware-map.md 34).

Source of the repeat: the input-path state machine sub_22F2C7. When a path's
detection round ends while its port shows no signal (+0x20 & 0x2C), it calls
sub_26A809 (0x22F734) and sets the path back to detection (path +4 = 2); the
round repeats every ~8 s. sub_26A809 picks the OSD state from the signal
status; for "no signal" it stores state 4 (0x26A90A), then (0x26A866) clears
the OSD timer, sets the countdown 0x4551A6 to 0 and runs the state change
(sub_257493 event 0x1E), whose state-4 entry handler sets the countdown again
(standby-timeout: 30 s). Every round therefore restarts the countdown, which
never reaches 0: no power-save request, no deep standby. Same code in stock
(countdown 255 s).

Patch: the "state 4" store in sub_26A809 (0x26A90A: movhi r12,0x45; movi r7,4;
sb 0x7854(r12),r7; j 0x26A840) goes to a stub that, when the OSD state is
already 4, skips the store and the state change and continues at 0x26A895
(clears 0x453C70 bit 19 and returns, as the normal path does after the state
change). Any other previous state (normal picture, menu, logo) enters
"No signal" as before, with a fresh countdown. Side effect: with automatic
input, the scan moving to the next port while "No signal" is shown no longer
restarts the countdown either.
"""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeon'))
import aeondis as A, aeonasm as S

d = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
def cur(a, n): return d[a - 0x200000:a - 0x200000 + n]

SITE = 0x26A90A                      # sub_26A809: movhi r12,0x45; movi r7,4; sb 0x7854(r12),r7; j 0x26A840
CONT, SKIP = 0x26A840, 0x26A895
CAVE = 0x203B80                      # linker padding freed by gate-all-dp v4 (0x203B78-0x203BFF); v2 used 0x2039B0
R7, R12 = 7, 12

assert cur(SITE, 10).hex() == 'c18008a198e4f8ec7854'
assert A.decode(d, SITE + 10 - 0x200000, SITE + 10)['target'] == CONT
assert A.decode(d, 0x26A891 - 0x200000, 0x26A891)['target'] == 0x257493     # state change (event 0x1E)
assert A.decode(d, SKIP - 0x200000, SKIP)['ops'] == 'r7,0x3c70(r11)'         # lwz r7,0x3c70(r11)
assert A.decode(d, 0x26A81B - 0x200000, 0x26A81B)['ops'] == 'r11,0x45'       # r11 = 0x45xxxx base
assert cur(0x23AB8D, 8).hex() == 'c0e008a1f80751a6'                          # restart path: cnt = 0 (0x23AB91)

prog = [
 'ns4:',
 ('bg.movhi', {'D': R12, 'U': 0x45}),
 ('bg.lbz', {'?': R7, 'A': R12, '!': 0x7854}),            # current OSD state
 ('bg.bnei', {'A': R7, 'I': 4, ';': 'ns4_in'}),           # not "No signal" yet: enter as stock
 ('bg.lbz', {'?': R7, 'A': R12, '!': 0x51A6}),            # countdown still running: no restart
 ('bg.bnei', {'A': R7, 'I': 0, ';': 'ns4_skip'}),
 ('bg.lbz', {'?': R7, 'A': R12, '!': 0x51CC}),            # link-held standby (rws): stay there
 ('bg.bnei', {'A': R7, 'I': 0, ';': 'ns4_skip'}),
 ('bg.lhz', {'D': R7, 'A': R12, 'X': 0x51AC}), ('bn.andi', {'D': R7, 'A': R7, 'N': 2}),
 ('bg.bnei', {'A': R7, 'I': 0, ';': 'ns4_skip'}),         # power-save already requested
 'ns4_in:',                                               # (countdown cleared by a restart: enter again, reloads it)
 ('bt.movi', {'D': R7, 'I': 4}),
 ('bg.sb', {'Y': 0x7854, 'A': R12, 'B': R7}),
 ('bg.j', {'/': CONT}),
 'ns4_skip:',
 ('bg.j', {'/': SKIP}),
]
code, L = S.assemble(prog, CAVE)
assert CAVE + len(code) <= 0x203C00, hex(CAVE + len(code))   # popup-flat from 0x203C00
assert cur(CAVE, len(code)) == b'\0' * len(code)
for a, b, x in A.disasm(code, CAVE, CAVE + len(code), CAVE):
    lab = [k for k, v in L.items() if v == a]
    print(('%-10s' % (lab[0] + ':' if lab else '')) + '%08x: %-12s %-9s %s' % (a, b.hex(' '), x['mnem'], x['ops']))
hook = S.encode('bg.j', {'/': CAVE}, SITE)
print('%06x: %s -> %s' % (SITE, cur(SITE, 4).hex(), hook.hex()))

patch = {
 'name': 'nosignal-once',
 'summary': ('v3: while "No signal" is already shown and its standby countdown runs, the input path\'s ~8 s detection '
             'rounds no longer re-enter it, so the countdown runs to standby; when a detection restart cleared the '
             'countdown, "No signal" is entered again and reloads it (v2 left it at 0: black screen, no standby)'),
 'status': ('v3 hardware-tested 2026-10-08 (automatic input, DP and laptop outputs disabled, deep standby, USB-C '
            'replugged: wake, "No signal", scan, "No signal" again, pre-standby; the stuck case of section 49 no longer '
            'occurs). v2 left the countdown at 0 after a restart during "No signal" (docs/firmware-map.md section 49)'),
 'edits': [
  {'addr': '0x%06X' % CAVE, 'old': '00' * len(code), 'new': code.hex(),
   'asm': 'ns4 (linker padding 0x203B80): OSD state 4 with countdown running / power-save requested / rws -> j 0x26A895, else store 4 and j 0x26A840'},
  {'addr': '0x%06X' % SITE, 'old': cur(SITE, 4).hex(), 'new': hook.hex(),
   'asm': 'sub_26A809 "No signal" store: movhi r12,0x45 -> j ns4'},
 ],
 'notes': 'See the docstring of tools/patches_src_nosignal_once.py. Generated by tools/patches_src_nosignal_once.py.',
}
out = os.environ.get('OUT', 'nosignal-once.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
