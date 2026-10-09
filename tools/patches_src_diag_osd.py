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
R0, R3, R4, R5, R6, R7, R23 = 0, 3, 4, 5, 6, 7, 23

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

prog = [
 # ---- SET (r6 = VCP code, value u16 at 0x453C84) ----
 'osd_set:',
 ori(R7, R0, VCP), beq(R6, R7, 'os_go'),
 mh(R7, 0x48), j(SET_CONT),                               # replaced instruction (diag-fe fall-through)
 'os_go:',
 mh(R7, 0x45), lhz(R4, 0x3C84, R7),                       # r4 = value
 ori(R7, R0, 0xFF), ('bg.bgtu', {'A': R4, 'B': R7, ';': 'os_bad'}),
 mh(R7, 0x20), lwz(R3, ADDR_VAR, R7),                     # r3 = address
 srli(R6, R3, 9), ori(R7, R0, BANK), bne(R6, R7, 'os_bad'),   # 0x101C00-0x101DFF only
 jal(RIU_WR),                                             # plain byte write, as the firmware's OSD code
 mh(R7, 0x20), lbz(R6, lo, R7), ('bt.addi', {'D': R6, 'I': 1}), sb(lo, R7, R6),
 j(SET_DONE),
 'os_bad:',
 mh(R7, 0x20), ori(R6, R0, 1), sb(lo + 1, R7, R6),
 j(SET_DONE),
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
assert CODE + len(code) <= 0x202800
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
 'status': 'diagnostic; v1 closed the menu on every DDC write (hardware 2026-10-09); v2 keeps it open for 0xEA-0xEE, untested',
 'requires': ['diag-poke', 'diag-fe'],
 'edits': [
  {'addr': '0x%06X' % CODE, 'old': '00' * len(code), 'new': code.hex(),
   'asm': 'osd_set / osd_get (image head zero area 0x202600): VCP 0xEE, OSD bank only, plain RIU byte access'},
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
           "(the vendor closes it on any SET, 0x26B211). Generated by tools/patches_src_diag_osd.py."),
}
out = os.environ.get('OUT', 'diag-osd.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
