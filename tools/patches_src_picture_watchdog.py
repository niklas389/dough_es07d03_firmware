#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Source of patches/picture-watchdog.json. Run in an unpacked work dir (RT=runtime_0x200000.bin).

Picture watchdog: when the selected input keeps restarting its signal
detection without ever accepting a signal, the input selection is repeated
(as the vendor does at menu close), and if that does not help, the input gets
one hot-plug pulse (the stock wake behaviour).

Finding (diag-log-ring, 2026-10-08, input fixed to DP, after a start): black
screen, no "No signal", for ~45 min. Port 1 (DP) cycled: no-signal decision
(state 2), 0.2-7 s later a short signal (status 0x03 for 2-10 ms, then 0x0F)
that made the port monitor restart detection (sub_23B068 -> sub_23E64A(port,
1) at 0x23B367, flags bit 0 'change'), 4-6 s later the next no-signal
decision, ... The port never reached state 3 (signal stable for +0x18
passes, sub_23E64A(port, 3) at 0x23B33B). Every restart also restarted the
input path's detection round, so "No signal" was never entered and the
standby countdown never ran. Keys and DDC/CI worked. Opening and closing the
menu ran the vendor's retry (sub_258E5D -> sub_2678D9(0, DP)): front-end port
disable, 0x60 sub 6, HPD high, then the attach (HPD high, 0x60 sub 2, enable);
DP was accepted 0.7 s later and the picture came. Cause of the unstable
front-end output not known (docs/firmware-map.md section 40).

Patch (code in the image head zero area 0x201800; state at RAM 0x2024D0):
- 0x23B2E9 'jal sub_23E64A' (no-signal decision) -> pw_ns: for the main
  path's port (path 0 record +0x28, 0x4821D4) set 0x2024D4.
- 0x23B367 'jal sub_23E64A' (restart) -> pw_rst: for the main path's port,
  count the restart (0x2024D1) only if a no-signal decision came since the
  last counted one (0x2024D4, then cleared); a different port resets the
  counters first (0x2024D3 = port). v2 (2026-10-08): v1 counted every
  restart, and the restarts of a normal signal acquisition (several within
  ~1 s after an attach) triggered recovery 1 one second after a USB-C wake;
  the black-screen pattern has a no-signal decision between restarts.
- 0x23B33B 'jal sub_23E64A' (signal accepted) -> pw_acc: count accepts of any
  port (0x2024D0, used by scan-active-first); for the main path's port clear
  the restart and recovery counters.
- 0x26214F 'jal sub_260ACF' (main loop, every pass, same place as the OSD task
  that runs the vendor retry) -> pw_task: when the restart count reaches
  RESTARTS (3) and fewer than 2 recoveries were made since the last accept,
  and the monitor is not in power-save (0x4551AC bit 0; in power-save the
  restart count is cleared):
  recovery 1: sub_2678D9(0, settings +0x4F), the start-up selection call;
  recovery 2 (PULSE=1): sub_23EE83(port, 650), the vendor hot-plug pulse
  (the source sees an unplug of ~0.7 s), then the same selection.
  Afterwards nothing more until a signal is accepted on the main path's port
  or another port becomes the main path's port.
A restart after a failed mode set (sub_241D2B, after an accept) is not
counted: the accept resets the counters, and a new selection would not help
an unsupported timing.
"""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeon'))
import aeondis as A, aeonasm as S

d = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
def cur(a, n): return d[a - 0x200000:a - 0x200000 + n]

RESTARTS = int(os.environ.get('RESTARTS', '3'))
PULSE = int(os.environ.get('PULSE', '1'))
assert 2 <= RESTARTS <= 10 and PULSE in (0, 1)
MAXREC = 2 if PULSE else 1
RST_SITE, ACC_SITE, LOOP_SITE, NS_SITE = 0x23B367, 0x23B33B, 0x26214F, 0x23B2E9
PSTATE, LOOP_FN, SELECT, HPD = 0x23E64A, 0x260ACF, 0x2678D9, 0x23EE83
CAVE = 0x201800                       # head zero area: after diag-log-ring code (ends 0x2016C8), before gate-all-dp v3 (0x201900)
ACC, RST, REC, PORT, NSD = 0x2024D0, 0x2024D1, 0x2024D2, 0x2024D3, 0x2024D4
R0, R1, R3, R4, R5, R6, R7, R9 = 0, 1, 3, 4, 5, 6, 7, 9

assert A.decode(d, RST_SITE - 0x200000, RST_SITE)['target'] == PSTATE and cur(RST_SITE - 2, 2).hex() == '9881'   # movi r4,1
assert A.decode(d, NS_SITE - 0x200000, NS_SITE)['target'] == PSTATE and cur(NS_SITE - 2, 2).hex() == '9882'     # movi r4,2
assert A.decode(d, ACC_SITE - 0x200000, ACC_SITE)['target'] == PSTATE and cur(ACC_SITE - 2, 2).hex() == '9883'   # movi r4,3
assert A.decode(d, LOOP_SITE - 0x200000, LOOP_SITE)['target'] == LOOP_FN
assert A.decode(d, 0x26214B - 0x200000, 0x26214B)['target'] == 0x261496 and cur(LOOP_SITE + 4, 2).hex() == '93b2'  # j loop head
assert A.decode(d, 0x2684CA - 0x200000, 0x2684CA)['target'] == SELECT and cur(0x2684C1, 9).hex() == 'ecec5f3a986010874f'
assert cur(0x23E5FF, 8).hex() == 'c0e00901fcc721d4'                       # path records: port of path 0 at 0x4821D4
assert A.decode(d, 0x260179 - 0x200000, 0x260179)['target'] == HPD and cur(0x260175, 4).hex() == 'c8800258'  # sub_23EE83(port, 600)
assert cur(PSTATE, 3).hex() == '50e0b0'
assert cur(CAVE, 0x100) == b'\0' * 0x100 and cur(ACC, 0x10) == b'\0' * 0x10

mh = lambda r, v: ('bg.movhi', {'D': r, 'U': v})
lbz = lambda rd, a, ra: ('bg.lbz', {'?': rd, 'A': ra, '!': a & 0xFFFF})
sb = lambda a, ra, rb: ('bg.sb', {'Y': a & 0xFFFF, 'A': ra, 'B': rb})
prog = [
 # ---- restart of a port's detection (r3 = port, r4 = 1) ----
 'pw_rst:',
 mh(R7, 0x48), ('bg.lbz', {'?': R6, 'A': R7, '!': 0x21D4}),          # main path's port
 ('bg.bne', {'A': R3, 'B': R6, ';': 'pw_rx'}),
 mh(R7, 0x20), lbz(R5, PORT, R7),
 ('bg.beq', {'A': R5, 'B': R3, ';': 'pw_r1'}),
 sb(PORT, R7, R3), sb(RST, R7, R0), sb(REC, R7, R0), sb(NSD, R7, R0),   # another port: start over
 'pw_r1:',
 lbz(R5, NSD, R7), ('bg.beqi', {'A': R5, 'I': 0, ';': 'pw_rx'}),     # count only a restart after a no-signal decision
 sb(NSD, R7, R0),
 lbz(R5, RST, R7), ('bg.bgtui', {'A': R5, 'I': 14, ';': 'pw_rx'}),   # stops counting at 15
 ('bn.addi', {'D': R5, 'A': R5, 'O': 1}), sb(RST, R7, R5),
 'pw_rx:',
 ('bg.j', {'/': PSTATE}),

 # ---- no-signal decision (r3 = port, r4 = 2) ----
 'pw_ns:',
 mh(R7, 0x48), ('bg.lbz', {'?': R6, 'A': R7, '!': 0x21D4}),
 ('bg.bne', {'A': R3, 'B': R6, ';': 'pw_nx'}),
 mh(R7, 0x20), ('bt.movi', {'D': R6, 'I': 1}), sb(NSD, R7, R6),
 'pw_nx:',
 ('bg.j', {'/': PSTATE}),

 # ---- signal accepted (r3 = port, r4 = 3) ----
 'pw_acc:',
 mh(R7, 0x20), lbz(R5, ACC, R7), ('bn.addi', {'D': R5, 'A': R5, 'O': 1}), sb(ACC, R7, R5),   # any port (wraps)
 mh(R6, 0x48), ('bg.lbz', {'?': R6, 'A': R6, '!': 0x21D4}),
 ('bg.bne', {'A': R3, 'B': R6, ';': 'pw_ax'}),
 sb(RST, R7, R0), sb(REC, R7, R0), sb(NSD, R7, R0),
 'pw_ax:',
 ('bg.j', {'/': PSTATE}),

 # ---- main loop, every pass (r3-r8 free) ----
 'pw_task:',
 mh(R7, 0x20), lbz(R6, RST, R7),
 ('bg.bleui', {'A': R6, 'I': RESTARTS - 1, ';': 'pw_tx'}),
 lbz(R5, REC, R7),
 ('bg.bgtui', {'A': R5, 'I': MAXREC - 1, ';': 'pw_tx'}),
 mh(R6, 0x45), ('bg.lhz', {'D': R6, 'A': R6, 'X': 0x51AC}), ('bn.andi', {'D': R6, 'A': R6, 'N': 1}),
 ('bg.bnei', {'A': R6, 'I': 0, ';': 'pw_ps'}),                         # power-save: leave it alone
 ('bn.addi', {'D': R5, 'A': R5, 'O': 1}), sb(REC, R7, R5), sb(RST, R7, R0),
 ('bn.addi', {'D': R1, 'A': R1, 'O': -4}), ('bn.sw', {':': 0, 'A': R1, 'B': R9}),
 *([('bg.bnei', {'A': R5, 'I': 2, ';': 'pw_sel'}),                    # recovery 2: hot-plug pulse first
    mh(R6, 0x48), ('bg.lbz', {'?': R3, 'A': R6, '!': 0x21D4}),
    ('bg.ori', {'D': R4, 'A': R0, 't': 650}), ('bg.jal', {'/': HPD}),
    'pw_sel:'] if PULSE else []),
 mh(R7, 0x3B), ('bg.lwz', {'D': R7, 'A': R7, 'W': 0x5F38}),
 ('bt.movi', {'D': R3, 'I': 0}), ('bn.lbz', {'?': R4, 'A': R7, 'z': 0x4F}),
 ('bg.jal', {'/': SELECT}),                                            # as the start-up selection
 ('bn.lwz', {'D': R9, 'A': R1, ':': 0}), ('bn.addi', {'D': R1, 'A': R1, 'O': 4}),
 'pw_tx:',
 ('bg.j', {'/': LOOP_FN}),
 'pw_ps:',
 sb(RST, R7, R0),                                                      # nothing carried over to the wake
 ('bg.j', {'/': LOOP_FN}),
]
code, L = S.assemble(prog, CAVE)
assert CAVE + len(code) <= 0x201900, hex(CAVE + len(code))   # gate-all-dp v3 from 0x201900
for a, b, x in A.disasm(code, CAVE, CAVE + len(code), CAVE):
    lab = [k for k, v in L.items() if v == a]
    print(('%-9s' % (lab[0] + ':' if lab else '')) + '%08x: %-12s %-9s %s' % (a, b.hex(' '), x['mnem'], x['ops']))
hooks = [(RST_SITE, 'pw_rst', 'sub_23B068 restart: jal sub_23E64A(port, 1) -> jal pw_rst'),
         (NS_SITE, 'pw_ns', 'sub_23B068 no-signal decision: jal sub_23E64A(port, 2) -> jal pw_ns'),
         (ACC_SITE, 'pw_acc', 'sub_23B068 signal accepted: jal sub_23E64A(port, 3) -> jal pw_acc'),
         (LOOP_SITE, 'pw_task', 'main loop: jal sub_260ACF -> jal pw_task')]
edits = [{'addr': '0x%06X' % CAVE, 'old': '00' * len(code), 'new': code.hex(),
          'asm': 'pw_rst / pw_acc / pw_task (image head zero area 0x201800); state RAM 0x2024D0-D4'}]
for a, lab, txt in hooks:
    b = S.encode('bg.jal', {'/': L[lab]}, a)
    print('%06x: %s -> %s' % (a, cur(a, 4).hex(), b.hex()))
    edits.append({'addr': '0x%06X' % a, 'old': cur(a, 4).hex(), 'new': b.hex(), 'asm': txt})

patch = {
 'name': 'picture-watchdog',
 'summary': ('When the selected input restarts its detection %d times without ever accepting a signal (black screen '
             'without "No signal"), repeat the input selection as the vendor does at menu close%s; '
             'RAM 0x2024D1 restarts, 0x2024D2 recoveries' %
             (RESTARTS, '; if that does not help, one hot-plug pulse (stock wake behaviour) and the selection again'
              if PULSE else '')),
 'status': 'v1 fired falsely after a normal attach (2026-10-08, harmless); v2 untested',
 'edits': edits,
 'notes': 'See the docstring of tools/patches_src_picture_watchdog.py. Generated by tools/patches_src_picture_watchdog.py.',
}
out = os.environ.get('OUT', 'picture-watchdog.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
