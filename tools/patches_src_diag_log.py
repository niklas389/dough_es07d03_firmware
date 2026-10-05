#!/usr/bin/env python3
"""Source of patches/diag-log.json. Run in an unpacked work dir (RT=runtime_0x200000.bin).

DIAGNOSTIC: event log in RAM, read with diag-poke (page 0x203Bxx) and
tools/logread.sh. Records who switches the panel on/off and the standby
decisions, with a millisecond time stamp, to find what wakes the panel in
link-held standby and where wake/start-up time goes.

Data (linker padding, zero at every start, lost on deep standby/restart):
  0x203968 u32  ms counter, incremented by the 1 ms timer ISR (sub_240C55)
  0x20396C u32  number of events written so far
  0x203970      16 entries x 8 bytes, ring (entry = count & 15):
                +0 u32 ms, +4 u32 = hook tag << 24 | value & 0xFFFFFF
                (tag = low byte of the hook cave's return address; value =
                caller of the hooked function, or a result)
Code: hook stubs at 0x203A99, log routine at 0x203B08.

Hooks (all keep the hooked function's behaviour; the log routine preserves
r3-r8 and r10-r31):
  T  sub_240C55 entry   1 ms ISR: ms counter
  F  sub_245860 entry   panel off (only when pnl = 1, i.e. the panel is on;
                        pre-standby calls it on every main-loop pass)  value = caller
  N  sub_245919 +5      panel on (after r9/r10 saved; works with bl-supply-off)
                                               value = caller
  S  sub_258AB1 entry   re-enter "No signal" (OSD state 4) after a timer
                                               value = caller
  E  sub_26A7C5 entry   OSD state 4 entry handler (arms the 255 s countdown)
                                               value = caller
  G  0x2613A0           standby_gate_query in the power-save entry
                                               value = result (1 = refused)
"""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeon'))
import aeondis as A, aeonasm as S

d = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
def cur(a, n): return d[a - 0x200000:a - 0x200000 + n]

DATA = 0x203968                     # after bl-supply-off (0x203940-0x203967), before panel-prepower
STUB = 0x203A99                     # right after panel-prepower (0x203A00-0x203A98)
LOGC = 0x203B08                     # after eeprom-fast-read's cave (0x203B00-0x203B05, not used in builds)
LOGT, IDX, BUF = DATA - 0x200000, DATA + 4 - 0x200000, DATA + 8 - 0x200000
R0, R1, R3, R4, R5, R6, R7, R8, R9, R10 = 0, 1, 3, 4, 5, 6, 7, 8, 9, 10

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
 'log_r3:', *SAVE,
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
 'isr:',                            # replaces sub_240C55: addi r1,-8; sw 4(r1),r9
 ('bt.addi', {'D': R1, 'I': -8}), nsw(4, R1, R9),
 mh(R7, 0x20), lwz(R6, LOGT, R7), ('bt.addi', {'D': R6, 'I': 1}), sw(LOGT, R7, R6),
 j(0x240C5A),
 'h_off:',                          # replaces sub_245860: addi r1,-4; sw 0(r1),r9
 ('bt.addi', {'D': R1, 'I': -4}), nsw(0, R1, R9),
 mh(R7, 0x45), ('bg.lbz', {'?': R7, 'A': R7, '!': 0x51A8}),      # pnl: log only real panel-offs
 ('bg.beqi', {'A': R7, 'I': 0, ';': 'off_go'}),                 # (pre-standby calls this every main-loop pass)
 jal(LL['log_s0']),
 'off_go:', j(0x245865),
 'h_on:',                           # replaces sub_245919+5: sw 0(r1),r10; movhi r10,0x45
 nsw(0, R1, R10), mh(R10, 0x45),
 jal(LL['log_s4']), j(0x245925),
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
for code, base, labs in ((scode, STUB, L), (lcode, LOGC, LL)):
    for a, b, x in A.disasm(code, base, base + len(code), base):
        lab = [k for k, v in labs.items() if v == a]
        print(('%-8s' % (lab[0] + ':' if lab else '')) + '%08x: %-12s %-9s %s' % (a, b.hex(' '), x['mnem'], x['ops']))
    print('cave %#x-%#x (%d bytes)' % (base, base + len(code), len(code)))
assert STUB + len(scode) <= 0x203B00 and LOGC + len(lcode) <= 0x203C00
assert DATA + 8 + 16 * 8 <= 0x203A00
for base, code in ((STUB, scode), (LOGC, lcode)):
    assert cur(base, len(code)) == b'\0' * len(code)
assert cur(DATA, 8 + 16 * 8) == b'\0' * (8 + 16 * 8)
# tag of each hook = low byte of the return address after its jal to a log routine
TAGS = {}
for a, b, x in A.disasm(scode, STUB, STUB + len(scode), STUB):
    if x.get('target') in (LL['log_s0'], LL['log_s4'], LL['log_r3']):
        owner = max((v, k) for k, v in L.items() if v <= a)[1]
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
]
edits = [{'addr': '0x%06X' % STUB, 'old': '00' * len(scode), 'new': scode.hex(),
          'asm': 'diag-log hook stubs (linker padding 0x203A9C)'},
         {'addr': '0x%06X' % LOGC, 'old': '00' * len(lcode), 'new': lcode.hex(),
          'asm': 'diag-log log routine (linker padding 0x203B08); data at 0x203968-0x2039EF'}]
for a, old, lab, what in hooks:
    assert cur(a, len(old) // 2).hex() == old, (hex(a), cur(a, len(old) // 2).hex())
    nb = S.encode('bg.j', {'/': L[lab]}, a)
    edits.append({'addr': '0x%06X' % a, 'old': cur(a, 4).hex(), 'new': nb.hex(),
                  'asm': '%s -> j %s (%s)' % (A.decode(cur(a, 4), 0, a)['mnem'], lab, what)})

patch = {
 'name': 'diag-log',
 'summary': 'DIAGNOSTIC: RAM event log (ms time stamps) of panel on/off callers, No-signal re-entry and the standby gate; read with diag-poke + tools/logread.sh',
 'status': 'diagnostic, hardware test pending',
 'requires': ['diag-poke'],
 'edits': edits,
 'tags': {k: '0x%02X' % v for k, v in TAGS.items()},
 'data': {'ms': '0x%06X' % DATA, 'count': '0x%06X' % (DATA + 4), 'ring': '0x%06X' % (DATA + 8), 'entries': 16},
 'notes': ("Log at 0x203968 (ms counter), 0x20396C (event count), 0x203970 (16 x 8-byte ring: ms, tag<<24 | value). "
           "tools/logread.sh maps the tags (see 'tags') to F (panel off), N (panel on), S (No-signal re-entry), E (state 4 entry), G (gate result). "
           "The log is in RAM and starts empty at every firmware start. Generated by tools/patches_src_diag_log.py."),
}
out = os.environ.get('OUT', 'diag-log.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
