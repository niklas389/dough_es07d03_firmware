#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Source of patches/diag-log.json. Run in an unpacked work dir (RT=runtime_0x200000.bin).

DIAGNOSTIC: timing log in RAM, read with diag-poke and tools/logread.py, to
find the critical path of a start or a deep-standby wake.

Location (since 2026-10-07): code and data are in the zero areas of the
uncompressed image head, which the boot loader copies to 0x200000 with the
rest of the head; no firmware code references them (only register offsets
with the same numeric value, added to the RIU base). So the log no longer
shares the 0x203800 linker padding with the regular patches and combines with
the whole build list (wake-no-replug, panel-prepower v2, ...).

Data (zero at every start; lost on deep standby/restart):
  0x202200 u32  ms counter, incremented by the 1 ms timer ISR (sub_240C55)
  0x202204 u32  number of events written so far
  0x202208      64 entries x 8 bytes: +0 u32 ms, +4 u32 = tag << 24 | value
                (tag = low byte of the stub's return address); the first 64
                events are kept, later ones are only counted.

Events (tools/logread.py names):
  I  0x261FF0  main init start            D  0x26208C  init done (EEPROM, scaler)
  X  0x26209C  sub_261FA8 done (input front-end set-up)
  R  0x2620D2  panel preparation returned (panel-prepower boot step)
  M  0x2620F9  main loop about to start
  P  0x22F300  port state change            value = port << 8 | state
  W  0x262105  watched byte changed (table WATCH; checked every main-loop pass)
  Q  0x238FD5  mailbox command sent         value = cmd << 16 | sub << 8 | data[0]
               (until the backlight is on, so the log is not filled later; ring: see below)
  N  sub_245919+5 panel on (pnl = 0)        F sub_245860 panel off (pnl = 1)
  B  0x2459C0  backlight on                 S sub_258AB1 OSD timer end
  E  sub_26A7C5 state 4 ("No signal")       G 0x2613A0 standby gate result

MODE=ring (patches/diag-log-ring.json): as diag-log, but the log keeps the
LAST 64 events (for loops long after the start) and also watches the current
port, the No-signal restart flags (0x453C70 bits 15/14) and the states of
ports 0 and 1, and (v3) every input selection sub_2678D9 with its caller,
and (v4) every mailbox transaction that fails (mailbox_query returns 0: the
PM51 / front-end did not take or answer it within 10 s per phase).
Since 2026-10-07 (v2) it logs mailbox commands for the whole
run (to see the hot-plug and port configuration commands of an input
switch), skips the periodic posted 0x20 sub 18 (every ~8.4 s), and carries
data[1] & 0xF in the low nibble of the command byte (all commands are 0xN0),
e.g. the level of 0x20 sub 3 / sub 14 (id, level, ...).

MODE=mb (patches/diag-log-mb.json, a separate diagnostic; same areas, so use
only one diag-log variant): no watcher; the log keeps the LAST 64 events; Q is logged at
the end of every mailbox transaction (common epilogue 0x239002) for the whole
run, value = cmd << 16 | sub << 8 | duration in ms (capped at 255); messages
posted without waiting for an answer (r8 = 0, e.g. the periodic 0x20 sub 18
from sub_20D134 every ~8 s) are not logged. Used to
see whether the transactions stay slow (~66 ms) long after a deep-standby
wake or become fast (~5 ms, as after a mains start).
"""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeon'))
import aeondis as A, aeonasm as S

d = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
def cur(a, n): return d[a - 0x200000:a - 0x200000 + n]

MODE = os.environ.get('MODE', 'timing')   # 'timing' (diag-log), 'mb' (diag-log-mb: mailbox durations, last 64 events)
                                          # or 'ring' (diag-log-ring: as timing, but the last 64 events)
MB = MODE == 'mb'
RING = MODE in ('mb', 'ring')
QALL = MODE == 'ring'                     # ring: Q for the whole run (not only until the backlight), without the
                                          # periodic 0x20 sub 18, with data[1] & 0xF in the low nibble of cmd
assert MODE in ('timing', 'mb', 'ring')
CODE = 0x201400                     # head zero area 0x201214-0x201FFF
DATA = 0x202200                     # head zero area 0x202087-0x2037FF (after the TEL key table)
N = 64
LOGT, IDX, BUF = DATA - 0x200000, DATA + 4 - 0x200000, DATA + 8 - 0x200000
QOFF = DATA + 8 + 8 * N - 0x200000  # mailbox logging off flag (set by the backlight stub)
WFLAG = QOFF + 1                    # watcher: first pass done
MBC = QOFF + 2                      # mb mode: cmd, sub of the running mailbox transaction
MBT = (QOFF + 4 + 3) & ~3           # mb mode: u32 start time of the running transaction
WATCH = [(0x3B4970, 'port 0 +0x20 status'), (0x3B4A20, 'port 1 +0x20 status'),
         (0x3B4A1C, 'port 1 +0x1C flags'), (0x457854, 'OSD state'),
         (0x203FF0, 'panel-prepower state (1 waiting, 2 ready)')]
if MODE == 'ring':
    WATCH += [(0x47FAF5, 'current port (power-save hand-off +2)'),
              (0x453C71, 'flags 0x453C70 bits 15-8 (0x80 bit 15: countdown paused, 0x40 bit 14: No-signal restart, section 11)'),
              (0x453C72, 'flags 0x453C70 bits 23-16 (0x01 bit 16: key/menu pending, blocks the scan\'s No signal, section 47)'),
              (0x3B495F, 'port 0 state'), (0x3B4A0F, 'port 1 state')]
R0, R1, R3, R4, R5, R6, R7, R8, R9, R10 = 0, 1, 3, 4, 5, 6, 7, 8, 9, 10
R11, R12, R13, R14, R17 = 11, 12, 13, 14, 17

mh = lambda rd, v: ('bg.movhi', {'D': rd, 'U': v})
lwz = lambda rd, off, ra: ('bg.lwz', {'D': rd, 'A': ra, 'W': off})
sw = lambda off, ra, rb: ('bg.sw', {'W': off, 'A': ra, 'B': rb})
lbz = lambda rd, off, ra: ('bg.lbz', {'?': rd, 'A': ra, '!': off})
sb = lambda off, ra, rb: ('bg.sb', {'Y': off, 'A': ra, 'B': rb})
nsw = lambda off, ra, rb: ('bn.sw', {':': off, 'A': ra, 'B': rb})
nlw = lambda rd, off, ra: ('bn.lwz', {'D': rd, 'A': ra, ':': off})
j = lambda t: ('bg.j', {'/': t})
jal = lambda t: ('bg.jal', {'/': t})
movi = lambda r, i: ('bt.movi', {'D': r, 'I': i})
SAVE = [('bn.addi', {'D': R1, 'A': R1, 'O': -24})] + [nsw(4 * i, R1, r) for i, r in enumerate((R3, R4, R5, R6, R7, R8))]
REST = [nlw(r, 4 * i, R1) for i, r in enumerate((R3, R4, R5, R6, R7, R8))] + [('bn.addi', {'D': R1, 'A': R1, 'O': 24})]

def program(pad):
    """pad: label -> number of 2-byte nops inserted before that stub (to make the tags unique)."""
    P = lambda lab: [('bt.nop', {})] * pad.get(lab, 0) + [lab + ':']
    return [
     # ---- log routines (r9 = stub return address = tag; preserve r3-r8, r10-r31) ----
     'log_s0:', *SAVE, nlw(R4, 24, R1), j('log_c'),          # value = word at caller's 0(r1) (saved r9)
     'log_s4:', *SAVE, nlw(R4, 28, R1), j('log_c'),          # value = word at caller's 4(r1)
     'log_r3:', *SAVE, ('bn.or', {'D': R4, 'A': R3, 'B': R0}),
     'log_c:',
     mh(R7, 0x20), lwz(R5, IDX, R7),
     *([('bn.andi', {'D': R6, 'A': R5, 'N': N - 1}), ('bn.slli', {'D': R6, 'A': R6, 'H': 3})] if RING else   # ring: last N
       [('bg.sfgtui', {'A': R5, 'Y': N - 1}), ('bg.bf', {"'": 'log_cnt'}),                               # full: count only
        ('bn.slli', {'D': R6, 'A': R5, 'H': 3})]),
     ('bn.add', {'D': R6, 'A': R6, 'B': R7}),
     lwz(R8, LOGT, R7), sw(BUF, R6, R8),
     mh(R8, 0xFF), ('bg.ori', {'D': R8, 'A': R8, 't': 0xFFFF}), ('bn.and', {'D': R4, 'A': R4, 'B': R8}),
     ('bn.slli', {'D': R8, 'A': R9, 'H': 24}), ('bn.or', {'D': R4, 'A': R4, 'B': R8}),
     sw(BUF + 4, R6, R4),
     'log_cnt:',
     ('bt.addi', {'D': R5, 'I': 1}), sw(IDX, R7, R5),
     *REST, ('bt.jr', {'A': R9}),

     # ---- 1 ms ISR: ms counter (replaces sub_240C55: addi r1,-8; sw 4(r1),r9) ----
     'isr:', ('bt.addi', {'D': R1, 'I': -8}), nsw(4, R1, R9),
     mh(R7, 0x20), lwz(R6, LOGT, R7), ('bt.addi', {'D': R6, 'I': 1}), sw(LOGT, R7, R6),
     j(0x240C5A),

     # ---- milestones ----
     *P('m_init'), jal('log_s0'), ('bg.ori', {'D': R3, 'A': R0, 't': 0x42C}), j(0x261FF4),   # ori r3,r0,0x42c
     *P('m_dev'), jal('log_s0'), jal(0x23FF28), j(0x262090),                                  # jal sub_23FF28
     *P('m_fe'), jal('log_s0'), jal(0x2411A5), j(0x2620A0),                                   # jal sub_2411A5 (after sub_261FA8)
     *P('m_prep'), jal('log_s0'), jal(0x2676B2), j(0x2620D6),                                 # jal sub_2676B2 (after the boot prep)
     *P('m_loop'), jal('log_s0'), mh(R10, 0x45), j(0x2620FD),                                 # movhi r10,0x45
     *P('m_bl'), jal('log_s4'),                                                               # backlight on; stop Q logging
     *([] if QALL else [movi(R6, 1), mh(R7, 0x20), sb(QOFF, R7, R6)]),                        # (ring: Q for the whole run)
     ('bg.ori', {'D': R3, 'A': R0, 't': 0x426}), j(0x2459C4),

     # ---- panel on / off, OSD timer, state 4, standby gate ----
     *P('h_off'), ('bt.addi', {'D': R1, 'I': -4}), nsw(0, R1, R9),
     mh(R7, 0x45), lbz(R7, 0x51A8, R7), ('bg.beqi', {'A': R7, 'I': 0, ';': 'off_go'}),
     jal('log_s0'),
     'off_go:', j(0x245865),
     *P('h_on'), nsw(0, R1, R10), mh(R10, 0x45),
     lbz(R7, 0x51A8, R10), ('bg.bnei', {'A': R7, 'I': 0, ';': 'on_go'}),
     jal('log_s4'),
     'on_go:', j(0x245925),
     *P('h_sig'), ('bt.addi', {'D': R1, 'I': -8}), nsw(4, R1, R9), jal('log_s4'), j(0x258AB6),
     *P('h_st4'), ('bt.addi', {'D': R1, 'I': -8}), nsw(4, R1, R9), jal('log_s4'), j(0x26A7CA),
     *P('h_gate'), jal(0x2612F9), jal('log_r3'), j(0x2613A4),

     # ---- ring: input selection sub_2678D9(path, input) entry (replaces addi r1,r1,-0x14; sw 0x10(r1),r9) ----
     *([*P('h_sel'), ('bn.addi', {'D': R1, 'A': R1, 'O': -0x14}), nsw(0x10, R1, R9),
        ('bn.addi', {'D': R1, 'A': R1, 'O': -4}), nsw(0, R1, R3),
        ('bn.andi', {'D': R5, 'A': R3, 'N': 0xF}), ('bn.slli', {'D': R5, 'A': R5, 'H': 20}),
        ('bn.andi', {'D': R6, 'A': R4, 'N': 0xF}), ('bn.slli', {'D': R6, 'A': R6, 'H': 16}),
        ('bn.or', {'D': R5, 'A': R5, 'B': R6}),
        ('bg.andi', {'D': R6, 'A': R9, 't': 0xFFFF}), ('bn.or', {'D': R3, 'A': R5, 'B': R6}),   # path<<20|input<<16|caller
        jal('log_r3'),
        nlw(R3, 0, R1), ('bn.addi', {'D': R1, 'A': R1, 'O': 4}), nlw(R9, 0x10, R1),
        j(0x2678DF)] if QALL else []),

     # ---- port state change in sub_22F2C7 (replaces beq r7,r6,0x22F307; sb 0(r11),r7) ----
     *P('h_port'),
     ('bg.beq', {'A': R7, 'B': R6, ';': 'port_x'}), ('bn.sb', {'z': 0, 'A': R11, 'B': R7}),
     ('bn.addi', {'D': R1, 'A': R1, 'O': -4}), nsw(0, R1, R3),
     ('bn.slli', {'D': R3, 'A': R10, 'H': 8}), ('bn.or', {'D': R3, 'A': R3, 'B': R7}),
     jal('log_r3'), nlw(R3, 0, R1), ('bn.addi', {'D': R1, 'A': R1, 'O': 4}),
     'port_x:', j(0x22F307),

     # ---- mailbox command (replaces movhi r14,0x45 at 0x238FD5; r12 cmd, r13 sub, r11 length, r17 data) ----
     *P('h_mb'),
     *([mh(R7, 0x20), sb(MBC, R7, R12), sb(MBC + 1, R7, R13),                 # mb mode: remember cmd/sub/start
        sb(QOFF, R7, 19),                                                     # and r19 = wait-for-answer flag (0: posted)
        lwz(R6, LOGT, R7), sw(MBT, R7, R6), j('mb_x')] if MB else []),
     *([mh(R7, 0x20), sb(MBC, R7, R12), sb(MBC + 1, R7, R13)] if QALL else []),   # ring: cmd/sub for h_mbf
     mh(R7, 0x20), lbz(R6, QOFF, R7), ('bg.bnei', {'A': R6, 'I': 0, ';': 'mb_x'}),
     *([('bg.ori', {'D': R6, 'A': R0, 't': 0x20}), ('bg.bne', {'A': R12, 'B': R6, ';': 'mb_go'}),   # ring: skip the
        ('bg.ori', {'D': R6, 'A': R0, 't': 18}),
        ('bg.beq', {'A': R13, 'B': R6, ';': 'mb_x'}), 'mb_go:'] if QALL else []),               # periodic 0x20 sub 18
     movi(R4, 0), ('bg.beqi', {'A': R11, 'I': 0, ';': 'mb_v'}), ('bn.lbz', {'?': R4, 'A': R17, 'z': 0}),
     'mb_v:',
     *([movi(R5, 0), ('bg.bleui', {'A': R11, 'I': 1, ';': 'mb_d1_v'}),                               # ring: data[1] & 0xF
        ('bn.lbz', {'?': R5, 'A': R17, 'z': 1}), ('bn.andi', {'D': R5, 'A': R5, 'N': 0xF}),     # in the low nibble of
        'mb_d1_v:', ('bn.or', {'D': R5, 'A': R5, 'B': R12}), ('bn.slli', {'D': R3, 'A': R5, 'H': 16})]   # cmd (cmds are 0xN0)
       if QALL else [('bn.slli', {'D': R3, 'A': R12, 'H': 16})]),
     ('bn.slli', {'D': R5, 'A': R13, 'H': 8}),
     ('bn.or', {'D': R3, 'A': R3, 'B': R5}), ('bn.or', {'D': R3, 'A': R3, 'B': R4}),
     jal('log_r3'),
     'mb_x:', mh(R14, 0x45), j(0x238FD9),
     # ---- mb mode: mailbox_query epilogue 0x239002 (replaces lwz r19,0(r1); lwz r18,4(r1); r3 = result, r4-r8 free) ----
     *([*P('h_mbx'), nlw(19, 0, R1), nlw(18, 4, R1),
     mh(R7, 0x20), lbz(R6, QOFF, R7), ('bg.beqi', {'A': R6, 'I': 0, ';': 'mbx_x'}),   # posted (no answer awaited): not logged
     lwz(R6, LOGT, R7), lwz(R5, MBT, R7), ('bn.sub', {'D': R6, 'A': R6, 'B': R5}),
     ('bg.sfgtui', {'A': R6, 'Y': 255}), ('bg.bnf', {"'": 'mbx_v'}), ('bg.ori', {'D': R6, 'A': R0, 't': 255}),
     'mbx_v:',
     lbz(R5, MBC, R7), ('bn.slli', {'D': R5, 'A': R5, 'H': 16}), ('bn.or', {'D': R6, 'A': R6, 'B': R5}),
     lbz(R5, MBC + 1, R7), ('bn.slli', {'D': R5, 'A': R5, 'H': 8}), ('bn.or', {'D': R6, 'A': R6, 'B': R5}),
     ('bn.or', {'D': R8, 'A': R3, 'B': R0}), ('bn.or', {'D': R3, 'A': R6, 'B': R0}),
     jal('log_r3'), ('bn.or', {'D': R3, 'A': R8, 'B': R0}),
     'mbx_x:', j(0x239008)] if MB else []),

     # ---- ring: failed mailbox transaction (epilogue 0x239002, r3 = result 0; r4-r8 free) ----
     *([*P('h_mbf'), nlw(19, 0, R1), nlw(18, 4, R1),
        ('bg.bnei', {'A': R3, 'I': 0, ';': 'mbf_x'}),
        ('bn.or', {'D': R8, 'A': R3, 'B': R0}),
        mh(R7, 0x20), lbz(R5, MBC, R7), ('bn.slli', {'D': R5, 'A': R5, 'H': 16}),
        lbz(R6, MBC + 1, R7), ('bn.slli', {'D': R6, 'A': R6, 'H': 8}),
        ('bn.or', {'D': R3, 'A': R5, 'B': R6}),
        jal('log_r3'), ('bn.or', {'D': R3, 'A': R8, 'B': R0}),
        'mbf_x:', j(0x239008)] if QALL else []),

     # ---- main-loop watcher (replaces jal sub_261C04 at 0x262105; r3-r8 free there) ----
     'h_loop:', jal('w_run'), jal(0x261C04), j(0x262109),
     'w_run:',
     ('bn.or', {'D': R8, 'A': R9, 'B': R0}),
     mh(R7, 0x20), lbz(R6, WFLAG, R7), ('bg.ori', {'D': R7, 'A': R7, 't': 0}),    # r7 = table (patched below)
     'w_lp:',
     nlw(R5, 0, R7), ('bn.lbz', {'?': R4, 'A': R5, 'z': 0}), ('bn.lbz', {'?': R3, 'A': R7, 'z': 4}),
     ('bg.beq', {'A': R3, 'B': R4, ';': 'w_nx'}),
     ('bn.sb', {'z': 4, 'A': R7, 'B': R4}),
     ('bg.beqi', {'A': R6, 'I': 0, ';': 'w_nx'}),
     ('bn.slli', {'D': R3, 'A': R7, 'H': 8}), ('bn.or', {'D': R3, 'A': R3, 'B': R4}),
     jal('log_r3'),
     'w_nx:',
     ('bn.addi', {'D': R7, 'A': R7, 'O': 8}),
     mh(R3, 0x20), ('bg.ori', {'D': R3, 'A': R3, 't': 0}),                            # r3 = table end (patched below)
     ('bn.sfne', {'A': R7, 'B': R3}), ('bg.bf', {"'": 'w_lp'}),
     movi(R6, 1), mh(R7, 0x20), sb(WFLAG, R7, R6),
     ('bt.jr', {'A': R8}),
    ]

def assemble(pad, wtab):
    prog = program(pad)
    k = 0
    for i, it in enumerate(prog):                      # fill the watch-table start / end
        if isinstance(it, tuple) and it[0] == 'bg.ori' and it[1]['t'] == 0 and it[1]['A'] in (R7, R3) and it[1]['D'] == it[1]['A']:
            prog[i] = ('bg.ori', {'D': it[1]['D'], 'A': it[1]['A'], 't': (wtab if k == 0 else wtab + 8 * len(WATCH)) & 0xFFFF})
            k += 1
    assert k == 2
    return S.assemble(prog, CODE)

LOGS = ('log_s0', 'log_s4', 'log_r3')
def tags_of(code, L):
    t = {}
    for a, b, x in A.disasm(code, CODE, CODE + len(code), CODE):
        if x['mnem'] == 'b.jal' and x['target'] in [L[k] for k in LOGS]:
            owner = max((v, k) for k, v in L.items() if v <= a and k not in LOGS and not k.endswith(('_go', '_x', '_v', '_nx', '_lp')))[1]
            owner = 'h_mb' if owner == 'h_mbx' else owner
            t[owner] = (a + x['len']) & 0xFF
    return t

pad = {}
for _ in range(64):                                     # insert nops until every stub has its own tag
    code, L = assemble(pad, 0x201000)
    t = tags_of(code, L)
    seen, clash = {}, None
    for k, v in sorted(t.items(), key=lambda kv: L[kv[0]]):
        if v in seen: clash = k; break
        seen[v] = k
    if clash is None: break
    pad[clash] = pad.get(clash, 0) + 1
else:
    raise SystemExit('could not make the tags unique')
wtab = (CODE + len(code) + 7) & ~7
code, L = assemble(pad, wtab)
TAGS = tags_of(code, L)
assert len(set(TAGS.values())) == len(TAGS)
wbytes = b''.join(a.to_bytes(4, 'little') + b'\0' * 4 for a, _ in WATCH)
blob = code + b'\0' * (wtab - CODE - len(code)) + wbytes
for a, b, x in A.disasm(code, CODE, CODE + len(code), CODE):
    lab = [k for k, v in L.items() if v == a]
    print(('%-8s' % (lab[0] + ':' if lab else '')) + '%08x: %-12s %-9s %s' % (a, b.hex(' '), x['mnem'], x['ops']))
print('code %#x-%#x, watch table %#x, data %#x-%#x' % (CODE, CODE + len(code), wtab, DATA, 0x200000 + WFLAG + 1))
print('tags', {k: '%02X' % v for k, v in TAGS.items()})
assert CODE + len(blob) <= 0x202000
assert 0x200000 + MBT + 4 <= 0x202500
assert cur(CODE, len(blob)) == b'\0' * len(blob)
assert cur(DATA, MBT + 4 - LOGT) == b'\0' * (MBT + 4 - LOGT)
assert cur(0x201200, 0x14) != b'\0' * 0x14 and cur(0x201214, 0x201400 - 0x201214) == b'\0' * (0x201400 - 0x201214)
assert cur(0x202087, DATA - 0x202087) == b'\0' * (DATA - 0x202087)

hooks = [  # addr, expected original bytes, label, what
 (0x240C55, '9c380d2104', 'isr', '1 ms ISR entry: ms counter'),
 (0x261FF0, 'c860042c', 'm_init', 'sub_261FDE after the prologue (main init start)'),
 (0x26208C, 'e7fbbd38', 'm_dev', 'jal sub_23FF28 after sub_23D3EB (init done)'),
 (0x26209C, 'e7fbe212', 'm_fe', 'jal sub_2411A5 after sub_261FA8 (front-end set-up done)'),
 (0x2620D2, 'e400abc0', 'm_prep', 'jal sub_2676B2 after the boot panel preparation'),
 (0x2620F9, 'c14008a1', 'm_loop', 'movhi r10,0x45 before the main loop'),
 (0x2459C0, 'c8600426', 'm_bl', 'sub_245919 backlight-on step'),
 (0x245860, '9c3c0d2100', 'h_off', 'sub_245860 entry (panel off)'),
 (0x24591E, '0d4100c14008a1', 'h_on', 'sub_245919+5 (panel on)'),
 (0x258AB1, '9c380d2104', 'h_sig', 'sub_258AB1 entry (OSD timer end)'),
 (0x26A7C5, '9c380d2104', 'h_st4', 'sub_26A7C5 entry (OSD state 4 entry)'),
 (0x2613A0, 'e7fffeb2', 'h_gate', 'jal standby_gate_query in the power-save entry'),
 (0x22F300, 'd4e6003a18eb00', 'h_port', 'sub_22F2C7 port state change check (beq + sb)'),
 (0x238FD5, 'c1c008a1', 'h_mb', 'mailbox_query: movhi r14,0x45 after the argument moves'),
 (0x262105, 'e7fff5fe', 'h_loop', 'main-loop head: jal sub_261C04'),
]
if QALL:  # ring: who selects an input (value = path << 20 | input << 16 | low 16 bits of the return address)
    hooks.append((0x2678D9, '1c21ec0d2110', 'h_sel', 'sub_2678D9 entry (input selection)'))
    hooks.append((0x239002, '0e61020e4106', 'h_mbf', 'mailbox_query epilogue: log failed transactions'))
if MB:   # no watcher (saves ring entries); mailbox duration at the common epilogue
    hooks = [h for h in hooks if h[2] != 'h_loop'] + [(0x239002, '0e61020e4106', 'h_mbx', 'mailbox_query epilogue: log cmd, sub, duration')]
edits = [{'addr': '0x%06X' % CODE, 'old': '00' * len(blob), 'new': blob.hex(),
          'asm': 'diag-log code and watch table (image head zero area 0x201400); data at 0x%06X' % DATA}]
# build signature: one constant byte in the data area (copied from flash at every start, never written by the
# code), so tools/logread.py can tell whether the monitor runs the build described by this file
SIG = DATA + 0x214                    # after MBT (0x20240C-0x20240F); gate-all-dp uses 0x2024C0 on
import zlib
sig = zlib.crc32(repr((MODE, N, [(a, w) for a, w in WATCH], sorted(TAGS.items()), blob)).encode()) % 255 + 1   # 1-255
assert cur(SIG, 1) == b'\0'
edits.append({'addr': '0x%06X' % SIG, 'old': '00', 'new': '%02x' % sig,
              'asm': 'build signature 0x%02X for tools/logread.py (constant, data area)' % sig})
for a, old, lab, what in hooks:
    assert cur(a, len(old) // 2).hex() == old, (hex(a), cur(a, len(old) // 2).hex())
    nb = S.encode('bg.j', {'/': L[lab]}, a)
    edits.append({'addr': '0x%06X' % a, 'old': cur(a, 4).hex(), 'new': nb.hex(),
                  'asm': '%s -> j %s (%s)' % (A.decode(cur(a, 4), 0, a)['mnem'], lab, what)})

patch = {
 'name': {'mb': 'diag-log-mb', 'ring': 'diag-log-ring'}.get(MODE, 'diag-log'),
 'summary': ('DIAGNOSTIC: mailbox log in RAM (last 64 events): every mailbox command with its duration for the whole run, start-up milestones, port states, panel/backlight; read with diag-poke + LOG=diag-log-mb tools/logread.py' if MB else
             'DIAGNOSTIC: event log in RAM (last 64 events): port states, watched bytes (ports 0/1, current port, No-signal restart flags, OSD state), No-signal entries, standby gate, panel on/off; read with diag-poke + LOG=diag-log-ring tools/logread.py' if MODE == 'ring' else
             'DIAGNOSTIC: timing log in RAM (ms time stamps, 64 events): start-up milestones, mailbox commands, port states, watched bytes, panel/backlight; read with diag-poke + tools/logread.py'),
 'status': 'diagnostic, hardware test pending (first use of the image head area)',
 'requires': ['diag-poke'],
 'conflicts': [n for n in ('diag-log', 'diag-log-mb', 'diag-log-ring') if n != {'mb': 'diag-log-mb', 'ring': 'diag-log-ring'}.get(MODE, 'diag-log')],
 'edits': edits,
 'tags': {k: '0x%02X' % v for k, v in TAGS.items()},
 'keep_first': not RING,
 'q_format': 'cmd_sub_dur' if MB else 'cmd_d1_sub_data0' if QALL else 'cmd_sub_data0',
 'data': {'ms': '0x%06X' % DATA, 'count': '0x%06X' % (DATA + 4), 'ring': '0x%06X' % (DATA + 8), 'entries': N,
          'sig': '0x%06X' % SIG, 'sig_value': '0x%02X' % sig},
 'watch': {} if MB else {'0x%04X' % ((wtab + 8 * i) & 0xFFFF): {'addr': '0x%06X' % a, 'what': w} for i, (a, w) in enumerate(WATCH)},
 'notes': ("Code in the uncompressed image head (0x201400, zero in the stock image, copied to RAM by the boot loader, "
           "not referenced by the firmware); data at 0x%06X (needs the diag-poke version that reads pages 0x2022xx-0x2024xx). "
           "Does not use the 0x203800 linker padding, so it combines with all regular patches. "
           "Generated by tools/patches_src_diag_log.py." % DATA),
}
out = os.environ.get('OUT', {'mb': 'diag-log-mb.json', 'ring': 'diag-log-ring.json'}.get(MODE, 'diag-log.json'))
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
