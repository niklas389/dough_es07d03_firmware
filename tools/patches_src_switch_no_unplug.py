#!/usr/bin/env python3
"""Source of patches/switch-no-unplug.json. Run in an unpacked work dir (RT=runtime_0x200000.bin).

EXPERIMENTAL. Input switches between DP and USB-C without an emulated unplug,
replacing select-no-replug / attach-no-replug (docs/firmware-map.md §28-31).

Findings:
- The input front-end feeds both scaler receivers (ports 0 and 1) with the
  same stream; that is why both ports always report a signal together. The
  actual input switch happens in the front-end.
- With DisplayPort Mode "1.4 without DSC" and select-no-replug, a switch
  sends only the disable of the old connector, 0x60 sub 6 and the enable of
  the new one, and the picture stays on DP although USB-C is selected
  (2026-10-08). The stock switch in that mode additionally sends the
  selection's HPD pulse (0x20 sub 14 (id, 0, 0), (id, 1, 0) from
  sub_265A25) - the command select-no-replug removed. So a 0x20 sub 14
  command for the new connector is what makes the front-end switch
  (inference; whether the "high" command alone is enough is what this patch
  tests).
- In DisplayPort Mode 1.4 the attach (sub_239618, +0x0E path) adds a 650 ms
  pulse and 0x60 sub 2 (id, 1); the detach (sub_23979A, +0x0E path) sends
  0x60 sub 2 (id, 0). 0x60 sub 2 is most likely the DSC capability of that
  connector: sub_26535A, the DisplayPort Mode handler, sends it with
  (+0xCB == 2) for both DP and USB-C. Withdrawing DSC from the deselected
  connector changes what that connector reports, which is why the vendor
  then pulses HPD on the next attach.

Patch:
1. sub_265A25's HPD call for front-end ports (0x265B4C): with duration 0
   (input selection, sub_2678D9) only (id, 1, 0) is sent - "HPD high", no low
   phase. Setting changes (600 / 650 ms) keep the full pulse.
2. sub_239618 +0x0E path (0x239747): the 650 ms pulse becomes (id, 1, 0).
3. sub_23979A +0x0E path (0x239855): 0x60 sub 2 (id, 0) on detach is not
   sent, so DSC stays advertised on the connector that is not selected (as
   after every mains start and DisplayPort Mode change, where sub_26535A
   sets it for both). Nothing the source reads changes at a switch.
A real DisplayPort Mode change still pulses through sub_26535A (650 ms).
Conflicts with select-no-replug and attach-no-replug (same call sites).
"""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeon'))
import aeondis as A, aeonasm as S

d = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
def cur(a, n): return d[a - 0x200000:a - 0x200000 + n]

HPD = 0x23EE83                       # sub_23EE83(port, duration)
HPD_FE = 0x239479                    # sub_239479(id, level, duration): 0x20 sub 14
CAVE = 0x203980                      # linker padding (after bl-supply-off and the archived port-nosignal-v2 stub)
R0, R3, R4, R5, R6, R7 = 0, 3, 4, 5, 6, 7

# vendor code the patch relies on
assert cur(HPD, 2).hex() == '9c34'
assert cur(HPD_FE, 2).hex() == '9c34'
assert cur(0x265B48, 8).hex() == '886a888de7fb266e'       # mov r3,r10; mov r4,r13; jal sub_23EE83
assert A.decode(d, 0x265B4C - 0x200000, 0x265B4C)['target'] == HPD
assert cur(0x239743, 8).hex() == 'c880028ae400ae78'       # ori r4,r0,0x28a; jal sub_23EE83 (r3 = entry = port)
assert cur(0x239850, 5).hex() == '106a049880'                     # lbz r3,4(r10); movi r4,0
assert A.decode(d, 0x239855 - 0x200000, 0x239855)['target'] == 0x239333   # 0x60 sub 2 wrapper
assert cur(0x2679B5, 2).hex() == '98a0'                   # input selection passes duration 0
assert A.decode(d, 0x2679B7 - 0x200000, 0x2679B7)['target'] == 0x265A25

prog = [
 'sel_hpd:',                                              # r3 = port, r4 = duration (sub_265A25)
 ('bg.beqi', {'A': R4, 'I': 0, ';': 'hi_only'}),
 ('bg.j', {'/': HPD}),                                    # setting changes: full pulse as stock
 'hi_only:',                                              # r3 = port: send (id, 1, 0) only
 ('bg.ori', {'D': R7, 'A': R0, 't': 0x18}), ('bn.mul', {'D': R7, 'A': R3, 'B': R7}),   # as the vendor code
 ('bg.movhi', {'D': R6, 'U': 0x3B}), ('bg.addi', {'D': R6, 'A': R6, 'Y': 0x4288}),
 ('bn.add', {'D': R7, 'A': R7, 'B': R6}),
 ('bn.lbz', {'?': R3, 'A': R7, 'z': 4}),                  # front-end id (table 0x3B4288 +4)
 ('bt.movi', {'D': R4, 'I': 1}), ('bt.movi', {'D': R5, 'I': 0}),
 ('bg.j', {'/': HPD_FE}),
]
code, L = S.assemble(prog, CAVE)
assert CAVE + len(code) <= 0x203A00                      # panel-prepower from 0x203A00
assert cur(CAVE, len(code)) == b'\0' * len(code)
for a, b, x in A.disasm(code, CAVE, CAVE + len(code), CAVE):
    lab = [k for k, v in L.items() if v == a]
    print(('%-9s' % (lab[0] + ':' if lab else '')) + '%08x: %-12s %-9s %s' % (a, b.hex(' '), x['mnem'], x['ops']))

e_sel = S.encode('bg.jal', {'/': L['sel_hpd']}, 0x265B4C)
e_att = S.encode('bg.jal', {'/': L['hi_only']}, 0x239747)
e_det = S.encode('bg.j', {'/': 0x239859}, 0x239855)
edits = [
 {'addr': '0x%06X' % CAVE, 'old': '00' * len(code), 'new': code.hex(),
  'asm': 'sel_hpd / hi_only (linker padding 0x203980): duration 0 -> 0x20 sub 14 (id, 1, 0) only'},
 {'addr': '0x265B4C', 'old': cur(0x265B4C, 4).hex(), 'new': e_sel.hex(),
  'asm': 'sub_265A25 front-end path: jal sub_23EE83 -> jal sel_hpd'},
 {'addr': '0x239747', 'old': cur(0x239747, 4).hex(), 'new': e_att.hex(),
  'asm': 'sub_239618 +0x0E path: jal sub_23EE83 (pulse 650) -> jal hi_only'},
 {'addr': '0x239855', 'old': cur(0x239855, 4).hex(), 'new': e_det.hex(),
  'asm': 'sub_23979A +0x0E path: jal 0x60 sub 2 (id, 0) -> j 0x239859 (DSC stays advertised)'},
]
for e in edits[1:]:
    print(e['addr'], e['old'], '->', e['new'])

patch = {
 'name': 'switch-no-unplug',
 'summary': ('EXPERIMENTAL: input switches between DP and USB-C send only "HPD high" to the new connector (the '
             "front-end's switch trigger) instead of an unplug pulse; in DisplayPort Mode 1.4 DSC stays advertised "
             'on both connectors'),
 'status': ('hardware-tested 2026-10-08: manual switches DP <-> USB-C in DisplayPort Mode "1.4 without DSC" and 1.4 '
            '(DSC): correct picture in 1-2 s, no re-plug on either PC, other monitor undisturbed; main PC re-plugged '
            'while USB-C was selected, then DP selected: works. Not yet tested: automatic input, deep-standby wake'),
 'conflicts': ['select-no-replug', 'attach-no-replug'],
 'edits': edits,
 'notes': ('See the docstring of tools/patches_src_switch_no_unplug.py and docs/firmware-map.md section 31. '
           'Generated by tools/patches_src_switch_no_unplug.py.'),
}
out = os.environ.get('OUT', 'switch-no-unplug.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
