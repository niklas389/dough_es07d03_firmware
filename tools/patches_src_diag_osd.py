#!/usr/bin/env python3
"""Source of patches/diag-osd.json. Run in an unpacked work dir (RT=runtime_0x200000.bin).

DIAGNOSTIC (requires diag-poke and diag-fe): plain byte access to the OSD
engine's register bank 0x101C00-0x101DFF over DDC/CI, for live experiments
with the OSD font RAM, tile RAM and window registers (tools/osdtest.sh;
docs/firmware-map.md section 56).

  specctl set 0xEA 0x0010 ; specctl set 0xEB 0x1C68    address (diag-poke's address variable)
  specctl set 0xEE <byte>     write the byte to that OSD register (sub_23D9E7, as the firmware's
                              own OSD code; value <= 0xFF and address 0x101C00-0x101DFF only)
  specctl get 0xEE            read it (sub_23D972); 0xFFFF = blocked (outside the bank, or the
                              data port 0x101C66, whose read could advance the RAM pointer)

RAM 0x2024B0 counts accepted writes (u8, wraps), 0x2024B1 = 1 after a refused
write; both readable with tools/poke.sh (diag-poke page 0x2024xx).

Safety: the OSD bank holds only display state (font RAM, tile RAM, window
and palette registers); everything written is lost when the OSD is redrawn
or at the next power cycle. No other register, no EEPROM, flash or PM51.
A write can disturb the OSD picture until the firmware redraws it (closing
and opening the menu, or a power cycle).

Hooks: diag-fe's SET fall-through (movhi r7,0x48; j 0x26B335) -> j osd_set;
diag-poke's GET fall-through (movhi r23,0x48; j 0x26B180) -> j osd_get;
0x26B211 (movhi r7,0x45) -> j osd_keep. The vendor SET path closes an open
menu on every VCP SET (0x26B211: OSD state 0x457854 > 0x0D -> 0x4551A4 = 0,
0x453C70 bit 0 set, bit 15 cleared), so the address writes of osdtest.py
closed the menu at once (hardware, 2026-10-09). osd_keep skips that for the
diagnostic codes 0xEA-0xEE only (r4 = VCP code there).
Code in the image head zero area at 0x202600.
"""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeon'))
import aeondis as A, aeonasm as S

HERE = os.path.dirname(os.path.abspath(__file__))
d = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
def cur(a, n): return d[a - 0x200000:a - 0x200000 + n]

CODE = 0x202600
VCP = 0xEE
CNT = 0x2024B0                       # u8 accepted writes, +1 = refused flag
ADDR_VAR = 0x3FF4                    # diag-poke address variable (u32 at 0x203FF4)
SET_CONT, SET_DONE = 0x26B335, 0x26AFC9
KEEP, KEEP_CONT, KEEP_SKIP = 0x26B211, 0x26B215, 0x26B23F
GET_CONT, GET_REPLY = 0x26B180, 0x26B1A0
RIU_RD, RIU_WR = 0x23D972, 0x23D9E7
BANK = 0x101C00 >> 9                 # 0x101C00-0x101DFF
PORT = 0x101C66                      # font/tile RAM data port: never read
R0, R1, R3, R4, R5, R6, R7, R9, R23 = 0, 1, 3, 4, 5, 6, 7, 9, 23
R10, R11, R12, R13, R14 = 10, 11, 12, 13, 14
WMASK, W16 = 0x23DC0F, 0x23DBE4      # masked write (reg, value, mask) under the RIU lock; 16-bit write lo/hi
TILES = 0x25C8F5                     # (col, row, code low byte, count): attribute RAM 0x3C5389, code bits 8-11 RAM 0x457889
GTAB, TTAB = 0x202A00, 0x202C00      # v3 test data (image head zero area)

# ---- v3 test data: 2-bit glyphs (18 rows x 12 px, values 0-3) and the test row ----
def pack(rows):
    out = bytearray()
    for r in rows:
        v = 0
        for ch in r:
            v = (v << 2) | int(ch)
        out += bytes([v >> 16, (v >> 8) & 0xFF, v & 0xFF])
    assert len(out) == 54
    return bytes(out)
BANDS = ['000111222333'] * 18
SAMPLE = ['000000000000000000000000000000000000', '000000000000000000000000000000000000',
          '000000000000000000000000000000000000', '000003300000220000000000000000000000',
          '000013320000220000000000000000000000', '000022230000220000000000000000000000',
          '000031031000222332100002332130000000', '000130022000232002300013101330000000',
          '000220013000230000310031000130000000', '001310003100220000220031000130000000',
          '002333333200220000220031000130000000', '003200001310230000310031000130000000',
          '013100000320232002300013101330000000', '023000000230222332100002332130000000',
          '000000000000000000000000000130000000', '000000000000000000000012001320000000',
          '000000000000000000000001333100000000', '000000000000000000000000000000000000']
# Codes (v4): a 2-bit glyph occupies two code slots (c, c + 1) at the same RAM word as a 1-bit glyph of
# code c: word = 0x880 + 12 x c (hardware test 2026-10-09, section 56). The firmware's 2-bit icons sit at
# 0x300-0x30F and 0x372-0x3C9; the test uses even codes from 0x3D0.
GLYPHS = {0x3D0: pack(BANDS), 0x3D2: pack(['1' * 12] * 18), 0x3D4: pack(['2' * 12] * 18),
          0x3D6: pack(['3' * 12] * 18), 0x3DE: pack(BANDS)}
for k in range(3):
    GLYPHS[0x3D8 + 2 * k] = pack([r[12 * k:12 * k + 12] for r in SAMPLE])
def font_addr(code):
    a = 0x880 + 12 * code
    assert 0x300 <= code <= 0x3FD and code % 2 == 0 and a + 24 <= 0x4000
    return a
gtab = b''.join(font_addr(c).to_bytes(2, 'little') + GLYPHS[c] for c in sorted(GLYPHS))
NG = len(GLYPHS)
ROW = [(6, 0x21)]                    # marker: solid base glyph 6
for at in (0x21, 0xF2, 0x40, 0xC8, 0x12):
    ROW += [(0x3D0, at), (0x3D2, at), (0x3D4, at), (0x3D6, at)]
ROW += [(0, 0x21), (0x3D8, 0x21), (0x3DA, 0x21), (0x3DC, 0x21), (0, 0x21), (0x3DE, 0x21), (6, 0x21)]
NT = len(ROW)
ttab = b''.join(bytes([1 + k, c >> 8, c & 0xFF, at]) for k, (c, at) in enumerate(ROW))

def find_fall(name, addr, reg, target):
    p = json.load(open(os.path.join(HERE, '..', 'patches', name + '.json')))
    e = next(e for e in p['edits'] if e['addr'] == addr)
    b, a0 = bytes.fromhex(e['new']), int(addr, 16)
    for a, _, x in A.disasm(b, a0, a0 + len(b), a0):
        if x['mnem'] == 'b.movhi' and x['ops'] == '%s,0x48' % reg:
            y = A.decode(b, a - a0 + x['len'], a + x['len'])
            if y['mnem'] == 'b.j' and y.get('target') == target and x['len'] == 4:
                return a, b[a - a0:a - a0 + 4]
    raise SystemExit('%s: fall-through not found' % name)

SET_FALL, set_old = find_fall('diag-fe', '0x201C00', 'r7', SET_CONT)
GET_FALL, get_old = find_fall('diag-poke', '0x203DC0', 'r23', GET_CONT)

mh = lambda rd, v: ('bg.movhi', {'D': rd, 'U': v})
ori = lambda rd, ra, v: ('bg.ori', {'D': rd, 'A': ra, 't': v})
sb = lambda off, ra, rb: ('bg.sb', {'Y': off, 'A': ra, 'B': rb})
lbz = lambda rd, off, ra: ('bg.lbz', {'?': rd, 'A': ra, '!': off})
lhz = lambda rd, off, ra: ('bg.lhz', {'D': rd, 'A': ra, 'X': off})
lwz = lambda rd, off, ra: ('bg.lwz', {'D': rd, 'A': ra, 'W': off})
beq = lambda a, b, l: ('bg.beq', {'A': a, 'B': b, ';': l})
bne = lambda a, b, l: ('bg.bne', {'A': a, 'B': b, ';': l})
j = lambda t: ('bg.j', {'/': t})
jal = lambda t: ('bg.jal', {'/': t})
srli = lambda rd, ra, n: ('bn.srli', {'D': rd, 'A': ra, 'H': n})
lo = CNT & 0xFFFF

sw = lambda off, ra, rb: ('bn.sw', {':': off, 'A': ra, 'B': rb})
lw = lambda rd, off, ra: ('bn.lwz', {'D': rd, 'A': ra, ':': off})
def const32(r, v): return [mh(r, v >> 16), ori(r, r, v & 0xFFFF)]
def call(fn, *args):                 # args: ('c', const) or ('r', reg)
    out = []
    for k, (t, v) in enumerate(args):
        out += const32(3 + k, v) if t == 'c' else [('bn.or', {'D': 3 + k, 'A': v, 'B': R0})]
    return out + [jal(fn)]
SAVE = [('bg.addi', {'D': R1, 'A': R1, 'Y': -24})] + [sw(4 * k, R1, r) for k, r in enumerate((R9, R10, R11, R12, R13, R14))]
REST = [lw(r, 4 * k, R1) for k, r in enumerate((R9, R10, R11, R12, R13, R14))] + [('bg.addi', {'D': R1, 'A': R1, 'Y': 24})]
RUNCNT = [mh(R7, 0x20), lbz(R6, lo + 2, R7), ('bt.addi', {'D': R6, 'I': 1}), sb(lo + 2, R7, R6)]

prog = [
 # ---- SET (r6 = VCP code, value u16 at 0x453C84) ----
 'osd_set:',
 ori(R7, R0, VCP), beq(R6, R7, 'os_go'),
 mh(R7, 0x48), j(SET_CONT),                               # replaced instruction (diag-fe fall-through)
 'os_go:',
 mh(R7, 0x45), lhz(R4, 0x3C84, R7),                       # r4 = value
 srli(R5, R4, 8), ('bg.beqi', {'A': R5, 'I': 0, ';': 'os_raw'}),
 ('bg.beqi', {'A': R5, 'I': 1, ';': 'osd_load'}),         # v3: 0x100 = load the test glyphs
 ('bg.beqi', {'A': R5, 'I': 2, ';': 'osd_row'}),          # v3: 0x200 | row = place the test row
 j('os_bad'),
 'os_raw:',
 mh(R7, 0x20), lwz(R3, ADDR_VAR, R7),                     # r3 = address
 srli(R6, R3, 9), ori(R7, R0, BANK), bne(R6, R7, 'os_bad'),   # 0x101C00-0x101DFF only
 jal(RIU_WR),                                             # plain byte write, as the firmware's OSD code
 mh(R7, 0x20), lbz(R6, lo, R7), ('bt.addi', {'D': R6, 'I': 1}), sb(lo, R7, R6),
 j(SET_DONE),
 'os_bad:',
 mh(R7, 0x20), ori(R6, R0, 1), sb(lo + 1, R7, R6),
 j(SET_DONE),
 # ---- v3: load the test glyphs (table GTAB: u16 RAM word, 54 bytes) with the firmware loaders' sequence ----
 'osd_load:',
 *SAVE,
 *const32(R10, GTAB), ori(R11, R0, NG),
 'gl_next:',
 *call(WMASK, ('c', 0x101C6D), ('c', 0), ('c', 0xC0)),     # 0x101C6D bits 6-7 cleared (as 0x27BC9C / 0x27BA9E)
 *call(WMASK, ('c', 0x101C68), ('c', 0), ('c', 0x1F)),     # mode 0: address
 lbz(R4, 1, R10), ('bn.slli', {'D': R4, 'A': R4, 'H': 8}), lbz(R5, 0, R10), ('bn.or', {'D': R4, 'A': R4, 'B': R5}),
 *const32(R3, 0x101C66), jal(W16),
 *call(WMASK, ('c', 0x101C68), ('c', 3), ('c', 0x1F)),     # mode 3: font data
 ('bg.addi', {'D': R12, 'A': R10, 'Y': 2}), ori(R13, R0, 54),
 'gl_byte:',
 lbz(R4, 0, R12), *const32(R3, 0x101C66), jal(RIU_WR),
 ('bt.addi', {'D': R12, 'I': 1}), ('bg.addi', {'D': R13, 'A': R13, 'Y': -1}), ('bg.bnei', {'A': R13, 'I': 0, ';': 'gl_byte'}),
 ('bg.addi', {'D': R10, 'A': R10, 'Y': 56}), ('bg.addi', {'D': R11, 'A': R11, 'Y': -1}), ('bg.bnei', {'A': R11, 'I': 0, ';': 'gl_next'}),
 *call(WMASK, ('c', 0x101C68), ('c', 0), ('c', 0x1F)),
 *RUNCNT, *REST, j(SET_DONE),
 # ---- v3: place the test row with the firmware's tile routine (table TTAB: col, code bits 8-11, code low, attribute) ----
 'osd_row:',
 *SAVE,
 ('bn.andi', {'D': R14, 'A': R4, 'N': 0x7F}),            # row
 mh(R7, 0x3C), lbz(R13, 0x5389, R7), mh(R7, 0x45), lbz(R12, 0x7889, R7),   # keep the firmware's attribute / code-high
 *const32(R10, TTAB), ori(R11, R0, NT),
 'tr_next:',
 lbz(R6, 3, R10), mh(R7, 0x3C), sb(0x5389, R7, R6),
 lbz(R6, 1, R10), mh(R7, 0x45), sb(0x7889, R7, R6),
 lbz(R3, 0, R10), ('bn.or', {'D': R4, 'A': R14, 'B': R0}), lbz(R5, 2, R10), ('bt.movi', {'D': R6, 'I': 1}),
 jal(TILES),
 ('bg.addi', {'D': R10, 'A': R10, 'Y': 4}), ('bg.addi', {'D': R11, 'A': R11, 'Y': -1}), ('bg.bnei', {'A': R11, 'I': 0, ';': 'tr_next'}),
 mh(R7, 0x3C), sb(0x5389, R7, R13), mh(R7, 0x45), sb(0x7889, R7, R12),
 *RUNCNT, *REST, j(SET_DONE),
 # ---- GET (r5 = VCP code) ----
 'osd_get:',
 ori(R7, R0, VCP), beq(R5, R7, 'og_go'),
 mh(R23, 0x48), j(GET_CONT),                              # replaced instruction (diag-poke fall-through)
 'og_go:',
 mh(R7, 0x20), lwz(R3, ADDR_VAR, R7),
 srli(R6, R3, 9), ori(R7, R0, BANK), bne(R6, R7, 'og_blk'),
 mh(R7, PORT >> 16), ori(R7, R7, PORT & 0xFFFF), beq(R3, R7, 'og_blk'),
 jal(RIU_RD), ori(R7, R0, 0xFF), ('bn.and', {'D': R4, 'A': R3, 'B': R7}), j('og_ret'),
 'og_blk:', ori(R4, R0, 0xFFFF),
 'og_ret:',                                               # as diag-poke's reply: max 0xFF, type 0, value r4
 mh(R7, 0x45), ori(R6, R0, 0xFF), sb(0x3C88, R7, R6), sb(0x3C87, R7, R6),
 srli(R6, R4, 8), sb(0x3C86, R7, R6), sb(0x3C82, R7, R4),
 ('bt.movi', {'D': R5, 'I': 0}), j(GET_REPLY),
 # ---- keep the menu open for the diagnostic SET codes (r4 = VCP code) ----
 'osd_keep:',
 ('bg.addi', {'D': R6, 'A': R4, 'Y': -0xEA}), ('bg.bleui', {'A': R6, 'I': 4, ';': 'ok_skip'}),
 mh(R7, 0x45), j(KEEP_CONT),                              # replaced instruction: vendor close-on-SET
 'ok_skip:', j(KEEP_SKIP),
]
labels = [x for x in prog if isinstance(x, str)]
assert len(labels) == len(set(labels)), 'duplicate labels'
code, L = S.assemble(prog, CODE)
for a, b, x in A.disasm(code, CODE, CODE + len(code), CODE):
    lab = [k for k, v in L.items() if v == a]
    print(('%-9s' % (lab[0] + ':' if lab else '')) + '%08x: %-12s %-9s %s' % (a, b.hex(' '), x['mnem'], x['ops']))
assert CODE + len(code) <= GTAB
assert GTAB + len(gtab) <= TTAB and TTAB + len(ttab) <= 0x202E00
assert cur(GTAB, len(gtab)) == b'\0' * len(gtab) and cur(TTAB, len(ttab)) == b'\0' * len(ttab)
assert cur(0x2024B2, 1) == b'\0'
assert cur(TILES, 6).hex() == '8ae38b048b25'        # 0x25C8F5: mov r23,r3; mov r24,r4; mov r25,r5
assert A.decode(d, WMASK - 0x200000, WMASK)['ops'] == 'r1,r1,-0x18' and A.decode(d, W16 - 0x200000, W16)['ops'] == 'r1,r1,-0xc'
assert cur(CODE, len(code)) == b'\0' * len(code)
assert cur(CNT, 2) == b'\0' * 2
# vendor code relied on
assert cur(KEEP, 4).hex() == 'c0e008a1'                                      # movhi r7,0x45
assert A.decode(d, KEEP + 4 - 0x200000, KEEP + 4)['ops'] == 'r7,0x7854(r7)'   # lbz OSD state
assert A.decode(d, 0x26B209 - 0x200000, 0x26B209)['ops'] == 'r4,0x3c80(r14)'  # r4 = VCP code
assert A.decode(d, KEEP_SKIP - 0x200000, KEEP_SKIP)['ops'] == 'r6,0x3c80(r14)'
assert cur(RIU_RD, 1) and cur(RIU_WR, 1)
assert A.decode(d, GET_REPLY - 0x200000, GET_REPLY)['mnem'] != '' and cur(SET_DONE, 2) != b'\0\0'

set_hook = S.encode('bg.j', {'/': L['osd_set']}, SET_FALL)
get_hook = S.encode('bg.j', {'/': L['osd_get']}, GET_FALL)
keep_hook = S.encode('bg.j', {'/': L['osd_keep']}, KEEP)
assert len(set_hook) == 4 and len(get_hook) == 4 and len(keep_hook) == 4
print('SET fall-through %#x %s -> %s; GET fall-through %#x %s -> %s'
      % (SET_FALL, set_old.hex(), set_hook.hex(), GET_FALL, get_old.hex(), get_hook.hex()))

patch = {
 'name': 'diag-osd',
 'summary': 'DIAGNOSTIC: VCP 0xEE reads/writes one byte of the OSD register bank 0x101C00-0x101DFF at the diag-poke address (font RAM, tile RAM, windows; tools/osdtest.sh)',
 'status': 'diagnostic; v1 closed the menu on every DDC write; v2 hardware-tested 2026-10-09 (menu stays open; raw writes work but DDC/CI is too slow for glyph uploads); v3 hardware-tested (commands work; its glyph addresses were wrong); v4 hardware-tested 2026-10-09 (2-bit tiles shown; colour = palette 16 x fg + value)',
 'requires': ['diag-poke', 'diag-fe'],
 'edits': [
  {'addr': '0x%06X' % CODE, 'old': '00' * len(code), 'new': code.hex(),
   'asm': 'osd_set / osd_get (image head zero area 0x202600): VCP 0xEE, OSD bank only, plain RIU byte access'},
  {'addr': '0x%06X' % GTAB, 'old': '00' * len(gtab), 'new': gtab.hex(),
   'asm': 'v3 test glyphs: %d x (u16 OSD RAM word, 54 bytes 2-bit glyph) for codes %s' % (NG, ', '.join('0x%X' % c for c in sorted(GLYPHS)))},
  {'addr': '0x%06X' % TTAB, 'old': '00' * len(ttab), 'new': ttab.hex(),
   'asm': 'v3 test row: %d x (column, code bits 8-11, code low byte, attribute)' % NT},
  {'addr': '0x%06X' % SET_FALL, 'old': set_old.hex(), 'new': set_hook.hex(),
   'asm': 'diag-fe SET fall-through (movhi r7,0x48) -> j osd_set'},
  {'addr': '0x%06X' % GET_FALL, 'old': get_old.hex(), 'new': get_hook.hex(),
   'asm': 'diag-poke GET fall-through (movhi r23,0x48) -> j osd_get'},
  {'addr': '0x%06X' % KEEP, 'old': cur(KEEP, 4).hex(), 'new': keep_hook.hex(),
   'asm': 'vendor close-menu-on-SET (movhi r7,0x45) -> j osd_keep: not for VCP 0xEA-0xEE'},
 ],
 'notes': ("Address: diag-poke's VCP 0xEA/0xEB. SET 0xEE = byte (<= 0xFF) written with sub_23D9E7 when the address is in "
           "0x101C00-0x101DFF; GET 0xEE reads with sub_23D972 (0xFFFF outside the bank and for the data port 0x101C66). "
           "RAM 0x2024B0 counts accepted writes, 0x2024B1 = 1 after a refused one. Only OSD display state can change; "
           "a redraw or power cycle restores it. v2: an open menu is no longer closed by SETs of VCP 0xEA-0xEE "
           "(the vendor closes it on any SET, 0x26B211). v3/v4: SET 0xEE = 0x100 loads the built-in 2-bit test glyphs "
           "(v4: even codes 0x3D0-0x3DE, RAM word 0x880 + 12 x code) with the firmware loaders' register sequence; 0x200 | row places the test row in window "
           "1 with the firmware's tile routine 0x25C8F5; RAM 0x2024B2 counts completed commands. Generated by tools/patches_src_diag_osd.py."),
}
out = os.environ.get('OUT', 'diag-osd.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
