#!/usr/bin/env python3
"""Source of patches/diag-log.json. Run in an unpacked work dir (RT=runtime_0x200000.bin).

DIAGNOSTIC: event log in RAM, read with diag-poke (page 0x2039xx) and
tools/logread.py. Records who switches the panel on/off, the standby
decisions and the start-up milestones, with a millisecond time stamp, to find
what wakes the panel in link-held standby and where wake/start-up time goes.

Data (linker padding, zero at every start, lost on deep standby/restart):
  0x203968 u32  ms counter, incremented by the 1 ms timer ISR (sub_240C55)
  0x20396C u32  number of events written so far
  0x203970      16 entries x 8 bytes, ring (entry = count & 15):
                +0 u32 ms, +4 u32 = hook tag << 24 | value & 0xFFFFFF
                (tag = low byte of the hook cave's return address; value =
                caller of the hooked function, or a result)
Code: hook stubs at 0x203A99, ISR stub at 0x203CE0, log routine at 0x203B08,
start-up milestone and port-state stubs at 0x203BA3, mailbox exit stub at
0x2038AA, mailbox entry stub at 0x203FB8, path-state stub at 0x203D9A. Mailbox scratch:
0x2039F0 u32 start ms, 0x2039F4 cmd, 0x2039F5 sub.

Hooks (all keep the hooked function's behaviour; the log routine preserves
r3-r8 and r10-r31):
  T  sub_240C55 entry   1 ms ISR: ms counter
  F  sub_245860 entry   panel off (only when pnl = 1, i.e. the panel is on;
                        pre-standby calls it on every main-loop pass)  value = caller
  N  sub_245919 +5      panel on (after r9/r10 saved; works with bl-supply-off;
                        only when pnl = 0, i.e. the panel is off)
                                               value = caller
  S  sub_258AB1 entry   OSD timer expiry handler (re-enters "No signal",
                        ends the logo or a popup)  value = caller
  E  sub_26A7C5 entry   OSD state 4 entry handler (arms the 255 s countdown)
                                               value = caller
  G  0x2613A0           standby_gate_query in the power-save entry
                                               value = result (1 = refused)
Start-up milestones (no value):
  I  0x261FF0           main init start (sub_261FDE after its prologue)
  D  0x26208C           after sub_23D3EB (EEPROM settings, scaler/receiver init)
  M  0x2620F9           main loop about to start (after the panel prepower)
  B  0x2459C0           backlight on (sub_245919, after the T8 wait or the
                        prepared-panel shortcut)   value = caller of sub_245919
  C  checkpoint after a call (list CALLS, currently empty; used 2026-10-06 to
     find that sub_261FA8 takes 4.6 s after a mains power cut)
  Q  mailbox_query sub_238FA5 (main CPU -> PM51 mailbox 0x1033C0..) taking
     >= 100 ms: entry at 0x238FD5 stores the start time and the command (r3, r4),
     the common epilogue 0x239002 logs   value = cmd << 16 | (sub & 0xF) << 12 |
     min(duration / 2 ms, 0xFFF); the entry time is the end of the transaction
     (a normal transaction takes ~66 ms, measured 2026-10-06)
  P  sub_22F2C7 0x22F300: port state (0x3B495C + n*0xB0) changed   value = n << 8 | state
  Y  sub_22F2C7 0x22F35A: input path state (0x47FA64 + n*0x7C) changed
                                                   value = n << 8 | state
"""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeon'))
import aeondis as A, aeonasm as S

d = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
def cur(a, n): return d[a - 0x200000:a - 0x200000 + n]

DATA = 0x203968                     # after bl-supply-off (0x203940-0x203967), before panel-prepower
STUB = 0x203A99                     # right after panel-prepower (0x203A00-0x203A98)
ISR = 0x203CE0                      # after diag-poke's stable-read cave (0x203C60-0x203CDD)
LOGC = 0x203B08                     # after eeprom-fast-read's cave (0x203B00-0x203B05, not used in builds)
BOOT = 0x203BA3                     # after the log routine, before popup-flat (0x203C00)
CHK = 0x2038AA                      # after standby-lhs (0x203800-0x2038A9), before panel-t12 (0x203900)
MBIN = 0x203FB8                     # after diag-poke (0x203DC0-0x203FB7), before the panel-prepower flags (0x203FF0)
MBT, MBC = 0x2039F0 - 0x200000, 0x2039F4 - 0x200000   # mailbox scratch, after the log ring
# checkpoints: (address of the jal, callee); the first N_BOOT go after the milestones, the rest to MBIN
CALLS = []
N_BOOT = 0
ST2 = 0x203D9A                      # after popup-round (0x203D00-0x203D99), before diag-poke (0x203DC0)
LOGT, IDX, BUF = DATA - 0x200000, DATA + 4 - 0x200000, DATA + 8 - 0x200000
R0, R1, R3, R4, R5, R6, R7, R8, R9, R10 = 0, 1, 3, 4, 5, 6, 7, 8, 9, 10
R11, R12, R13, R14, R18, R19, R28 = 11, 12, 13, 14, 18, 19, 28
def state_stub(lab, cur_r, old_r, idx_r, cache_r, back):
    # replaces 'beq cur,old,back' + the following 'sb 0(cache),cur': log index << 8 | new state on a change
    go = lab + '_go'
    return [lab + ':', ('bg.beq', {'A': cur_r, 'B': old_r, ';': go}), ('bn.sb', {'z': 0, 'A': cache_r, 'B': cur_r}),
            ('bn.addi', {'D': R1, 'A': R1, 'O': -4}), nsw(0, R1, R3),
            ('bn.slli', {'D': R3, 'A': idx_r, 'H': 8}), ('bn.or', {'D': R3, 'A': R3, 'B': cur_r}),
            jal(LL['log_r3']), nlw(R3, 0, R1), ('bn.addi', {'D': R1, 'A': R1, 'O': 4}),
            go + ':', j(back)]

mh = lambda rd, v: ('bg.movhi', {'D': rd, 'U': v})
lwz = lambda rd, off, ra: ('bg.lwz', {'D': rd, 'A': ra, 'W': off})
sw = lambda off, ra, rb: ('bg.sw', {'W': off, 'A': ra, 'B': rb})
nsw = lambda off, ra, rb: ('bn.sw', {':': off, 'A': ra, 'B': rb})
nlw = lambda rd, off, ra: ('bn.lwz', {'D': rd, 'A': ra, ':': off})
j = lambda t: ('bg.j', {'/': t})
jal = lambda t: ('bg.jal', {'/': t})
SAVE = [('bn.addi', {'D': R1, 'A': R1, 'O': -24})] + [nsw(4 * i, R1, r) for i, r in enumerate((R3, R4, R5, R6, R7, R8))]
REST = [nlw(r, 4 * i, R1) for i, r in enumerate((R3, R4, R5, R6, R7, R8))] + [('bn.addi', {'D': R1, 'A': R1, 'O': 24})]

log_prog = [
 # ---- log routines: r9 = hook return address; value from the caller's frame or r3 ----
 'log_s0:', *SAVE, nlw(R4, 24, R1), j('log_c'),
 'log_s4:', *SAVE, nlw(R4, 28, R1), j('log_c'),
 'log_r3:', *SAVE, ('bn.or', {'D': R4, 'A': R3, 'B': R0}),
 'log_c:',
 mh(R7, 0x20), lwz(R5, IDX, R7), ('bn.andi', {'D': R6, 'A': R5, 'N': 0x0F}),
 ('bn.slli', {'D': R6, 'A': R6, 'H': 3}), ('bn.add', {'D': R6, 'A': R6, 'B': R7}),    # r6 = 0x200000 + 8*slot
 lwz(R8, LOGT, R7), sw(BUF, R6, R8),
 mh(R8, 0xFF), ('bg.ori', {'D': R8, 'A': R8, 't': 0xFFFF}),
 ('bn.and', {'D': R4, 'A': R4, 'B': R8}),                                          # value & 0xFFFFFF
 ('bn.slli', {'D': R8, 'A': R9, 'H': 24}), ('bn.or', {'D': R4, 'A': R4, 'B': R8}),   # | tag << 24
 sw(BUF + 4, R6, R4),
 ('bt.addi', {'D': R5, 'I': 1}), sw(IDX, R7, R5),
 *REST, ('bt.jr', {'A': R9}),
]
lcode, LL = S.assemble(log_prog, LOGC)
stub_prog = [
 'h_off:',                          # replaces sub_245860: addi r1,-4; sw 0(r1),r9
 ('bt.addi', {'D': R1, 'I': -4}), nsw(0, R1, R9),
 mh(R7, 0x45), ('bg.lbz', {'?': R7, 'A': R7, '!': 0x51A8}),      # pnl: log only real panel-offs
 ('bg.beqi', {'A': R7, 'I': 0, ';': 'off_go'}),                 # (pre-standby calls this every main-loop pass)
 jal(LL['log_s0']),
 'off_go:', j(0x245865),
 'h_on:',                           # replaces sub_245919+5: sw 0(r1),r10; movhi r10,0x45
 nsw(0, R1, R10), mh(R10, 0x45),
 ('bg.lbz', {'?': R7, 'A': R10, '!': 0x51A8}),                   # pnl: log only real panel-ons
 ('bg.bnei', {'A': R7, 'I': 0, ';': 'on_go'}),                  # (the relight calls this on every pass while on)
 jal(LL['log_s4']),
 'on_go:', j(0x245925),
 'h_sig:',                          # replaces sub_258AB1: addi r1,-8; sw 4(r1),r9
 ('bt.addi', {'D': R1, 'I': -8}), nsw(4, R1, R9),
 jal(LL['log_s4']), j(0x258AB6),
 'h_st4:',                          # replaces sub_26A7C5: addi r1,-8; sw 4(r1),r9
 ('bt.addi', {'D': R1, 'I': -8}), nsw(4, R1, R9),
 jal(LL['log_s4']), j(0x26A7CA),
 'h_gate:',                         # replaces jal standby_gate_query at 0x2613A0
 jal(0x2612F9), jal(LL['log_r3']), j(0x2613A4),
]
scode, L = S.assemble(stub_prog, STUB)
isr_prog = [
 'isr:',                            # replaces sub_240C55: addi r1,-8; sw 4(r1),r9
 ('bt.addi', {'D': R1, 'I': -8}), nsw(4, R1, R9),
 mh(R7, 0x20), lwz(R6, LOGT, R7), ('bt.addi', {'D': R6, 'I': 1}), sw(LOGT, R7, R6),
 j(0x240C5A),
]
icode, IL = S.assemble(isr_prog, ISR)
boot_prog = [
 'm_init:', jal(LL['log_s0']), ('bg.ori', {'D': R3, 'A': R0, 't': 0x42C}), j(0x261FF4),   # replaces ori r3,r0,0x42c
 'm_dev:', jal(LL['log_s0']), jal(0x23FF28), j(0x262090),                                  # replaces jal sub_23FF28
 'm_loop:', jal(LL['log_s0']), mh(R10, 0x45), j(0x2620FD),                                 # replaces movhi r10,0x45
 'm_bl:', jal(LL['log_s4']), ('bg.ori', {'D': R3, 'A': R0, 't': 0x426}), j(0x2459C4),     # replaces ori r3,r0,0x426
]
chk = lambda a, t: ['c_%x:' % a, jal(t), jal(LL['log_s0']), j(a + 4)]   # replaces jal t at a; r3 (result) preserved
for a, t in CALLS[:N_BOOT]:
    boot_prog += chk(a, t)
boot_prog += state_stub('h_port', R7, R6, R10, R11, 0x22F307)     # beq r7,r6 at 0x22F300; cache r11, port r10
st2_prog = state_stub('h_path', R10, R28, R11, R13, 0x22F361)       # beq r10,r28 at 0x22F35A; cache r13, path r11
mbin_prog = [
 'mb_in:',                          # replaces movhi r14,0x45 at 0x238FD5 (r12 = cmd, r13 = sub; r7 is free here)
 mh(R14, 0x20), lwz(R7, LOGT, R14), sw(MBT, R14, R7),
 ('bg.sb', {'Y': MBC, 'A': R14, 'B': R12}), ('bg.sb', {'Y': MBC + 1, 'A': R14, 'B': R13}),
 mh(R14, 0x45), j(0x238FD9),
] + [x for a, t in CALLS[N_BOOT:] for x in chk(a, t)]
ccode_prog = [
 'h_mb:',                           # replaces lwz r19,0(r1); lwz r18,4(r1) at 0x239002 (r3 = result; r4-r8 free)
 nlw(R19, 0, R1), nlw(R18, 4, R1),
 mh(R7, 0x20), lwz(R6, LOGT, R7), lwz(R5, MBT, R7), ('bn.sub', {'D': R6, 'A': R6, 'B': R5}),
 ('bg.sfleui', {'A': R6, 'Y': 99}), ('bg.bf', {"'": 'mb_done'}),          # < 100 ms: no entry
 ('bn.srli', {'D': R6, 'A': R6, 'H': 1}), ('bg.sfgtui', {'A': R6, 'Y': 0xFFF}),
 ('bg.ori', {'D': R5, 'A': R0, 't': 0xFFF}), ('bn.cmov', {'D': R6, 'A': R5, 'B': R6}),  # min(dt/2, 0xFFF)
 ('bg.lbz', {'?': R5, 'A': R7, '!': MBC}), ('bn.slli', {'D': R5, 'A': R5, 'H': 16}), ('bn.or', {'D': R6, 'A': R6, 'B': R5}),
 ('bg.lbz', {'?': R5, 'A': R7, '!': MBC + 1}), ('bn.andi', {'D': R5, 'A': R5, 'N': 0x0F}),
 ('bn.slli', {'D': R5, 'A': R5, 'H': 12}), ('bn.or', {'D': R6, 'A': R6, 'B': R5}),
 ('bn.or', {'D': R8, 'A': R3, 'B': R0}), ('bn.or', {'D': R3, 'A': R6, 'B': R0}),
 jal(LL['log_r3']), ('bn.or', {'D': R3, 'A': R8, 'B': R0}),
 'mb_done:', j(0x239008),
]
bcode, BL = S.assemble(boot_prog, BOOT)
ccode, CL = S.assemble(ccode_prog, CHK)
mcode, ML = S.assemble(mbin_prog, MBIN)
tcode, TL = S.assemble(st2_prog, ST2)
BL.update(CL); BL.update(ML); BL.update(TL)
L.update(IL)
for code, base, labs in ((scode, STUB, L), (icode, ISR, IL), (lcode, LOGC, LL), (bcode, BOOT, BL), (ccode, CHK, CL), (mcode, MBIN, ML), (tcode, ST2, TL)):
    for a, b, x in A.disasm(code, base, base + len(code), base):
        lab = [k for k, v in labs.items() if v == a]
        print(('%-8s' % (lab[0] + ':' if lab else '')) + '%08x: %-12s %-9s %s' % (a, b.hex(' '), x['mnem'], x['ops']))
    print('cave %#x-%#x (%d bytes)' % (base, base + len(code), len(code)))
assert STUB + len(scode) <= 0x203B00 and LOGC + len(lcode) <= BOOT and ISR + len(icode) <= 0x203D00
assert BOOT + len(bcode) <= 0x203C00 and CHK + len(ccode) <= 0x203900 and MBIN + len(mcode) <= 0x203FF0 and ST2 + len(tcode) <= 0x203DC0
assert DATA + 8 + 16 * 8 <= 0x203A00
for base, code in ((STUB, scode), (ISR, icode), (LOGC, lcode), (BOOT, bcode), (CHK, ccode), (MBIN, mcode), (ST2, tcode)):
    assert cur(base, len(code)) == b'\0' * len(code)
assert cur(DATA, 8 + 16 * 8) == b'\0' * (8 + 16 * 8) and DATA + 8 + 16 * 8 <= 0x200000 + MBT
assert cur(0x200000 + MBT, 6) == b'\0' * 6
# tag of each hook = low byte of the return address after its jal to a log routine
TAGS = {}
for a, b, x in A.disasm(scode, STUB, STUB + len(scode), STUB):
    if x.get('target') in (LL['log_s0'], LL['log_s4'], LL['log_r3']):
        owner = max((v, k) for k, v in L.items() if v <= a)[1]
        TAGS[owner] = (a + x['len']) & 0xFF
for code, base in ((bcode, BOOT), (ccode, CHK), (mcode, MBIN), (tcode, ST2)):
    for a, b, x in A.disasm(code, base, base + len(code), base):
        if x.get('target') in (LL['log_s0'], LL['log_s4'], LL['log_r3']):
            owner = max((v, k) for k, v in BL.items() if v <= a and base <= v < base + len(code))[1]
            TAGS[owner] = (a + x['len']) & 0xFF
print('tags', {k: '%02X' % v for k, v in TAGS.items()})
assert len(set(TAGS.values())) == len(TAGS)

hooks = [  # addr, expected original bytes, label, what
 (0x240C55, '9c380d2104', 'isr', '1 ms ISR entry: ms counter'),
 (0x245860, '9c3c0d2100', 'h_off', 'sub_245860 entry (panel off)'),
 (0x24591E, '0d4100c14008a1', 'h_on', 'sub_245919+5 (panel on)'),
 (0x258AB1, '9c380d2104', 'h_sig', 'sub_258AB1 entry (re-enter No signal)'),
 (0x26A7C5, '9c380d2104', 'h_st4', 'sub_26A7C5 entry (OSD state 4 entry)'),
 (0x2613A0, 'e7fffeb2', 'h_gate', 'jal standby_gate_query in the power-save entry'),
 (0x261FF0, 'c860042c', 'm_init', 'sub_261FDE after the prologue (main init start)'),
 (0x26208C, 'e7fbbd38', 'm_dev', 'jal sub_23FF28 after sub_23D3EB (init done)'),
 (0x2620F9, 'c14008a1', 'm_loop', 'movhi r10,0x45 before the main loop'),
 (0x2459C0, 'c8600426', 'm_bl', 'sub_245919 backlight-on step'),
 (0x238FD5, 'c1c008a1', 'mb_in', 'mailbox_query: movhi r14,0x45 after the argument moves (start time, command)'),
 (0x239002, '0e61020e4106', 'h_mb', 'mailbox_query epilogue: lwz r19/r18 (log if >= 100 ms); 0x239006-07 unused'),
 (0x22F300, 'd4e6003a18eb00', 'h_port', 'sub_22F2C7 port state change check (beq + sb)'),
 (0x22F35A, 'd55c003a194d00', 'h_path', 'sub_22F2C7 input path state change check (beq + sb)'),
] + [(a, S.encode('bg.jal', {'/': t}, a).hex(), 'c_%x' % a, 'jal sub_%X: time stamp after it returns' % t) for a, t in CALLS]
L.update(BL)
edits = [{'addr': '0x%06X' % STUB, 'old': '00' * len(scode), 'new': scode.hex(),
          'asm': 'diag-log hook stubs (linker padding 0x203A9C)'},
         {'addr': '0x%06X' % ISR, 'old': '00' * len(icode), 'new': icode.hex(),
          'asm': 'diag-log 1 ms ISR stub (linker padding 0x203CE0)'},
         {'addr': '0x%06X' % LOGC, 'old': '00' * len(lcode), 'new': lcode.hex(),
          'asm': 'diag-log log routine (linker padding 0x203B08); data at 0x203968-0x2039EF'},
         {'addr': '0x%06X' % BOOT, 'old': '00' * len(bcode), 'new': bcode.hex(),
          'asm': 'diag-log start-up milestone stubs (linker padding 0x203BA3)'},
         {'addr': '0x%06X' % CHK, 'old': '00' * len(ccode), 'new': ccode.hex(),
          'asm': 'diag-log mailbox exit stub (linker padding 0x2038AA)'},
         {'addr': '0x%06X' % MBIN, 'old': '00' * len(mcode), 'new': mcode.hex(),
          'asm': 'diag-log mailbox entry stub (linker padding 0x203FB8); scratch 0x2039F0-0x2039F5'},
         {'addr': '0x%06X' % ST2, 'old': '00' * len(tcode), 'new': tcode.hex(),
          'asm': 'diag-log input path state stub (linker padding 0x203D9A)'}]
for a, old, lab, what in hooks:
    assert cur(a, len(old) // 2).hex() == old, (hex(a), cur(a, len(old) // 2).hex())
    nb = S.encode('bg.j', {'/': L[lab]}, a)
    edits.append({'addr': '0x%06X' % a, 'old': cur(a, 4).hex(), 'new': nb.hex(),
                  'asm': '%s -> j %s (%s)' % (A.decode(cur(a, 4), 0, a)['mnem'], lab, what)})

patch = {
 'name': 'diag-log',
 'summary': 'DIAGNOSTIC: RAM event log (ms time stamps) of panel on/off callers, OSD timer expiry, the standby gate and start-up milestones; read with diag-poke + tools/logread.py',
 'status': 'diagnostic, hardware test pending',
 'requires': ['diag-poke'],
 'edits': edits,
 'tags': {k: '0x%02X' % v for k, v in TAGS.items()},
 'data': {'ms': '0x%06X' % DATA, 'count': '0x%06X' % (DATA + 4), 'ring': '0x%06X' % (DATA + 8), 'entries': 16},
 'calls': {'c_%x' % a: '0x%06X' % t for a, t in CALLS},
 'notes': ("Log at 0x203968 (ms counter), 0x20396C (event count), 0x203970 (16 x 8-byte ring: ms, tag<<24 | value). "
           "tools/logread.py maps the tags (see 'tags') to F (panel off), N (panel on), S (OSD timer expiry), E (state 4 entry), G (gate result), "
           "I (main init start), D (init done), M (main loop start), B (backlight on), C (after a start-up call, c_<call address>), "
           "Q (mailbox transaction >= 100 ms: cmd << 16 | sub << 12 | duration / 2 ms), P/Y (port/input path state change: n << 8 | state). "
           "The log is in RAM and starts empty at every firmware start. Generated by tools/patches_src_diag_log.py."),
}
out = os.environ.get('OUT', 'diag-log.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
