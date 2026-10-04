#!/usr/bin/env python3
"""Source of patches/diag-poke.json. Run in an unpacked work dir (RT=runtime_0x200000.bin).

DIAGNOSTIC: read and write a small, fixed set of chip registers over DDC/CI
(VCP codes 0xEA-0xEC, unused by the vendor firmware), for live experiments
such as finding what really switches the backlight off.

  specctl set 0xEA <hi16>     register address bits 31..16
  specctl set 0xEB <lo16>     register address bits 15..0
  specctl get 0xEC            read the byte at that address (0xFFFF = blocked)
  specctl set 0xEC <byte>     write the byte (ignored unless allowlisted, value <= 0xFF)
  specctl get 0xEA / 0xEB     read back the address halves

Addresses use the firmware's own register helpers (sub_23D972 read; writes
to PM pin registers through reg_write_mask 0x23DADB, which holds the lock
shared with the PM51, scaler writes through sub_23D9E7): RIU byte address for PM registers (e.g. 0x00000426), or the
scaler sub-bank form (e.g. 0x2E902F4B = sub-bank 0x2E, bank 0x102F, reg 0x4B).

Safety:
- Writes only to an exact allowlist of volatile pin/scaler registers (WRITE_OK).
  No flash/SPI, EEPROM (incl. its write-protect pin 0x42C/0x42E), PM51,
  clock or factory-data access is possible. Every write is lost at power-off.
- Reads only from the pages in READ_PAGES (PM 0x03xx/0x04xx, chip-top pad
  configuration 0x101Exx, scaler bank 0x102Fxx with any sub-bank); no data-port
  or controller registers whose read could have side effects.
- No firmware function is called except the two register helpers; nothing is
  stored in the EEPROM. Power-cycle to undo any experiment.
"""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aeon'))
import aeondis as A, aeonasm as S

d = open(os.environ.get('RT', 'runtime_0x200000.bin'), 'rb').read()
def cur(a, n): return d[a - 0x200000:a - 0x200000 + n]

CAVE = 0x203DC0                         # after popup-round (0x203D00-0x203D99), below the flags at 0x203FF0
ADDR_VAR = 0x3FF4                       # u32 at 0x203FF4 (linker padding, reloaded at boot)
GET_HOOK, GET_CONT = 0x26B17C, 0x26B180  # GET chain: unsupported code (b.movhi r23,0x48)
SET_HOOK, SET_CONT = 0x26B331, 0x26B335  # SET chain: unsupported code (b.movhi r7,0x48)
GET_REPLY = 0x26B1A0                     # reply builder: max 0x3C88/0x3C87, cur 0x3C86/0x3C82, r5 = type
SET_DONE = 0x26AFC9                      # r3 = 0, no reply (as the vendor SET handlers)
RIU_RD, RIU_WR = 0x23D972, 0x23D9E7
REG_WRITE_MASK = 0x23DADB                 # (reg, set?, mask) read-modify-write under the PM51 register lock

WRITE_OK = [0x00000422, 0x00000426, 0x00000428, 0x00000434, 0x00000436, 0x0000043A, 0x0000043B,
            0x0000044A, 0x0000044B, 0x0000044C, 0x0000044D,
            0x2E902F4A, 0x2E902F4B]
READ_PAGES = [0x000300, 0x000400, 0x101E00, 0x102F00]      # (addr & 0x7FFF00); top byte only for 0x102F00

R0, R1, R3, R4, R5, R6, R7, R8, R9, R23 = 0, 1, 3, 4, 5, 6, 7, 8, 9, 23
ori = lambda rd, ra, v: ('bg.ori', {'D': rd, 'A': ra, 't': v})
mh = lambda rd, v: ('bg.movhi', {'D': rd, 'U': v})
beq = lambda a, b, l: ('bg.beq', {'A': a, 'B': b, ';': l})
bne = lambda a, b, l: ('bg.bne', {'A': a, 'B': b, ';': l})
beqz = lambda a, l: ('bg.beqi', {'A': a, 'I': 0, ';': l})
j = lambda t: ('bg.j', {'/': t})
jal = lambda t: ('bg.jal', {'/': t})
lwz = lambda rd, off, ra: ('bg.lwz', {'D': rd, 'A': ra, 'W': off})
sw = lambda off, ra, rb: ('bg.sw', {'W': off, 'A': ra, 'B': rb})
lhz = lambda rd, off, ra: ('bg.lhz', {'D': rd, 'A': ra, 'X': off})
sb = lambda off, ra, rb: ('bg.sb', {'Y': off, 'A': ra, 'B': rb})
srli = lambda rd, ra, n: ('bn.srli', {'D': rd, 'A': ra, 'H': n})
slli = lambda rd, ra, n: ('bn.slli', {'D': rd, 'A': ra, 'H': n})
orr = lambda rd, ra, rb: ('bn.or', {'D': rd, 'A': ra, 'B': rb})
andr = lambda rd, ra, rb: ('bn.and', {'D': rd, 'A': ra, 'B': rb})
const32 = lambda rd, v: [mh(rd, v >> 16), ori(rd, rd, v & 0xFFFF)]

prog = [
 # ---------------- GET (r5 = VCP code) ----------------
 'get_hook:',
 ori(R7, R0, 0xEA), beq(R5, R7, 'g_hi'),
 ori(R7, R0, 0xEB), beq(R5, R7, 'g_lo'),
 ori(R7, R0, 0xEC), beq(R5, R7, 'g_rd'),
 mh(R23, 0x48), j(GET_CONT),                       # replaced instruction, vendor "unsupported"
 'g_hi:', mh(R7, 0x20), lwz(R4, ADDR_VAR, R7), srli(R4, R4, 16), j('g_ret'),
 'g_lo:', mh(R7, 0x20), lwz(R4, ADDR_VAR, R7), ori(R7, R0, 0xFFFF), andr(R4, R4, R7), j('g_ret'),
 'g_rd:', mh(R7, 0x20), lwz(R3, ADDR_VAR, R7),
 jal('chk_rd'), beqz(R3, 'g_blk'),
 mh(R7, 0x20), lwz(R3, ADDR_VAR, R7), jal(RIU_RD),
 ori(R7, R0, 0xFF), andr(R4, R3, R7), j('g_ret'),
 'g_blk:', ori(R4, R0, 0xFFFF),
 'g_ret:',                                         # r4 = 16-bit value; max = 0xFFFF, type 0
 mh(R7, 0x45), ori(R6, R0, 0xFF), sb(0x3C88, R7, R6), sb(0x3C87, R7, R6),
 srli(R6, R4, 8), sb(0x3C86, R7, R6), sb(0x3C82, R7, R4),
 ('bt.movi', {'D': R5, 'I': 0}), j(GET_REPLY),
 # ---------------- SET (r6 = VCP code, value u16 at 0x453C84) ----------------
 'set_hook:',
 ori(R7, R0, 0xEA), beq(R6, R7, 's_hi'),
 ori(R7, R0, 0xEB), beq(R6, R7, 's_lo'),
 ori(R7, R0, 0xEC), beq(R6, R7, 's_wr'),
 mh(R7, 0x48), j(SET_CONT),                        # replaced instruction
 's_hi:', mh(R7, 0x45), lhz(R4, 0x3C84, R7), slli(R4, R4, 16),
 mh(R7, 0x20), lwz(R5, ADDR_VAR, R7), ori(R6, R0, 0xFFFF), andr(R5, R5, R6), orr(R5, R5, R4),
 sw(ADDR_VAR, R7, R5), j(SET_DONE),
 's_lo:', mh(R7, 0x45), lhz(R4, 0x3C84, R7),
 mh(R7, 0x20), lwz(R5, ADDR_VAR, R7), srli(R5, R5, 16), slli(R5, R5, 16), orr(R5, R5, R4),
 sw(ADDR_VAR, R7, R5), j(SET_DONE),
 's_wr:', mh(R7, 0x45), lhz(R4, 0x3C84, R7), ori(R7, R0, 0xFF), ('bg.bgtu', {'A': R4, 'B': R7, ';': 's_end'}),
 mh(R7, 0x20), lwz(R3, ADDR_VAR, R7),
 ('bt.addi', {'D': R1, 'I': -8}), ('bn.sw', {':': 0, 'A': R1, 'B': R4}), ('bn.sw', {':': 4, 'A': R1, 'B': R3}),
 jal('chk_wr'), beqz(R3, 's_pop'),
 ('bn.lwz', {'D': R3, 'A': R1, ':': 4}), ('bn.lwz', {'D': R4, 'A': R1, ':': 0}),
 srli(R6, R3, 24), beqz(R6, 's_pm'),
 jal(RIU_WR), j('s_pop'),                          # scaler sub-bank register: plain byte write
 's_pm:',                                          # PM pin register: masked writes under the PM lock
 ('bn.or', {'D': R5, 'A': R4, 'B': R0}), ('bt.movi', {'D': R4, 'I': 1}), jal(REG_WRITE_MASK),   # set the 1 bits
 ('bn.lwz', {'D': R3, 'A': R1, ':': 4}), ('bn.lwz', {'D': R5, 'A': R1, ':': 0}),
 ('bn.xori', {'D': R5, 'A': R5, 'O': -1}), ('bt.movi', {'D': R4, 'I': 0}), jal(REG_WRITE_MASK),  # clear the 0 bits
 's_pop:', ('bt.addi', {'D': R1, 'I': 8}),
 's_end:', j(SET_DONE),
 # ---------------- checks: r3 = address -> r3 = 1 allowed / 0 blocked (leaf, r9 kept) ----------------
 'chk_wr:', mh(R5, 0x20), ori(R5, R5, 0), 'w_loop:',          # r5 = table pointer (patched below)
 lwz(R6, 0, R5), beqz(R6, 'no'), beq(R3, R6, 'yes'), ('bt.addi', {'D': R5, 'I': 4}), j('w_loop'),
 'chk_rd:',
 *const32(R7, 0x007FFF00), andr(R4, R3, R7),             # r4 = page
 srli(R6, R3, 24), beqz(R6, 'r_any'),                    # top byte set: only the scaler bank
 *const32(R7, 0x00102F00), beq(R4, R7, 'yes'), j('no'),
 'r_any:', mh(R5, 0x20), ori(R5, R5, 0), 'r_loop:',       # r5 = page table pointer (patched below)
 lwz(R6, 0, R5), beqz(R6, 'no'), beq(R4, R6, 'yes'), ('bt.addi', {'D': R5, 'I': 4}), j('r_loop'),
 'yes:', ('bt.movi', {'D': R3, 'I': 1}), ('bt.jr', {'A': R9}),
 'no:', ('bt.movi', {'D': R3, 'I': 0}), ('bt.jr', {'A': R9}),
]

def build(wtab, rtab):
    p = []
    for it in prog:
        p.append(it)
    out = []
    k = 0
    for it in p:                                           # fill the two table pointers
        if isinstance(it, tuple) and it[0] == 'bg.ori' and it[1]['D'] == R5 and it[1]['A'] == R5:
            out.append(ori(R5, R5, (wtab if k == 0 else rtab) & 0xFFFF)); k += 1
        else:
            out.append(it)
    return S.assemble(out, CAVE)

code, L = build(0, 0)
wtab = (CAVE + len(code) + 3) & ~3
tables = b''.join(a.to_bytes(4, 'little') for a in WRITE_OK + [0])
rtab = wtab + len(tables)
tables += b''.join(a.to_bytes(4, 'little') for a in READ_PAGES + [0])
code, L = build(wtab, rtab)
assert (wtab >> 16) == 0x20 and (rtab >> 16) == 0x20
blob = code + b'\0' * (wtab - CAVE - len(code)) + tables
for a, b, x in A.disasm(code, CAVE, CAVE + len(code), CAVE):
    lab = [k for k, v in L.items() if v == a]
    print(('%-10s' % (lab[0] + ':' if lab else '')) + '%08x: %-12s %-9s %s' % (a, b.hex(' '), x['mnem'], x['ops']))
print('tables at %#x / %#x, end %#x' % (wtab, rtab, CAVE + len(blob)))
assert CAVE + len(blob) <= 0x203FF0             # panel-prepower flags at 0x203FF0/1, address variable at 0x203FF4
assert cur(CAVE, len(blob)) == b'\0' * len(blob)
assert cur(0x200000 + ADDR_VAR, 4) == b'\0' * 4
assert cur(GET_HOOK, 4).hex() == 'c2e00901'                # b.movhi r23,0x48
assert cur(SET_HOOK, 4).hex() == 'c0e00901'                # b.movhi r7,0x48

edits = [
 {'addr': '0x%06X' % CAVE, 'old': '00' * len(blob), 'new': blob.hex(),
  'asm': 'diag-poke handlers, allowlist checks and tables (linker padding 0x203DC0); address variable at 0x203FF4'},
 {'addr': '0x%06X' % GET_HOOK, 'old': cur(GET_HOOK, 4).hex(), 'new': S.encode('bg.j', {'/': L['get_hook']}, GET_HOOK).hex(),
  'asm': 'VCP GET unsupported-code path -> get_hook (0xEA/0xEB/0xEC)'},
 {'addr': '0x%06X' % SET_HOOK, 'old': cur(SET_HOOK, 4).hex(), 'new': S.encode('bg.j', {'/': L['set_hook']}, SET_HOOK).hex(),
  'asm': 'VCP SET unsupported-code path -> set_hook (0xEA/0xEB/0xEC)'},
]
patch = {
 'name': 'diag-poke',
 'summary': 'DIAGNOSTIC: read/write an allowlisted set of volatile pin and scaler registers over DDC (VCP 0xEA/0xEB address, 0xEC data)',
 'status': 'diagnostic, hardware test pending',
 'edits': edits,
 'notes': ("VCP 0xEA/0xEB set the register address (high/low 16 bits), VCP 0xEC reads (GET) or writes (SET, value <= 0xFF) "
           "one byte through the firmware's register helpers. Writes are limited to: %s. Reads are limited to the pages "
           "0x0003xx, 0x0004xx, 0x101Exx and the scaler bank 0x102Fxx (any sub-bank); blocked reads return 0xFFFF. "
           "No EEPROM, flash, PM51 or factory-data access; all writes are volatile (power-cycle to undo). "
           "Generated by tools/patches_src_diag_poke.py." % ', '.join('0x%08X' % a for a in WRITE_OK)),
}
out = os.environ.get('OUT', 'diag-poke.json')
json.dump(patch, open(out, 'w'), indent=2)
open(out, 'a').write('\n')
