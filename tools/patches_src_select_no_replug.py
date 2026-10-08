#!/usr/bin/env python3
"""Source of patches/select-no-replug.json and patches/attach-no-replug.json.

SUPERSEDED by tools/patches_src_switch_no_unplug.py (2026-10-08): without the
selection's HPD command the front-end does not switch to the new connector
in DisplayPort Mode "1.4 without DSC" (docs/firmware-map.md section 31).
Run in an unpacked work dir (RT=runtime_0x200000.bin).

EXPERIMENTAL. Input switches to DP / USB-C without an emulated unplug.

Findings (diag-log-ring v2, 2026-10-07, docs/firmware-map.md section 28): a
manual switch from USB-C to DP sends, besides the port disable / enable,
TWO hot-plug pulses to the newly selected connector (0x20 sub 14: (id, 0, 0)
= HPD low, then (id, 1, duration) = HPD high):

  A  sub_2678D9 (input selection: OSD, keys, start-up, DDC/CI) calls
     sub_265A25(0, settings +0x9C, duration 0). For front-end ports it sends
     0x60 sub 6 (id, +0x9C) and sub_23EE83(port, 0): low, then high ~5 ms
     later. A low phase over 2 ms is an unplug for a DP source.
  B  The port attach (sub_23F836 -> sub_2398F9 -> sub_239618), for DP-class
     entries whose +0x0E flag is set, sends sub_23EE83(port, 650), 0x60 sub 2
     (id, 1) and the configuration. The flags are set for all entries at
     every start, because settings +0xA5 = 1 on the test monitor and the
     cached mode (0x455061) is 0 after a start (section 27). B also runs on
     every automatic-scan step to a DP-class port and after a deep-standby
     wake (the replug that wake-no-replug v3 removes for DP only).

The PC then removes and re-adds the monitor; the selected DP input reported a
signal 3.1 s after the switch (USB-C: 9.6 s, second PC). Twice a second full
selection followed and repeated both pulses.

The setting handlers keep their own pulse: sub_265A25 with 600 / 650 ms
(+0x9C changed, profile restore, factory reset) and sub_26535A (650 ms, +0xCB
changed). M27P20P (same MST9U + MSB3300 combination, other front-end
firmware) sends no HPD pulse to DP-class inputs at input selection.

MODE=select (select-no-replug): part A. sub_265A25's HPD call for front-end
  ports (0x265B4C jal sub_23EE83) goes through a stub that returns without
  the pulse when the duration is 0, i.e. only for the input selection.
  0x60 sub 6 and the EDID loop stay.
MODE=attach (attach-no-replug): part B. The jal sub_23EE83 at 0x239747 in
  sub_239618's +0x0E path becomes a jump to the next instruction; 0x60 sub 2
  and the configuration stay. Risk: 0x60 sub 2 (id, 1) may change what the
  connector reports to the source (meaning unknown); without the pulse the
  source is not asked to read it again. Test separately from part A.
"""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeon'))
import aeondis as A, aeonasm as S

d = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
def cur(a, n): return d[a - 0x200000:a - 0x200000 + n]

MODE = os.environ.get('MODE', 'select')
assert MODE in ('select', 'attach')
HPD = 0x23EE83                       # sub_23EE83(port, duration): HPD routine
R0, R4, R9 = 0, 4, 9

# vendor code both parts rely on
assert cur(HPD, 2).hex() == '9c34'                             # addi r1,r1,-0xc
assert cur(0x265B48, 8).hex() == '886a888de7fb266e'            # mov r3,r10; mov r4,r13; jal sub_23EE83
assert cur(0x239743, 8).hex() == 'c880028ae400ae78'            # ori r4,r0,0x28a; jal sub_23EE83
assert cur(0x2679B5, 2).hex() == '98a0'                          # movi r5,0 (duration 0) before
assert A.decode(d, 0x2679B7 - 0x200000, 0x2679B7)['target'] == 0x265A25   # jal sub_265A25 (input selection)
assert A.decode(d, 0x265B4C - 0x200000, 0x265B4C)['target'] == HPD

edits = []
if MODE == 'select':
    CAVE = 0x203980                  # linker padding, after bl-supply-off (0x203940-0x203967) and the
                                     # archived port-nosignal-v2 stub (0x203970-0x20397B)
    prog = [
     'sel_hpd:',
     ('bg.beqi', {'A': R4, 'I': 0, ';': 'sel_skip'}),       # duration 0: input selection -> no pulse
     ('bg.j', {'/': HPD}),                                  # 600 / 650 (setting changes): as stock
     'sel_skip:',
     ('bt.jr', {'A': R9}),
    ]
    code, L = S.assemble(prog, CAVE)
    assert CAVE + len(code) <= 0x203A00                     # panel-prepower from 0x203A00
    assert cur(CAVE, len(code)) == b'\0' * len(code)
    hook = S.encode('bg.jal', {'/': CAVE}, 0x265B4C)
    edits = [
     {'addr': '0x%06X' % CAVE, 'old': '00' * len(code), 'new': code.hex(),
      'asm': 'sel_hpd (linker padding 0x203980): duration 0 -> return, else j sub_23EE83'},
     {'addr': '0x265B4C', 'old': cur(0x265B4C, 4).hex(), 'new': hook.hex(),
      'asm': 'sub_265A25 front-end path: jal sub_23EE83 -> jal sel_hpd'},
    ]
    listing = A.disasm(code, CAVE, CAVE + len(code), CAVE)
else:
    nb = S.encode('bg.j', {'/': 0x23974B}, 0x239747)
    edits = [
     {'addr': '0x239747', 'old': cur(0x239747, 4).hex(), 'new': nb.hex(),
      'asm': 'sub_239618 +0x0E path: jal sub_23EE83 (HPD 650) -> j 0x23974B (next instruction)'},
    ]
    listing = A.disasm(nb, 0x239747, 0x23974B, 0x239747)
for a, b, x in listing:
    print('%08x: %-12s %-9s %s' % (a, b.hex(' '), x['mnem'], x['ops']))
for e in edits:
    print(e['addr'], e['old'], '->', e['new'])

name = {'select': 'select-no-replug', 'attach': 'attach-no-replug'}[MODE]
patch = {
 'name': name,
 'summary': {
  'select': 'EXPERIMENTAL: input selection (menu, keys, DDC/CI) sends no HPD pulse (emulated unplug) to the selected DP / USB-C input; setting changes keep theirs',
  'attach': 'EXPERIMENTAL: the port attach of DP / USB-C (selection, automatic scan, wake) sends no 650 ms HPD pulse; 0x60 sub 2 and the configuration are sent as stock',
 }[MODE],
 'status': 'SUPERSEDED by switch-no-unplug - do not use: with DisplayPort Mode "1.4 without DSC" or 1.2 the input no longer switches (2026-10-08)',
 'conflicts': ['switch-no-unplug'],
 'edits': edits,
 'notes': ("See the docstring of tools/patches_src_select_no_replug.py and docs/firmware-map.md section 28. "
           "The two parts are independent; test select-no-replug first. Generated by tools/patches_src_select_no_replug.py."),
}
out = os.environ.get('OUT', name + '.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
